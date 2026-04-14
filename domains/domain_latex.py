from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, ujson as json


def parse_bibtex(bib_str):
    entries = {}
    # Match @type{key, ... } blocks
    pattern = r'@(\w+)\s*\{\s*([^,]+)\s*,([^@]*?)(?=\n@|\Z)'
    for match in re.finditer(pattern, bib_str, re.DOTALL):
        entry_type, key, fields_str = match.groups()
        key = key.strip()
        entry = {"_type": entry_type.lower(), "_key": key}
        # Parse fields: field = {value} or field = "value"
        field_pattern = r'(\w+)\s*=\s*(?:\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}|"([^"]*)")'
        for field_match in re.finditer(field_pattern, fields_str):
            field_name = field_match.group(1).lower()
            field_value = field_match.group(2) if field_match.group(2) is not None else field_match.group(3)
            entry[field_name] = field_value.strip() if field_value else ""
        entries[key] = entry
    return entries


def normalize_text(text):
    # Strip outer braces (BibTeX case preservation), collapse whitespace, lowercase
    text = text.strip()
    while text.startswith('{') and text.endswith('}'):
        text = text[1:-1]
    text = re.sub(r'[{}]', '', text)  # Remove any remaining braces
    return re.sub(r'\s+', ' ', text.lower().strip())


def extract_first_author(entry):
    authors = entry.get("author", "")
    # Take first author (before "and")
    first = authors.split(" and ")[0].strip() if authors else ""
    # Extract last name (usually before comma, or last word)
    if "," in first:
        return normalize_text(first.split(",")[0])
    parts = first.split()
    return normalize_text(parts[-1]) if parts else ""


def build_entry_fingerprint(entry):
    # Content-based fingerprint: (title_prefix, year, first_author_lastname)
    title = normalize_text(entry.get("title", ""))[:60]
    year = entry.get("year", "")
    first_author = extract_first_author(entry)
    return (title, year, first_author)


def extract_text_content(latex_str):
    text = latex_str
    # Remove comments
    text = re.sub(r'%.*$', '', text, flags=re.MULTILINE)
    # Extract citation keys and replace with placeholder
    cite_pattern = r'\\(?:cite|citep|citet|citeauthor|citeyear|autocite|textcite|parencite)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}'
    citations = []
    def replace_cite(m):
        keys = [k.strip() for k in m.group(1).split(',')]
        citations.extend(keys)
        return f" [CITE:{','.join(keys)}] "
    text = re.sub(cite_pattern, replace_cite, text)
    # Remove ref commands but keep marker
    text = re.sub(r'\\ref\{([^}]+)\}', r'[REF:\1]', text)
    text = re.sub(r'\\label\{[^}]+\}', '', text)
    # Strip formatting commands
    text = re.sub(r'\\textit\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\textbf\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\emph\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\texttt\{([^}]*)\}', r'\1', text)
    # Handle section commands - keep title
    text = re.sub(r'\\section\*?\{([^}]*)\}', r'\n\n## \1\n\n', text)
    text = re.sub(r'\\subsection\*?\{([^}]*)\}', r'\n\n### \1\n\n', text)
    # Remove remaining LaTeX commands
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?', '', text)
    # Clean up
    text = re.sub(r'\s+', ' ', text).strip()
    return text, citations


def extract_citation_sequence(latex_str, bib_entries):
    # Extract citations in document order, mapped to fingerprints
    cite_pattern = r'\\(?:cite|citep|citet|citeauthor|citeyear|autocite|textcite|parencite)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}'
    sequence = []
    for match in re.finditer(cite_pattern, latex_str):
        keys = [k.strip() for k in match.group(1).split(',')]
        for key in keys:
            if key in bib_entries:
                fp = build_entry_fingerprint(bib_entries[key])
                sequence.append(fp)
    return sequence


def compute_text_score(ref_latex, gen_latex):
    ref_text, _ = extract_text_content(ref_latex)
    gen_text, _ = extract_text_content(gen_latex)
    return SequenceMatcher(None, normalize_text(ref_text), normalize_text(gen_text)).ratio()


def compute_citation_sequence_score(ref_latex, ref_bib, gen_latex, gen_bib):
    ref_entries = parse_bibtex(ref_bib)
    gen_entries = parse_bibtex(gen_bib)
    ref_seq = extract_citation_sequence(ref_latex, ref_entries)
    gen_seq = extract_citation_sequence(gen_latex, gen_entries)
    if not ref_seq and not gen_seq:
        return 1.0
    if not ref_seq or not gen_seq:
        return 0.0
    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


