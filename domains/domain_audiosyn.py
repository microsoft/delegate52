from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json


def _normalize_numeric_token(tok):
    """Normalize a numeric token to a canonical string representation.

    Handles common LLM formatting variations that are semantically equivalent
    in CSound:
      - leading-zero omission: '.6' -> '0.6'
      - trailing zeros: '89.700000' -> '89.7'
      - integer vs float: '960' vs '960.0' -> both kept as-is after
        stripping trailing zeros (so '960.0' -> '960.0' stays, and '960' stays)
    """
    try:
        val = float(tok)
    except (ValueError, OverflowError):
        return tok  # not a number — return unchanged
    # Format back to canonical string: strips trailing zeros, keeps '.0' for floats
    if val == int(val) and 'e' not in tok.lower() and 'E' not in tok:
        return str(int(val))
    # Use repr-style to avoid losing precision, then strip trailing zeros
    formatted = f"{val:.15g}"
    return formatted


def _normalize_score_line(line):
    """Normalize numeric tokens in a CSound score event line (i/f statement).

    Preserves comments, only touches whitespace-delimited numeric tokens.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(';'):
        return line

    # Only process i-statements and f-statements
    if not (stripped.startswith('i') or stripped.startswith('f')):
        return line

    # Separate code from inline comment
    comment = ''
    if ';' in stripped:
        code_part, comment = stripped.split(';', 1)
        comment = ';' + comment
    else:
        code_part = stripped

    tokens = code_part.split()
    if len(tokens) < 2:
        return line

    # First token: i<instr> or f<num> — normalize the number part after the letter
    prefix_char = tokens[0][0]  # 'i' or 'f'
    instr_part = tokens[0][1:]
    normalized_first = prefix_char + _normalize_numeric_token(instr_part) if instr_part else tokens[0]

    # Normalize remaining tokens (skip carry '.')
    normalized = [normalized_first]
    for tok in tokens[1:]:
        if tok == '.':
            normalized.append(tok)
        else:
            normalized.append(_normalize_numeric_token(tok))

    result = ' '.join(normalized)
    if comment:
        result += ' ' + comment
    return result


def _preprocess_csd_content(content):
    """Normalize numeric formatting in the CsScore section of a CSD file.

    Applies _normalize_score_line to each line within <CsScore>...</CsScore>
    to canonicalize numeric representations so that semantically identical
    events produce identical fingerprints.
    """
    m = re.search(r'(<CsScore>)(.*?)(</CsScore>)', content,
                  re.DOTALL | re.IGNORECASE)
    if not m:
        return content

    open_tag = m.group(1)
    score_body = m.group(2)
    close_tag = m.group(3)

    # Normalize each line in the score section
    lines = score_body.split('\n')
    normalized_lines = [_normalize_score_line(line) for line in lines]
    normalized_body = '\n'.join(normalized_lines)

    return content[:m.start()] + open_tag + normalized_body + close_tag + content[m.end():]


def parse_csd_sections(content):
    """Parse a CSD file into its three main sections: options, instruments, score.
    
    A CSD file has the structure:
        <CsoundSynthesizer>
        <CsOptions> ... </CsOptions>
        <CsInstruments> ... </CsInstruments>
        <CsScore> ... </CsScore>
        </CsoundSynthesizer>
    
    Returns dict with keys: options, instruments_raw, score_raw
    """
    result = {'options': '', 'instruments_raw': '', 'score_raw': ''}
    
    # Extract CsOptions
    m = re.search(r'<CsOptions>(.*?)</CsOptions>', content, re.DOTALL | re.IGNORECASE)
    if m:
        result['options'] = m.group(1).strip()
    
    # Extract CsInstruments
    m = re.search(r'<CsInstruments>(.*?)</CsInstruments>', content, re.DOTALL | re.IGNORECASE)
    if m:
        result['instruments_raw'] = m.group(1).strip()
    
    # Extract CsScore
    m = re.search(r'<CsScore>(.*?)</CsScore>', content, re.DOTALL | re.IGNORECASE)
    if m:
        result['score_raw'] = m.group(1).strip()
    
    return result


def parse_header_settings(instruments_raw):
    """Extract sr, ksmps, nchnls, 0dbfs from instruments section header."""
    settings = {}
    for key in ['sr', 'ksmps', 'nchnls', '0dbfs']:
        m = re.search(rf'^\s*{re.escape(key)}\s*=\s*(\S+)', instruments_raw, re.MULTILINE)
        if m:
            settings[key] = m.group(1).strip()
    return settings


def parse_instruments(instruments_raw):
    """Parse instrument blocks from the CsInstruments section.
    
    Each instrument is delimited by 'instr <number_or_name>' and 'endin'.
    Returns list of dicts: {id, name, body, comments}
    """
    instruments = []
    # Find all instr...endin blocks including preceding comment block
    pattern = re.compile(
        r'((?:;[^\n]*\n)*)'     # preceding comment lines (group 1)
        r'\s*instr\s+(\S+)'     # instr keyword + identifier (group 2)
        r'(.*?)'                # body (group 3)
        r'endin',               # endin keyword
        re.DOTALL
    )
    
    for m in pattern.finditer(instruments_raw):
        comments = m.group(1).strip()
        instr_id = m.group(2).strip().rstrip(',')
        body = m.group(3).strip()
        
        # Extract variable assignments and opcode calls from body
        body_lines = [line.strip() for line in body.split('\n') if line.strip() and not line.strip().startswith(';')]
        
        instruments.append({
            'id': instr_id,
            'comments': comments,
            'body': body,
            'body_lines': body_lines,
            'body_line_count': len(body_lines),
        })
    
    return instruments


def parse_function_tables(score_raw):
    """Parse f-statements (function table definitions) from score.
    
    Format: f<num> <time> <size> <gen_routine> <args...>
    Returns list of dicts: {table_num, time, size, gen_routine, args, comment, raw}
    """
    tables = []
    for line in score_raw.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith(';'):
            continue
        # Match f-statement: f1 0 65536 10 1
        m = re.match(r'^f(\d+)\s+([\d.]+)\s+(\d+)\s+(-?\d+)\s*(.*?)(?:\s*;(.*))?$', stripped)
        if m:
            args_str = m.group(5).strip()
            comment = m.group(6).strip() if m.group(6) else ''
            tables.append({
                'table_num': int(m.group(1)),
                'time': float(m.group(2)),
                'size': int(m.group(3)),
                'gen_routine': int(m.group(4)),
                'args': args_str,
                'comment': comment,
                'raw': stripped,
            })
    return tables


def parse_score_events(score_raw):
    """Parse i-statements (note events) from score.
    
    Format: i<instr> <start> <dur> <p4> <p5> ... ;comment
    Handles carry (.) for repeated values.
    
    Returns list of dicts: {instr, start, dur, pfields, comment, raw}
    """
    events = []
    last_values = {}  # track last values per position for carry (.)
    
    for line in score_raw.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith(';') or stripped.startswith('f') or stripped.startswith('e'):
            continue
        
        # Match i-statement
        # Split on comment first
        comment = ''
        if ';' in stripped:
            code_part, comment = stripped.split(';', 1)
            comment = comment.strip()
        else:
            code_part = stripped
        
        code_part = code_part.strip()
        if not code_part.startswith('i'):
            continue
        
        # Tokenize: split on whitespace
        tokens = code_part.split()
        if len(tokens) < 3:
            continue
        
        # First token is i<instr>
        instr_str = tokens[0][1:]  # remove leading 'i'
        
        # Resolve carry (.) for each field
        resolved = [instr_str]
        for i, tok in enumerate(tokens[1:], 1):
            if tok == '.':
                # Carry from last event's same field position
                resolved.append(last_values.get(i, tok))
            else:
                resolved.append(tok)
        
        # Update last_values for carry
        for i, val in enumerate(resolved):
            last_values[i] = val
        
        # Parse resolved values
        instr = resolved[0]
        start = resolved[1] if len(resolved) > 1 else '0'
        dur = resolved[2] if len(resolved) > 2 else '0'
        pfields = resolved[3:] if len(resolved) > 3 else []
        
        events.append({
            'instr': instr,
            'start': start,
            'dur': dur,
            'pfields': pfields,
            'comment': comment,
            'raw': stripped,
        })
    
    return events


def parse_score_comments(score_raw):
    """Extract comment lines from the score section (section headers, descriptions)."""
    comments = []
    for line in score_raw.split('\n'):
        stripped = line.strip()
        if stripped.startswith(';'):
            comments.append(stripped)
    return comments


def parse_opcodes(instruments_raw):
    """Parse user-defined opcodes (UDOs) from the instruments section.
    
    Format: opcode <name>, <output_types>, <input_types>
            ... body ...
            endop
    """
    opcodes = []
    pattern = re.compile(
        r'((?:;[^\n]*\n)*)'          # preceding comments
        r'\s*opcode\s+(\w+)'         # opcode name
        r'\s*,\s*([^,]+)'            # output types
        r'\s*,\s*([^\n]+)'           # input types
        r'(.*?)'                     # body
        r'endop',                    # endop
        re.DOTALL
    )
    
    for m in pattern.finditer(instruments_raw):
        comments = m.group(1).strip()
        name = m.group(2).strip()
        out_types = m.group(3).strip()
        in_types = m.group(4).strip()
        body = m.group(5).strip()
        
        opcodes.append({
            'name': name,
            'out_types': out_types,
            'in_types': in_types,
            'body': body,
            'comments': comments,
        })
    
    return opcodes


def parse_global_variables(instruments_raw):
    """Extract global variable definitions (gi_, gk_, ga_, gS_ prefixed) from instruments section."""
    globals_list = []
    for line in instruments_raw.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith(';'):
            continue
        # Match global variable assignment: gi_foo = ..., or giXxx ftgen ...
        m = re.match(r'^(g[ikaS]\w*)\s*(?:=|ftgen)\s*(.*?)(?:\s*;(.*))?$', stripped)
        if m:
            globals_list.append({
                'name': m.group(1),
                'value': m.group(2).strip(),
                'comment': m.group(3).strip() if m.group(3) else '',
            })
    return globals_list


def parse_macros(instruments_raw):
    """Extract #define macros from the instruments section."""
    macros = []
    for line in instruments_raw.split('\n'):
        stripped = line.strip()
        m = re.match(r'^#define\s+(\w+)\s+#(.+?)#', stripped)
        if m:
            macros.append({
                'name': m.group(1),
                'value': m.group(2).strip(),
            })
    return macros


