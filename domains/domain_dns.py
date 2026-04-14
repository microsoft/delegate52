from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
import dns.zone
import dns.rdatatype
import dns.name
import dns.tokenizer
import io


def _extract_origin(content):
    """Extract $ORIGIN from zone content, defaulting to example.com."""
    for line in content.split('\n'):
        line_stripped = line.strip()
        if line_stripped.upper().startswith('$ORIGIN'):
            parts = line_stripped.split(None, 1)
            if len(parts) > 1:
                origin_str = parts[1].strip()
                if not origin_str.endswith('.'):
                    origin_str += '.'
                try:
                    return dns.name.from_text(origin_str)
                except Exception:
                    pass
            break
    return dns.name.from_text('example.com.')


def _strip_conflicting_cnames(content):
    """Remove CNAME lines from nodes that also have non-CNAME records.

    RFC 1034 forbids CNAME coexistence with other record types.  LLMs
    sometimes produce this; dnspython refuses to parse the whole zone.
    Stripping the offending CNAME lets us score the remaining records
    (the missing CNAME naturally lowers coverage/rdata).
    """
    lines = content.split('\n')
    # Pass 1 — collect names that own at least one non-CNAME RR
    current_name = None
    names_with_data = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(';') or stripped.startswith('$'):
            continue
        if line[0] not in (' ', '\t', ';'):
            parts = stripped.split()
            if parts:
                current_name = parts[0]
        if current_name is None:
            continue
        upper = stripped.upper().split()
        for j, tok in enumerate(upper):
            if tok == 'IN' and j + 1 < len(upper) and upper[j + 1] != 'CNAME':
                names_with_data.add(current_name.lower())
                break

    # Pass 2 — drop CNAME lines for those names
    out = []
    current_name = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(';') or stripped.startswith('$'):
            out.append(line)
            continue
        if line[0] not in (' ', '\t', ';'):
            parts = stripped.split()
            if parts:
                current_name = parts[0]
        skip = False
        if current_name and current_name.lower() in names_with_data:
            if 'CNAME' in stripped.upper().split():
                skip = True
        if not skip:
            out.append(line)
    return '\n'.join(out)


def _build_known_rdtypes():
    """Return a frozen set of all known DNS record type names (upper-case)."""
    types = set()
    for i in range(65536):
        try:
            t = dns.rdatatype.to_text(i)
            if not t.startswith("TYPE"):
                types.add(t.upper())
        except Exception:
            pass
    return frozenset(types)


_KNOWN_RDTYPES = _build_known_rdtypes()


