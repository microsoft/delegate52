from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
import polib


def parse_po_from_string(content):
    """Parse a PO file string into a list of entry dicts using polib."""
    try:
        po = polib.pofile(content, wrapwidth=0)
    except Exception as e:
        print(f"\033[91mPO parsing error: {e}\033[0m")
        return [], {}

    metadata = dict(po.metadata) if po.metadata else {}
    entries = []

    for entry in po:
        if entry.obsolete:
            continue

        e = {
            'msgid': entry.msgid.strip(),
            'msgstr': entry.msgstr.strip(),
            'msgctxt': (entry.msgctxt or '').strip(),
            'msgid_plural': (entry.msgid_plural or '').strip(),
            'msgstr_plural': dict(entry.msgstr_plural) if entry.msgstr_plural else {},
            'flags': sorted(entry.flags),
            'occurrences': sorted(entry.occurrences),
            'comment': (entry.comment or '').strip(),         # extracted / auto
            'tcomment': (entry.tcomment or '').strip(),        # translator
        }
        entries.append(e)

    return entries, metadata


def parse_all_po_entries(context):
    """Parse all PO files in a context dict, returning combined entries + metadata."""
    all_entries = []
    all_metadata = {}

    for filename, content in sorted(context.items()):
        if filename.endswith('.po') or filename.endswith('.pot'):
            entries, metadata = parse_po_from_string(content)
            all_entries.extend(entries)
            if metadata:
                all_metadata = metadata

    return all_entries, all_metadata


def entry_fingerprint(entry):
    """Unique fingerprint for an entry: (msgctxt, msgid)."""
    return (entry['msgctxt'], entry['msgid'])


def normalize_text(text):
    """Normalize whitespace and case for fuzzy comparison."""
    return ' '.join(text.lower().split())


def compute_entry_coverage_score(ref_entries, gen_entries):
    """Jaccard similarity on entry fingerprints."""
    if not ref_entries and not gen_entries:
        return 1.0
    if not ref_entries or not gen_entries:
        return 0.0

    ref_fps = {entry_fingerprint(e) for e in ref_entries}
    gen_fps = {entry_fingerprint(e) for e in gen_entries}

    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def compute_translation_accuracy(ref_entries, gen_entries):
    """Compare translations for matching entries (by fingerprint).
    Returns (accuracy_score, matched_count).
    """
    ref_by_fp = {}
    for e in ref_entries:
        fp = entry_fingerprint(e)
        ref_by_fp[fp] = e

    gen_by_fp = {}
    for e in gen_entries:
        fp = entry_fingerprint(e)
        gen_by_fp[fp] = e

    common_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not common_fps:
        return 0.0, 0

    scores = []
    for fp in common_fps:
        ref_e = ref_by_fp[fp]
        gen_e = gen_by_fp[fp]

        # Compare msgstr
        if ref_e['msgid_plural']:
            # Plural form: compare each msgstr[n]
            ref_plurals = ref_e['msgstr_plural']
            gen_plurals = gen_e['msgstr_plural']
            all_keys = set(ref_plurals.keys()) | set(gen_plurals.keys())
            if all_keys:
                plural_scores = []
                for k in all_keys:
                    ref_val = ref_plurals.get(k, '')
                    gen_val = gen_plurals.get(k, '')
                    plural_scores.append(SequenceMatcher(None, normalize_text(ref_val), normalize_text(gen_val)).ratio())
                msgstr_sim = sum(plural_scores) / len(plural_scores)
            else:
                msgstr_sim = 1.0
            # Also compare msgid_plural string
            plural_id_sim = SequenceMatcher(None, normalize_text(ref_e['msgid_plural']), normalize_text(gen_e['msgid_plural'])).ratio()
            msgstr_sim = 0.7 * msgstr_sim + 0.3 * plural_id_sim
        else:
            # Simple entry: compare msgstr
            msgstr_sim = SequenceMatcher(None, normalize_text(ref_e['msgstr']), normalize_text(gen_e['msgstr'])).ratio()

        scores.append(msgstr_sim)

    return sum(scores) / len(scores), len(common_fps)