def parse_csound(content):
    """Parse a complete CSD file into structured representation.
    
    Returns dict with:
        - options: command line options string
        - settings: {sr, ksmps, nchnls, 0dbfs}
        - instruments: list of instrument dicts
        - opcodes: list of UDO dicts
        - macros: list of macro dicts
        - globals: list of global variable dicts
        - function_tables: list of f-statement dicts
        - score_events: list of i-statement dicts
        - score_comments: list of score comment strings
        - instruments_raw: raw orchestra section
        - score_raw: raw score section
    """
    sections = parse_csd_sections(content)
    instruments_raw = sections['instruments_raw']
    score_raw = sections['score_raw']
    
    return {
        'options': sections['options'],
        'settings': parse_header_settings(instruments_raw),
        'instruments': parse_instruments(instruments_raw),
        'opcodes': parse_opcodes(instruments_raw),
        'macros': parse_macros(instruments_raw),
        'globals': parse_global_variables(instruments_raw),
        'function_tables': parse_function_tables(score_raw),
        'score_events': parse_score_events(score_raw),
        'score_comments': parse_score_comments(score_raw),
        'instruments_raw': instruments_raw,
        'score_raw': score_raw,
    }


# --- Evaluator scoring functions ---

def compute_instrument_score(ref_instrs, gen_instrs):
    """Compare instruments by ID matching and body similarity.
    
    Returns (coverage, accuracy) tuple.
    Coverage: Jaccard on instrument IDs.
    Accuracy: average body similarity for matched instruments.
    """
    if not ref_instrs and not gen_instrs:
        return 1.0, 1.0
    if not ref_instrs or not gen_instrs:
        return 0.0, 0.0
    
    ref_ids = {i['id'] for i in ref_instrs}
    gen_ids = {i['id'] for i in gen_instrs}
    
    # Coverage: Jaccard
    intersection = ref_ids & gen_ids
    union = ref_ids | gen_ids
    coverage = len(intersection) / len(union) if union else 1.0
    
    # Accuracy: body similarity for matched instruments
    ref_by_id = {i['id']: i for i in ref_instrs}
    gen_by_id = {i['id']: i for i in gen_instrs}
    
    if not intersection:
        return coverage, 0.0
    
    body_scores = []
    for iid in intersection:
        ref_body = ref_by_id[iid]['body']
        gen_body = gen_by_id[iid]['body']
        # Normalize whitespace for comparison
        ref_norm = re.sub(r'\s+', ' ', ref_body).strip()
        gen_norm = re.sub(r'\s+', ' ', gen_body).strip()
        body_scores.append(SequenceMatcher(None, ref_norm, gen_norm).ratio())
    
    accuracy = sum(body_scores) / len(body_scores) if body_scores else 0.0
    return coverage, accuracy