def _preprocess_zone_content(content):
    """Strip lines that are clearly not valid DNS records.

    LLM outputs frequently contain non-record text that causes dnspython
    to reject the entire zone.  Common patterns:

    * Bare name references with comments:  ``archive ; (already defined)``
    * Name with IN but no rdtype:  ``stack IN ; (placeholder)``
    * Prose / labels:  ``testnet-related (placeholder)``
    * Tab-indented new records mistaken for continuation lines

    Multi-line records inside parentheses (SOA, etc.) are always preserved.
    """
    lines = content.split('\n')
    cleaned = []
    paren_depth = 0

    for line in lines:
        stripped = line.strip()

        # Inside a multi-line record (parentheses) — keep unconditionally.
        if paren_depth > 0:
            in_q = False
            for ch in stripped:
                if ch == '"':
                    in_q = not in_q
                elif ch == ';' and not in_q:
                    break
                elif ch == '(' and not in_q:
                    paren_depth += 1
                elif ch == ')' and not in_q:
                    paren_depth -= 1
            cleaned.append(line)
            continue

        # Empty, directive, or full-line comment — always keep.
        if not stripped or stripped.startswith('$') or stripped.startswith(';'):
            cleaned.append(line)
            continue

        # Count paren deltas on this line (outside quotes / comments).
        line_paren_delta = 0
        in_q = False
        for ch in stripped:
            if ch == '"':
                in_q = not in_q
            elif ch == ';' and not in_q:
                break
            elif ch == '(' and not in_q:
                line_paren_delta += 1
            elif ch == ')' and not in_q:
                line_paren_delta -= 1

        # Strip inline comment for token analysis.
        no_comment = stripped
        in_q = False
        for ci, ch in enumerate(stripped):
            if ch == '"':
                in_q = not in_q
            elif ch == ';' and not in_q:
                no_comment = stripped[:ci].strip()
                break

        tokens_str = no_comment.replace('(', ' ').replace(')', ' ').strip()

        if not tokens_str:
            cleaned.append('; ' + line.lstrip())
            continue

        tokens = tokens_str.split()

        # Need at least 2 tokens for a valid record line.
        if len(tokens) < 2:
            cleaned.append('; ' + line.lstrip())
            continue

        # "name IN" with nothing after — no rdtype.
        if tokens[-1].upper() == 'IN':
            cleaned.append('; ' + line.lstrip())
            continue

        upper_tokens = [t.upper() for t in tokens]

        # Check for "IN <known_type>" pattern.
        has_valid_record = False
        for idx, tok in enumerate(upper_tokens):
            if tok == 'IN' and idx + 1 < len(upper_tokens):
                if upper_tokens[idx + 1] in _KNOWN_RDTYPES:
                    has_valid_record = True
                    break

        # Fallback: any known rdtype followed by at least one more token.
        if not has_valid_record:
            for idx, tok in enumerate(upper_tokens):
                if tok in _KNOWN_RDTYPES and idx + 1 < len(upper_tokens):
                    has_valid_record = True
                    break

        if has_valid_record:
            # De-indent tab-indented new records that would be misread as
            # continuation lines by dnspython.
            if line[0] in (' ', '\t') and 'IN' in upper_tokens and not tokens[0].isdigit():
                cleaned.append(stripped)
                paren_depth += line_paren_delta
                continue
            cleaned.append(line)
            paren_depth += line_paren_delta
        else:
            cleaned.append('; ' + line.lstrip())

    return '\n'.join(cleaned)


def _try_parse_zone(content, filename="zone"):
    """Try to parse a zone file using dnspython. Returns (zone, error_msg).

    Fallback chain when the initial parse fails:
    1. Strip conflicting CNAME lines (RFC 1034 coexistence).
    2. Preprocess to strip non-record lines.
    3. Iterative line stripping — comment out individual failing lines
       (up to 5 attempts) to salvage as many records as possible.
    """
    origin = _extract_origin(content)

    # --- attempt 1: raw content ---
    try:
        zone = dns.zone.from_text(content, origin=origin, relativize=True, check_origin=False)
        return zone, None
    except Exception as e:
        err = str(e)

    # --- attempt 2: strip conflicting CNAMEs ---
    if 'CNAME' in err:
        cleaned = _strip_conflicting_cnames(content)
        try:
            zone = dns.zone.from_text(cleaned, origin=origin, relativize=True, check_origin=False)
            return zone, None
        except Exception:
            pass

    # --- attempt 3: preprocess (strip non-record lines, de-indent) ---
    preprocessed = _preprocess_zone_content(content)
    try:
        zone = dns.zone.from_text(preprocessed, origin=origin, relativize=True, check_origin=False)
        return zone, None
    except Exception:
        pass

    # --- attempt 4: iterative single-line stripping (max 5 bad lines) ---
    text = preprocessed
    for _ in range(5):
        try:
            zone = dns.zone.from_text(text, origin=origin, relativize=True, check_origin=False)
            return zone, None
        except Exception as exc:
            m = re.search(r'<string>:(\d+)', str(exc))
            if not m:
                return None, str(exc)
            lineno = int(m.group(1))
            lines = text.split('\n')
            if lineno > len(lines):
                return None, str(exc)
            lines[lineno - 1] = '; [stripped] ' + lines[lineno - 1]
            text = '\n'.join(lines)

    # All attempts exhausted.
    try:
        zone = dns.zone.from_text(text, origin=origin, relativize=True, check_origin=False)
        return zone, None
    except Exception as e_final:
        return None, str(e_final)


