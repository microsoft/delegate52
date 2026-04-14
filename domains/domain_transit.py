from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
from collections import defaultdict
import csv, io, os
import ujson as json


# -- GTFS file classification --
# Core GTFS files and their primary key columns
GTFS_FILE_KEYS = {
    "agency.txt":          ["agency_id"],
    "routes.txt":          ["route_id"],
    "stops.txt":           ["stop_id"],
    "trips.txt":           ["trip_id"],
    "stop_times.txt":      ["trip_id", "stop_sequence"],
    "calendar.txt":        ["service_id"],
    "calendar_dates.txt":  ["service_id", "date"],
    "fare_attributes.txt": ["fare_id"],
    "fare_rules.txt":      ["fare_id", "route_id", "origin_id", "destination_id"],
    "frequencies.txt":     ["trip_id", "start_time"],
    "shapes.txt":          ["shape_id", "shape_pt_sequence"],
    "directions.txt":      ["route_id", "direction_id"],
    "feed_info.txt":       [],
}

# Cross-file foreign key relationships: (file, column) -> (referenced_file, referenced_column)
GTFS_FOREIGN_KEYS = {
    ("routes.txt", "agency_id"):      ("agency.txt", "agency_id"),
    ("trips.txt", "route_id"):        ("routes.txt", "route_id"),
    ("trips.txt", "service_id"):      ("calendar.txt", "service_id"),
    ("stop_times.txt", "trip_id"):    ("trips.txt", "trip_id"),
    ("stop_times.txt", "stop_id"):    ("stops.txt", "stop_id"),
    ("fare_rules.txt", "route_id"):   ("routes.txt", "route_id"),
    ("directions.txt", "route_id"):   ("routes.txt", "route_id"),
}


def parse_gtfs_csv(content):
    """Parse a GTFS CSV file into (headers, rows). Handles quoting and empty fields."""
    try:
        content = content.strip()
        if not content:
            return [], []
        reader = csv.DictReader(io.StringIO(content))
        rows = []
        headers = reader.fieldnames if reader.fieldnames else []
        for row in reader:
            if row and all(k is not None for k in row.keys()):
                clean_row = {}
                for k, v in row.items():
                    if k is not None:
                        clean_row[k] = str(v).strip().strip('"') if v is not None else ''
                if clean_row:
                    rows.append(clean_row)
        return headers, rows
    except Exception as e:
        print(f"\033[93mWarning: GTFS CSV parse error: {e}\033[0m")
        return [], []


def normalize_value(v):
    """Normalize a GTFS value for comparison: strip whitespace and quotes, lowercase."""
    if v is None:
        return ''
    return str(v).strip().strip('"').lower()


def row_to_key(row, key_columns):
    """Build a compound key tuple from a row and its key columns."""
    return tuple(normalize_value(row.get(col, '')) for col in key_columns)


def parse_full_gtfs(context):
    """Parse all GTFS files from a context dict into a structured representation.
    Returns {filename: {"headers": [...], "rows": [...], "by_key": {key_tuple: row}}}
    """
    result = {}
    for filename, content in context.items():
        headers, rows = parse_gtfs_csv(content)
        base = os.path.basename(filename)
        key_columns = GTFS_FILE_KEYS.get(base, [])
        by_key = {}
        for row in rows:
            if key_columns:
                key = row_to_key(row, key_columns)
                by_key[key] = row
        result[base] = {
            "headers": headers,
            "rows": rows,
            "by_key": by_key,
            "key_columns": key_columns,
        }
    return result


def compute_file_presence_score(ref_parsed, gen_parsed):
    """Score: what fraction of reference files are present in the generated output."""
    if not ref_parsed:
        return 1.0 if not gen_parsed else 0.0
    ref_files = set(ref_parsed.keys())
    gen_files = set(gen_parsed.keys())
    if not ref_files:
        return 1.0
    return len(ref_files & gen_files) / len(ref_files)


def compute_header_score(ref_parsed, gen_parsed):
    """Score: average header match across all files."""
    scores = []
    for filename, ref_data in ref_parsed.items():
        if filename not in gen_parsed:
            scores.append(0.0)
            continue
        gen_data = gen_parsed[filename]
        ref_h = [h.strip().lower() for h in ref_data["headers"] if h]
        gen_h = [h.strip().lower() for h in gen_data["headers"] if h]
        if not ref_h and not gen_h:
            scores.append(1.0)
        elif not ref_h or not gen_h:
            scores.append(0.0)
        elif set(ref_h) == set(gen_h):
            scores.append(1.0 if ref_h == gen_h else 0.95)
        else:
            ref_set, gen_set = set(ref_h), set(gen_h)
            inter = len(ref_set & gen_set)
            union = len(ref_set | gen_set)
            scores.append(inter / union if union > 0 else 0.0)
    return sum(scores) / len(scores) if scores else 1.0


