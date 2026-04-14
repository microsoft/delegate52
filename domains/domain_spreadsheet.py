from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
from collections import defaultdict
import csv, io, os
import ujson as json


def parse_csv(content):
    try:
        reader = csv.DictReader(io.StringIO(content.strip()))
        rows = []
        headers = reader.fieldnames if reader.fieldnames else []
        for row in reader:
            # Skip rows with None keys or completely empty rows
            if row and all(k is not None for k in row.keys()):
                # Filter out None values, convert to string
                clean_row = {k: (str(v) if v is not None else '') for k, v in row.items() if k is not None}
                if clean_row:
                    rows.append(clean_row)
        return headers, rows
    except Exception as e:
        print(f"\033[93mWarning: CSV parse error: {e}\033[0m")
        return [], []


def normalize_row(row):
    try:
        return tuple(sorted((str(k).strip(), str(v).strip()) for k, v in row.items() if k is not None and str(k).strip()))
    except Exception:
        return tuple()


def rows_to_set(rows):
    result = set()
    for r in rows:
        try:
            normalized = normalize_row(r)
            if normalized:  # skip empty tuples
                result.add(normalized)
        except Exception:
            continue
    return result


def compute_row_preservation_score(ref_rows, gen_rows):
    if not ref_rows and not gen_rows:
        return 1.0
    if not ref_rows or not gen_rows:
        return 0.0
    
    try:
        ref_set = rows_to_set(ref_rows)
        gen_set = rows_to_set(gen_rows)
        
        if not ref_set and not gen_set:
            return 1.0
        if not ref_set or not gen_set:
            return 0.0
        
        intersection = len(ref_set & gen_set)
        union = len(ref_set | gen_set)
        return intersection / union if union > 0 else 1.0
    except Exception as e:
        print(f"\033[93mWarning: Row preservation score error: {e}\033[0m")
        return 0.0


def compute_header_score(ref_headers, gen_headers):
    if not ref_headers and not gen_headers:
        return 1.0
    if not ref_headers or not gen_headers:
        return 0.0
    try:
        ref_norm = [str(h).strip().lower() for h in ref_headers if h]
        gen_norm = [str(h).strip().lower() for h in gen_headers if h]
        if not ref_norm or not gen_norm:
            return 0.0
        if set(ref_norm) == set(gen_norm):
            return 1.0 if ref_norm == gen_norm else 0.9
        ref_set, gen_set = set(ref_norm), set(gen_norm)
        intersection = len(ref_set & gen_set)
        union = len(ref_set | gen_set)
        return intersection / union if union > 0 else 0.0
    except Exception as e:
        print(f"\033[93mWarning: Header score error: {e}\033[0m")
        return 0.0


def compute_order_score_with_tie_tolerance(ref_rows, gen_rows, group_key=None):
    if not ref_rows or not gen_rows:
        return 1.0 if (not ref_rows and not gen_rows) else 0.0
    
    # Parse group_key - can be a single column or comma-separated compound key
    if group_key is None:
        key_columns = []
    elif isinstance(group_key, str):
        key_columns = [k.strip() for k in group_key.split(',')]
    else:
        key_columns = []
    
    # If no group_key specified, use strict sequence matching
    if not key_columns:
        ref_seq = [normalize_row(r) for r in ref_rows if normalize_row(r)]
        gen_seq = [normalize_row(r) for r in gen_rows if normalize_row(r)]
        if not ref_seq or not gen_seq:
            return 0.0
        return SequenceMatcher(None, ref_seq, gen_seq).ratio()
    
    try:
        def get_compound_key(row):
            """Build a compound key from multiple columns."""
            parts = []
            for col in key_columns:
                val = row.get(col)
                parts.append(str(val) if val is not None else '')
            return '|'.join(parts)
        
        def group_rows(rows):
            groups = defaultdict(list)
            order = []
            for r in rows:
                key = get_compound_key(r)
                if key not in [g[0] for g in order]:
                    order.append((key, []))
                normalized = normalize_row(r)
                if normalized:
                    groups[key].append(normalized)
            # Filter out empty keys (all key columns were missing)
            empty_key = '|'.join(['' for _ in key_columns])
            return [(k, set(groups[k])) for k in [g[0] for g in order] if k != empty_key and groups[k]]
        
        ref_groups = group_rows(ref_rows)
        gen_groups = group_rows(gen_rows)
        
        if not ref_groups or not gen_groups:
            # Fallback to sequence matching
            ref_seq = [normalize_row(r) for r in ref_rows if normalize_row(r)]
            gen_seq = [normalize_row(r) for r in gen_rows if normalize_row(r)]
            if not ref_seq or not gen_seq:
                return 0.0
            return SequenceMatcher(None, ref_seq, gen_seq).ratio()
        
        ref_keys = [g[0] for g in ref_groups]
        gen_keys = [g[0] for g in gen_groups]
        
        if ref_keys != gen_keys:
            key_score = SequenceMatcher(None, ref_keys, gen_keys).ratio()
        else:
            key_score = 1.0
        
        content_scores = []
        for ref_key, ref_set in ref_groups:
            matching_gen = [g for g in gen_groups if g[0] == ref_key]
            if matching_gen:
                gen_set = matching_gen[0][1]
                intersection = len(ref_set & gen_set)
                union = len(ref_set | gen_set)
                content_scores.append(intersection / union if union > 0 else 1.0)
            else:
                content_scores.append(0.0)
        
        content_score = sum(content_scores) / len(content_scores) if content_scores else 0.0
        return 0.4 * key_score + 0.6 * content_score
    except Exception as e:
        print(f"\033[93mWarning: Order score error: {e}\033[0m")
        return 0.0


