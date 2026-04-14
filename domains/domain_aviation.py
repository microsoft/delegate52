from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json


def parse_notam_entry(text):
    """Parse a single NOTAM entry into a structured dict.

    Expected format (ICAO NOTAM format):
        A1348/20 NOTAMN
        Q) LGGG/QFMLC/IV/BO /A /000/999/3647N02705E005
        A) LGKO B) 2005051152 C) 2006302359
        D) MAY 21 22  DAILY 0500-1900
        E) ANEMOMETER RWY32 U/S.
        F) GND                             G) 1000FT AMSL
        CREATED: 05 May 2020 11:55:00
        SOURCE: LGGGYNYX

    Returns dict with keys: notam_id, notam_type, replaced_id, q_line, location,
    valid_from, valid_to, schedule, text, lower_alt, upper_alt, created, source,
    fir, qcode, traffic, purpose, scope, q_lower, q_upper, q_coords
    """
    entry = {
        'notam_id': '', 'notam_type': '', 'replaced_id': '',
        'q_line': '', 'location': '', 'valid_from': '', 'valid_to': '',
        'schedule': '', 'text': '', 'lower_alt': '', 'upper_alt': '',
        'created': '', 'source': '',
        'fir': '', 'qcode': '', 'traffic': '', 'purpose': '', 'scope': '',
        'q_lower': '', 'q_upper': '', 'q_coords': '',
    }

    lines = text.strip().split('\n')
    if not lines:
        return entry

    # Parse first line: NOTAM ID and type
    first_line = lines[0].strip()
    # Match patterns like: A1348/20 NOTAMN or B0535/20 NOTAMR B0419/20
    id_match = re.match(r'(\S+)\s+(NOTAM[NRC])(?:\s+(\S+))?', first_line)
    if id_match:
        entry['notam_id'] = id_match.group(1)
        entry['notam_type'] = id_match.group(2)
        if id_match.group(3):
            entry['replaced_id'] = id_match.group(3)
    else:
        # Accept bare NOTAM ID without type suffix (LLMs sometimes omit NOTAMN/R/C)
        bare_id_match = re.match(r'([A-Z]\d+/\d+)\s*$', first_line)
        if bare_id_match:
            entry['notam_id'] = bare_id_match.group(1)

    # Join remaining lines for field extraction
    rest = '\n'.join(lines[1:])

    # Parse Q) line
    q_match = re.search(r'Q\)\s*(.+?)(?=\n[A-G]\)|\nCREATED|\nSOURCE|\Z)', rest, re.DOTALL | re.IGNORECASE)
    if q_match:
        q_raw = q_match.group(1).strip()
        entry['q_line'] = q_raw
        # Parse Q-line components: FIR/QCODE/TRAFFIC/PURPOSE/SCOPE/LOWER/UPPER/COORDS
        q_parts = re.match(
            r'(\w+)/(\w+)/(\w+)/(\S+)\s*/(\S+)\s*/(\d+)/(\d+)/(.+)',
            q_raw
        )
        if q_parts:
            entry['fir'] = q_parts.group(1)
            entry['qcode'] = q_parts.group(2)
            entry['traffic'] = q_parts.group(3)
            entry['purpose'] = q_parts.group(4).strip()
            entry['scope'] = q_parts.group(5).strip()
            entry['q_lower'] = q_parts.group(6)
            entry['q_upper'] = q_parts.group(7)
            entry['q_coords'] = q_parts.group(8).strip()

    # Parse A) location — may be on same line as B) and C)
    a_match = re.search(r'A\)\s*(\w+)', rest)
    if a_match:
        entry['location'] = a_match.group(1)

    # Parse B) valid from
    b_match = re.search(r'B\)\s*(\S+)', rest)
    if b_match:
        entry['valid_from'] = b_match.group(1)

    # Parse C) valid to
    c_match = re.search(r'C\)\s*(\S+)', rest)
    if c_match:
        entry['valid_to'] = c_match.group(1)

    # Parse D) schedule (optional, can be multi-line until E))
    d_match = re.search(r'D\)\s*(.+?)(?=\nE\))', rest, re.DOTALL)
    if d_match:
        entry['schedule'] = d_match.group(1).strip()

    # Parse E) text (can be multi-line, until F) or G) or CREATED or SOURCE or end)
    e_match = re.search(r'E\)\s*(.+?)(?=\nF\)|\nG\)|\nCREATED|\nSOURCE|\Z)', rest, re.DOTALL | re.IGNORECASE)
    if e_match:
        entry['text'] = e_match.group(1).strip()

    # Parse F) lower altitude (optional)
    f_match = re.search(r'F\)\s*(.+?)(?=\s{2,}G\)|\nG\)|\nCREATED|\nSOURCE|\Z)', rest, re.DOTALL | re.IGNORECASE)
    if f_match:
        entry['lower_alt'] = f_match.group(1).strip()

    # Parse G) upper altitude (optional)
    g_match = re.search(r'G\)\s*(.+?)(?=\nCREATED|\nSOURCE|\Z)', rest, re.DOTALL | re.IGNORECASE)
    if g_match:
        entry['upper_alt'] = g_match.group(1).strip()

    # Parse CREATED timestamp (case-insensitive — LLMs may output Created:/created:)
    created_match = re.search(r'CREATED:\s*(.+?)(?=\nSOURCE|\Z)', rest, re.DOTALL | re.IGNORECASE)
    if created_match:
        entry['created'] = created_match.group(1).strip()

    # Parse SOURCE (case-insensitive)
    source_match = re.search(r'SOURCE:\s*(.+?)(?=\Z)', rest, re.DOTALL | re.IGNORECASE)
    if source_match:
        entry['source'] = source_match.group(1).strip()

    return entry


