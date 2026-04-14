from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
import hcl2
import io


def _try_parse_hcl(content, filename="main.tf"):
    """Try to parse HCL content using python-hcl2. Returns (parsed_dict, error_msg)."""
    try:
        parsed = hcl2.load(io.StringIO(content))
        return parsed, None
    except Exception as e:
        return None, str(e)


def extract_blocks(parsed):
    """Extract all top-level blocks from parsed HCL into a flat list of structured dicts.

    Each block has: block_type, type_label (for resource/data), name_label, body.
    """
    blocks = []

    # terraform block
    for item in parsed.get("terraform", []):
        blocks.append({
            "block_type": "terraform",
            "type_label": None,
            "name_label": None,
            "body": item,
        })

    # provider blocks
    for item in parsed.get("provider", []):
        # provider is a dict like {"aws": {...}}
        if isinstance(item, dict):
            for pname, pbody in item.items():
                blocks.append({
                    "block_type": "provider",
                    "type_label": pname,
                    "name_label": None,
                    "body": pbody,
                })
        else:
            blocks.append({
                "block_type": "provider",
                "type_label": None,
                "name_label": None,
                "body": item,
            })

    # locals blocks
    for item in parsed.get("locals", []):
        blocks.append({
            "block_type": "locals",
            "type_label": None,
            "name_label": None,
            "body": item,
        })

    # variable blocks
    for item in parsed.get("variable", []):
        if isinstance(item, dict):
            for vname, vbody in item.items():
                blocks.append({
                    "block_type": "variable",
                    "type_label": None,
                    "name_label": vname,
                    "body": vbody,
                })

    # output blocks
    for item in parsed.get("output", []):
        if isinstance(item, dict):
            for oname, obody in item.items():
                blocks.append({
                    "block_type": "output",
                    "type_label": None,
                    "name_label": oname,
                    "body": obody,
                })

    # resource blocks
    for item in parsed.get("resource", []):
        if isinstance(item, dict):
            for rtype, rdict in item.items():
                if isinstance(rdict, dict):
                    for rname, rbody in rdict.items():
                        blocks.append({
                            "block_type": "resource",
                            "type_label": rtype,
                            "name_label": rname,
                            "body": rbody,
                        })

    # data blocks
    for item in parsed.get("data", []):
        if isinstance(item, dict):
            for dtype, ddict in item.items():
                if isinstance(ddict, dict):
                    for dname, dbody in ddict.items():
                        blocks.append({
                            "block_type": "data",
                            "type_label": dtype,
                            "name_label": dname,
                            "body": dbody,
                        })

    # module blocks
    for item in parsed.get("module", []):
        if isinstance(item, dict):
            for mname, mbody in item.items():
                blocks.append({
                    "block_type": "module",
                    "type_label": None,
                    "name_label": mname,
                    "body": mbody,
                })

    return blocks


def block_fingerprint(block):
    """Create a unique fingerprint for matching blocks across contexts."""
    bt = block["block_type"]
    tl = block.get("type_label") or ""
    nl = block.get("name_label") or ""
    return (bt, tl, nl)


def parse_all_hcl(context):
    """Parse all .tf files in a context dict. Returns (blocks_list, error_msg)."""
    all_blocks = []
    for filename, content in context.items():
        if filename.endswith('.tf'):
            parsed, err = _try_parse_hcl(content, filename)
            if err:
                return [], f"Error parsing {filename}: {err}"
            blocks = extract_blocks(parsed)
            all_blocks.extend(blocks)
    return all_blocks, None


def normalize_body(body):
    """Recursively normalize a body dict for comparison.
    Sorts dict keys, normalizes strings, handles nested structures."""
    if isinstance(body, dict):
        return {k: normalize_body(v) for k, v in sorted(body.items())}
    elif isinstance(body, list):
        return [normalize_body(item) for item in body]
    elif isinstance(body, str):
        return body.strip()
    else:
        return body