def parse_zone_records(content):
    """Parse a zone file into a list of structured records.

    Returns a list of dicts:
      {name, ttl, rdtype, rdata_str, rdata_items}
    where rdata_items is a list of individual rdata string representations.
    """
    zone, err = _try_parse_zone(content)
    if zone is None:
        return [], err

    records = []
    for name, node in zone.items():
        name_str = name.to_text()
        for rdataset in node.rdatasets:
            rdtype_str = dns.rdatatype.to_text(rdataset.rdtype)
            rdata_items = []
            for rdata in rdataset:
                rdata_items.append(rdata.to_text())
            records.append({
                'name': name_str,
                'ttl': rdataset.ttl,
                'rdtype': rdtype_str,
                'rdata_items': sorted(rdata_items),
            })
    return records, None


def parse_all_zone_records(context):
    """Parse all zone files in a context dict. Returns (records_list, error_msg)."""
    all_records = []
    for filename, content in context.items():
        if filename.endswith('.zone') or filename.endswith('.db') or filename.endswith('.txt'):
            records, err = parse_zone_records(content)
            if err:
                return [], f"Error parsing {filename}: {err}"
            all_records.extend(records)
    return all_records, None


def record_fingerprint(record):
    """Create a fingerprint for matching records: (name, rdtype)."""
    return (record['name'].lower(), record['rdtype'])


def rdata_set_similarity(ref_items, gen_items):
    """Compare two sorted lists of rdata strings using Jaccard + fuzzy matching."""
    if not ref_items and not gen_items:
        return 1.0
    if not ref_items or not gen_items:
        return 0.0

    # Normalize rdata strings for comparison
    ref_set = {r.lower().strip().rstrip('.') for r in ref_items}
    gen_set = {r.lower().strip().rstrip('.') for r in gen_items}

    # Exact Jaccard
    intersection = len(ref_set & gen_set)
    union = len(ref_set | gen_set)

    if union == 0:
        return 1.0
    return intersection / union


def compute_record_coverage(ref_records, gen_records):
    """Compute Jaccard coverage on (name, rdtype) fingerprints."""
    if not ref_records and not gen_records:
        return 1.0
    if not ref_records or not gen_records:
        return 0.0

    ref_fps = {record_fingerprint(r) for r in ref_records}
    gen_fps = {record_fingerprint(r) for r in gen_records}

    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def compute_rdata_accuracy(ref_records, gen_records):
    """For records that match on (name, rdtype), compare their rdata."""
    # Group records by fingerprint
    ref_by_fp = {}
    for r in ref_records:
        fp = record_fingerprint(r)
        ref_by_fp[fp] = r

    gen_by_fp = {}
    for r in gen_records:
        fp = record_fingerprint(r)
        gen_by_fp[fp] = r

    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0

    scores = []
    for fp in matched_fps:
        ref_r = ref_by_fp[fp]
        gen_r = gen_by_fp[fp]
        sim = rdata_set_similarity(ref_r['rdata_items'], gen_r['rdata_items'])
        scores.append(sim)

    return sum(scores) / len(scores)


def compute_ttl_accuracy(ref_records, gen_records):
    """For matched records, compare TTL values."""
    ref_by_fp = {record_fingerprint(r): r for r in ref_records}
    gen_by_fp = {record_fingerprint(r): r for r in gen_records}

    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0

    scores = []
    for fp in matched_fps:
        ref_ttl = ref_by_fp[fp]['ttl']
        gen_ttl = gen_by_fp[fp]['ttl']
        if ref_ttl == gen_ttl:
            scores.append(1.0)
        elif ref_ttl == 0 or gen_ttl == 0:
            scores.append(0.0)
        else:
            # Ratio-based TTL similarity
            ratio = min(ref_ttl, gen_ttl) / max(ref_ttl, gen_ttl)
            scores.append(ratio)

    return sum(scores) / len(scores)