def compute_row_preservation_score(ref_parsed, gen_parsed):
    """Score: row-level recall across files, weighted by row count.
    For each reference row, check if it appears correctly in the generated output.
    Missing rows and corrupted field values both reduce the score."""
    total_ref_rows = sum(len(d["rows"]) for d in ref_parsed.values())
    if total_ref_rows == 0:
        return 1.0 if all(len(d.get("rows", [])) == 0 for d in gen_parsed.values()) else 0.0

    weighted_score = 0.0
    for filename, ref_data in ref_parsed.items():
        ref_rows = ref_data["rows"]
        weight = len(ref_rows) / total_ref_rows if total_ref_rows > 0 else 0.0
        if filename not in gen_parsed:
            continue  # 0 contribution (file missing)
        gen_rows = gen_parsed[filename]["rows"]
        if not ref_rows and not gen_rows:
            weighted_score += weight * 1.0
            continue
        if not ref_rows or not gen_rows:
            continue  # 0 contribution
        key_columns = ref_data["key_columns"]
        if key_columns:
            # For keyed files: per-row recall with field accuracy
            gen_by_key = gen_parsed[filename]["by_key"]
            row_scores = []
            for key, ref_row in ref_data["by_key"].items():
                if key in gen_by_key:
                    gen_row = gen_by_key[key]
                    all_cols = set(ref_row.keys()) | set(gen_row.keys())
                    match_count = sum(1 for c in all_cols
                                      if normalize_value(ref_row.get(c)) == normalize_value(gen_row.get(c)))
                    row_scores.append(match_count / len(all_cols) if all_cols else 1.0)
                else:
                    row_scores.append(0.0)  # row missing
            file_score = sum(row_scores) / len(row_scores) if row_scores else 0.0
            # Penalize extra rows not in reference
            extra = max(0, len(gen_rows) - len(ref_rows))
            if extra > 0:
                file_score *= len(ref_rows) / (len(ref_rows) + extra)
        else:
            # No key columns — compare as sets of normalized tuples
            def row_tuple(r):
                return tuple(sorted((k, normalize_value(v)) for k, v in r.items()))
            ref_set = set(row_tuple(r) for r in ref_rows)
            gen_set = set(row_tuple(r) for r in gen_rows)
            # Use recall against reference
            matched = len(ref_set & gen_set)
            file_score = matched / len(ref_set) if ref_set else 1.0
        weighted_score += weight * file_score
    return weighted_score


def compute_row_count_score(ref_parsed, gen_parsed):
    """Score: penalize for missing or extra rows across all files."""
    total_ref = sum(len(d["rows"]) for d in ref_parsed.values())
    total_gen = sum(len(d["rows"]) for d in gen_parsed.values())
    if total_ref == 0 and total_gen == 0:
        return 1.0
    max_count = max(total_ref, total_gen, 1)
    return 1.0 - abs(total_ref - total_gen) / max_count


def compute_referential_integrity_score(ref_parsed, gen_parsed):
    """Score: check that foreign key relationships in the generated GTFS are intact.
    Checks both directions: generated FK values must exist in target table,
    and reference FK relationships must be preserved."""
    if not gen_parsed:
        return 0.0
    # Check FK validity on generated output
    checks = 0
    passed = 0
    for (src_file, src_col), (tgt_file, tgt_col) in GTFS_FOREIGN_KEYS.items():
        if src_file not in gen_parsed or tgt_file not in gen_parsed:
            continue
        src_rows = gen_parsed[src_file]["rows"]
        tgt_rows = gen_parsed[tgt_file]["rows"]
        if not src_rows or not tgt_rows:
            continue
        tgt_ids = set(normalize_value(r.get(tgt_col, '')) for r in tgt_rows)
        tgt_ids.discard('')
        if not tgt_ids:
            continue
        for row in src_rows:
            val = normalize_value(row.get(src_col, ''))
            if val:
                checks += 1
                if val in tgt_ids:
                    passed += 1
    # Also check reference FK completeness: reference FK values should appear in generated
    for (src_file, src_col), (tgt_file, tgt_col) in GTFS_FOREIGN_KEYS.items():
        if src_file not in ref_parsed or tgt_file not in ref_parsed:
            continue
        if src_file not in gen_parsed or tgt_file not in gen_parsed:
            continue
        ref_src_rows = ref_parsed[src_file]["rows"]
        gen_tgt_rows = gen_parsed[tgt_file]["rows"]
        if not ref_src_rows:
            continue
        gen_tgt_ids = set(normalize_value(r.get(tgt_col, '')) for r in gen_tgt_rows)
        gen_tgt_ids.discard('')
        for row in ref_src_rows:
            val = normalize_value(row.get(src_col, ''))
            if val:
                checks += 1
                if val in gen_tgt_ids:
                    passed += 1
    if checks == 0:
        return 1.0
    return passed / checks


