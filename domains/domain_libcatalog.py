from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, math, re, ujson as json
from pymarc import parse_xml_to_array, Record
from io import BytesIO


def preprocess_marcxml(content):
    """Normalize raw MARCXML string before parsing.

    Fixes common LLM syntax errors that cause the XML parser to reject
    otherwise semantically correct content:
    1. Strips trailing content after the root </collection> tag (e.g. stray '?>')
    2. Fixes '--' inside XML comments (illegal per XML spec), replacing with '- -'
    """
    # Strip content after the last </collection> closing tag
    idx = content.rfind('</collection>')
    if idx >= 0:
        content = content[:idx + len('</collection>')]
    # Fix '--' inside XML comments (not allowed in XML spec)
    # Replace <!-- ... -- ... --> patterns where '--' appears mid-comment
    def _fix_comment_dashes(m):
        body = m.group(1)
        # Replace interior '--' with '- -' (but not the closing '-->')
        fixed = body.replace('--', '- -')
        return '<!--' + fixed + '-->'
    content = re.sub(r'<!--(.*?)-->', _fix_comment_dashes, content, flags=re.DOTALL)
    return content


def parse_marcxml_records(content):
    """Parse MARCXML content into a list of pymarc Record objects."""
    try:
        # pymarc's parse_xml_to_array expects a file-like object or filename
        records = parse_xml_to_array(BytesIO(content.encode("utf-8")))
        return records
    except Exception as e:
        print(f"\033[91mMARCXML parsing error: {e}\033[0m")
        return []


def parse_all_records(context):
    """Parse all MARCXML records from all files in the context."""
    all_records = []
    for filename, content in context.items():
        if filename.endswith(".xml"):
            records = parse_marcxml_records(content)
            all_records.extend(records)
    return all_records


def record_control_number(record):
    """Get the 001 control number as a record identifier."""
    f001 = record.get("001")
    if f001:
        return f001.data.strip()
    return None


def extract_leader_data(record):
    """Extract leader string from a record."""
    return str(record.leader) if record.leader else ""


def extract_control_fields(record):
    """Extract control fields (001-009) as a list of (tag, data) tuples."""
    fields = []
    for field in record.fields:
        if hasattr(field, "data"):  # ControlField
            data = field.data if field.data else ""
            fields.append((field.tag, data.strip()))
    return fields


def extract_data_fields(record):
    """Extract data fields (010+) as a list of structured dicts."""
    fields = []
    for field in record.fields:
        if hasattr(field, "subfields"):  # DataField
            subfields = []
            for sf in field.subfields:
                subfields.append((sf.code, sf.value.strip() if sf.value else ""))
            fields.append({
                "tag": field.tag,
                "ind1": field.indicator1 or " ",
                "ind2": field.indicator2 or " ",
                "subfields": subfields,
            })
    return fields


def fingerprint_data_field(field_dict):
    """Create a fingerprint for a data field for matching purposes."""
    sf_str = "|".join(f"{code}={val}" for code, val in field_dict["subfields"])
    return f"{field_dict['tag']}_{field_dict['ind1']}{field_dict['ind2']}_{sf_str}"


def compute_record_coverage(ref_records, gen_records):
    """Score: what fraction of reference records are present in generated output.
    Uses Jaccard similarity on control numbers."""
    if not ref_records and not gen_records:
        return 1.0
    if not ref_records or not gen_records:
        return 0.0

    ref_ids = set()
    for r in ref_records:
        cn = record_control_number(r)
        if cn:
            ref_ids.add(cn)

    gen_ids = set()
    for r in gen_records:
        cn = record_control_number(r)
        if cn:
            gen_ids.add(cn)

    if not ref_ids and not gen_ids:
        # Fall back to count-based comparison
        return min(len(gen_records), len(ref_records)) / max(len(gen_records), len(ref_records))

    intersection = len(ref_ids & gen_ids)
    union = len(ref_ids | gen_ids)
    return intersection / union if union > 0 else 0.0


def compute_leader_accuracy(ref_records, gen_records):
    """Score: how accurately leaders are preserved across matched records."""
    ref_by_id = {}
    for r in ref_records:
        cn = record_control_number(r)
        if cn:
            ref_by_id[cn] = r

    gen_by_id = {}
    for r in gen_records:
        cn = record_control_number(r)
        if cn:
            gen_by_id[cn] = r

    matched_ids = set(ref_by_id.keys()) & set(gen_by_id.keys())
    if not matched_ids:
        return 0.0

    scores = []
    for cid in matched_ids:
        ref_leader = extract_leader_data(ref_by_id[cid])
        gen_leader = extract_leader_data(gen_by_id[cid])
        if ref_leader == gen_leader:
            scores.append(1.0)
        elif ref_leader and gen_leader:
            # Character-level comparison of the 24-character leader
            matches = sum(1 for a, b in zip(ref_leader, gen_leader) if a == b)
            scores.append(matches / max(len(ref_leader), len(gen_leader)))
        else:
            scores.append(0.0)

    return sum(scores) / len(scores)