def compute_score_event_score(ref_events, gen_events):
    """Compare score events using sequence matching on (instr, start, dur, pfields).
    
    Returns (coverage, accuracy, sequence) tuple.
    """
    if not ref_events and not gen_events:
        return 1.0, 1.0, 1.0
    if not ref_events or not gen_events:
        return 0.0, 0.0, 0.0
    
    def event_fingerprint(ev):
        pf = ','.join(ev['pfields'])
        return f"{ev['instr']}|{ev['start']}|{ev['dur']}|{pf}"
    
    ref_fps = [event_fingerprint(e) for e in ref_events]
    gen_fps = [event_fingerprint(e) for e in gen_events]
    
    ref_set = set(ref_fps)
    gen_set = set(gen_fps)
    
    # Coverage: Jaccard
    intersection = ref_set & gen_set
    union = ref_set | gen_set
    coverage = len(intersection) / len(union) if union else 1.0
    
    # Accuracy: for matched events, compare pfields more precisely
    # Use Hungarian matching for best pairing based on similarity
    ref_remaining = [e for e, fp in zip(ref_events, ref_fps) if fp in intersection]
    gen_remaining = [e for e, fp in zip(gen_events, gen_fps) if fp in intersection]
    accuracy = 1.0 if intersection else 0.0  # exact matches by fingerprint
    
    # For non-matching events, compute partial similarity
    ref_unmatched = [fp for fp in ref_fps if fp not in intersection]
    gen_unmatched = [fp for fp in gen_fps if fp not in intersection]
    if ref_unmatched and gen_unmatched:
        # Compute average best-match similarity
        partial_scores = []
        for r_fp in ref_unmatched:
            best = max(SequenceMatcher(None, r_fp, g_fp).ratio() for g_fp in gen_unmatched)
            partial_scores.append(best)
        partial_avg = sum(partial_scores) / len(partial_scores)
        # Blend exact match fraction with partial scores
        exact_frac = len(intersection) / len(ref_set) if ref_set else 1.0
        accuracy = exact_frac * 1.0 + (1 - exact_frac) * partial_avg
    
    # Sequence: ordering similarity
    sequence = SequenceMatcher(None, ref_fps, gen_fps).ratio()
    
    return coverage, accuracy, sequence


