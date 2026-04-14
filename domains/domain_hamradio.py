from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
import adif_io


def preprocess_adif(text):
    """Fix common LLM errors in ADIF output before parsing.
    
    Three preprocessing steps:
    1. Fix field length specifiers — rewrite <FIELD:N> so N matches actual
       character count (up to next '<'). LLMs frequently get this wrong.
    2. Insert missing <EOR> tags — when no EOR delimiters exist, detect
       record boundaries by repeated core fields (QSO_DATE/CALL) and insert.
    3. Deduplicate fields within QSO records — when the same field name
       appears twice in one record (often identical values), keep only the
       last occurrence to avoid AdifDuplicateFieldError.
    
    Content values are never modified — only structural/syntactic repairs.
    """
    # Step 1: Fix field length specifiers
    text = re.sub(
        r'<([A-Za-z_][A-Za-z0-9_]*):(\d+)>([^<]*)',
        lambda m: f"<{m.group(1)}:{len(m.group(3))}>{m.group(3)}",
        text
    )

    # Step 2: Insert missing <EOR> tags
    # Find body after <EOH> (if present)
    eoh_match = re.search(r'<EOH[^>]*>', text, re.IGNORECASE)
    body_start = eoh_match.end() if eoh_match else 0
    header = text[:body_start]
    body = text[body_start:]

    if body.strip() and not re.search(r'<EOR>', body, re.IGNORECASE):
        # No EOR tags at all — insert before repeated core fields
        field_tag_re = re.compile(r'<([A-Za-z_]\w*):(\d+)>([^<]*)')
        seen_fields = set()
        new_body_parts = []
        last_boundary = 0  # start of text for current QSO record
        for m in field_tag_re.finditer(body):
            fname = m.group(1).upper()
            if fname in ('QSO_DATE', 'CALL') and fname in seen_fields:
                # Record boundary — include all text up to here as previous record
                new_body_parts.append(body[last_boundary:m.start()])
                new_body_parts.append('<EOR>\n')
                last_boundary = m.start()  # next record starts at this match
                seen_fields = set()
            seen_fields.add(fname)
        if new_body_parts:
            # Append final record
            new_body_parts.append(body[last_boundary:])
            body = ''.join(new_body_parts)
            # Add final EOR if not present
            if not body.rstrip().upper().endswith('<EOR>'):
                body = body.rstrip() + '\n<EOR>\n'
        text = header + body

    # Step 3: Deduplicate fields within each QSO record
    # Split body by <EOR>, deduplicate fields within each segment
    eoh_match = re.search(r'<EOH[^>]*>', text, re.IGNORECASE)
    body_start = eoh_match.end() if eoh_match else 0
    header = text[:body_start]
    body = text[body_start:]

    segments = re.split(r'(<EOR>)', body, flags=re.IGNORECASE)
    field_tag_re = re.compile(r'(<([A-Za-z_]\w*):(\d+)>[^<]*)')
    new_segments = []
    for seg in segments:
        if seg.upper() == '<EOR>':
            new_segments.append(seg)
            continue
        # Within this QSO segment, find all field tokens and deduplicate
        tokens = list(field_tag_re.finditer(seg))
        if not tokens:
            new_segments.append(seg)
            continue
        # Track last occurrence of each field name
        seen = {}
        for tok in tokens:
            fname = tok.group(2).upper()
            seen[fname] = tok  # last wins
        # Rebuild segment keeping only last occurrence of each field
        keep_spans = {(tok.start(), tok.end()) for tok in seen.values()}
        result_parts = []
        last_end = 0
        for tok in tokens:
            span = (tok.start(), tok.end())
            if span in keep_spans:
                # Include inter-tag text and the kept token
                result_parts.append(seg[last_end:tok.start()])
                result_parts.append(tok.group(0))
                last_end = tok.end()
            # For dropped duplicates: skip the token but keep scanning
            # (inter-tag text before the _next_ kept token will be included)
            else:
                # Advance last_end past the dropped token
                last_end = tok.end()
        result_parts.append(seg[last_end:])
        new_segments.append(''.join(result_parts))

    text = header + ''.join(new_segments)
    return text


