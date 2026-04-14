from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import email
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
import os, re, ujson as json
import numpy as np
from scipy.optimize import linear_sum_assignment

SEPARATOR = '-' * 60


def decode_mime_header(value):
    if not value:
        return ''
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or 'utf-8', errors='replace'))
        else:
            result.append(part)
    return ''.join(result)


def parse_address(addr_str):
    if not addr_str:
        return {'name': '', 'email': ''}
    decoded = decode_mime_header(addr_str)
    name, email_addr = parseaddr(decoded)
    return {'name': name.strip(), 'email': email_addr.strip().lower()}


def parse_address_list(addr_str):
    if not addr_str:
        return []
    decoded = decode_mime_header(addr_str)
    # Split on comma, but handle quoted names
    addresses = []
    parts = re.split(r',\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', decoded)
    for part in parts:
        part = part.strip()
        if part:
            name, email_addr = parseaddr(part)
            addresses.append({'name': name.strip(), 'email': email_addr.strip().lower()})
    return addresses


def parse_single_email(raw_text):
    raw_text = raw_text.strip()
    if not raw_text:
        return None
    
    try:
        msg = email.message_from_string(raw_text)
    except Exception as e:
        print(f"\033[91mEmail parsing error: {e}\033[0m")
        return None
    
    from_addr = parse_address(msg.get('From', ''))
    to_addrs = parse_address_list(msg.get('To', ''))
    cc_addrs = parse_address_list(msg.get('Cc', ''))
    subject = decode_mime_header(msg.get('Subject', ''))
    date_str = msg.get('Date', '')
    message_id = msg.get('Message-ID', '').strip()
    in_reply_to = msg.get('In-Reply-To', '')
    # Clean up In-Reply-To (might have extra text like "(message from ...)")
    if in_reply_to:
        match = re.search(r'<[^>]+>', in_reply_to)
        in_reply_to = match.group(0) if match else in_reply_to.strip()
    
    # Parse date
    date_parsed = None
    if date_str:
        try:
            date_parsed = parsedate_to_datetime(date_str)
        except:
            pass
    
    # Get body - for simple messages, payload is the body
    if msg.is_multipart():
        body = ''
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode('utf-8', errors='replace')
                    break
    else:
        payload = msg.get_payload(decode=False)
        if isinstance(payload, bytes):
            body = payload.decode('utf-8', errors='replace')
        else:
            body = payload or ''
    
    return {
        'from': from_addr,
        'to': to_addrs,
        'cc': cc_addrs,
        'subject': subject.strip(),
        'date': date_parsed,
        'date_str': date_str.strip(),
        'message_id': message_id,
        'in_reply_to': in_reply_to,
        'body': body.strip(),
    }


def parse_email_thread(text):
    raw_messages = text.split(SEPARATOR)
    messages = []
    for raw in raw_messages:
        msg = parse_single_email(raw)
        if msg:
            messages.append(msg)
    return messages


def parse_all_emails(context):
    all_messages = []
    for filename, content in context.items():
        if filename.endswith('.eml') or filename.endswith('.txt'):
            messages = parse_email_thread(content)
            all_messages.extend(messages)
    return all_messages


def message_fingerprint(msg):
    # Use message_id as primary fingerprint, fall back to subject+date+from
    if msg['message_id']:
        return msg['message_id'].lower().strip('<>')
    fallback = f"{msg['subject']}|{msg['date_str']}|{msg['from']['email']}"
    return fallback.lower()


def normalize_text(text):
    return ' '.join(text.lower().split())


