from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, ujson as json
import srt


def _preprocess_srt_content(content):
    """Normalize raw SRT content to handle common LLM formatting quirks."""
    lines = content.splitlines()
    cleaned = []
    for line in lines:
        # Only process timestamp lines (contain ' --> ')
        if ' --> ' in line:
            # 1. Strip trailing comments after the timestamp range
            #    e.g. "00:07:08,000 --> 00:07:13,000  <-- Note: ..." → keep only the timestamp part
            line = re.sub(r'(\d[\d:,.\s]*-->[\s\d:,.]+\d)\s+<--.*', r'\1', line)
            line = re.sub(r'(\d[\d:,.\s]*-->[\s\d:,.]+\d)\s+#.*', r'\1', line)

            # 2. Fix question-mark placeholders in timestamps: 00:06:59,?33 → 00:06:59,033
            line = re.sub(r'\?', '0', line)

            # 3. Fix 4-segment timestamps with extra leading segment:
            #    00:00:00:41,000 → 00:00:41,000  (drop the extra leading HH:)
            def fix_four_segment_ts(m):
                # Split on colons; if 4+ colon-segments, drop the first
                ts = m.group(0)
                colon_parts = ts.split(':')
                if len(colon_parts) == 4:
                    # e.g. ['00','00','00','41,000'] → drop first → '00:00:41,000'
                    return ':'.join(colon_parts[1:])
                return ts
            line = re.sub(r'\d{2}:\d{2}:\d{2}:\d{2},\d{3}', fix_four_segment_ts, line)

        cleaned.append(line)
    return '\n'.join(cleaned)


def _strip_speaker_label(content):
    """Strip speaker labels prepended to subtitle content by LLMs.
    
    When models convert from screenplay format back to SRT, they often keep
    speaker labels that don't belong in the original SRT:
      - Separate line:  'CELIA\\nYou're a jerk, Thom.'  →  'You're a jerk, Thom.'
      - Inline colon:   'CELIA: You're a jerk, Thom.'   →  'You're a jerk, Thom.'
      - With markers:   'THOM (cont\\'d)\\nLine...'       →  'Line...'
    
    Speaker labels are identified as ALL-CAPS names (2+ chars) optionally followed
    by parenthetical markers like (cont'd), (V.O.), (O.S.).
    """
    stripped = content.strip()
    lines = stripped.split('\n')
    
    # Pattern 1: speaker on its own first line, actual text on subsequent lines
    if len(lines) >= 2:
        first = lines[0].strip()
        if re.match(r"^[A-Z][A-Z '.]+(?:\s*\([^)]*\))?\s*$", first):
            return '\n'.join(lines[1:]).strip()
    
    # Pattern 2: inline "SPEAKER: text" or "SPEAKER (marker): text"
    m = re.match(r"^[A-Z][A-Z '.]+(?:\s*\([^)]*\))?\s*:\s*", stripped)
    if m:
        rest = stripped[m.end():]
        if rest:  # only strip if there's actual text after
            return rest
    
    return content


def parse_srt_entries(content):
    try:
        entries = list(srt.parse(content))
    except Exception as e:
        print(f"\033[91mSRT parsing error: {e}\033[0m")
        return []
    
    parsed = []
    for entry in entries:
        content_text = _strip_speaker_label(entry.content.strip())
        parsed.append({
            'index': entry.index,
            'start_ms': int(entry.start.total_seconds() * 1000),
            'end_ms': int(entry.end.total_seconds() * 1000),
            'content': content_text,
        })
    return parsed


def parse_all_srt_entries(context):
    all_entries = []
    for filename, content in context.items():
        if filename.endswith('.srt'):
            entries = parse_srt_entries(content)
            all_entries.extend(entries)
    return all_entries


def normalize_text(text):
    # Normalize whitespace and case for comparison
    return ' '.join(text.lower().split())


def compute_entry_coverage_score(ref_entries, gen_entries):
    if not ref_entries and not gen_entries:
        return 1.0
    if not ref_entries or not gen_entries:
        return 0.0
    
    # Use normalized text content as fingerprint
    ref_fps = {normalize_text(e['content']) for e in ref_entries}
    gen_fps = {normalize_text(e['content']) for e in gen_entries}
    
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def compute_text_accuracy_score(ref_entries, gen_entries):
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    
    if not ref_entries and not gen_entries:
        return 1.0, []
    if not ref_entries or not gen_entries:
        return 0.0, []
    
    n_ref, n_gen = len(ref_entries), len(gen_entries)
    
    # Build similarity matrix based on text content
    sim_matrix = np.zeros((n_ref, n_gen))
    for i, ref in enumerate(ref_entries):
        for j, gen in enumerate(gen_entries):
            sim_matrix[i, j] = SequenceMatcher(None, normalize_text(ref['content']), normalize_text(gen['content'])).ratio()
    
    # Hungarian algorithm to find optimal matching
    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    
    # Compute average text similarity for matched pairs
    matched_pairs = list(zip(row_ind, col_ind))
    text_scores = [sim_matrix[i, j] for i, j in matched_pairs]
    
    return sum(text_scores) / n_ref if text_scores else 0.0, matched_pairs


