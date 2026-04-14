from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
from decimal import Decimal, InvalidOperation


def normalize_account(account):
    # Normalize account names: remove extra spaces, standardize separators
    # "Wells Fargo" -> "wellsfargo", "Zach Latta" -> "zachlatta"
    return re.sub(r'\s+', '', account.lower())


def parse_amount(amount_str):
    # Parse amount string like "$9.40", "-$9.40", "$1,430.00", "€8.36"
    if not amount_str:
        return None
    amount_str = amount_str.strip()
    negative = amount_str.startswith('-')
    amount_str = amount_str.lstrip('-')
    amount_str = re.sub(r'[$€£,]', '', amount_str)
    amount_str = re.sub(r'\s*(USD|EUR|GBP)\s*', '', amount_str)
    try:
        value = Decimal(amount_str.strip())
        return -value if negative else value
    except (InvalidOperation, ValueError):
        return None


def parse_ledger(text):
    # Parse ledger format into list of transactions
    transactions = []
    current_txn = None
    current_posting = None
    
    for line in text.split('\n'):
        if not line.strip():
            if current_txn:
                if current_posting:
                    current_txn['postings'].append(current_posting)
                    current_posting = None
                transactions.append(current_txn)
                current_txn = None
            continue
        
        # Transaction header: DATE [*|!] PAYEE [| DESCRIPTION] (also handle YYYY-MM-DD format)
        header_match = re.match(r'^(\d{4}[/-]\d{2}[/-]\d{2})\s+(.+)$', line)
        if header_match:
            if current_txn:
                if current_posting:
                    current_txn['postings'].append(current_posting)
                    current_posting = None
                transactions.append(current_txn)
            date_str = header_match.group(1).replace('-', '/')
            payee_raw = header_match.group(2).strip()
            # Strip cleared/pending status markers (* or !) from start
            payee_raw = re.sub(r'^[*!]\s*', '', payee_raw)
            # Extract just the payee name (before | if present)
            if '|' in payee_raw:
                payee_raw = payee_raw.split('|')[0].strip()
            current_txn = {'date': date_str, 'payee': payee_raw, 'postings': [], 'comments': []}
            continue
        
        if current_txn is None:
            continue
        
        # Comment line
        if line.strip().startswith(';'):
            comment = line.strip()[1:].strip()
            if current_posting:
                current_posting['comments'].append(comment)
            else:
                current_txn['comments'].append(comment)
            continue
        
        # Treat "Receipt:" lines as comments even without semicolon (common LLM formatting error)
        stripped = line.strip()
        if stripped.lower().startswith('receipt:'):
            comment = stripped
            if current_posting:
                current_posting['comments'].append(comment)
            else:
                current_txn['comments'].append(comment)
            continue
        
        # Posting line: ACCOUNT [AMOUNT]
        posting_match = re.match(r'^\s+(\S.*?)(?:\s{2,}(.+))?$', line)
        if posting_match:
            if current_posting:
                current_txn['postings'].append(current_posting)
            account = posting_match.group(1).strip()
            amount_str = posting_match.group(2)
            current_posting = {
                'account': account,
                'amount': parse_amount(amount_str) if amount_str else None,
                'comments': []
            }
    
    if current_txn:
        if current_posting:
            current_txn['postings'].append(current_posting)
        transactions.append(current_txn)
    
    return transactions


def parse_all_ledger_files(context):
    all_transactions = []
    for filename, content in context.items():
        if filename.endswith('.ledger') or filename.endswith('.dat') or filename.endswith('.txt'):
            all_transactions.extend(parse_ledger(content))
    return all_transactions


def get_txn_amount(txn):
    # Get the primary amount (first explicit positive amount)
    for p in txn['postings']:
        if p['amount'] is not None and p['amount'] > 0:
            return p['amount']
    return Decimal('0')


def normalize_comment(comment):
    # Normalize comment: lowercase, strip whitespace and quotes
    c = comment.lower().strip()
    c = c.replace('"', '').replace("'", '')
    return c


