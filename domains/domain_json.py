from utils_context import build_context_from_folder
from .domain_base import DomainBase
import os, re, ujson as json
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def preprocess_json(text):
    """Fix common LLM JSON syntax errors so the text can be parsed.
    
    Fixes applied:
      1. Replace JavaScript `undefined` with JSON `null`.
      2. Remove trailing commas before } or ].
      3. Balance unclosed brackets/braces at EOF (LLM truncation).
    """
    # 1. undefined -> null
    text = re.sub(r'\bundefined\b', 'null', text)
    # 2. Trailing commas
    text = re.sub(r',\s*([\}\]])', r'\1', text)
    # 3. Balance unclosed brackets at EOF
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')
    if open_braces > 0 or open_brackets > 0:
        text = text + '}' * max(open_braces, 0) + ']' * max(open_brackets, 0)
    return text


def parse_json_or_yaml(content, filename):
    """Parse content as JSON or YAML based on extension."""
    if filename.endswith('.yaml') or filename.endswith('.yml'):
        if not HAS_YAML:
            raise ImportError("PyYAML required for YAML files")
        return yaml.safe_load(content)
    else:
        return json.loads(content)


def get_single_file_content(context):
    """Extract the single file from context."""
    if len(context) != 1:
        return None, None, f"Expected 1 file, got {len(context)}"
    filename = list(context.keys())[0]
    content = context[filename]
    return filename, content, None


def deep_compare(ref, gen):
    """Recursively compare two JSON values. Returns similarity score 0-1.
    - Dict key order doesn't matter
    - Array order matters
    - Types must match
    """
    if ref is None and gen is None:
        return 1.0
    if ref is None or gen is None:
        return 0.0
    if type(ref) != type(gen):
        # Type mismatch - check for int/float equivalence
        if isinstance(ref, (int, float)) and isinstance(gen, (int, float)):
            return 1.0 if ref == gen else 0.0
        return 0.0
    
    if isinstance(ref, dict):
        if not ref and not gen:
            return 1.0
        all_keys = set(ref.keys()) | set(gen.keys())
        if not all_keys:
            return 1.0
        scores = []
        for key in all_keys:
            if key in ref and key in gen:
                scores.append(deep_compare(ref[key], gen[key]))
            else:
                scores.append(0.0)
        return sum(scores) / len(scores)
    
    elif isinstance(ref, list):
        if not ref and not gen:
            return 1.0
        if len(ref) != len(gen):
            min_len = min(len(ref), len(gen))
            max_len = max(len(ref), len(gen))
            if max_len == 0:
                return 1.0
            if min_len == 0:
                return 0.0
            elem_scores = [deep_compare(ref[i], gen[i]) for i in range(min_len)]
            return sum(elem_scores) / max_len
        return sum(deep_compare(r, g) for r, g in zip(ref, gen)) / len(ref)
    
    elif isinstance(ref, str):
        return 1.0 if ref == gen else 0.0
    
    elif isinstance(ref, bool):
        return 1.0 if ref == gen else 0.0
    
    elif isinstance(ref, (int, float)):
        return 1.0 if ref == gen else 0.0
    
    else:
        return 1.0 if ref == gen else 0.0