def compute_timing_accuracy_score(ref_entries, gen_entries, matched_pairs):
    if not matched_pairs:
        return 1.0 if (not ref_entries and not gen_entries) else 0.0
    
    timing_scores = []
    for ref_idx, gen_idx in matched_pairs:
        ref = ref_entries[ref_idx]
        gen = gen_entries[gen_idx]
        
        # Compare start times
        ref_start, gen_start = ref['start_ms'], gen['start_ms']
        if ref_start == 0 and gen_start == 0:
            start_score = 1.0
        elif ref_start == 0 or gen_start == 0:
            start_score = 0.0
        else:
            start_score = min(ref_start, gen_start) / max(ref_start, gen_start)
        
        # Compare end times
        ref_end, gen_end = ref['end_ms'], gen['end_ms']
        if ref_end == 0 and gen_end == 0:
            end_score = 1.0
        elif ref_end == 0 or gen_end == 0:
            end_score = 0.0
        else:
            end_score = min(ref_end, gen_end) / max(ref_end, gen_end)
        
        timing_scores.append((start_score + end_score) / 2.0)
    
    return sum(timing_scores) / len(timing_scores) if timing_scores else 0.0


def compute_sequence_score(ref_entries, gen_entries, matched_pairs):
    if not matched_pairs:
        return 1.0 if (not ref_entries and not gen_entries) else 0.0
    
    # Sort both by start time to get canonical order
    ref_sorted_indices = sorted(range(len(ref_entries)), key=lambda i: ref_entries[i]['start_ms'])
    gen_sorted_indices = sorted(range(len(gen_entries)), key=lambda i: gen_entries[i]['start_ms'])
    
    # Map original indices to sorted positions
    ref_rank = {idx: rank for rank, idx in enumerate(ref_sorted_indices)}
    gen_rank = {idx: rank for rank, idx in enumerate(gen_sorted_indices)}
    
    # Build sequences of ranks for matched pairs
    ref_seq = [ref_rank[ref_idx] for ref_idx, _ in matched_pairs]
    gen_seq = [gen_rank[gen_idx] for _, gen_idx in matched_pairs]
    
    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


class DomainSubtitles(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "subtitles"
        self.summary = "SRT subtitle files with timestamps, dialogue, and formatting"
        self.description = "SRT subtitle files"
        self.file_format = [".srt"]
        self.domain_parser = "srt"
        self.category = "creative"
    
    def preprocess_context(self, context):
        """Normalize raw SRT content before parsing to handle common LLM formatting quirks."""
        cleaned = {}
        for filename, content in context.items():
            if filename.endswith('.srt'):
                content = _preprocess_srt_content(content)
            cleaned[filename] = content
        return cleaned

    def parse_all_entries(self, context):
        return parse_all_srt_entries(context)

    def parse_context(self, context):
        context = self.preprocess_context(context)
        entries = self.parse_all_entries(context)
        return {"entries": entries}
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        entries = parsed["entries"]
        total_text = sum(len(e.get('content', '')) for e in entries)
        if entries:
            start = min(e.get('start_ms', 0) for e in entries)
            end = max(e.get('end_ms', 0) for e in entries)
            duration_min = round((end - start) / 60000, 1)
        else:
            duration_min = 0
        return {
            "Entries": len(entries),
            "Duration": f"{duration_min} min",
            "Text Chars": total_text,
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
        
        ref_entries = self.parse_context(reference_context)["entries"]
        gen_entries = self.parse_context(generated_context)["entries"]
        
        if debug:
            print(f"Reference entries: {len(ref_entries)}, Generated entries: {len(gen_entries)}")
        
        # Compute component scores
        coverage_score = compute_entry_coverage_score(ref_entries, gen_entries)
        text_score, matched_pairs = compute_text_accuracy_score(ref_entries, gen_entries)
        timing_score_raw = compute_timing_accuracy_score(ref_entries, gen_entries, matched_pairs)
        sequence_score_raw = compute_sequence_score(ref_entries, gen_entries, matched_pairs)
        
        # Scale timing and sequence by coverage factor so missing entries reduce these scores
        # (they are otherwise computed only over matched pairs and stay ~1.0 when entries are removed)
        coverage_factor = len(matched_pairs) / max(len(ref_entries), 1) if matched_pairs else (1.0 if not ref_entries else 0.0)
        timing_score = timing_score_raw * coverage_factor
        sequence_score = sequence_score_raw * coverage_factor
        
        # Weighted aggregate: 20% coverage, 40% text, 25% timing, 15% sequence
        score = 0.20 * coverage_score + 0.40 * text_score + 0.25 * timing_score + 0.15 * sequence_score
        
        eval_obj = {
            "score": score,
            "entry_coverage_score": coverage_score,
            "text_accuracy_score": text_score,
            "timing_accuracy_score": timing_score,
            "sequence_score": sequence_score,
            "ref_entry_count": len(ref_entries),
            "gen_entry_count": len(gen_entries),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