def split_notams(content):
    """Split a NOTAM bulletin into individual NOTAM entries.
    
    NOTAMs are separated by blank lines. Each starts with an ID line
    matching the pattern: LETTER+DIGITS/DIGITS NOTAM[NRC]
    """
    entries = []
    current = []

    for line in content.split('\n'):
        # Check if this line starts a new NOTAM entry
        # Accept both "A1348/20 NOTAMN" and bare "A1348/20" (LLMs sometimes omit the type)
        if re.match(r'^[A-Z]\d+/\d+(?:\s+NOTAM[NRC]|\s*$)', line.strip()) and current:
            # Save previous entry
            entry_text = '\n'.join(current).strip()
            if entry_text:
                entries.append(entry_text)
            current = [line]
        else:
            current.append(line)

    # Don't forget the last entry
    if current:
        entry_text = '\n'.join(current).strip()
        if entry_text:
            entries.append(entry_text)

    return entries


def parse_notam_file(content):
    """Parse a NOTAM file (potentially containing multiple NOTAMs) into a list of parsed entries."""
    raw_entries = split_notams(content)
    parsed = []
    for raw in raw_entries:
        entry = parse_notam_entry(raw)
        if entry['notam_id']:  # Only keep entries that parsed successfully
            parsed.append(entry)
    return parsed


def parse_all_notams(context):
    """Parse all NOTAM files in a context dict. Returns list of parsed entries."""
    all_entries = []
    for filename, content in context.items():
        entries = parse_notam_file(content)
        all_entries.extend(entries)
    return all_entries


def notam_fingerprint(entry):
    """Create a fingerprint for matching NOTAMs: NOTAM ID."""
    return entry['notam_id'].upper().strip()


def compute_notam_coverage(ref_entries, gen_entries):
    """Compute Jaccard coverage on NOTAM ID fingerprints."""
    if not ref_entries and not gen_entries:
        return 1.0
    if not ref_entries or not gen_entries:
        return 0.0

    ref_fps = {notam_fingerprint(e) for e in ref_entries}
    gen_fps = {notam_fingerprint(e) for e in gen_entries}

    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def field_similarity(ref_val, gen_val):
    """Compare two field values. Returns [0, 1]."""
    if not ref_val and not gen_val:
        return 1.0
    if not ref_val or not gen_val:
        return 0.0
    ref_norm = ' '.join(ref_val.upper().split())
    gen_norm = ' '.join(gen_val.upper().split())
    if ref_norm == gen_norm:
        return 1.0
    return SequenceMatcher(None, ref_norm, gen_norm).ratio()