def flatten_keys(obj, prefix=''):
    """Flatten nested dict/list into set of key paths."""
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            keys.add(path)
            keys.update(flatten_keys(v, path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            path = f"{prefix}[{i}]"
            keys.add(path)
            keys.update(flatten_keys(v, path))
    return keys


def compute_key_coverage(ref, gen):
    """Jaccard similarity on flattened key paths."""
    ref_keys = flatten_keys(ref)
    gen_keys = flatten_keys(gen)
    if not ref_keys and not gen_keys:
        return 1.0
    if not ref_keys or not gen_keys:
        return 0.0
    intersection = len(ref_keys & gen_keys)
    union = len(ref_keys | gen_keys)
    return intersection / union if union > 0 else 1.0


def normalize_json(obj):
    """Recursively sort dict keys for comparison."""
    if isinstance(obj, dict):
        return {k: normalize_json(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, list):
        return [normalize_json(v) for v in obj]
    else:
        return obj


class DomainJSON(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "json"
        self.summary = "Generic JSON data transformations with nested structures"
        self.description = "JSON/YAML structured data"
        self.file_format = [".json", ".yaml"]
        self.domain_parser = "custom"
        self.category = "code"

    def preprocess_context(self, context):
        """Apply JSON/YAML preprocessing to fix common LLM syntax errors."""
        cleaned = {}
        for filename, content in context.items():
            if filename.endswith('.json'):
                content = preprocess_json(content)
            cleaned[filename] = content
        return cleaned

    def parse_context(self, context):
        """Parse the single JSON/YAML file from the context.

        Args:
            context: dict of filename -> content

        Returns:
            dict with keys 'filename' and 'parsed_data'
        """
        context = self.preprocess_context(context)
        filename, content, err = get_single_file_content(context)
        if err:
            raise ValueError(err)
        parsed_data = parse_json_or_yaml(content, filename)
        return {'filename': filename, 'parsed_data': parsed_data}

    def compute_domain_statistics(self, context):
        try:
            parsed = self.parse_context(context)
            obj = parsed['parsed_data']
            keys = flatten_keys(obj)
            def max_depth(o, d=0):
                if isinstance(o, dict):
                    return max((max_depth(v, d+1) for v in o.values()), default=d)
                elif isinstance(o, list):
                    return max((max_depth(v, d+1) for v in o), default=d)
                return d
            return {
                "Key Paths": len(keys),
                "Max Depth": max_depth(obj),
            }
        except Exception:
            pass
        return {}
    
    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        # Parse reference and generated contexts
        try:
            ref_parsed = self.parse_context(reference_context)
            ref_data = ref_parsed['parsed_data']
        except Exception as e:
            return {"error": "ref_parse_error", "details": str(e), "score": 0.0}
        
        try:
            gen_parsed = self.parse_context(generated_context)
            gen_data = gen_parsed['parsed_data']
        except Exception as e:
            return {"error": "gen_parse_error", "details": str(e), "score": 0.0}
        
        # Unwrap single-key dict wrapper when types differ (e.g. ref is [...], gen is {"key": [...]})
        if isinstance(ref_data, list) and isinstance(gen_data, dict) and len(gen_data) == 1:
            inner = next(iter(gen_data.values()))
            if isinstance(inner, list):
                gen_data = inner
        elif isinstance(ref_data, dict) and isinstance(gen_data, list) and len(ref_data) == 1:
            inner = next(iter(ref_data.values()))
            if isinstance(inner, list):
                ref_data = inner
        
        # Check for exact match after normalization
        ref_normalized = normalize_json(ref_data)
        gen_normalized = normalize_json(gen_data)
        exact_match = ref_normalized == gen_normalized
        
        if exact_match:
            eval_obj = {"score": 1.0, "exact_match": True}
            print(f"\033[94m{eval_obj}\033[0m")
            return eval_obj
        
        # Compute similarity scores
        key_coverage = compute_key_coverage(ref_data, gen_data)
        value_score = deep_compare(ref_data, gen_data)
        
        # Combined score: key coverage gates, value score is primary
        score = key_coverage * 0.3 + value_score * 0.7
        
        eval_obj = {
            "score": score,
            "exact_match": False,
            "key_coverage": key_coverage,
            "value_score": value_score,
        }
        
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


if __name__ == "__main__":
    # Test deep_compare
    print("=" * 60)
    print("JSON DEEP COMPARE TESTS")
    print("=" * 60)
    
    # Test 1: Exact match
    a = {"x": 1, "y": [1, 2, 3]}
    b = {"y": [1, 2, 3], "x": 1}  # Different key order
    print(f"Dict order test: {deep_compare(a, b)}")  # Should be 1.0
    
    # Test 2: Array order matters
    a = {"arr": [1, 2, 3]}
    b = {"arr": [3, 2, 1]}
    print(f"Array order test: {deep_compare(a, b)}")  # Should be < 1.0
    
    # Test 3: Missing key
    a = {"x": 1, "y": 2}
    b = {"x": 1}
    print(f"Missing key test: {deep_compare(a, b)}")  # Should be 0.5
    
    # Test 4: Nested
    a = {"outer": {"inner": {"deep": 42}}}
    b = {"outer": {"inner": {"deep": 42}}}
    print(f"Nested match test: {deep_compare(a, b)}")  # Should be 1.0
    
    # Test 5: Type mismatch
    a = {"x": "123"}
    b = {"x": 123}
    print(f"Type mismatch test: {deep_compare(a, b)}")  # Should be 0.0
    
    # Test 6: Partial array
    a = {"arr": [1, 2, 3, 4, 5]}
    b = {"arr": [1, 2, 3]}
    print(f"Partial array test: {deep_compare(a, b)}")  # Should be 0.6