def compute_function_table_score(ref_tables, gen_tables):
    """Compare function table definitions.
    
    Returns (coverage, accuracy) tuple.
    """
    if not ref_tables and not gen_tables:
        return 1.0, 1.0
    if not ref_tables or not gen_tables:
        return 0.0, 0.0
    
    ref_by_num = {t['table_num']: t for t in ref_tables}
    gen_by_num = {t['table_num']: t for t in gen_tables}
    
    ref_nums = set(ref_by_num.keys())
    gen_nums = set(gen_by_num.keys())
    
    intersection = ref_nums & gen_nums
    union = ref_nums | gen_nums
    coverage = len(intersection) / len(union) if union else 1.0
    
    if not intersection:
        return coverage, 0.0
    
    # Accuracy: compare gen_routine + args for matched tables
    scores = []
    for num in intersection:
        r = ref_by_num[num]
        g = gen_by_num[num]
        # Gen routine must match
        gen_match = 1.0 if r['gen_routine'] == g['gen_routine'] else 0.0
        # Size should match
        size_match = 1.0 if r['size'] == g['size'] else min(r['size'], g['size']) / max(r['size'], g['size'])
        # Args similarity
        args_sim = SequenceMatcher(None, r['args'], g['args']).ratio()
        scores.append(0.3 * gen_match + 0.2 * size_match + 0.5 * args_sim)
    
    accuracy = sum(scores) / len(scores)
    return coverage, accuracy