def compute_header_accuracy(ref_entries, gen_entries):
    """Compare NOTAM header fields (ID, type, Q-line, location, dates) for matched entries.

    Fields compared with weights:
    - notam_type: 0.10 (NOTAMN/R/C)
    - replaced_id: 0.05
    - location: 0.15
    - qcode: 0.15
    - valid_from: 0.15
    - valid_to: 0.10
    - schedule: 0.10
    - lower_alt: 0.10
    - upper_alt: 0.10
    """
    ref_by_id = {notam_fingerprint(e): e for e in ref_entries}
    gen_by_id = {notam_fingerprint(e): e for e in gen_entries}

    matched_ids = set(ref_by_id.keys()) & set(gen_by_id.keys())
    if not matched_ids:
        return 0.0

    field_weights = {
        'notam_type': 0.10,
        'replaced_id': 0.05,
        'location': 0.15,
        'qcode': 0.15,
        'valid_from': 0.15,
        'valid_to': 0.10,
        'schedule': 0.10,
        'lower_alt': 0.10,
        'upper_alt': 0.10,
    }

    scores = []
    for nid in matched_ids:
        ref = ref_by_id[nid]
        gen = gen_by_id[nid]
        entry_score = 0.0
        for field, weight in field_weights.items():
            sim = field_similarity(ref.get(field, ''), gen.get(field, ''))
            entry_score += sim * weight
        scores.append(entry_score)

    return sum(scores) / len(scores)


def compute_text_accuracy(ref_entries, gen_entries):
    """Compare E) free-text field for matched NOTAMs using SequenceMatcher."""
    ref_by_id = {notam_fingerprint(e): e for e in ref_entries}
    gen_by_id = {notam_fingerprint(e): e for e in gen_entries}

    matched_ids = set(ref_by_id.keys()) & set(gen_by_id.keys())
    if not matched_ids:
        return 0.0

    scores = []
    for nid in matched_ids:
        ref_text = ref_by_id[nid].get('text', '')
        gen_text = gen_by_id[nid].get('text', '')
        sim = field_similarity(ref_text, gen_text)
        scores.append(sim)

    return sum(scores) / len(scores)


def compute_q_line_accuracy(ref_entries, gen_entries):
    """Compare the full Q) qualifier line for matched NOTAMs."""
    ref_by_id = {notam_fingerprint(e): e for e in ref_entries}
    gen_by_id = {notam_fingerprint(e): e for e in gen_entries}

    matched_ids = set(ref_by_id.keys()) & set(gen_by_id.keys())
    if not matched_ids:
        return 0.0

    scores = []
    for nid in matched_ids:
        ref_q = ref_by_id[nid].get('q_line', '')
        gen_q = gen_by_id[nid].get('q_line', '')
        sim = field_similarity(ref_q, gen_q)
        scores.append(sim)

    return sum(scores) / len(scores)


def compute_metadata_accuracy(ref_entries, gen_entries):
    """Compare CREATED and SOURCE metadata for matched NOTAMs."""
    ref_by_id = {notam_fingerprint(e): e for e in ref_entries}
    gen_by_id = {notam_fingerprint(e): e for e in gen_entries}

    matched_ids = set(ref_by_id.keys()) & set(gen_by_id.keys())
    if not matched_ids:
        return 0.0

    scores = []
    for nid in matched_ids:
        ref = ref_by_id[nid]
        gen = gen_by_id[nid]
        created_sim = field_similarity(ref.get('created', ''), gen.get('created', ''))
        source_sim = field_similarity(ref.get('source', ''), gen.get('source', ''))
        scores.append(0.6 * created_sim + 0.4 * source_sim)

    return sum(scores) / len(scores)