def compute_soa_accuracy(ref_records, gen_records):
    """Compare SOA records specifically, which carry critical zone metadata."""
    ref_soa = [r for r in ref_records if r['rdtype'] == 'SOA']
    gen_soa = [r for r in gen_records if r['rdtype'] == 'SOA']

    if not ref_soa and not gen_soa:
        return 1.0
    if not ref_soa or not gen_soa:
        return 0.0

    # Compare the SOA rdata (mname rname serial refresh retry expire minimum)
    ref_parts = ref_soa[0]['rdata_items'][0].lower().split() if ref_soa[0]['rdata_items'] else []
    gen_parts = gen_soa[0]['rdata_items'][0].lower().split() if gen_soa[0]['rdata_items'] else []

    if len(ref_parts) < 7 or len(gen_parts) < 7:
        return SequenceMatcher(None,
                               ' '.join(ref_parts),
                               ' '.join(gen_parts)).ratio()

    scores = []
    # mname (primary nameserver)
    scores.append(1.0 if ref_parts[0].rstrip('.') == gen_parts[0].rstrip('.') else 0.0)
    # rname (admin email)
    scores.append(1.0 if ref_parts[1].rstrip('.') == gen_parts[1].rstrip('.') else 0.0)
    # serial
    scores.append(1.0 if ref_parts[2] == gen_parts[2] else 0.0)
    # refresh, retry, expire, minimum — numeric comparison
    for i in range(3, 7):
        try:
            ref_val = int(ref_parts[i])
            gen_val = int(gen_parts[i])
            if ref_val == gen_val:
                scores.append(1.0)
            elif ref_val == 0 or gen_val == 0:
                scores.append(0.0)
            else:
                scores.append(min(ref_val, gen_val) / max(ref_val, gen_val))
        except ValueError:
            scores.append(1.0 if ref_parts[i] == gen_parts[i] else 0.0)

    return sum(scores) / len(scores)


def compute_record_type_distribution(ref_records, gen_records):
    """Compare the distribution of record types."""
    if not ref_records and not gen_records:
        return 1.0
    if not ref_records or not gen_records:
        return 0.0

    ref_types = {}
    for r in ref_records:
        ref_types[r['rdtype']] = ref_types.get(r['rdtype'], 0) + 1

    gen_types = {}
    for r in gen_records:
        gen_types[r['rdtype']] = gen_types.get(r['rdtype'], 0) + 1

    all_types = set(ref_types.keys()) | set(gen_types.keys())
    if not all_types:
        return 1.0

    # Jaccard on the type set + count similarity
    type_jaccard = len(set(ref_types.keys()) & set(gen_types.keys())) / len(all_types)

    count_sims = []
    for rtype in set(ref_types.keys()) & set(gen_types.keys()):
        rc = ref_types[rtype]
        gc = gen_types[rtype]
        count_sims.append(min(rc, gc) / max(rc, gc))

    count_sim = sum(count_sims) / len(count_sims) if count_sims else 0.0

    return 0.5 * type_jaccard + 0.5 * count_sim


def extract_comments(content):
    """Extract inline and standalone comments from zone file content."""
    comments = []
    for line in content.split('\n'):
        line_stripped = line.strip()
        # Skip empty lines and directives
        if not line_stripped or line_stripped.startswith('$'):
            continue
        # Standalone comment line
        if line_stripped.startswith(';'):
            comment_text = line_stripped[1:].strip()
            if comment_text:
                comments.append(comment_text.lower())
            continue
        # Inline comment after record data
        # Be careful not to match semicolons inside TXT record strings
        # Simple approach: find ; that's not inside quotes
        in_quote = False
        for i, ch in enumerate(line_stripped):
            if ch == '"':
                in_quote = not in_quote
            elif ch == ';' and not in_quote:
                comment_text = line_stripped[i + 1:].strip()
                if comment_text:
                    comments.append(comment_text.lower())
                break
    return comments


