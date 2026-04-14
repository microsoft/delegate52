from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
import numpy as np
from scipy.optimize import linear_sum_assignment


# ---- TLE Parsing ----

def parse_tle_line1(line):
    """Parse TLE line 1 into a dict of fields.
    
    Line 1 format (1-indexed columns):
      Col  1     : Line number (always '1')
      Col  3-7   : Satellite catalog number
      Col  8     : Classification (U/C/S)
      Col 10-11  : International designator - launch year
      Col 12-14  : International designator - launch number
      Col 15-17  : International designator - piece of launch
      Col 19-20  : Epoch year (2-digit)
      Col 21-32  : Epoch day of year + fractional day
      Col 34-43  : First derivative of mean motion (rev/day²)
      Col 45-52  : Second derivative of mean motion (rev/day³) - assumed decimal point
      Col 54-61  : BSTAR drag term - assumed decimal point
      Col 63     : Ephemeris type
      Col 65-68  : Element set number
      Col 69     : Checksum
    """
    # Require at least 62 chars to cover all scoring-relevant fields
    # (through BSTAR at cols 54-61). Trailing fields (ephemeris type,
    # element set number, checksum) are extracted safely via slicing.
    if len(line) < 62:
        return None
    
    try:
        return {
            'catalog_number': line[2:7].strip(),
            'classification': line[7:8].strip(),
            'intl_designator': line[9:17].strip(),
            'epoch_year': line[18:20].strip(),
            'epoch_day': line[20:32].strip(),
            'mean_motion_dot': line[33:43].strip(),
            'mean_motion_ddot': line[44:52].strip(),
            'bstar': line[53:61].strip(),
            'ephemeris_type': line[62:63].strip() if len(line) > 62 else '',
            'element_set_number': line[64:68].strip() if len(line) > 64 else '',
            'checksum': line[68:69].strip() if len(line) > 68 else '',
        }
    except Exception:
        return None


def parse_tle_line2(line):
    """Parse TLE line 2 into a dict of fields.
    
    Line 2 format (1-indexed columns):
      Col  1     : Line number (always '2')
      Col  3-7   : Satellite catalog number
      Col  9-16  : Inclination (degrees)
      Col 18-25  : Right Ascension of Ascending Node (degrees)
      Col 27-33  : Eccentricity (assumed leading decimal point)
      Col 35-42  : Argument of Perigee (degrees)
      Col 44-51  : Mean Anomaly (degrees)
      Col 53-63  : Mean Motion (revs/day)
      Col 64-68  : Revolution number at epoch
      Col 69     : Checksum
    """
    # Require at least 63 chars to cover all scoring-relevant fields
    # (through mean_motion at cols 53-63). Trailing fields (rev number,
    # checksum) are extracted safely via slicing.
    if len(line) < 63:
        return None
    
    try:
        return {
            'catalog_number': line[2:7].strip(),
            'inclination': line[8:16].strip(),
            'raan': line[17:25].strip(),
            'eccentricity': line[26:33].strip(),
            'arg_perigee': line[34:42].strip(),
            'mean_anomaly': line[43:51].strip(),
            'mean_motion': line[52:63].strip(),
            'rev_number': line[63:68].strip() if len(line) > 63 else '',
            'checksum': line[68:69].strip() if len(line) > 68 else '',
        }
    except Exception:
        return None


def parse_tle_entries(content):
    """Parse a 3LE (three-line element) file into a list of satellite entries.
    
    Each entry is a dict with:
      - name: satellite name (line 0)
      - line1: parsed fields from TLE line 1
      - line2: parsed fields from TLE line 2
      - raw_name: original name line
      - raw_line1: original line 1 string
      - raw_line2: original line 2 string
    """
    entries = []
    lines = content.strip().split('\n')
    lines = [l.rstrip() for l in lines]
    
    i = 0
    while i < len(lines):
        # Skip blank lines and comments
        if not lines[i].strip() or lines[i].strip().startswith('#'):
            i += 1
            continue
        
        # Check for 3LE format: name line followed by line 1 and line 2
        if (i + 2 < len(lines) and
            not lines[i].startswith('1 ') and
            not lines[i].startswith('2 ') and
            lines[i+1].startswith('1 ') and
            lines[i+2].startswith('2 ')):
            
            name = lines[i].strip()
            l1 = parse_tle_line1(lines[i+1])
            l2 = parse_tle_line2(lines[i+2])
            
            if l1 and l2:
                entries.append({
                    'name': name,
                    'line1': l1,
                    'line2': l2,
                    'raw_name': lines[i],
                    'raw_line1': lines[i+1],
                    'raw_line2': lines[i+2],
                })
            i += 3
        # Check for 2LE format: just line 1 and line 2 (no name line)
        elif (i + 1 < len(lines) and
              lines[i].startswith('1 ') and
              lines[i+1].startswith('2 ')):
            
            l1 = parse_tle_line1(lines[i])
            l2 = parse_tle_line2(lines[i+1])
            
            if l1 and l2:
                entries.append({
                    'name': '',
                    'line1': l1,
                    'line2': l2,
                    'raw_name': '',
                    'raw_line1': lines[i],
                    'raw_line2': lines[i+1],
                })
            i += 2
        else:
            i += 1
    
    return entries