def compute_sequence_score(ref_entries, gen_entries):
    """Compare ordering of NOTAMs by ID sequence."""
    if not ref_entries and not gen_entries:
        return 1.0
    if not ref_entries or not gen_entries:
        return 0.0

    ref_seq = [notam_fingerprint(e) for e in ref_entries]
    gen_seq = [notam_fingerprint(e) for e in gen_entries]

    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


class DomainAviation(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "aviation"
        self.summary = "ICAO NOTAM bulletin with military exercises, obstacles, aerodrome ops, and navigation aid notices"
        self.description = "ICAO NOTAM notices"
        self.file_format = [".txt"]
        self.domain_parser = "custom"
        self.category = "science"

    def parse_context(self, context):
        """Parse context dict of filename->content into structured NOTAM data.

        Returns dict with:
            - entries: list of parsed NOTAM entry dicts
            - entry_count: number of parsed NOTAMs
            - locations: set of unique ICAO location codes
            - by_id: dict mapping NOTAM fingerprint -> entry
        """
        entries = parse_all_notams(context)
        return {
            "entries": entries,
            "entry_count": len(entries),
            "locations": {e['location'] for e in entries},
            "by_id": {notam_fingerprint(e): e for e in entries},
        }

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        all_entries = parsed["entries"]
        if not all_entries:
            return {"parse_error": "No NOTAMs parsed"}

        locations = set()
        qcodes = {}
        types = {}
        has_schedule = 0
        has_altitudes = 0

        for e in all_entries:
            locations.add(e['location'])
            qc = e['qcode']
            qcodes[qc] = qcodes.get(qc, 0) + 1
            nt = e['notam_type']
            types[nt] = types.get(nt, 0) + 1
            if e['schedule']:
                has_schedule += 1
            if e['lower_alt'] or e['upper_alt']:
                has_altitudes += 1

        return {
            "NOTAM Count": len(all_entries),
            "Locations": len(locations),
            "Q-Code Types": len(qcodes),
            "NOTAM Types": types,
            "With Schedule": has_schedule,
            "With Altitudes": has_altitudes,
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

        # Parse entries from both contexts
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        ref_entries = ref_parsed["entries"]
        gen_entries = gen_parsed["entries"]

        if not ref_entries:
            return {"score": 0.0, "error": "Reference context has no parseable NOTAMs"}
        if not gen_entries:
            return {"score": 0.0, "error": "Generated context has no parseable NOTAMs"}

        if debug:
            print(f"Reference NOTAMs: {len(ref_entries)}, Generated NOTAMs: {len(gen_entries)}")

        # Compute component scores
        coverage = compute_notam_coverage(ref_entries, gen_entries)
        header_accuracy = compute_header_accuracy(ref_entries, gen_entries)
        text_accuracy = compute_text_accuracy(ref_entries, gen_entries)
        q_line_accuracy = compute_q_line_accuracy(ref_entries, gen_entries)
        metadata_accuracy = compute_metadata_accuracy(ref_entries, gen_entries)
        sequence_score = compute_sequence_score(ref_entries, gen_entries)

        # Score formula:
        # coverage^2 (critical gate) × content_accuracy × sqrt((metadata + sequence) / 2)
        # where content_accuracy = weighted mix of header, text, and q-line accuracy
        # Content is the most important, metadata and ordering are secondary
        content_accuracy = 0.30 * header_accuracy + 0.45 * text_accuracy + 0.25 * q_line_accuracy
        auxiliary = (metadata_accuracy + sequence_score) / 2.0
        score = (coverage ** 2) * content_accuracy * math.sqrt(max(auxiliary, 0.0))

        eval_obj = {
            "score": score,
            "notam_coverage": coverage,
            "header_accuracy": header_accuracy,
            "text_accuracy": text_accuracy,
            "q_line_accuracy": q_line_accuracy,
            "metadata_accuracy": metadata_accuracy,
            "sequence_score": sequence_score,
            "ref_notam_count": len(ref_entries),
            "gen_notam_count": len(gen_entries),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