def compute_settings_score(ref_settings, gen_settings):
    """Compare header settings (sr, ksmps, nchnls, 0dbfs)."""
    if not ref_settings and not gen_settings:
        return 1.0
    if not ref_settings or not gen_settings:
        return 0.0
    
    all_keys = set(ref_settings.keys()) | set(gen_settings.keys())
    if not all_keys:
        return 1.0
    
    matches = sum(1 for k in all_keys if ref_settings.get(k) == gen_settings.get(k))
    return matches / len(all_keys)


def compute_comment_score(ref_comments, gen_comments):
    """Compare score section comments using sequence matching."""
    if not ref_comments and not gen_comments:
        return 1.0
    if not ref_comments or not gen_comments:
        return 0.0
    
    # Normalize comments: strip semicolons and whitespace
    def norm(c):
        return re.sub(r'\s+', ' ', c.lstrip(';').strip()).lower()
    
    ref_norm = [norm(c) for c in ref_comments if norm(c)]
    gen_norm = [norm(c) for c in gen_comments if norm(c)]
    
    if not ref_norm and not gen_norm:
        return 1.0
    if not ref_norm or not gen_norm:
        return 0.0
    
    return SequenceMatcher(None, ref_norm, gen_norm).ratio()


def merge_all_csd_content(context):
    """Merge all .csd file content from a context dict."""
    merged = ""
    for filename, content in context.items():
        if filename.endswith('.csd') or filename.endswith('.orc') or filename.endswith('.sco'):
            merged += content + "\n"
    return merged