def parse_adif_records(text):
    """Parse ADIF text into (header_text, list of QSO dicts).
    
    Uses adif_io library for robust parsing. Returns normalized field names
    (uppercase) and stripped values.
    """
    try:
        qsos_raw, header = adif_io.read_from_string(text)
    except Exception as e:
        print(f"\033[91mADIF parsing error: {e}\033[0m")
        return "", []

    header_text = str(header) if header else ""
    
    qsos = []
    for raw in qsos_raw:
        qso = {}
        for key, value in raw.items():
            qso[key.upper().strip()] = value.strip() if isinstance(value, str) else str(value)
        qsos.append(qso)
    return header_text, qsos


def parse_all_adif_records(context):
    """Parse all .adi/.adif files in a context dict, returning combined QSO list."""
    all_qsos = []
    for filename, content in context.items():
        lower = filename.lower()
        if lower.endswith('.adi') or lower.endswith('.adif'):
            _, qsos = parse_adif_records(content)
            all_qsos.extend(qsos)
    return all_qsos


def qso_fingerprint(qso):
    """Create a matching fingerprint from the core QSO fields.
    
    Uses CALL + QSO_DATE + TIME_ON + BAND as the primary identity.
    These four fields together uniquely identify a contact in any ham radio log.
    """
    call = qso.get('CALL', '').upper().strip()
    date = qso.get('QSO_DATE', '').strip()
    time_on = qso.get('TIME_ON', '').strip()
    band = qso.get('BAND', '').upper().strip()
    return f"{call}|{date}|{time_on}|{band}"


def normalize_freq(freq_str):
    """Normalize frequency string to MHz float, handling variations."""
    if not freq_str:
        return None
    freq_str = freq_str.strip().upper().replace('MHZ', '').strip()
    try:
        return round(float(freq_str), 6)
    except (ValueError, TypeError):
        return None


def normalize_rst(rst_str):
    """Normalize RST (signal report) string for comparison."""
    if not rst_str:
        return ''
    return rst_str.strip().upper()


def normalize_grid(grid_str):
    """Normalize Maidenhead grid square for comparison."""
    if not grid_str:
        return ''
    return grid_str.strip().upper()


QSO_CORE_FIELDS = ['CALL', 'QSO_DATE', 'TIME_ON', 'BAND', 'MODE', 'FREQ']
QSO_SIGNAL_FIELDS = ['RST_SENT', 'RST_RCVD']
QSO_GEO_FIELDS = ['GRIDSQUARE', 'MY_GRIDSQUARE', 'STATE', 'CNTY', 'CQZ', 'ITUZ', 'DXCC', 'CONT']
QSO_CONTACT_FIELDS = ['NAME', 'QTH']
QSO_META_FIELDS = ['QSL_SENT', 'QSL_RCVD', 'LOTW_QSL_SENT', 'EQSL_QSL_SENT',
                    'TX_PWR', 'COMMENT', 'NOTES', 'AWARD',
                    'TIME_OFF', 'QSO_DATE_OFF',
                    'LOTW_QSLSDATE', 'EQSL_QSLSDATE']

ALL_COMPARED_FIELDS = QSO_CORE_FIELDS + QSO_SIGNAL_FIELDS + QSO_GEO_FIELDS + QSO_CONTACT_FIELDS + QSO_META_FIELDS

# Also match APP_* fields dynamically
def get_all_field_names(qsos):
    """Collect all field names across a list of QSOs."""
    names = set()
    for qso in qsos:
        names.update(qso.keys())
    return names