def compute_control_field_accuracy(ref_records, gen_records):
    """Score: how accurately control fields are preserved."""
    ref_by_id = {}
    for r in ref_records:
        cn = record_control_number(r)
        if cn:
            ref_by_id[cn] = r

    gen_by_id = {}
    for r in gen_records:
        cn = record_control_number(r)
        if cn:
            gen_by_id[cn] = r

    matched_ids = set(ref_by_id.keys()) & set(gen_by_id.keys())
    if not matched_ids:
        return 0.0

    scores = []
    for cid in matched_ids:
        ref_cfs = extract_control_fields(ref_by_id[cid])
        gen_cfs = extract_control_fields(gen_by_id[cid])

        ref_cf_dict = {tag: data for tag, data in ref_cfs}
        gen_cf_dict = {tag: data for tag, data in gen_cfs}

        all_tags = set(ref_cf_dict.keys()) | set(gen_cf_dict.keys())
        if not all_tags:
            scores.append(1.0)
            continue

        tag_scores = []
        for tag in all_tags:
            if tag in ref_cf_dict and tag in gen_cf_dict:
                if ref_cf_dict[tag] == gen_cf_dict[tag]:
                    tag_scores.append(1.0)
                else:
                    tag_scores.append(SequenceMatcher(None, ref_cf_dict[tag], gen_cf_dict[tag]).ratio() * 0.5)
            else:
                tag_scores.append(0.0)

        scores.append(sum(tag_scores) / len(tag_scores))

    return sum(scores) / len(scores)


def compute_data_field_accuracy(ref_records, gen_records):
    """Score: how accurately data fields are preserved, including indicators and subfields."""
    ref_by_id = {}
    for r in ref_records:
        cn = record_control_number(r)
        if cn:
            ref_by_id[cn] = r

    gen_by_id = {}
    for r in gen_records:
        cn = record_control_number(r)
        if cn:
            gen_by_id[cn] = r

    matched_ids = set(ref_by_id.keys()) & set(gen_by_id.keys())
    if not matched_ids:
        return 0.0

    scores = []
    for cid in matched_ids:
        ref_dfs = extract_data_fields(ref_by_id[cid])
        gen_dfs = extract_data_fields(gen_by_id[cid])

        if not ref_dfs and not gen_dfs:
            scores.append(1.0)
            continue
        if not ref_dfs or not gen_dfs:
            scores.append(0.0)
            continue

        # Group fields by tag for comparison
        ref_by_tag = {}
        for df in ref_dfs:
            ref_by_tag.setdefault(df["tag"], []).append(df)
        gen_by_tag = {}
        for df in gen_dfs:
            gen_by_tag.setdefault(df["tag"], []).append(df)

        all_tags = set(ref_by_tag.keys()) | set(gen_by_tag.keys())
        tag_scores = []
        tag_weights = []

        for tag in all_tags:
            ref_fields = ref_by_tag.get(tag, [])
            gen_fields = gen_by_tag.get(tag, [])

            # Weight by max of ref/gen field count so removal is proportional
            weight = max(len(ref_fields), len(gen_fields), 1)

            if not ref_fields and not gen_fields:
                tag_scores.append(1.0)
                tag_weights.append(weight)
                continue
            if not ref_fields or not gen_fields:
                tag_scores.append(0.0)
                tag_weights.append(weight)
                continue

            # Match fields within the same tag using fingerprint similarity
            # Use greedy matching: for each ref field, find best gen match
            matched_scores = []
            gen_used = set()

            for rf in ref_fields:
                best_score = 0.0
                best_idx = -1
                for gi, gf in enumerate(gen_fields):
                    if gi in gen_used:
                        continue
                    s = _compare_data_fields(rf, gf)
                    if s > best_score:
                        best_score = s
                        best_idx = gi
                if best_idx >= 0:
                    gen_used.add(best_idx)
                matched_scores.append(best_score)

            # Penalize extra generated fields
            extra_gen = len(gen_fields) - len(gen_used)
            total_count = max(len(ref_fields), len(gen_fields))
            field_score = sum(matched_scores) / total_count if total_count > 0 else 1.0
            tag_scores.append(field_score)
            tag_weights.append(weight)

        # Weighted average: tags with more fields contribute proportionally more
        total_weight = sum(tag_weights)
        if total_weight > 0 and tag_scores:
            scores.append(sum(s * w for s, w in zip(tag_scores, tag_weights)) / total_weight)
        else:
            scores.append(1.0)

    return sum(scores) / len(scores)