def get_all_comments(txn):
    # Collect all comments from transaction and postings, normalized
    comments = set(normalize_comment(c) for c in txn['comments'])
    for p in txn['postings']:
        comments.update(normalize_comment(c) for c in p['comments'])
    return comments


def compute_payee_similarity(ref_payee, gen_payee):
    # Compute payee similarity, handling cases where description is appended
    ref_lower = ref_payee.lower().strip()
    gen_lower = gen_payee.lower().strip()
    # Exact match
    if ref_lower == gen_lower:
        return 1.0
    # Check if one is a prefix of the other (description appended without separator)
    if gen_lower.startswith(ref_lower + ' ') or ref_lower.startswith(gen_lower + ' '):
        return 1.0
    # Fall back to sequence matcher
    return SequenceMatcher(None, ref_lower, gen_lower).ratio()


def compute_txn_similarity(ref_txn, gen_txn):
    # Compute similarity between two transactions
    # Date match (exact)
    date_sim = 1.0 if ref_txn['date'] == gen_txn['date'] else 0.0
    
    # Payee similarity
    payee_sim = compute_payee_similarity(ref_txn['payee'], gen_txn['payee'])
    
    # Amount similarity
    ref_amt = get_txn_amount(ref_txn)
    gen_amt = get_txn_amount(gen_txn)
    if ref_amt == gen_amt:
        amt_sim = 1.0
    elif ref_amt == 0 or gen_amt == 0:
        amt_sim = 0.0
    else:
        amt_sim = float(min(ref_amt, gen_amt) / max(ref_amt, gen_amt))
    
    # Account similarity (best match between postings, using normalized accounts)
    ref_accounts = [normalize_account(p['account']) for p in ref_txn['postings']]
    gen_accounts = [normalize_account(p['account']) for p in gen_txn['postings']]
    if ref_accounts and gen_accounts:
        account_sims = [max(SequenceMatcher(None, ra, ga).ratio() for ga in gen_accounts) for ra in ref_accounts]
        account_sim = sum(account_sims) / len(account_sims)
    else:
        account_sim = 1.0 if not ref_accounts and not gen_accounts else 0.0
    
    # Comment similarity (Jaccard)
    ref_comments = get_all_comments(ref_txn)
    gen_comments = get_all_comments(gen_txn)
    if not ref_comments and not gen_comments:
        comment_sim = 1.0
    elif not ref_comments:
        comment_sim = 1.0  # Extra comments ok
    elif not gen_comments:
        comment_sim = 0.0
    else:
        intersection = len(ref_comments & gen_comments)
        union = len(ref_comments | gen_comments)
        comment_sim = intersection / union if union > 0 else 1.0
    
    # Weighted combination: date and payee gate, amount critical, accounts important, comments secondary
    # If date or payee don't match well, this isn't the same transaction
    if date_sim < 1.0 or payee_sim < 0.8:
        return 0.0
    return 0.3 * amt_sim + 0.4 * account_sim + 0.2 * comment_sim + 0.1 * payee_sim


