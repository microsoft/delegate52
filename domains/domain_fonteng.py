from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, math, re, io, logging, ujson as json

from fontTools.feaLib.parser import Parser
from fontTools.feaLib import ast as fea_ast


def preprocess_fea_content(content):
    """Normalize common syntactic issues in .fea content that cause parse failures
    without changing semantic meaning.

    Handled cases:
    - Lowercase 'dflt' script tag in languagesystem → 'DFLT' (case-sensitivity)
    - C-style /* ... */ block comments → # line comments (.fea only supports #)
    """
    # Normalize 'languagesystem dflt' → 'languagesystem DFLT'
    # The OpenType spec requires the default script tag to be uppercase 'DFLT',
    # but models sometimes output lowercase 'dflt'. The language tag 'dflt' is
    # already lowercase by convention, so we only fix the script position.
    content = re.sub(
        r'(?m)^(\s*languagesystem\s+)dflt(\s)',
        r'\1DFLT\2',
        content,
    )

    # Convert C-style block comments /* ... */ to # line comments.
    # The .fea spec only supports # comments; models occasionally emit C-style.
    def _block_comment_to_hash(m):
        body = m.group(1)
        lines = body.split('\n')
        return '\n'.join('# ' + line.strip() for line in lines if line.strip())

    content = re.sub(r'/\*(.+?)\*/', _block_comment_to_hash, content, flags=re.DOTALL)

    return content


def parse_fea_content(content):
    """Parse .fea content into structured components using fontTools.feaLib.
    Returns a dict with language_systems, glyph_classes, features, and tables.

    When parsing fails, the offending line is commented out and parsing is
    retried (up to ``max_retries`` times).  This prevents a single syntax
    error from zeroing the score for the entire file — the correctly-written
    portions still get parsed and scored, while broken lines naturally reduce
    coverage and accuracy.
    """
    result = {
        "language_systems": [],
        "glyph_classes": {},
        "features": {},
        "tables": {},
        "parse_error": None,
    }

    content = preprocess_fea_content(content)

    max_retries = 50
    # Suppress noisy "Ambiguous glyph name" warnings from fontTools parser
    fea_logger = logging.getLogger("fontTools.feaLib")
    prev_level = fea_logger.level
    fea_logger.setLevel(logging.ERROR)
    try:
      for _attempt in range(max_retries):
        try:
            parser = Parser(io.StringIO(content))
            doc = parser.parse()
            break  # success
        except Exception as e:
            err_str = str(e)
            # Extract the line number from the error message
            m = re.search(r"<features>:(\d+):", err_str)
            if not m:
                # Cannot locate the offending line — bail out
                result["parse_error"] = err_str
                return result
            line_num = int(m.group(1))
            lines = content.split("\n")
            if line_num < 1 or line_num > len(lines):
                result["parse_error"] = err_str
                return result
            # Comment out the offending line and retry
            lines[line_num - 1] = "# [parse-skip] " + lines[line_num - 1]
            content = "\n".join(lines)
      else:
        # Exhausted retries — return the last error
        result["parse_error"] = err_str
        return result
    finally:
      fea_logger.setLevel(prev_level)

    for stmt in doc.statements:
        if isinstance(stmt, fea_ast.LanguageSystemStatement):
            result["language_systems"].append((stmt.script, stmt.language))
        elif isinstance(stmt, fea_ast.GlyphClassDefinition):
            result["glyph_classes"][stmt.name] = stmt.asFea()
        elif isinstance(stmt, fea_ast.FeatureBlock):
            tag = stmt.name if hasattr(stmt, 'name') else str(stmt)
            result["features"][tag] = stmt.asFea()
        elif isinstance(stmt, fea_ast.TableBlock):
            tag = stmt.name if hasattr(stmt, 'name') else str(stmt)
            result["tables"][tag] = stmt.asFea()

    return result