def _compare_data_fields(ref_field, gen_field):
    """Compare two data field dicts (same tag assumed). Returns 0-1 score."""
    score = 0.0
    total = 3.0  # indicators (2 × 0.5) + subfields (2.0)

    # Indicators (0.5 weight each)
    if ref_field["ind1"] == gen_field["ind1"]:
        score += 0.5
    if ref_field["ind2"] == gen_field["ind2"]:
        score += 0.5

    # Subfields comparison (2.0 weight)
    ref_sfs = ref_field["subfields"]
    gen_sfs = gen_field["subfields"]

    if not ref_sfs and not gen_sfs:
        score += 2.0
    elif not ref_sfs or not gen_sfs:
        pass  # 0 for subfields
    else:
        # Compare subfield sequences
        ref_sf_strs = [f"{code}={val}" for code, val in ref_sfs]
        gen_sf_strs = [f"{code}={val}" for code, val in gen_sfs]

        # Use SequenceMatcher for ordered comparison
        sf_ratio = SequenceMatcher(None, ref_sf_strs, gen_sf_strs).ratio()
        score += 2.0 * sf_ratio

    return score / total


class DomainLibcatalog(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "libcatalog"
        self.summary = "MARCXML library catalog records with bibliographic data"
        self.description = "MARCXML library records"
        self.file_format = [".xml"]
        self.domain_parser = "pymarc"
        self.category = "records"

    def preprocess_context(self, context):
        """Preprocess all XML files in the context dict."""
        cleaned = {}
        for filename, content in context.items():
            if filename.endswith('.xml'):
                cleaned[filename] = preprocess_marcxml(content)
            else:
                cleaned[filename] = content
        return cleaned

    def parse_context(self, context):
        """Parse MARCXML context into a dict with 'records' key."""
        context = self.preprocess_context(context)
        return {"records": parse_all_records(context)}

    def parse_all_records(self, context):
        return parse_all_records(context)

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        records = parsed["records"]
        material_types = set()
        field_count = 0
        for r in records:
            leader_str = str(r.leader) if r.leader else ""
            if len(leader_str) > 6:
                material_types.add(leader_str[6])
            field_count += len(r.fields)
        return {
            "Records": len(records),
            "Material Types": len(material_types),
            "Total Fields": field_count,
        }

    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {"score": None}

        try:
            sample_folder = f"{self.samples_folder}{sample_id}/"
            with open(os.path.join(sample_folder, "sample.json"), "r") as f:
                sample = json.load(f)

            start_state_id = sample["start_state"]
            start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
            reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))

            ref_records = self.parse_context(reference_context)["records"]
            gen_records = self.parse_context(generated_context)["records"]

            if debug:
                print(f"Reference records: {len(ref_records)}, Generated records: {len(gen_records)}")

            # Compute component scores
            coverage_score = compute_record_coverage(ref_records, gen_records)
            leader_score = compute_leader_accuracy(ref_records, gen_records)
            control_score = compute_control_field_accuracy(ref_records, gen_records)
            datafield_score = compute_data_field_accuracy(ref_records, gen_records)

            # Weighted combination for matched-record quality:
            # Leader encodes material type — 5%
            # Control fields encode key metadata — 5%
            # Data fields carry most semantic content — 90%
            quality_score = (
                0.05 * leader_score
                + 0.05 * control_score
                + 0.90 * datafield_score
            )
            # Final score = coverage × quality
            # This ensures removing K/N records drops score by at least K/N
            score = coverage_score * quality_score

            eval_obj = {
                "score": score,
                "record_coverage": coverage_score,
                "leader_accuracy": leader_score,
                "control_field_accuracy": control_score,
                "data_field_accuracy": datafield_score,
                "ref_record_count": len(ref_records),
                "gen_record_count": len(gen_records),
            }
            print(f"\033[94m{eval_obj}\033[0m")
            return eval_obj
        except Exception as e:
            print(f"\033[91mError in libcatalog evaluation: {e}\033[0m")
            import traceback
            traceback.print_exc()
            return {"score": 0.0, "error": "evaluation_error", "detailed_error": str(e)}