def compute_comment_score(ref_content, gen_content):
    """Compare comments between reference and generated zone files."""
    ref_comments = set()
    gen_comments = set()

    for content in (ref_content.values() if isinstance(ref_content, dict) else [ref_content]):
        ref_comments.update(extract_comments(content))

    for content in (gen_content.values() if isinstance(gen_content, dict) else [gen_content]):
        gen_comments.update(extract_comments(content))

    if not ref_comments and not gen_comments:
        return 1.0
    if not ref_comments:
        return 1.0  # Extra comments are fine
    if not gen_comments:
        return 0.0

    # Jaccard on comment sets
    intersection = len(ref_comments & gen_comments)
    union = len(ref_comments | gen_comments)
    return intersection / union if union > 0 else 1.0


class DomainDns(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "dns"
        self.summary = "BIND DNS zone files with SOA, NS, A, AAAA, MX, CNAME, TXT, SRV, and CAA records"
        self.description = "BIND DNS zone files"
        self.file_format = [".zone"]
        self.domain_parser = "dnspython"
        self.category = "code"

    def preprocess_context(self, context):
        """Normalize raw context before parsing.

        Strips a spurious first line when the LLM echoes the filename
        inside the code-block content (e.g. the first line equals the
        dict key).  This is a common LLM artefact that would otherwise
        cause dnspython to reject the whole zone.
        """
        cleaned = {}
        for filename, content in context.items():
            lines = content.split('\n')
            first = lines[0].strip() if lines else ''
            if first and (first == filename or first == filename.rstrip('.')):
                content = '\n'.join(lines[1:])
            cleaned[filename] = content
        return cleaned

    def parse_context(self, context):
        """Parse context dict into structured data: zone records and comments."""
        context = self.preprocess_context(context)
        all_records, err = parse_all_zone_records(context)

        all_comments = set()
        for filename, content in context.items():
            all_comments.update(extract_comments(content))

        return {
            "records": all_records,
            "parse_error": err,
            "comments": all_comments,
        }

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        if parsed["parse_error"]:
            return {"parse_error": parsed["parse_error"]}

        all_records = parsed["records"]

        type_counts = {}
        names = set()
        for r in all_records:
            type_counts[r['rdtype']] = type_counts.get(r['rdtype'], 0) + 1
            names.add(r['name'])

        return {
            "Hostnames": len(names),
            "Record Sets": len(all_records),
            "Total RRs": sum(len(r['rdata_items']) for r in all_records),
            "Record Types": len(type_counts),
            "Type Distribution": type_counts,
        }

    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}

        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)

        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(
            os.path.join(sample_folder, start_state["solution_folder"])
        )

        # Parse records from both contexts
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)

        if ref_parsed["parse_error"]:
            return {"score": 0.0, "error": f"Reference parse error: {ref_parsed['parse_error']}"}
        if gen_parsed["parse_error"]:
            return {"score": 0.0, "error": f"Generated parse error: {gen_parsed['parse_error']}"}

        ref_records = ref_parsed["records"]
        gen_records = gen_parsed["records"]

        if debug:
            print(f"Reference record sets: {len(ref_records)}, Generated record sets: {len(gen_records)}")

        # Compute component scores
        coverage = compute_record_coverage(ref_records, gen_records)
        rdata_accuracy = compute_rdata_accuracy(ref_records, gen_records)
        ttl_accuracy = compute_ttl_accuracy(ref_records, gen_records)
        soa_accuracy = compute_soa_accuracy(ref_records, gen_records)

        # Final score formula (comments excluded — they are cosmetic, not semantic):
        # coverage^2 (critical) * rdata_accuracy (critical) * sqrt((ttl + soa) / 2)
        auxiliary = (ttl_accuracy + soa_accuracy) / 2.0
        score = (coverage ** 2) * rdata_accuracy * math.sqrt(max(auxiliary, 0.0))

        eval_obj = {
            "score": score,
            "record_coverage": coverage,
            "rdata_accuracy": rdata_accuracy,
            "ttl_accuracy": ttl_accuracy,
            "soa_accuracy": soa_accuracy,
            "ref_record_sets": len(ref_records),
            "gen_record_sets": len(gen_records),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