def compute_message_coverage_score(ref_msgs, gen_msgs):
    if not ref_msgs and not gen_msgs:
        return 1.0
    if not ref_msgs or not gen_msgs:
        return 0.0
    
    ref_fps = {message_fingerprint(m) for m in ref_msgs}
    gen_fps = {message_fingerprint(m) for m in gen_msgs}
    
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def compute_header_similarity(ref_msg, gen_msg):
    scores = []
    weights = []
    
    # From (name + email) - 25%
    ref_from = f"{ref_msg['from']['name']} {ref_msg['from']['email']}".lower().strip()
    gen_from = f"{gen_msg['from']['name']} {gen_msg['from']['email']}".lower().strip()
    scores.append(SequenceMatcher(None, ref_from, gen_from).ratio())
    weights.append(0.25)
    
    # To - 15%
    ref_to = ' '.join(f"{a['name']} {a['email']}" for a in ref_msg['to']).lower()
    gen_to = ' '.join(f"{a['name']} {a['email']}" for a in gen_msg['to']).lower()
    scores.append(SequenceMatcher(None, ref_to, gen_to).ratio())
    weights.append(0.15)
    
    # Subject - 20%
    ref_subj = normalize_text(ref_msg['subject'])
    gen_subj = normalize_text(gen_msg['subject'])
    scores.append(SequenceMatcher(None, ref_subj, gen_subj).ratio())
    weights.append(0.20)
    
    # Date - 15%
    ref_date = ref_msg['date_str'].lower() if ref_msg['date_str'] else ''
    gen_date = gen_msg['date_str'].lower() if gen_msg['date_str'] else ''
    scores.append(SequenceMatcher(None, ref_date, gen_date).ratio())
    weights.append(0.15)
    
    # Message-ID - 15%
    ref_mid = ref_msg['message_id'].lower()
    gen_mid = gen_msg['message_id'].lower()
    scores.append(1.0 if ref_mid == gen_mid else 0.0)
    weights.append(0.15)
    
    # In-Reply-To - 10%
    ref_irt = ref_msg['in_reply_to'].lower() if ref_msg['in_reply_to'] else ''
    gen_irt = gen_msg['in_reply_to'].lower() if gen_msg['in_reply_to'] else ''
    if not ref_irt and not gen_irt:
        scores.append(1.0)
    else:
        scores.append(1.0 if ref_irt == gen_irt else 0.0)
    weights.append(0.10)
    
    return sum(s * w for s, w in zip(scores, weights)) / sum(weights)


def compute_body_similarity(ref_msg, gen_msg):
    ref_body = normalize_text(ref_msg['body'])
    gen_body = normalize_text(gen_msg['body'])
    return SequenceMatcher(None, ref_body, gen_body).ratio()


def compute_message_similarity(ref_msg, gen_msg):
    # Combined similarity for matching purposes
    header_sim = compute_header_similarity(ref_msg, gen_msg)
    body_sim = compute_body_similarity(ref_msg, gen_msg)
    return 0.3 * header_sim + 0.7 * body_sim


def compute_matched_scores(ref_msgs, gen_msgs):
    if not ref_msgs and not gen_msgs:
        return 1.0, 1.0, []
    if not ref_msgs or not gen_msgs:
        return 0.0, 0.0, []
    
    n_ref, n_gen = len(ref_msgs), len(gen_msgs)
    
    # Build similarity matrix
    sim_matrix = np.zeros((n_ref, n_gen))
    for i, ref in enumerate(ref_msgs):
        for j, gen in enumerate(gen_msgs):
            sim_matrix[i, j] = compute_message_similarity(ref, gen)
    
    # Hungarian algorithm for optimal matching
    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    matched_pairs = list(zip(row_ind, col_ind))
    
    # Compute header and body scores for matched pairs
    header_scores = []
    body_scores = []
    for ref_idx, gen_idx in matched_pairs:
        header_scores.append(compute_header_similarity(ref_msgs[ref_idx], gen_msgs[gen_idx]))
        body_scores.append(compute_body_similarity(ref_msgs[ref_idx], gen_msgs[gen_idx]))
    
    avg_header = sum(header_scores) / n_ref if header_scores else 0.0
    avg_body = sum(body_scores) / n_ref if body_scores else 0.0
    
    return avg_header, avg_body, matched_pairs


def get_sort_key(msg):
    # Return a sortable key - prefer parsed datetime, fall back to date string
    if msg['date']:
        return (0, msg['date'].isoformat())
    elif msg['date_str']:
        return (1, msg['date_str'])
    else:
        return (2, '')