def body_similarity(ref_body, gen_body):
    """Compare two block bodies using recursive key-value matching.
    Returns a score in [0, 1]."""
    if ref_body is None and gen_body is None:
        return 1.0
    if ref_body is None or gen_body is None:
        return 0.0

    ref_norm = normalize_body(ref_body)
    gen_norm = normalize_body(gen_body)

    if ref_norm == gen_norm:
        return 1.0

    # Both should be dicts for block bodies
    if isinstance(ref_norm, dict) and isinstance(gen_norm, dict):
        return _dict_similarity(ref_norm, gen_norm)

    # Fallback: string comparison
    ref_str = json.dumps(ref_norm, sort_keys=True)
    gen_str = json.dumps(gen_norm, sort_keys=True)
    return SequenceMatcher(None, ref_str, gen_str).ratio()


def _dict_similarity(ref_dict, gen_dict):
    """Compare two normalized dicts key by key."""
    if not ref_dict and not gen_dict:
        return 1.0

    all_keys = set(ref_dict.keys()) | set(gen_dict.keys())
    if not all_keys:
        return 1.0

    scores = []
    for key in all_keys:
        if key not in ref_dict:
            scores.append(0.0)  # Extra key in generated
        elif key not in gen_dict:
            scores.append(0.0)  # Missing key from generated
        else:
            ref_val = ref_dict[key]
            gen_val = gen_dict[key]
            scores.append(_value_similarity(ref_val, gen_val))

    return sum(scores) / len(scores)


def _value_similarity(ref_val, gen_val):
    """Compare two values recursively."""
    if ref_val == gen_val:
        return 1.0

    if isinstance(ref_val, dict) and isinstance(gen_val, dict):
        return _dict_similarity(ref_val, gen_val)
    elif isinstance(ref_val, list) and isinstance(gen_val, list):
        return _list_similarity(ref_val, gen_val)
    elif isinstance(ref_val, (int, float)) and isinstance(gen_val, (int, float)):
        if ref_val == 0 and gen_val == 0:
            return 1.0
        if ref_val == 0 or gen_val == 0:
            return 0.0
        return min(ref_val, gen_val) / max(ref_val, gen_val)
    elif isinstance(ref_val, str) and isinstance(gen_val, str):
        ref_s = ref_val.strip()
        gen_s = gen_val.strip()
        if ref_s == gen_s:
            return 1.0
        return SequenceMatcher(None, ref_s, gen_s).ratio()
    else:
        # Type mismatch — try string comparison
        return SequenceMatcher(None, str(ref_val), str(gen_val)).ratio()


def _list_similarity(ref_list, gen_list):
    """Compare two lists using element-wise matching."""
    if not ref_list and not gen_list:
        return 1.0
    if not ref_list or not gen_list:
        return 0.0

    # Try to match by order first
    n = max(len(ref_list), len(gen_list))
    scores = []
    for i in range(n):
        if i >= len(ref_list):
            scores.append(0.0)
        elif i >= len(gen_list):
            scores.append(0.0)
        else:
            scores.append(_value_similarity(ref_list[i], gen_list[i]))

    return sum(scores) / len(scores)


def compute_block_coverage(ref_blocks, gen_blocks):
    """Compute Jaccard coverage on block fingerprints."""
    if not ref_blocks and not gen_blocks:
        return 1.0
    if not ref_blocks or not gen_blocks:
        return 0.0

    ref_fps = set(block_fingerprint(b) for b in ref_blocks)
    gen_fps = set(block_fingerprint(b) for b in gen_blocks)

    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def compute_body_accuracy(ref_blocks, gen_blocks):
    """For blocks that match on fingerprint, compare their bodies."""
    ref_by_fp = {}
    for b in ref_blocks:
        fp = block_fingerprint(b)
        ref_by_fp[fp] = b

    gen_by_fp = {}
    for b in gen_blocks:
        fp = block_fingerprint(b)
        gen_by_fp[fp] = b

    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0

    scores = []
    for fp in matched_fps:
        ref_b = ref_by_fp[fp]
        gen_b = gen_by_fp[fp]
        sim = body_similarity(ref_b["body"], gen_b["body"])
        scores.append(sim)

    return sum(scores) / len(scores)