class DomainAudiosyn(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "audiosyn"
        self.summary = "CSound audio synthesis with instruments, function tables, and score events"
        self.description = "CSound audio synthesis"
        self.file_format = [".csd"]
        self.domain_parser = "custom"
        self.category = "creative"
    
    def preprocess_context(self, context):
        """Normalize CSD content before parsing.

        Fixes minor LLM formatting differences that are semantically equivalent
        in CSound score events: leading-zero omission (.6 vs 0.6), trailing
        decimal zeros (89.700000 vs 89.7), and integer/float formatting
        (960 vs 960.0).
        """
        cleaned = {}
        for filename, content in context.items():
            if filename.endswith('.csd') or filename.endswith('.orc') or filename.endswith('.sco'):
                cleaned[filename] = _preprocess_csd_content(content)
            else:
                cleaned[filename] = content
        return cleaned

    def parse_context(self, context):
        """Parse a context dict (filename->content) into structured CSD data.
        
        Merges all CSD/ORC/SCO files and parses the combined content.
        
        Returns dict with parsed CSD structure including:
            options, settings, instruments, opcodes, macros, globals,
            function_tables, score_events, score_comments,
            instruments_raw, score_raw, merged_content
        """
        context = self.preprocess_context(context)
        merged = merge_all_csd_content(context)
        parsed = parse_csound(merged)
        parsed['merged_content'] = merged
        return parsed
    
    def compute_domain_statistics(self, context):
        try:
            parsed = self.parse_context(context)
        except Exception:
            return {}
        if not parsed['instruments'] and not parsed['score_events']:
            return {}
        return {
            "Instruments": len(parsed['instruments']),
            "UDOs": len(parsed['opcodes']),
            "Function Tables": len(parsed['function_tables']),
            "Score Events": len(parsed['score_events']),
            "Macros": len(parsed['macros']),
            "Settings": parsed['settings'],
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        # Parse all relevant files
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        
        if not ref_parsed['merged_content'].strip():
            return {"score": 0.0, "error": "empty_reference"}
        if not gen_parsed['merged_content'].strip():
            return {"score": 0.0, "error": "empty_generated"}
        
        # Component scores
        instr_coverage, instr_accuracy = compute_instrument_score(
            ref_parsed['instruments'], gen_parsed['instruments']
        )
        
        event_coverage, event_accuracy, event_sequence = compute_score_event_score(
            ref_parsed['score_events'], gen_parsed['score_events']
        )
        
        ftable_coverage, ftable_accuracy = compute_function_table_score(
            ref_parsed['function_tables'], gen_parsed['function_tables']
        )
        
        settings_score = compute_settings_score(
            ref_parsed['settings'], gen_parsed['settings']
        )
        
        comment_score = compute_comment_score(
            ref_parsed['score_comments'], gen_parsed['score_comments']
        )
        
        # Raw text similarity as fallback
        ref_norm = re.sub(r'\s+', ' ', ref_parsed['merged_content']).strip()
        gen_norm = re.sub(r'\s+', ' ', gen_parsed['merged_content']).strip()
        raw_text_score = SequenceMatcher(None, ref_norm, gen_norm).ratio()
        
        # Scoring formula: geometric weighted mean of multiplicative gates,
        # modulated by auxiliary detail scores.
        #
        # Core content gates (coverage² × accuracy):
        #   instr_gate: orchestra instrument definitions
        #   event_gate: score note events (i-statements)
        #
        # Core = instr_gate^0.5 × event_gate^0.5 (geometric mean)
        # This ensures removing K/N of either component drops score by ~K/N.
        #
        # Auxiliary scores (function tables, settings, comments, sequence, raw text)
        # are averaged and applied as sqrt-modulator.
        
        instr_gate = instr_coverage ** 2.5 * instr_accuracy
        event_gate = event_coverage ** 2.5 * event_accuracy
        
        aux_mean = (
            0.25 * ftable_coverage * ftable_accuracy +
            0.15 * settings_score +
            0.25 * comment_score +
            0.25 * event_sequence +
            0.10 * raw_text_score
        )
        
        # Geometric weighted mean — removing 1/3 of either component drops core by ~1/3
        core = max(instr_gate, 0.0001) ** 0.5 * max(event_gate, 0.0001) ** 0.5
        
        score = core * math.sqrt(max(aux_mean, 0.001))
        
        eval_obj = {
            "score": round(score, 6),
            "instrument_coverage": round(instr_coverage, 4),
            "instrument_accuracy": round(instr_accuracy, 4),
            "instrument_gate": round(instr_gate, 4),
            "event_coverage": round(event_coverage, 4),
            "event_accuracy": round(event_accuracy, 4),
            "event_sequence": round(event_sequence, 4),
            "event_gate": round(event_gate, 4),
            "core": round(core, 4),
            "aux_mean": round(aux_mean, 4),
            "ftable_coverage": round(ftable_coverage, 4),
            "ftable_accuracy": round(ftable_accuracy, 4),
            "settings_score": round(settings_score, 4),
            "comment_score": round(comment_score, 4),
            "raw_text_score": round(raw_text_score, 4),
            "ref_instrument_count": len(ref_parsed['instruments']),
            "gen_instrument_count": len(gen_parsed['instruments']),
            "ref_event_count": len(ref_parsed['score_events']),
            "gen_event_count": len(gen_parsed['score_events']),
            "ref_ftable_count": len(ref_parsed['function_tables']),
            "gen_ftable_count": len(gen_parsed['function_tables']),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