def compute_stop_times_order_score(ref_parsed, gen_parsed):
    """Score: check that stop_times within each trip preserve the correct stop sequence order."""
    if not gen_parsed or "stop_times.txt" not in gen_parsed:
        return 0.0 if (ref_parsed and "stop_times.txt" in ref_parsed and ref_parsed["stop_times.txt"]["rows"]) else 1.0
    if "stop_times.txt" not in ref_parsed:
        return 1.0

    def group_by_trip(rows):
        trips = defaultdict(list)
        for row in rows:
            tid = normalize_value(row.get("trip_id", ""))
            if tid:
                trips[tid].append(row)
        # Sort each trip's stops by stop_sequence
        for tid in trips:
            trips[tid].sort(key=lambda r: int(r.get("stop_sequence", 0)) if r.get("stop_sequence", "").strip().isdigit() else 0)
        return trips

    ref_trips = group_by_trip(ref_parsed["stop_times.txt"]["rows"])
    gen_trips = group_by_trip(gen_parsed["stop_times.txt"]["rows"])

    if not ref_trips:
        return 1.0 if not gen_trips else 0.0

    scores = []
    for tid, ref_stops in ref_trips.items():
        if tid not in gen_trips:
            scores.append(0.0)
            continue
        gen_stops = gen_trips[tid]
        # Compare stop_id sequence
        ref_seq = [normalize_value(s.get("stop_id", "")) for s in ref_stops]
        gen_seq = [normalize_value(s.get("stop_id", "")) for s in gen_stops]
        scores.append(SequenceMatcher(None, ref_seq, gen_seq).ratio())

    return sum(scores) / len(scores) if scores else 1.0


class DomainTransit(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "transit"
        self.summary = "GTFS transit feed with routes, stops, trips, and schedules"
        self.description = "GTFS transit schedules"
        self.file_format = [".txt"]
        self.domain_parser = "custom"
        self.category = "everyday"

    def parse_context(self, context):
        """Parse all GTFS files from a context dict into a structured representation.
        Returns {filename: {"headers": [...], "rows": [...], "by_key": {key_tuple: row}, "key_columns": [...]}}
        """
        return parse_full_gtfs(context)

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        num_files = len(parsed)
        num_routes = len(parsed.get("routes.txt", {}).get("rows", []))
        num_stops = len(parsed.get("stops.txt", {}).get("rows", []))
        num_trips = len(parsed.get("trips.txt", {}).get("rows", []))
        num_stop_times = len(parsed.get("stop_times.txt", {}).get("rows", []))
        return {
            "Files": num_files,
            "Routes": num_routes,
            "Stops": num_stops,
            "Trips": num_trips,
            "Stop Times": num_stop_times,
        }

    def evaluate_context(self, sample_id, generated_context, target_state):
        if target_state["state_id"] != "basic_state":
            return {}

        try:
            sample_folder = f"{self.samples_folder}{sample_id}/"
            with open(os.path.join(sample_folder, "sample.json"), "r") as f:
                sample = json.load(f)

            start_state_id = sample["start_state"]
            start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
            reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))

            ref_parsed = self.parse_context(reference_context)
            gen_parsed = self.parse_context(generated_context)

            # Component scores
            file_presence = compute_file_presence_score(ref_parsed, gen_parsed)
            header_score = compute_header_score(ref_parsed, gen_parsed)
            row_preservation = compute_row_preservation_score(ref_parsed, gen_parsed)
            row_count = compute_row_count_score(ref_parsed, gen_parsed)
            ref_integrity = compute_referential_integrity_score(ref_parsed, gen_parsed)
            order_score = compute_stop_times_order_score(ref_parsed, gen_parsed)

            # Scoring: multiplicative approach.
            # row_preservation is the dominant signal; other components act as quality multipliers.
            # This ensures removing K/N rows drops the score by at least K/N.
            quality = (
                0.35 * file_presence
                + 0.25 * order_score
                + 0.15 * ref_integrity
                + 0.15 * row_count
                + 0.10 * header_score
            )
            score = row_preservation * quality

            eval_obj = {
                "score": score,
                "file_presence_score": file_presence,
                "header_score": header_score,
                "row_preservation_score": row_preservation,
                "row_count_score": row_count,
                "referential_integrity_score": ref_integrity,
                "stop_times_order_score": order_score,
                "ref_file_count": len(ref_parsed),
                "gen_file_count": len(gen_parsed),
                "ref_total_rows": sum(len(d["rows"]) for d in ref_parsed.values()),
                "gen_total_rows": sum(len(d["rows"]) for d in gen_parsed.values()),
            }
            print(f"\033[94m{eval_obj}\033[0m")
            return eval_obj

        except Exception as e:
            print(f"\033[91mError in transit evaluation: {e}\033[0m")
            import traceback
            traceback.print_exc()
            return {
                "score": 0.0,
                "error": str(e),
            }