def compute_resource_type_distribution(ref_blocks, gen_blocks):
    """Compare the distribution of block types (resource types, data sources, etc.)."""
    def get_type_counts(blocks):
        counts = {}
        for b in blocks:
            if b["block_type"] == "resource":
                key = f"resource.{b['type_label']}"
            elif b["block_type"] == "data":
                key = f"data.{b['type_label']}"
            else:
                key = b["block_type"]
            counts[key] = counts.get(key, 0) + 1
        return counts

    if not ref_blocks and not gen_blocks:
        return 1.0
    if not ref_blocks or not gen_blocks:
        return 0.0

    ref_types = get_type_counts(ref_blocks)
    gen_types = get_type_counts(gen_blocks)

    all_types = set(ref_types.keys()) | set(gen_types.keys())
    if not all_types:
        return 1.0

    type_jaccard = len(set(ref_types.keys()) & set(gen_types.keys())) / len(all_types)

    count_sims = []
    for t in set(ref_types.keys()) & set(gen_types.keys()):
        rc = ref_types[t]
        gc = gen_types[t]
        count_sims.append(min(rc, gc) / max(rc, gc))

    count_sim = sum(count_sims) / len(count_sims) if count_sims else 0.0

    return 0.5 * type_jaccard + 0.5 * count_sim


def compute_reference_integrity(ref_blocks, gen_blocks):
    """Check that cross-references between resources are preserved.
    Looks for references like aws_vpc.main.id in attribute values."""

    def extract_references(body, prefix=""):
        """Extract all resource references from a body dict."""
        refs = set()
        if isinstance(body, dict):
            for k, v in body.items():
                refs.update(extract_references(v, f"{prefix}.{k}" if prefix else k))
        elif isinstance(body, list):
            for item in body:
                refs.update(extract_references(item, prefix))
        elif isinstance(body, str):
            # Match patterns like aws_vpc.main.id or local.name
            for m in re.finditer(r'\b((?:aws_|random_|data\.aws_)[a-z_]+\.[a-z_][a-z0-9_]*)\b', body):
                refs.add(m.group(1))
            # Also match var.xxx and local.xxx references
            for m in re.finditer(r'\b((?:var|local)\.[a-z_][a-z0-9_]*)\b', body):
                refs.add(m.group(1))
        return refs

    ref_refs = set()
    gen_refs = set()

    for b in ref_blocks:
        ref_refs.update(extract_references(b["body"]))
    for b in gen_blocks:
        gen_refs.update(extract_references(b["body"]))

    if not ref_refs and not gen_refs:
        return 1.0
    if not ref_refs:
        return 1.0  # Extra refs OK
    if not gen_refs:
        return 0.0

    intersection = len(ref_refs & gen_refs)
    union = len(ref_refs | gen_refs)
    return intersection / union if union > 0 else 1.0


def extract_comments(content):
    """Extract comments from HCL content."""
    comments = []
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#'):
            comment_text = stripped[1:].strip()
            if comment_text:
                comments.append(comment_text.lower())
        elif stripped.startswith('//'):
            comment_text = stripped[2:].strip()
            if comment_text:
                comments.append(comment_text.lower())
    # Also check for /* ... */ block comments
    for m in re.finditer(r'/\*(.+?)\*/', content, re.DOTALL):
        comment_text = m.group(1).strip()
        if comment_text:
            comments.append(comment_text.lower())
    return comments