def compute_flags_score(ref_entries, gen_entries):
    """Compare flags (fuzzy, c-format, python-format, etc.) for matching entries."""
    ref_by_fp = {entry_fingerprint(e): e for e in ref_entries}
    gen_by_fp = {entry_fingerprint(e): e for e in gen_entries}

    common_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not common_fps:
        return 1.0

    scores = []
    for fp in common_fps:
        ref_flags = set(ref_by_fp[fp]['flags'])
        gen_flags = set(gen_by_fp[fp]['flags'])
        if not ref_flags and not gen_flags:
            scores.append(1.0)
        elif not ref_flags or not gen_flags:
            scores.append(0.0)
        else:
            intersection = len(ref_flags & gen_flags)
            union = len(ref_flags | gen_flags)
            scores.append(intersection / union if union > 0 else 1.0)

    return sum(scores) / len(scores) if scores else 1.0


def compute_metadata_score(ref_metadata, gen_metadata):
    """Compare PO file header metadata fields."""
    if not ref_metadata and not gen_metadata:
        return 1.0
    if not ref_metadata or not gen_metadata:
        return 0.0

    # Key metadata fields to compare
    important_fields = [
        'Project-Id-Version', 'Language', 'Language-Team',
        'Content-Type', 'Plural-Forms', 'Last-Translator',
    ]
    secondary_fields = [
        'MIME-Version', 'Content-Transfer-Encoding',
        'Report-Msgid-Bugs-To', 'X-Generator',
    ]

    important_scores = []
    for field in important_fields:
        ref_val = ref_metadata.get(field, '').strip()
        gen_val = gen_metadata.get(field, '').strip()
        if not ref_val and not gen_val:
            continue
        if not ref_val or not gen_val:
            important_scores.append(0.0)
        else:
            important_scores.append(SequenceMatcher(None, ref_val.lower(), gen_val.lower()).ratio())

    secondary_scores = []
    for field in secondary_fields:
        ref_val = ref_metadata.get(field, '').strip()
        gen_val = gen_metadata.get(field, '').strip()
        if not ref_val and not gen_val:
            continue
        if not ref_val or not gen_val:
            secondary_scores.append(0.0)
        else:
            secondary_scores.append(SequenceMatcher(None, ref_val.lower(), gen_val.lower()).ratio())

    imp_score = sum(important_scores) / len(important_scores) if important_scores else 1.0
    sec_score = sum(secondary_scores) / len(secondary_scores) if secondary_scores else 1.0

    return 0.7 * imp_score + 0.3 * sec_score


def compute_comments_score(ref_entries, gen_entries):
    """Compare source references and translator/extracted comments for matching entries."""
    ref_by_fp = {entry_fingerprint(e): e for e in ref_entries}
    gen_by_fp = {entry_fingerprint(e): e for e in gen_entries}

    common_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not common_fps:
        return 1.0

    scores = []
    for fp in common_fps:
        ref_e = ref_by_fp[fp]
        gen_e = gen_by_fp[fp]

        sub_scores = []

        # Source references (occurrences)
        ref_occ = set(tuple(o) for o in ref_e['occurrences'])
        gen_occ = set(tuple(o) for o in gen_e['occurrences'])
        if ref_occ or gen_occ:
            if not ref_occ and not gen_occ:
                sub_scores.append(1.0)
            elif not ref_occ or not gen_occ:
                sub_scores.append(0.0)
            else:
                intersection = len(ref_occ & gen_occ)
                union = len(ref_occ | gen_occ)
                sub_scores.append(intersection / union if union > 0 else 1.0)

        # Extracted comment
        if ref_e['comment'] or gen_e['comment']:
            sub_scores.append(
                SequenceMatcher(None, normalize_text(ref_e['comment']), normalize_text(gen_e['comment'])).ratio()
                if ref_e['comment'] and gen_e['comment']
                else (1.0 if not ref_e['comment'] and not gen_e['comment'] else 0.0)
            )

        # Translator comment
        if ref_e['tcomment'] or gen_e['tcomment']:
            sub_scores.append(
                SequenceMatcher(None, normalize_text(ref_e['tcomment']), normalize_text(gen_e['tcomment'])).ratio()
                if ref_e['tcomment'] and gen_e['tcomment']
                else (1.0 if not ref_e['tcomment'] and not gen_e['tcomment'] else 0.0)
            )

        if sub_scores:
            scores.append(sum(sub_scores) / len(sub_scores))
        else:
            scores.append(1.0)

    return sum(scores) / len(scores) if scores else 1.0