def parse_fea_from_context(context):
    """Parse all .fea files in a context dict. Concatenates multiple .fea files."""
    fea_content = ""
    for filename in sorted(context.keys()):
        if filename.endswith('.fea'):
            fea_content += context[filename] + "\n"

    if not fea_content.strip():
        return {"language_systems": [], "glyph_classes": {}, "features": {},
                "tables": {}, "parse_error": "No .fea content found"}

    return parse_fea_content(fea_content)


def normalize_fea_text(text):
    """Normalize .fea text for comparison: strip comments, collapse whitespace."""
    # Remove comments
    lines = []
    for line in text.split('\n'):
        # Remove inline comments but preserve structure
        hash_pos = line.find('#')
        if hash_pos >= 0:
            line = line[:hash_pos]
        line = line.rstrip()
        if line.strip():
            lines.append(line)
    return '\n'.join(lines)


def fuzzy_compare_fea_blocks(ref_text, gen_text):
    """Compare two .fea text blocks with normalization. Returns 0-1 score."""
    ref_norm = normalize_fea_text(ref_text)
    gen_norm = normalize_fea_text(gen_text)

    if ref_norm == gen_norm:
        return 1.0

    return SequenceMatcher(None, ref_norm, gen_norm).ratio()


def compute_class_score(ref_classes, gen_classes):
    """Compare glyph class definitions. Returns (coverage, accuracy) tuple."""
    if not ref_classes and not gen_classes:
        return 1.0, 1.0
    if not ref_classes:
        return 1.0, 1.0  # no reference classes, nothing to check
    if not gen_classes:
        return 0.0, 0.0

    ref_names = set(ref_classes.keys())
    gen_names = set(gen_classes.keys())

    matched = ref_names & gen_names
    coverage = len(matched) / len(ref_names) if ref_names else 1.0

    # Accuracy for matched classes
    if not matched:
        return coverage, 0.0

    accuracy_scores = []
    for name in matched:
        score = fuzzy_compare_fea_blocks(ref_classes[name], gen_classes[name])
        accuracy_scores.append(score)

    accuracy = sum(accuracy_scores) / len(accuracy_scores)
    return coverage, accuracy


def compute_feature_score(ref_features, gen_features):
    """Compare feature blocks. Returns (coverage, accuracy) tuple."""
    if not ref_features and not gen_features:
        return 1.0, 1.0
    if not ref_features:
        return 1.0, 1.0
    if not gen_features:
        return 0.0, 0.0

    ref_tags = set(ref_features.keys())
    gen_tags = set(gen_features.keys())

    matched = ref_tags & gen_tags
    coverage = len(matched) / len(ref_tags) if ref_tags else 1.0

    if not matched:
        return coverage, 0.0

    accuracy_scores = []
    for tag in matched:
        score = fuzzy_compare_fea_blocks(ref_features[tag], gen_features[tag])
        accuracy_scores.append(score)

    accuracy = sum(accuracy_scores) / len(accuracy_scores)
    return coverage, accuracy


def compute_langsys_score(ref_langsys, gen_langsys):
    """Compare language system declarations. Returns Jaccard-like score."""
    ref_set = set(ref_langsys)
    gen_set = set(gen_langsys)

    if not ref_set and not gen_set:
        return 1.0
    if not ref_set or not gen_set:
        return 0.0

    intersection = len(ref_set & gen_set)
    union = len(ref_set | gen_set)
    return intersection / union if union > 0 else 1.0


def compute_table_score(ref_tables, gen_tables):
    """Compare table blocks. Returns (coverage, accuracy) tuple."""
    if not ref_tables and not gen_tables:
        return 1.0, 1.0
    if not ref_tables:
        return 1.0, 1.0
    if not gen_tables:
        return 0.0, 0.0

    ref_tags = set(ref_tables.keys())
    gen_tags = set(gen_tables.keys())

    matched = ref_tags & gen_tags
    coverage = len(matched) / len(ref_tags) if ref_tags else 1.0

    if not matched:
        return coverage, 0.0

    accuracy_scores = []
    for tag in matched:
        score = fuzzy_compare_fea_blocks(ref_tables[tag], gen_tables[tag])
        accuracy_scores.append(score)

    accuracy = sum(accuracy_scores) / len(accuracy_scores)
    return coverage, accuracy