def parse_context_to_rows(context):
    all_rows = []
    headers = []
    
    for filename, content in context.items():
        try:
            content = content.strip() if content else ''
            if not content:
                continue
            
            h, rows = parse_csv(content)
            
            if h and not headers:
                headers = h
            all_rows.extend(rows)
        except Exception as e:
            print(f"\033[93mWarning: Failed to parse {filename}: {e}\033[0m")
            continue
    
    return headers, all_rows


def _normalize_csv_content(content):
    """Normalize a CSV string to fix minor LLM formatting differences.

    Handles:
    - Non-breaking spaces (U+00A0) → regular spaces
    - Float precision artifacts (1.6900000000000002 → 1.69)
    - Scientific notation equivalence (1.75e+08 ↔ 175000000)
    - Strips empty-name index columns
    """
    content = content.replace('\u00a0', ' ')
    try:
        reader = csv.DictReader(io.StringIO(content.strip()))
        if not reader.fieldnames:
            return content
        # Filter out empty-name columns
        headers = [h for h in reader.fieldnames if h.strip()]
        rows = list(reader)
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=headers, lineterminator='\n')
        writer.writeheader()
        for row in rows:
            clean = {}
            for h in headers:
                v = row.get(h, '')
                v = str(v).strip() if v is not None else ''
                v = v.replace('\u00a0', ' ')
                if v:
                    try:
                        f = float(v)
                        v = f'{f:.10g}'
                    except (ValueError, OverflowError):
                        pass
                clean[h] = v
            writer.writerow(clean)
        return out.getvalue()
    except Exception:
        return content


class DomainSpreadsheet(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "spreadsheet"
        self.summary = "Tabular CSV data with rows, columns, and structured values"
        self.description = "Tabular CSV data"
        self.file_format = [".csv"]
        self.domain_parser = "custom"
        self.category = "records"

    def preprocess_context(self, context):
        """Normalize CSV content before parsing.

        Fixes minor LLM formatting differences that are semantically equivalent:
        non-breaking spaces, float precision artifacts, scientific notation,
        and empty-name index columns.
        """
        cleaned = {}
        for filename, content in context.items():
            if filename.endswith('.csv'):
                cleaned[filename] = _normalize_csv_content(content)
            else:
                cleaned[filename] = content
        return cleaned

    def parse_context(self, context):
        context = self.preprocess_context(context)
        headers, rows = parse_context_to_rows(context)
        return {
            "headers": headers,
            "rows": rows,
        }
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        return {
            "Rows": len(parsed["rows"]),
            "Columns": len(parsed["headers"]),
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        if target_state["state_id"] != "basic_state":
            return {}
        
        try:
            sample_folder = f"{self.samples_folder}{sample_id}/"
            with open(os.path.join(sample_folder, "sample.json"), "r") as f:
                sample = json.load(f)
            
            start_state_id = sample["start_state"]
            start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
            reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
            
            # Parse both contexts
            ref_parsed = self.parse_context(reference_context)
            ref_headers, ref_rows = ref_parsed["headers"], ref_parsed["rows"]
            gen_parsed = self.parse_context(generated_context)
            gen_headers, gen_rows = gen_parsed["headers"], gen_parsed["rows"]
            
            # Get group_key from sample.json (defaults to None for strict sequence matching)
            group_key = sample.get("group_key", None)
            
            # Compute component scores
            row_preservation = compute_row_preservation_score(ref_rows, gen_rows)
            header_score = compute_header_score(ref_headers, gen_headers)
            order_score = compute_order_score_with_tie_tolerance(ref_rows, gen_rows, group_key)
            
            # Row count match
            max_count = max(len(ref_rows), len(gen_rows), 1)
            count_score = 1.0 - abs(len(ref_rows) - len(gen_rows)) / max_count
            
            # Coverage-adjusted order: penalize missing rows in ordering assessment
            row_coverage = min(len(gen_rows), len(ref_rows)) / max(len(ref_rows), 1)
            adjusted_order = row_coverage ** 2 * order_score
            
            # Content score: row preservation (60%), coverage-adjusted order (25%), count (15%)
            content_score = 0.60 * row_preservation + 0.25 * adjusted_order + 0.15 * count_score
            
            # Header correctness as multiplicative gate (perfect headers = no penalty)
            score = content_score * (0.85 + 0.15 * header_score)
            
            eval_obj = {
                "score": score,
                "row_preservation_score": row_preservation,
                "order_score": order_score,
                "header_score": header_score,
                "count_score": count_score,
                "ref_row_count": len(ref_rows),
                "gen_row_count": len(gen_rows),
                "ref_headers": ref_headers,
                "gen_headers": gen_headers,
            }
            print(f"\033[94m{eval_obj}\033[0m")
            return eval_obj
        
        except Exception as e:
            print(f"\033[91mError in spreadsheet evaluation: {e}\033[0m")
            return {
                "score": 0.0,
                "error": str(e),
                "row_preservation_score": 0.0,
                "order_score": 0.0,
                "header_score": 0.0,
                "count_score": 0.0,
            }