def compute_sequence_score(ref_entries, gen_entries):
    """Compare the ordering of entries between reference and generated."""
    if not ref_entries or not gen_entries:
        return 1.0 if (not ref_entries and not gen_entries) else 0.0

    ref_fps = [entry_fingerprint(e) for e in ref_entries]
    gen_fps = [entry_fingerprint(e) for e in gen_entries]

    return SequenceMatcher(None, ref_fps, gen_fps).ratio()


class DomainTranslation(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "translation"
        self.summary = "GNU gettext PO translation files with msgid/msgstr pairs, plurals, flags, and metadata"
        self.description = "GNU gettext translations"
        self.file_format = [".po"]
        self.domain_parser = "polib"
        self.category = "code"

    def preprocess_context(self, context):
        """Normalize raw PO file content before parsing.

        Fixes three common LLM syntax errors that cause polib to reject the entire file:
        1. Misplaced #: or #, lines between msgid and msgstr → relocate before the entry
        2. #: continuation lines using backslash (missing #: prefix on next line) → join them
        3. Unescaped double quotes inside msgid/msgstr strings → escape them
        """
        result = {}
        for filename, content in context.items():
            if filename.endswith('.po') or filename.endswith('.pot'):
                content = self._preprocess_po(content)
            result[filename] = content
        return result

    def _preprocess_po(self, content):
        """Apply PO-specific syntax fixes to a single file's content."""
        lines = content.split('\n')
        fixed_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]

            # Fix 1: #: continuation lines with backslash (handles multi-line chains)
            # Pattern: "#: file1.cpp:82 \" followed by bare continuation lines
            if line.startswith('#:') and line.rstrip().endswith('\\'):
                merged = line.rstrip().rstrip('\\').rstrip()
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if not next_line or next_line.startswith(('#', 'msg', '"')):
                        break
                    # This is a continuation line — append it
                    merged += ' ' + next_line.rstrip('\\').rstrip()
                    if not lines[j].rstrip().endswith('\\'):
                        j += 1
                        break
                    j += 1
                if j > i + 1:
                    fixed_lines.append(merged)
                    i = j
                    continue

            # Fix 2: Misplaced #: or #, lines between msgid/msgid_plural and msgstr/msgid_plural
            # Handles both:
            #   - #: between msgid and msgid_plural
            #   - #: or #, between msgid_plural and msgstr
            if (line.startswith('msgid ') or line.startswith('msgid_plural ')) and i + 2 < len(lines):
                misplaced = []
                j = i + 1
                while j < len(lines) and (lines[j].startswith('#:') or lines[j].startswith('#,')):
                    misplaced.append(lines[j])
                    j += 1
                if misplaced and j < len(lines) and (lines[j].startswith('msgstr') or lines[j].startswith('msgid_plural')):
                    # Insert misplaced lines before the ENTRY block (before msgid, not just before current line)
                    # Search backwards in fixed_lines to find the entry start
                    insert_pos = len(fixed_lines)
                    if line.startswith('msgid_plural '):
                        # Look back past the msgid line to find proper insert position
                        k = len(fixed_lines) - 1
                        while k >= 0 and fixed_lines[k].startswith('msgid '):
                            k -= 1
                        insert_pos = k + 1
                    # Insert misplaced lines at the correct position
                    for idx_m, ml in enumerate(misplaced):
                        fixed_lines.insert(insert_pos + idx_m, ml)
                    fixed_lines.append(line)
                    i += 1
                    # Skip the misplaced lines (they've been moved)
                    while i < len(lines) and (lines[i].startswith('#:') or lines[i].startswith('#,')):
                        i += 1
                    continue

            # Fix 3: Unescaped double quotes in msgid/msgstr values
            # Pattern: msgid "Rename "%s"" → msgid "Rename \"%s\""
            if re.match(r'^(msgid|msgstr|msgid_plural|msgstr\[\d+\])\s+"', line):
                line = self._fix_unescaped_quotes(line)

            fixed_lines.append(line)
            i += 1

        return '\n'.join(fixed_lines)

    @staticmethod
    def _fix_unescaped_quotes(line):
        """Fix unescaped double quotes inside a PO msgid/msgstr line.

        Valid PO: msgid "some text with \\"quoted\\" words"
        Invalid:  msgid "some text with "quoted" words"

        Only fixes lines where internal unescaped quotes are detected.
        """
        # Split into keyword and quoted value
        m = re.match(r'^(msgid|msgstr|msgid_plural|msgstr\[\d+\])\s+"(.*)"\s*$', line)
        if not m:
            return line
        keyword = m.group(1)
        inner = m.group(2)
        # Check if there are unescaped double quotes inside
        # An unescaped quote is a " not preceded by \
        if re.search(r'(?<!\\)"', inner):
            # Escape all unescaped internal double quotes
            inner = re.sub(r'(?<!\\)"', r'\\"', inner)
            return f'{keyword} "{inner}"'
        return line

    def parse_all_entries(self, context):
        return parse_all_po_entries(context)

    def parse_context(self, context):
        """Parse context dict into structured data: PO entries and metadata."""
        entries, metadata = self.parse_all_entries(context)
        return {
            "entries": entries,
            "metadata": metadata,
        }

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        entries = parsed["entries"]
        metadata = parsed["metadata"]
        fuzzy_count = sum(1 for e in entries if 'fuzzy' in e.get('flags', []))
        plural_count = sum(1 for e in entries if e.get('msgid_plural'))
        with_comments = sum(1 for e in entries if e.get('comment') or e.get('tcomment'))
        lang = metadata.get('Language', 'unknown')
        return {
            "Entries": len(entries),
            "Language": lang,
            "Fuzzy": fuzzy_count,
            "Plurals": plural_count,
            "Comments": with_comments,
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

        ref_parsed = self.parse_context(reference_context)
        ref_entries, ref_metadata = ref_parsed["entries"], ref_parsed["metadata"]
        generated_context = self.preprocess_context(generated_context)
        gen_parsed = self.parse_context(generated_context)
        gen_entries, gen_metadata = gen_parsed["entries"], gen_parsed["metadata"]

        if debug:
            print(f"Reference entries: {len(ref_entries)}, Generated entries: {len(gen_entries)}")

        # Compute component scores
        coverage_score = compute_entry_coverage_score(ref_entries, gen_entries)
        translation_score, matched_count = compute_translation_accuracy(ref_entries, gen_entries)
        flags_score = compute_flags_score(ref_entries, gen_entries)
        metadata_score = compute_metadata_score(ref_metadata, gen_metadata)
        comments_score = compute_comments_score(ref_entries, gen_entries)
        sequence_score = compute_sequence_score(ref_entries, gen_entries)

        # Weighted aggregate:
        # coverage^2 gates everything (must have the right entries)
        # translation accuracy is the core content preservation
        # flags, comments, metadata capture PO-specific structure
        # sequence captures ordering
        score = (coverage_score ** 2) * (
            0.40 * translation_score
            + 0.10 * flags_score
            + 0.10 * metadata_score
            + 0.15 * comments_score
            + 0.10 * sequence_score
            + 0.15 * coverage_score  # reward coverage directly too
        )

        eval_obj = {
            "score": score,
            "entry_coverage_score": coverage_score,
            "translation_accuracy_score": translation_score,
            "flags_score": flags_score,
            "metadata_score": metadata_score,
            "comments_score": comments_score,
            "sequence_score": sequence_score,
            "ref_entry_count": len(ref_entries),
            "gen_entry_count": len(gen_entries),
            "matched_count": matched_count,
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