def field_value_match(field, ref_val, gen_val):
    """Compare two field values, returning a similarity in [0, 1].
    
    Uses field-appropriate comparison (e.g., frequency tolerance, RST normalization).
    """
    if not ref_val and not gen_val:
        return 1.0
    if not ref_val or not gen_val:
        return 0.0
    
    ref_val = ref_val.strip()
    gen_val = gen_val.strip()
    
    if ref_val.upper() == gen_val.upper():
        return 1.0
    
    # Frequency: allow small floating-point tolerance
    if field == 'FREQ':
        ref_f = normalize_freq(ref_val)
        gen_f = normalize_freq(gen_val)
        if ref_f is not None and gen_f is not None:
            if abs(ref_f - gen_f) < 0.001:
                return 1.0
            elif abs(ref_f - gen_f) < 0.01:
                return 0.8
            else:
                return 0.0
        return 0.0
    
    # RST: normalize and compare
    if field in ('RST_SENT', 'RST_RCVD'):
        return 1.0 if normalize_rst(ref_val) == normalize_rst(gen_val) else 0.0
    
    # Grid square: case-insensitive
    if field in ('GRIDSQUARE', 'MY_GRIDSQUARE'):
        return 1.0 if normalize_grid(ref_val) == normalize_grid(gen_val) else 0.0
    
    # Band: case-insensitive
    if field in ('BAND',):
        return 1.0 if ref_val.upper() == gen_val.upper() else 0.0
    
    # Default: case-insensitive string similarity
    ref_lower = ref_val.lower()
    gen_lower = gen_val.lower()
    if ref_lower == gen_lower:
        return 1.0
    return SequenceMatcher(None, ref_lower, gen_lower).ratio()


def compute_qso_similarity(ref_qso, gen_qso):
    """Compute similarity between two matched QSOs across all fields.
    
    Returns a score in [0, 1] based on weighted field comparison.
    """
    # Collect all fields present in either QSO
    all_fields = set(ref_qso.keys()) | set(gen_qso.keys())
    # Filter to known compared fields + any APP_* fields
    compare_fields = [f for f in all_fields 
                      if f in ALL_COMPARED_FIELDS or f.startswith('APP_')]
    
    if not compare_fields:
        return 1.0
    
    # Weight fields by importance
    field_weights = {}
    for f in compare_fields:
        if f in QSO_CORE_FIELDS:
            field_weights[f] = 3.0
        elif f in QSO_SIGNAL_FIELDS:
            field_weights[f] = 2.0
        elif f in QSO_GEO_FIELDS:
            field_weights[f] = 1.5
        elif f in QSO_CONTACT_FIELDS:
            field_weights[f] = 1.5
        else:
            field_weights[f] = 1.0
    
    weighted_sum = 0.0
    total_weight = 0.0
    for f in compare_fields:
        w = field_weights.get(f, 1.0)
        ref_val = ref_qso.get(f, '')
        gen_val = gen_qso.get(f, '')
        sim = field_value_match(f, ref_val, gen_val)
        weighted_sum += w * sim
        total_weight += w
    
    return weighted_sum / total_weight if total_weight > 0 else 1.0