def parse_all_tle_entries(context):
    """Parse all TLE entries from all files in a context dict."""
    all_entries = []
    for filename, content in sorted(context.items()):
        entries = parse_tle_entries(content)
        all_entries.extend(entries)
    return all_entries


# ---- TLE Field Comparison ----

def safe_float(s):
    """Try to parse a string as float, return None on failure."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_assumed_decimal(s):
    """Parse TLE assumed-decimal notation (e.g., '11458-3' -> 0.11458e-3).
    
    In TLE format, BSTAR and mean_motion_ddot use an assumed decimal point:
    ' 11458-3' means 0.11458 * 10^-3 = 1.1458e-4
    '+12345-2' means 0.12345 * 10^-2
    """
    s = s.strip()
    if not s or s == '00000+0' or s == '00000-0':
        return 0.0
    
    # Match patterns like '11458-3', '+12345-2', '-12345+3'
    m = re.match(r'^([+-]?)(\d+)([+-]\d+)$', s)
    if m:
        sign = -1 if m.group(1) == '-' else 1
        mantissa = float('0.' + m.group(2))
        exponent = int(m.group(3))
        return sign * mantissa * (10 ** exponent)
    
    # Try direct float
    try:
        return float(s)
    except ValueError:
        return None


def compare_float_fields(ref_val, gen_val, tolerance=1e-8):
    """Compare two float values, return similarity score [0, 1]."""
    if ref_val is None and gen_val is None:
        return 1.0
    if ref_val is None or gen_val is None:
        return 0.0
    
    ref_f = safe_float(ref_val) if isinstance(ref_val, str) else ref_val
    gen_f = safe_float(gen_val) if isinstance(gen_val, str) else gen_val
    
    if ref_f is None or gen_f is None:
        return 0.0
    
    if ref_f == gen_f:
        return 1.0
    
    # Use relative error for large values, absolute for small
    max_abs = max(abs(ref_f), abs(gen_f))
    if max_abs < tolerance:
        return 1.0  # Both effectively zero
    
    rel_error = abs(ref_f - gen_f) / max_abs
    # Score based on relative error: perfect at 0, drops to 0 at 100% error
    return max(0.0, 1.0 - rel_error)


def compare_string_fields(ref_val, gen_val):
    """Compare two string values, return 1.0 if exact match, 0.0 otherwise."""
    if ref_val is None and gen_val is None:
        return 1.0
    if ref_val is None or gen_val is None:
        return 0.0
    return 1.0 if ref_val.strip() == gen_val.strip() else 0.0


def compare_tle_entries(ref_entry, gen_entry):
    """Compare two TLE entries and return a similarity score [0, 1].
    
    Component scores:
      - Name match (10%): exact name comparison (case-insensitive, trimmed)
      - Identity fields (10%): catalog number, classification, intl designator
      - Epoch (15%): epoch year + epoch day fraction
      - Orbital elements (50%): inclination, RAAN, eccentricity, arg perigee, 
                                 mean anomaly, mean motion
      - Drag & derivatives (15%): BSTAR, mean motion dot, mean motion ddot, rev number
    """
    rl1, rl2 = ref_entry['line1'], ref_entry['line2']
    gl1, gl2 = gen_entry['line1'], gen_entry['line2']
    
    # Name match (case-insensitive)
    ref_name = ref_entry['name'].strip().upper()
    gen_name = gen_entry['name'].strip().upper()
    if ref_name == gen_name:
        name_score = 1.0
    else:
        name_score = SequenceMatcher(None, ref_name, gen_name).ratio()
    
    # Identity fields
    identity_scores = [
        compare_string_fields(rl1['catalog_number'], gl1['catalog_number']),
        compare_string_fields(rl1['classification'], gl1['classification']),
        compare_string_fields(rl1['intl_designator'], gl1['intl_designator']),
    ]
    identity_score = sum(identity_scores) / len(identity_scores)
    
    # Epoch
    epoch_year_score = compare_string_fields(rl1['epoch_year'], gl1['epoch_year'])
    epoch_day_score = compare_float_fields(rl1['epoch_day'], gl1['epoch_day'])
    epoch_score = 0.3 * epoch_year_score + 0.7 * epoch_day_score
    
    # Orbital elements (the core of the TLE)
    orbital_scores = [
        compare_float_fields(rl2['inclination'], gl2['inclination']),
        compare_float_fields(rl2['raan'], gl2['raan']),
        compare_float_fields(rl2['eccentricity'], gl2['eccentricity']),
        compare_float_fields(rl2['arg_perigee'], gl2['arg_perigee']),
        compare_float_fields(rl2['mean_anomaly'], gl2['mean_anomaly']),
        compare_float_fields(rl2['mean_motion'], gl2['mean_motion']),
    ]
    orbital_score = sum(orbital_scores) / len(orbital_scores)
    
    # Drag and derivatives
    bstar_ref = parse_assumed_decimal(rl1['bstar'])
    bstar_gen = parse_assumed_decimal(gl1['bstar'])
    bstar_score = compare_float_fields(bstar_ref, bstar_gen)
    
    mmddot_ref = parse_assumed_decimal(rl1['mean_motion_ddot'])
    mmddot_gen = parse_assumed_decimal(gl1['mean_motion_ddot'])
    mmddot_score = compare_float_fields(mmddot_ref, mmddot_gen)
    
    mmdot_score = compare_float_fields(rl1['mean_motion_dot'], gl1['mean_motion_dot'])
    rev_score = compare_string_fields(rl2['rev_number'], gl2['rev_number'])
    
    drag_score = 0.4 * bstar_score + 0.2 * mmdot_score + 0.1 * mmddot_score + 0.3 * rev_score
    
    return {
        'name_score': name_score,
        'identity_score': identity_score,
        'epoch_score': epoch_score,
        'orbital_score': orbital_score,
        'drag_score': drag_score,
        'total': (0.10 * name_score + 0.10 * identity_score + 0.15 * epoch_score +
                  0.50 * orbital_score + 0.15 * drag_score),
    }


# ---- Entry Matching ----

def match_entries(ref_entries, gen_entries):
    """Match reference entries to generated entries using catalog number and name.
    
    Returns list of (ref_idx, gen_idx) pairs.
    Uses Hungarian algorithm with a similarity matrix based on
    catalog number match (primary) and name similarity (secondary).
    """
    if not ref_entries or not gen_entries:
        return []
    
    n_ref = len(ref_entries)
    n_gen = len(gen_entries)
    
    # Build cost matrix
    sim_matrix = np.zeros((n_ref, n_gen))
    for i, ref in enumerate(ref_entries):
        for j, gen in enumerate(gen_entries):
            # Catalog number match is primary
            cat_match = 1.0 if ref['line1']['catalog_number'] == gen['line1']['catalog_number'] else 0.0
            # Name similarity is secondary
            ref_name = ref['name'].strip().upper()
            gen_name = gen['name'].strip().upper()
            name_sim = SequenceMatcher(None, ref_name, gen_name).ratio() if ref_name and gen_name else 0.0
            
            sim_matrix[i, j] = 0.7 * cat_match + 0.3 * name_sim
    
    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    return list(zip(row_ind.tolist(), col_ind.tolist()))


# ---- Task Class ----

class DomainSatellite(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "satellite"
        self.summary = "TLE (Two-Line Element) satellite orbital data files"
        self.description = "TLE satellite orbital data"
        self.file_format = [".tle"]
        self.domain_parser = "custom"
        self.category = "science"
    
    def preprocess_context(self, context):
        """Normalize raw context before parsing.
        
        Strips comment-only lines (starting with #) that are not part of TLE
        data, and ensures consistent line endings.
        """
        cleaned = {}
        for fname, content in context.items():
            lines = content.split('\n')
            # Strip trailing whitespace from each line (TLE is fixed-width,
            # but models sometimes add/drop trailing spaces)
            lines = [l.rstrip() for l in lines]
            cleaned[fname] = '\n'.join(lines)
        return cleaned
    
    def parse_all_entries(self, context):
        context = self.preprocess_context(context)
        return parse_all_tle_entries(context)
    
    def parse_context(self, context):
        context = self.preprocess_context(context)
        entries = parse_all_tle_entries(context)
        return {"entries": entries}
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        entries = parsed["entries"]
        if entries:
            inclinations = [safe_float(e['line2']['inclination']) for e in entries if safe_float(e['line2']['inclination']) is not None]
            mean_motions = [safe_float(e['line2']['mean_motion']) for e in entries if safe_float(e['line2']['mean_motion']) is not None]
            return {
                "Satellites": len(entries),
                "Files": len(context),
                "Inc Range": f"{min(inclinations):.1f}-{max(inclinations):.1f}°" if inclinations else "N/A",
                "MM Range": f"{min(mean_motions):.2f}-{max(mean_motions):.2f}" if mean_motions else "N/A",
            }
        return {"Satellites": 0, "Files": len(context)}
    
    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        ref_entries = self.parse_context(reference_context)["entries"]
        gen_entries = self.parse_context(generated_context)["entries"]
        
        if debug:
            print(f"Reference entries: {len(ref_entries)}, Generated entries: {len(gen_entries)}")
        
        if not ref_entries and not gen_entries:
            return {"score": 1.0}
        if not ref_entries or not gen_entries:
            return {"score": 0.0, "error": "empty_entries"}
        
        # Match entries
        matched_pairs = match_entries(ref_entries, gen_entries)
        
        # Count coverage
        n_ref = len(ref_entries)
        n_gen = len(gen_entries)
        n_matched = len(matched_pairs)
        
        # Entry coverage: penalize missing or extra entries
        coverage_score = n_matched / max(n_ref, n_gen) if max(n_ref, n_gen) > 0 else 1.0
        
        # Field accuracy: average comparison score across ALL reference entries
        # Unmatched reference entries get score 0
        matched_ref_indices = {p[0] for p in matched_pairs}
        entry_scores = []
        if n_ref > 0:
            pair_dict = {ref_idx: gen_idx for ref_idx, gen_idx in matched_pairs}
            for ref_idx in range(n_ref):
                if ref_idx in pair_dict:
                    score_dict = compare_tle_entries(ref_entries[ref_idx], gen_entries[pair_dict[ref_idx]])
                    entry_scores.append(score_dict['total'])
                else:
                    entry_scores.append(0.0)
            field_accuracy = sum(entry_scores) / len(entry_scores)
        else:
            field_accuracy = 0.0
        
        # Extra entries penalty: penalize generated entries not matched to reference
        extra_gen = max(0, n_gen - n_matched)
        extra_penalty = extra_gen / max(n_ref, n_gen) if max(n_ref, n_gen) > 0 else 0.0
        
        # Sequence preservation: check if order is maintained
        if len(matched_pairs) >= 2:
            ref_order = [p[0] for p in matched_pairs]
            # Check if reference indices are in sorted order
            is_sorted = all(ref_order[i] <= ref_order[i+1] for i in range(len(ref_order)-1))
            if is_sorted:
                sequence_score = 1.0
            else:
                # Use Kendall tau distance
                n = len(ref_order)
                concordant = 0
                total = n * (n - 1) // 2
                for i in range(n):
                    for j in range(i + 1, n):
                        if ref_order[i] < ref_order[j]:
                            concordant += 1
                sequence_score = concordant / total if total > 0 else 1.0
        else:
            sequence_score = 1.0
        
        # Score = field_accuracy (inherently proportional since missing entries get 0)
        # Apply sequence penalty: wrong order reduces score by up to 10%
        # Apply extra entries penalty: spurious entries reduce score by up to 5%
        order_factor = 0.90 + 0.10 * sequence_score  # 0.90 to 1.0
        score = field_accuracy * order_factor - 0.05 * extra_penalty
        score = max(0.0, min(1.0, score))
        
        eval_obj = {
            "score": score,
            "field_accuracy": field_accuracy,
            "entry_coverage": coverage_score,
            "sequence_score": sequence_score,
            "ref_entry_count": n_ref,
            "gen_entry_count": n_gen,
            "matched_count": n_matched,
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