def compute_scores(ref_txns, gen_txns):
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    
    if not ref_txns and not gen_txns:
        return 1.0, 1.0, 1.0, 1.0
    if not ref_txns or not gen_txns:
        return 0.0, 0.0, 0.0, 0.0
    
    n_ref, n_gen = len(ref_txns), len(gen_txns)
    
    # Build full similarity matrix
    sim_matrix = np.zeros((n_ref, n_gen))
    for i, ref_txn in enumerate(ref_txns):
        for j, gen_txn in enumerate(gen_txns):
            sim_matrix[i, j] = compute_txn_similarity(ref_txn, gen_txn)
    
    # Hungarian matching
    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    
    # Coverage: how many ref transactions have a good match (sim > 0.5)
    matched_pairs = [(i, j, sim_matrix[i, j]) for i, j in zip(row_ind, col_ind)]
    good_matches = sum(1 for _, _, sim in matched_pairs if sim > 0.5)
    coverage = good_matches / n_ref
    
    # For matched pairs, compute detailed scores
    posting_scores, amount_scores, comment_scores = [], [], []
    
    for i, j, sim in matched_pairs:
        if sim < 0.5:
            continue
        ref_txn, gen_txn = ref_txns[i], gen_txns[j]
        
        # Posting accuracy (using normalized accounts)
        ref_accounts = [normalize_account(p['account']) for p in ref_txn['postings']]
        gen_accounts = [normalize_account(p['account']) for p in gen_txn['postings']]
        if ref_accounts and gen_accounts:
            acc_sims = [max(SequenceMatcher(None, ra, ga).ratio() for ga in gen_accounts) for ra in ref_accounts]
            posting_scores.append(sum(acc_sims) / len(acc_sims))
        elif not ref_accounts and not gen_accounts:
            posting_scores.append(1.0)
        else:
            posting_scores.append(0.0)
        
        # Amount accuracy
        ref_amt = get_txn_amount(ref_txn)
        gen_amt = get_txn_amount(gen_txn)
        if ref_amt == gen_amt:
            amount_scores.append(1.0)
        elif ref_amt == 0 or gen_amt == 0:
            amount_scores.append(0.0)
        else:
            amount_scores.append(float(min(ref_amt, gen_amt) / max(ref_amt, gen_amt)))
        
        # Comment preservation
        ref_comments = get_all_comments(ref_txn)
        gen_comments = get_all_comments(gen_txn)
        if not ref_comments:
            comment_scores.append(1.0)
        elif not gen_comments:
            comment_scores.append(0.0)
        else:
            intersection = len(ref_comments & gen_comments)
            union = len(ref_comments | gen_comments)
            comment_scores.append(intersection / union if union > 0 else 1.0)
    
    posting_score = sum(posting_scores) / len(posting_scores) if posting_scores else 0.0
    amount_score = sum(amount_scores) / len(amount_scores) if amount_scores else 0.0
    comment_score = sum(comment_scores) / len(comment_scores) if comment_scores else 0.0
    
    return coverage, posting_score, amount_score, comment_score


class DomainAccounting(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "accounting"
        self.summary = "Ledger-cli financial records with transactions, postings, and account balances"
        self.description = "Ledger financial transactions"
        self.file_format = [".ledger"]
        self.domain_parser = "custom"
        self.category = "records"
    
    def parse_all_transactions(self, context):
        return parse_all_ledger_files(context)
    
    def parse_context(self, context):
        txns = self.parse_all_transactions(context)
        return {"transactions": txns}
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        txns = parsed["transactions"]
        num_postings = sum(len(t.get('postings', [])) for t in txns)
        accounts = set()
        for t in txns:
            for p in t.get('postings', []):
                if p.get('account'):
                    accounts.add(p['account'])
        num_comments = sum(1 for t in txns if t.get('comment'))
        num_comments += sum(1 for t in txns for p in t.get('postings', []) if p.get('comment'))
        return {
            "Transactions": len(txns),
            "Postings": num_postings,
            "Accounts": len(accounts),
            "Comments": num_comments,
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        ref_txns = self.parse_context(reference_context)["transactions"]
        gen_txns = self.parse_context(generated_context)["transactions"]
        
        if debug:
            print(f"Reference transactions: {len(ref_txns)}, Generated transactions: {len(gen_txns)}")
        
        coverage, posting_score, amount_score, comment_score = compute_scores(ref_txns, gen_txns)
        
        # Final score: coverage^2 * posting * amount * comment_factor
        # Comment factor: 0.5 + 0.5*sqrt(comment) so comments can remove at most 50% of score
        comment_factor = 0.5 + 0.5 * math.sqrt(comment_score)
        score = (coverage ** 2) * posting_score * amount_score * comment_factor
        
        eval_obj = {
            "score": score,
            "transaction_coverage_score": coverage,
            "posting_accuracy_score": posting_score,
            "amount_accuracy_score": amount_score,
            "comment_preservation_score": comment_score,
            "ref_transaction_count": len(ref_txns),
            "gen_transaction_count": len(gen_txns),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