class DomainFonteng(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "fonteng"
        self.summary = "OpenType feature (.fea) files for font engineering"
        self.description = "OpenType font features"
        self.file_format = [".fea"]
        self.domain_parser = "fontTools"
        self.category = "creative"

    def parse_context(self, context):
        """Parse context dict into structured font engineering data.
        Returns dict with language_systems, glyph_classes, features, tables, parse_error."""
        return parse_fea_from_context(context)

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        return {
            "Language Systems": len(parsed["language_systems"]),
            "Glyph Classes": len(parsed["glyph_classes"]),
            "Features": len(parsed["features"]),
            "Tables": len(parsed["tables"]),
            "Parse Error": parsed["parse_error"] is not None,
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

        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)

        if ref_parsed["parse_error"]:
            print(f"\033[91mReference parse error: {ref_parsed['parse_error']}\033[0m")
            return {"score": 0.0, "error": f"ref_parse_error: {ref_parsed['parse_error']}"}

        if gen_parsed["parse_error"]:
            if debug:
                print(f"\033[91mGenerated parse error: {gen_parsed['parse_error']}\033[0m")
            return {"score": 0.0, "error": f"gen_parse_error: {gen_parsed['parse_error']}"}

        # Compute component scores
        class_coverage, class_accuracy = compute_class_score(
            ref_parsed["glyph_classes"], gen_parsed["glyph_classes"])
        feature_coverage, feature_accuracy = compute_feature_score(
            ref_parsed["features"], gen_parsed["features"])
        langsys_score = compute_langsys_score(
            ref_parsed["language_systems"], gen_parsed["language_systems"])
        table_coverage, table_accuracy = compute_table_score(
            ref_parsed["tables"], gen_parsed["tables"])

        # Weight components by their block count for proportionality
        n_classes = max(len(ref_parsed["glyph_classes"]), 1)
        n_features = max(len(ref_parsed["features"]), 1)
        n_langsys = max(len(ref_parsed["language_systems"]), 1)
        n_tables = max(len(ref_parsed["tables"]), 1)
        total_blocks = n_classes + n_features + n_langsys + n_tables

        w_class = n_classes / total_blocks
        w_feature = n_features / total_blocks
        w_langsys = n_langsys / total_blocks
        w_table = n_tables / total_blocks

        # Per-component combined score = coverage² * accuracy
        # Coverage² gating penalizes missing content more heavily,
        # ensuring scores drop proportionally when content is removed.
        class_score = class_coverage ** 2 * class_accuracy
        feature_score = feature_coverage ** 2 * feature_accuracy
        table_score = table_coverage ** 2 * table_accuracy
        langsys_gated = langsys_score ** 2  # Jaccard already, square it

        # Final weighted score
        score = (w_class * class_score +
                 w_feature * feature_score +
                 w_langsys * langsys_gated +
                 w_table * table_score)
        score = round(score, 10)  # Avoid floating point artifacts

        eval_obj = {
            "score": score,
            "class_coverage": class_coverage,
            "class_accuracy": class_accuracy,
            "class_score": class_score,
            "feature_coverage": feature_coverage,
            "feature_accuracy": feature_accuracy,
            "feature_score": feature_score,
            "langsys_score": langsys_score,
            "table_coverage": table_coverage,
            "table_accuracy": table_accuracy,
            "table_score": table_score,
            "ref_classes": len(ref_parsed["glyph_classes"]),
            "ref_features": len(ref_parsed["features"]),
            "ref_langsys": len(ref_parsed["language_systems"]),
            "ref_tables": len(ref_parsed["tables"]),
            "gen_classes": len(gen_parsed["glyph_classes"]),
            "gen_features": len(gen_parsed["features"]),
            "gen_langsys": len(gen_parsed["language_systems"]),
            "gen_tables": len(gen_parsed["tables"]),
            "weights": {
                "class": round(w_class, 3),
                "feature": round(w_feature, 3),
                "langsys": round(w_langsys, 3),
                "table": round(w_table, 3),
            },
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