def compute_scores(ref_qsos, gen_qsos):
    """Compute coverage, field accuracy, and ordering scores.
    
    Uses fingerprint matching to pair QSOs, then evaluates field-level accuracy.
    Returns (coverage, field_accuracy, ordering).
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    
    if not ref_qsos and not gen_qsos:
        return 1.0, 1.0, 1.0
    if not ref_qsos or not gen_qsos:
        return 0.0, 0.0, 0.0
    
    n_ref = len(ref_qsos)
    n_gen = len(gen_qsos)
    
    # Build similarity matrix using fingerprints for matching, 
    # then detailed comparison for accuracy
    sim_matrix = np.zeros((n_ref, n_gen))
    for i, ref_qso in enumerate(ref_qsos):
        ref_fp = qso_fingerprint(ref_qso)
        for j, gen_qso in enumerate(gen_qsos):
            gen_fp = qso_fingerprint(gen_qso)
            # Fingerprint match gates detailed comparison
            if ref_fp == gen_fp:
                sim_matrix[i, j] = compute_qso_similarity(ref_qso, gen_qso)
            else:
                # Partial fingerprint match (e.g., same call + date but different time)
                ref_parts = ref_fp.split('|')
                gen_parts = gen_fp.split('|')
                partial_match = sum(1 for a, b in zip(ref_parts, gen_parts) if a == b)
                if partial_match >= 3:  # 3 of 4 core fields match
                    sim_matrix[i, j] = compute_qso_similarity(ref_qso, gen_qso) * 0.8
                elif partial_match >= 2:
                    sim_matrix[i, j] = compute_qso_similarity(ref_qso, gen_qso) * 0.3
    
    # Hungarian matching
    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    
    # Coverage: fraction of ref QSOs with a good match
    matched_pairs = [(i, j, sim_matrix[i, j]) for i, j in zip(row_ind, col_ind)]
    good_matches = sum(1 for _, _, sim in matched_pairs if sim > 0.3)
    coverage = good_matches / n_ref
    
    # Field accuracy: average similarity of well-matched pairs
    field_scores = [sim for _, _, sim in matched_pairs if sim > 0.3]
    field_accuracy = sum(field_scores) / len(field_scores) if field_scores else 0.0
    
    # Ordering: compare sequence of matched QSOs
    # Extract the order of matched ref indices from gen perspective
    matched_ref_order = [(i, j) for i, j, sim in matched_pairs if sim > 0.3]
    if len(matched_ref_order) <= 1:
        ordering = 1.0
    else:
        matched_ref_order.sort(key=lambda x: x[1])  # sort by gen position
        ref_indices = [i for i, j in matched_ref_order]
        # Count inversions relative to ref order
        ideal = sorted(ref_indices)
        ordering = SequenceMatcher(None, ref_indices, ideal).ratio()
    
    return coverage, field_accuracy, ordering


class DomainHamradio(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "hamradio"
        self.summary = "ADIF amateur radio QSO logs with contact records, signal reports, and geographic data"
        self.description = "ADIF amateur radio logs"
        self.file_format = [".adi"]
        self.domain_parser = "adif_io"
        self.category = "records"
    
    def preprocess_context(self, context):
        """Normalize raw ADIF context before parsing.
        
        Applies preprocess_adif to each .adi/.adif file to fix common LLM
        syntax errors (wrong field lengths, missing EOR tags, duplicate fields).
        """
        cleaned = {}
        for filename, content in context.items():
            lower = filename.lower()
            if lower.endswith('.adi') or lower.endswith('.adif'):
                cleaned[filename] = preprocess_adif(content)
            else:
                cleaned[filename] = content
        return cleaned

    def parse_all_qsos(self, context):
        return parse_all_adif_records(context)

    def parse_context(self, context):
        """Parse context into structured dict with QSO records."""
        context = self.preprocess_context(context)
        qsos = self.parse_all_qsos(context)
        return {"qsos": qsos}

    def compute_domain_statistics(self, context):
        qsos = self.parse_context(context)["qsos"]
        bands = set()
        modes = set()
        callsigns = set()
        states = set()
        for q in qsos:
            if q.get('BAND'):
                bands.add(q['BAND'].upper())
            if q.get('MODE'):
                modes.add(q['MODE'].upper())
            if q.get('CALL'):
                callsigns.add(q['CALL'].upper())
            if q.get('STATE'):
                states.add(q['STATE'].upper())
        return {
            "QSOs": len(qsos),
            "Bands": len(bands),
            "Modes": len(modes),
            "Unique Callsigns": len(callsigns),
            "States": len(states),
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
        
        ref_qsos = self.parse_context(reference_context)["qsos"]
        gen_qsos = self.parse_context(generated_context)["qsos"]
        
        if debug:
            print(f"Reference QSOs: {len(ref_qsos)}, Generated QSOs: {len(gen_qsos)}")
        
        coverage, field_accuracy, ordering = compute_scores(ref_qsos, gen_qsos)
        
        # Final score: coverage is most critical, field accuracy next, ordering last
        # coverage^2 ensures missing QSOs are heavily penalized
        # Weights: coverage 50%, field accuracy 35%, ordering 15%
        score = (coverage ** 2) * (0.50 + 0.35 * field_accuracy + 0.15 * ordering)
        
        eval_obj = {
            "score": score,
            "qso_coverage_score": coverage,
            "field_accuracy_score": field_accuracy,
            "ordering_score": ordering,
            "ref_qso_count": len(ref_qsos),
            "gen_qso_count": len(gen_qsos),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