def compute_sequence_score(ref_msgs, gen_msgs, matched_pairs):
    if not matched_pairs:
        return 1.0 if (not ref_msgs and not gen_msgs) else 0.0
    if len(matched_pairs) == 1:
        return 1.0  # single matched pair: trivially correct ordering

    # Sort reference by date to get canonical order
    ref_with_idx = [(i, get_sort_key(m)) for i, m in enumerate(ref_msgs)]
    ref_sorted = sorted(ref_with_idx, key=lambda x: x[1])
    ref_rank = {idx: rank for rank, (idx, _) in enumerate(ref_sorted)}

    # Sort generated by date
    gen_with_idx = [(i, get_sort_key(m)) for i, m in enumerate(gen_msgs)]
    gen_sorted = sorted(gen_with_idx, key=lambda x: x[1])
    gen_rank = {idx: rank for rank, (idx, _) in enumerate(gen_sorted)}

    ref_seq = [ref_rank[ref_idx] for ref_idx, _ in matched_pairs]
    gen_seq = [gen_rank[gen_idx] for _, gen_idx in matched_pairs]

    # Convert to relative ranks so sequences are comparable regardless
    # of ref/gen count differences (absolute ranks span different ranges)
    def _to_relative_ranks(seq):
        order = sorted(range(len(seq)), key=lambda i: seq[i])
        ranks = [0] * len(seq)
        for rank, idx in enumerate(order):
            ranks[idx] = rank
        return ranks

    ref_rel = _to_relative_ranks(ref_seq)
    gen_rel = _to_relative_ranks(gen_seq)

    return SequenceMatcher(None, ref_rel, gen_rel).ratio()


class DomainEmails(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "emails"
        self.summary = "Email threads in .eml format with headers, threading, and MIME content"
        self.description = "Email threads"
        self.file_format = [".eml"]
        self.domain_parser = "email"
        self.category = "records"
    
    def parse_all_messages(self, context):
        return parse_all_emails(context)
    
    def parse_context(self, context):
        messages = self.parse_all_messages(context)
        return {"messages": messages}
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        messages = parsed["messages"]
        senders = set(m['from']['email'] for m in messages if m.get('from') and m['from'].get('email'))
        replies = sum(1 for m in messages if m.get('in_reply_to'))
        return {
            "Messages": len(messages),
            "Senders": len(senders),
            "Replies": replies,
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        ref_msgs = self.parse_context(reference_context)["messages"]
        gen_msgs = self.parse_context(generated_context)["messages"]
        
        if debug:
            print(f"Reference messages: {len(ref_msgs)}, Generated messages: {len(gen_msgs)}")
        
        # Compute component scores
        coverage_score = compute_message_coverage_score(ref_msgs, gen_msgs)
        header_score, body_score, matched_pairs = compute_matched_scores(ref_msgs, gen_msgs)
        sequence_score = compute_sequence_score(ref_msgs, gen_msgs, matched_pairs)
        
        # Weighted average: 20% coverage, 25% headers, 40% body, 15% sequence
        score = 0.20 * coverage_score + 0.25 * header_score + 0.40 * body_score + 0.15 * sequence_score
        
        eval_obj = {
            "score": score,
            "message_coverage_score": coverage_score,
            "header_accuracy_score": header_score,
            "body_accuracy_score": body_score,
            "sequence_score": sequence_score,
            "ref_message_count": len(ref_msgs),
            "gen_message_count": len(gen_msgs),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


if __name__ == "__main__":
    # Test the parser
    with open("samples/emails1/basic_state/bytecode_tail_call_thread.eml", "r") as f:
        content = f.read()
    
    messages = parse_email_thread(content)
    
    print("=" * 60)
    print(f"MESSAGES ({len(messages)})")
    print("=" * 60)
    
    for i, msg in enumerate(messages, 1):
        from_str = f"{msg['from']['name']} <{msg['from']['email']}>" if msg['from']['name'] else msg['from']['email']
        reply_marker = " [reply]" if msg['in_reply_to'] else ""
        body_preview = msg['body'][:60].replace('\n', ' ') + "..." if len(msg['body']) > 60 else msg['body'].replace('\n', ' ')
        print(f"{i:2d}. {from_str[:30]:<30} | {msg['subject'][:25]:<25}{reply_marker}")
        print(f"    Date: {msg['date_str']}")
        print(f"    Body: {body_preview}")
        print()