def compute_comment_score(ref_content, gen_content):
    """Compare comments between reference and generated HCL files."""
    ref_comments = set()
    gen_comments = set()

    for content in (ref_content.values() if isinstance(ref_content, dict) else [ref_content]):
        ref_comments.update(extract_comments(content))

    for content in (gen_content.values() if isinstance(gen_content, dict) else [gen_content]):
        gen_comments.update(extract_comments(content))

    if not ref_comments and not gen_comments:
        return 1.0
    if not ref_comments:
        return 1.0  # Extra comments fine
    if not gen_comments:
        return 0.0

    intersection = len(ref_comments & gen_comments)
    union = len(ref_comments | gen_comments)
    return intersection / union if union > 0 else 1.0


class DomainInfra(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "infra"
        self.summary = "Terraform HCL infrastructure-as-code files with AWS resources (VPC, subnets, security groups, ASG, ALB, IAM, CloudWatch)"
        self.description = "Terraform infrastructure-as-code"
        self.file_format = [".tf"]
        self.domain_parser = "python-hcl2"
        self.category = "code"

    def parse_context(self, context):
        """Parse all .tf files in a context dict.

        Returns a dict with:
            blocks  – list of structured block dicts (from parse_all_hcl)
            comments – list of comment strings extracted from all .tf files
        Raises ValueError on HCL parse errors.
        """
        all_blocks, err = parse_all_hcl(context)
        if err:
            raise ValueError(err)

        all_comments = []
        for filename, content in context.items():
            if filename.endswith('.tf'):
                all_comments.extend(extract_comments(content))

        return {
            "blocks": all_blocks,
            "comments": all_comments,
        }

    def compute_domain_statistics(self, context):
        try:
            parsed = self.parse_context(context)
        except ValueError as e:
            return {"parse_error": str(e)}

        all_blocks = parsed["blocks"]

        type_counts = {}
        resource_types = set()
        for b in all_blocks:
            bt = b["block_type"]
            if bt == "resource":
                key = b["type_label"]
                resource_types.add(key)
            else:
                key = bt
            type_counts[key] = type_counts.get(key, 0) + 1

        return {
            "Total Blocks": len(all_blocks),
            "Resource Types": len(resource_types),
            "Block Types": type_counts,
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

        # Parse blocks from both contexts
        try:
            ref_parsed = self.parse_context(reference_context)
        except ValueError as e:
            return {"score": 0.0, "error": f"Reference parse error: {e}"}
        try:
            gen_parsed = self.parse_context(generated_context)
        except ValueError as e:
            return {"score": 0.0, "error": f"Generated parse error: {e}"}

        ref_blocks = ref_parsed["blocks"]
        gen_blocks = gen_parsed["blocks"]

        if debug:
            print(f"Reference blocks: {len(ref_blocks)}, Generated blocks: {len(gen_blocks)}")

        # Compute component scores
        coverage = compute_block_coverage(ref_blocks, gen_blocks)
        body_accuracy = compute_body_accuracy(ref_blocks, gen_blocks)
        type_dist = compute_resource_type_distribution(ref_blocks, gen_blocks)
        ref_integrity = compute_reference_integrity(ref_blocks, gen_blocks)
        comment_score = compute_comment_score(reference_context, generated_context)

        # Final score formula:
        # coverage^2 (critical — missing blocks heavily penalized)
        # * body_accuracy (most important content metric)
        # * sqrt((type_dist + ref_integrity + comment_score) / 3) (secondary precision)
        auxiliary = (type_dist + ref_integrity + comment_score) / 3.0
        score = (coverage ** 2) * body_accuracy * math.sqrt(max(auxiliary, 0.0))

        eval_obj = {
            "score": score,
            "block_coverage": coverage,
            "body_accuracy": body_accuracy,
            "type_distribution": type_dist,
            "reference_integrity": ref_integrity,
            "comment_preservation": comment_score,
            "ref_blocks": len(ref_blocks),
            "gen_blocks": len(gen_blocks),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