def compute_bib_completeness_score(ref_bib, gen_bib, debug=False):
    ref_entries = parse_bibtex(ref_bib)
    gen_entries = parse_bibtex(gen_bib)
    if debug:
        print(f"  Parsed {len(ref_entries)} ref entries, {len(gen_entries)} gen entries")
        print(f"  Ref keys: {list(ref_entries.keys())[:5]}...")
        print(f"  Gen keys: {list(gen_entries.keys())[:5]}...")
    ref_fps = {build_entry_fingerprint(e): k for k, e in ref_entries.items()}
    gen_fps = {build_entry_fingerprint(e): k for k, e in gen_entries.items()}
    ref_fp_set = set(ref_fps.keys())
    gen_fp_set = set(gen_fps.keys())
    if debug:
        print(f"  Ref fingerprints ({len(ref_fp_set)}):")
        for fp, k in list(ref_fps.items())[:3]:
            print(f"    {k}: {fp}")
        print(f"  Gen fingerprints ({len(gen_fp_set)}):")
        for fp, k in list(gen_fps.items())[:3]:
            print(f"    {k}: {fp}")
        matched = ref_fp_set & gen_fp_set
        print(f"  Matched: {len(matched)}, Union: {len(ref_fp_set | gen_fp_set)}")
        if len(matched) == 0 and len(ref_fp_set) > 0 and len(gen_fp_set) > 0:
            print("  WARNING: No matches! Showing first ref vs first gen fingerprint:")
            ref_fp = list(ref_fps.keys())[0]
            gen_fp = list(gen_fps.keys())[0]
            print(f"    Ref: title='{ref_fp[0]}', year='{ref_fp[1]}', author='{ref_fp[2]}'")
            print(f"    Gen: title='{gen_fp[0]}', year='{gen_fp[1]}', author='{gen_fp[2]}'")
    if not ref_fp_set and not gen_fp_set:
        return 1.0
    if not ref_fp_set or not gen_fp_set:
        return 0.0
    intersection = len(ref_fp_set & gen_fp_set)
    union = len(ref_fp_set | gen_fp_set)
    return intersection / union


def match_entries_by_fingerprint(ref_bib, gen_bib):
    ref_entries = parse_bibtex(ref_bib)
    gen_entries = parse_bibtex(gen_bib)
    ref_by_fp = {build_entry_fingerprint(e): e for e in ref_entries.values()}
    gen_by_fp = {build_entry_fingerprint(e): e for e in gen_entries.values()}
    matched = []
    for fp in ref_by_fp:
        if fp in gen_by_fp:
            matched.append((ref_by_fp[fp], gen_by_fp[fp]))
    return matched


def compute_field_accuracy_score(ref_bib, gen_bib):
    matched = match_entries_by_fingerprint(ref_bib, gen_bib)
    if not matched:
        return 0.0
    field_scores = []
    # Fields to compare (excluding internal fields)
    compare_fields = ['author', 'title', 'year', 'journal', 'booktitle', 'volume', 'number', 'pages', 'publisher']
    for ref_entry, gen_entry in matched:
        present_fields = [f for f in compare_fields if f in ref_entry or f in gen_entry]
        if not present_fields:
            field_scores.append(1.0)
            continue
        matches = 0
        for f in present_fields:
            ref_val = normalize_text(ref_entry.get(f, ""))
            gen_val = normalize_text(gen_entry.get(f, ""))
            # Use fuzzy matching for fields
            if ref_val == gen_val:
                matches += 1
            elif ref_val and gen_val:
                matches += SequenceMatcher(None, ref_val, gen_val).ratio()
        field_scores.append(matches / len(present_fields))
    return sum(field_scores) / len(field_scores)


class DomainLatex(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "latex"
        self.summary = "LaTeX documents with BibTeX bibliographies, equations, and formatting"
        self.description = "LaTeX academic documents"
        self.file_format = [".tex", ".bib"]
        self.domain_parser = "custom"
        self.category = "creative"
    
    def get_latex_and_bib(self, context):
        latex_content = ""
        bib_content = ""
        for filename, content in context.items():
            if filename.endswith('.tex'):
                latex_content += content + "\n"
            elif filename.endswith('.bib'):
                bib_content += content + "\n"
        return latex_content, bib_content

    def parse_context(self, context):
        """Parse context into structured dict with latex content, bib content, and parsed bib entries.

        Args:
            context: dict of filename -> content

        Returns:
            dict with keys 'latex_content', 'bib_content', 'bib_entries'
        """
        latex_content, bib_content = self.get_latex_and_bib(context)
        bib_entries = parse_bibtex(bib_content)
        return {
            'latex_content': latex_content,
            'bib_content': bib_content,
            'bib_entries': bib_entries,
        }
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        latex_content = parsed['latex_content']
        bib_content = parsed['bib_content']
        num_citations = len(re.findall(r'\\cite\{[^}]+\}', latex_content))
        num_sections = len(re.findall(r'\\(?:section|subsection|subsubsection)\{', latex_content))
        num_bib = len(parsed['bib_entries'])
        return {
            "Sections": num_sections,
            "Citations": num_citations,
            "Bib Entries": num_bib,
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
        gen_parsed = self.parse_context(generated_context)
        ref_latex, ref_bib = ref_parsed['latex_content'], ref_parsed['bib_content']
        gen_latex, gen_bib = gen_parsed['latex_content'], gen_parsed['bib_content']
        
        if debug:
            print(f"len(ref_latex): {len(ref_latex)}, len(gen_latex): {len(gen_latex)}")
            print(f"len(ref_bib): {len(ref_bib)}, len(gen_bib): {len(gen_bib)}")
            print(f"\n=== BIB COMPLETENESS DEBUG ===")
        
        # Compute component scores
        text_score = compute_text_score(ref_latex, gen_latex)
        cite_seq_score = compute_citation_sequence_score(ref_latex, ref_bib, gen_latex, gen_bib)
        bib_completeness = compute_bib_completeness_score(ref_bib, gen_bib, debug=debug)
        field_accuracy = compute_field_accuracy_score(ref_bib, gen_bib)
        
        # Weighted aggregate
        score = 0.35 * text_score + 0.25 * cite_seq_score + 0.20 * bib_completeness + 0.20 * field_accuracy
        
        eval_obj = {
            "score": score,
            "text_score": text_score,
            "citation_sequence_score": cite_seq_score,
            "bib_completeness_score": bib_completeness,
            "field_accuracy_score": field_accuracy,
            "ref_entry_count": len(parse_bibtex(ref_bib)),
            "gen_entry_count": len(parse_bibtex(gen_bib)),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
