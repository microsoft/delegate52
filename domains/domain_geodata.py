from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, math, re, ujson as json


def parse_geojson(content):
    """Parse GeoJSON content and extract features with all properties."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"\033[91mGeoJSON parsing error: {e}\033[0m")
        return [], {}

    # Handle case where parsed data is a list (raw feature array) instead of a dict
    if isinstance(data, list):
        data = {"type": "FeatureCollection", "features": data}
    if not isinstance(data, dict):
        print(f"\033[91mGeoJSON unexpected type: {type(data)}\033[0m")
        return [], {}

    metadata = {}
    for key in ("type", "name", "crs", "bbox"):
        if key in data:
            metadata[key] = data[key]

    features = []
    raw_features = data.get("features", [])
    for i, f in enumerate(raw_features):
        feat = {
            "index": i,
            "type": f.get("type", "Feature"),
            "geometry_type": None,
            "coordinates": None,
            "properties": {},
        }

        # Parse geometry
        geom = f.get("geometry") or {}
        feat["geometry_type"] = geom.get("type")
        coords = geom.get("coordinates")
        if coords is not None:
            feat["coordinates"] = coords
            # Extract centroid for Points
            if feat["geometry_type"] == "Point" and isinstance(coords, list) and len(coords) >= 2:
                try:
                    feat["centroid"] = (float(coords[0]), float(coords[1]))
                except (ValueError, TypeError):
                    feat["centroid"] = None
            else:
                feat["centroid"] = None
        else:
            feat["centroid"] = None

        # Parse all properties
        props = f.get("properties") or {}
        feat["properties"] = props

        features.append(feat)

    return features, metadata


def parse_all_features(context):
    """Parse features from all GeoJSON files in a context dict."""
    all_features = []
    all_metadata = {}
    for filename, content in context.items():
        if filename.endswith(".geojson") or filename.endswith(".json"):
            features, metadata = parse_geojson(content)
            all_features.extend(features)
            if metadata:
                all_metadata[filename] = metadata
    return all_features, all_metadata


def feature_fingerprint(feat):
    """Create a fingerprint for matching features across contexts.

    Uses the 'id' property if available, otherwise falls back to a
    combination of geometry type and the first property values.
    """
    props = feat.get("properties", {})

    # Primary: use 'id' property
    feat_id = props.get("id", "")
    if feat_id:
        return str(feat_id).lower().strip()

    # Fallback: combine first few property values
    parts = []
    for key in sorted(props.keys())[:3]:
        val = props.get(key, "")
        if isinstance(val, str):
            parts.append(val.lower().strip()[:40])
        elif val is not None:
            parts.append(str(val))
    if parts:
        return "|".join(parts)

    # Last resort: use coordinates
    centroid = feat.get("centroid")
    if centroid:
        return f"coord:{centroid[0]:.4f},{centroid[1]:.4f}"

    return f"idx:{feat.get('index', '?')}"


def build_fingerprint_map(features):
    """Build a dict mapping fingerprint -> feature, handling duplicates."""
    fp_map = {}
    for feat in features:
        fp = feature_fingerprint(feat)
        if fp not in fp_map:
            fp_map[fp] = feat
        else:
            # Duplicate fingerprint — append index to disambiguate
            fp_map[f"{fp}__dup{feat['index']}"] = feat
    return fp_map


def compute_feature_coverage(ref_features, gen_features):
    """Jaccard coverage of features by fingerprint."""
    if not ref_features and not gen_features:
        return 1.0
    if not ref_features or not gen_features:
        return 0.0

    ref_fps = {feature_fingerprint(f) for f in ref_features}
    gen_fps = {feature_fingerprint(f) for f in gen_features}

    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def normalize_text(text):
    """Normalize text for comparison."""
    if not text:
        return ""
    if not isinstance(text, str):
        return str(text)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def compare_values(ref_val, gen_val):
    """Compare two property values, returning similarity 0-1."""
    if ref_val is None and gen_val is None:
        return 1.0
    if ref_val is None or gen_val is None:
        return 0.0

    # Same type, same value
    if ref_val == gen_val:
        return 1.0

    # Both strings — use sequence matching
    if isinstance(ref_val, str) and isinstance(gen_val, str):
        ref_norm = normalize_text(ref_val)
        gen_norm = normalize_text(gen_val)
        if ref_norm == gen_norm:
            return 1.0
        return SequenceMatcher(None, ref_norm, gen_norm).ratio()

    # Both numbers — use ratio similarity
    if isinstance(ref_val, (int, float)) and isinstance(gen_val, (int, float)):
        if ref_val == 0 and gen_val == 0:
            return 1.0
        max_val = max(abs(ref_val), abs(gen_val))
        if max_val == 0:
            return 1.0
        return 1.0 - min(abs(ref_val - gen_val) / max_val, 1.0)

    # Both dicts — recursive comparison
    if isinstance(ref_val, dict) and isinstance(gen_val, dict):
        if not ref_val and not gen_val:
            return 1.0
        all_keys = set(ref_val.keys()) | set(gen_val.keys())
        if not all_keys:
            return 1.0
        scores = []
        for key in all_keys:
            if key in ref_val and key in gen_val:
                scores.append(compare_values(ref_val[key], gen_val[key]))
            else:
                scores.append(0.0)
        return sum(scores) / len(scores)

    # Both lists — element-wise comparison
    if isinstance(ref_val, list) and isinstance(gen_val, list):
        if not ref_val and not gen_val:
            return 1.0
        max_len = max(len(ref_val), len(gen_val))
        if max_len == 0:
            return 1.0
        min_len = min(len(ref_val), len(gen_val))
        scores = [compare_values(ref_val[i], gen_val[i]) for i in range(min_len)]
        # Penalize missing elements
        scores.extend([0.0] * (max_len - min_len))
        return sum(scores) / max_len

    # Type mismatch — try string comparison as fallback
    ref_str = normalize_text(str(ref_val))
    gen_str = normalize_text(str(gen_val))
    return SequenceMatcher(None, ref_str, gen_str).ratio() * 0.5


def compute_property_accuracy(ref_features, gen_features):
    """Compare properties of matched features.

    For each matched feature, compare all property keys and values.
    Returns average accuracy across matched features.
    """
    if not ref_features and not gen_features:
        return 1.0
    if not ref_features or not gen_features:
        return 0.0

    ref_map = build_fingerprint_map(ref_features)
    gen_map = build_fingerprint_map(gen_features)

    matched_fps = set(ref_map.keys()) & set(gen_map.keys())
    if not matched_fps:
        return 0.0

    feature_scores = []
    for fp in matched_fps:
        ref_feat = ref_map[fp]
        gen_feat = gen_map[fp]

        ref_props = ref_feat.get("properties", {})
        gen_props = gen_feat.get("properties", {})

        all_keys = set(ref_props.keys()) | set(gen_props.keys())
        if not all_keys:
            feature_scores.append(1.0)
            continue

        key_scores = []
        for key in all_keys:
            ref_val = ref_props.get(key)
            gen_val = gen_props.get(key)
            key_scores.append(compare_values(ref_val, gen_val))

        feature_scores.append(sum(key_scores) / len(key_scores))

    return sum(feature_scores) / len(feature_scores)


def compute_coordinate_accuracy(ref_features, gen_features):
    """Compare coordinates of matched features.

    For Point geometries, compares centroids directly.
    For other geometries, serializes coordinates and compares.
    """
    if not ref_features and not gen_features:
        return 1.0
    if not ref_features or not gen_features:
        return 0.0

    ref_map = build_fingerprint_map(ref_features)
    gen_map = build_fingerprint_map(gen_features)

    matched_fps = set(ref_map.keys()) & set(gen_map.keys())
    if not matched_fps:
        return 0.0

    coord_scores = []
    for fp in matched_fps:
        ref_feat = ref_map[fp]
        gen_feat = gen_map[fp]

        # Check geometry type match
        ref_geom_type = ref_feat.get("geometry_type")
        gen_geom_type = gen_feat.get("geometry_type")

        if ref_geom_type != gen_geom_type:
            coord_scores.append(0.0)
            continue

        # For Points, compare centroids
        ref_centroid = ref_feat.get("centroid")
        gen_centroid = gen_feat.get("centroid")

        if ref_centroid and gen_centroid:
            lon_diff = abs(ref_centroid[0] - gen_centroid[0])
            lat_diff = abs(ref_centroid[1] - gen_centroid[1])

            if lon_diff < 0.0001 and lat_diff < 0.0001:
                coord_scores.append(1.0)
            elif lon_diff < 0.001 and lat_diff < 0.001:
                coord_scores.append(0.9)
            elif lon_diff < 0.01 and lat_diff < 0.01:
                coord_scores.append(0.5)
            else:
                coord_scores.append(0.0)
        elif ref_centroid is None and gen_centroid is None:
            # Non-point geometry: compare raw coordinate arrays
            ref_coords = ref_feat.get("coordinates")
            gen_coords = gen_feat.get("coordinates")
            if ref_coords == gen_coords:
                coord_scores.append(1.0)
            elif ref_coords is None and gen_coords is None:
                coord_scores.append(1.0)
            else:
                # Serialize and compare
                ref_str = json.dumps(ref_coords, sort_keys=True)
                gen_str = json.dumps(gen_coords, sort_keys=True)
                coord_scores.append(SequenceMatcher(None, ref_str, gen_str).ratio())
        else:
            coord_scores.append(0.0)

    return sum(coord_scores) / len(coord_scores) if coord_scores else 0.0


def compute_ordering_score(ref_features, gen_features):
    """Compare the ordering of features using sequence matching."""
    if not ref_features and not gen_features:
        return 1.0
    if not ref_features or not gen_features:
        return 0.0

    ref_seq = [feature_fingerprint(f) for f in ref_features]
    gen_seq = [feature_fingerprint(f) for f in gen_features]

    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


def compute_metadata_score(ref_metadata, gen_metadata):
    """Compare collection-level metadata (type, crs, name, bbox)."""
    if not ref_metadata and not gen_metadata:
        return 1.0
    if not ref_metadata or not gen_metadata:
        return 0.5  # Partial if one has metadata

    scores = []
    # Compare across all files in the metadata dict
    all_files = set(ref_metadata.keys()) | set(gen_metadata.keys())
    for fn in all_files:
        ref_meta = ref_metadata.get(fn, {})
        gen_meta = gen_metadata.get(fn, {})
        all_keys = set(ref_meta.keys()) | set(gen_meta.keys())
        if not all_keys:
            scores.append(1.0)
            continue
        key_scores = []
        for key in all_keys:
            key_scores.append(compare_values(ref_meta.get(key), gen_meta.get(key)))
        scores.append(sum(key_scores) / len(key_scores))

    return sum(scores) / len(scores) if scores else 1.0


class DomainGeodata(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "geodata"
        self.summary = "GeoJSON geographic feature collections with coordinates, properties, and metadata"
        self.description = "GeoJSON geographic features"
        self.file_format = [".geojson"]
        self.domain_parser = "custom"
        self.category = "records"

    def parse_all_features(self, context):
        return parse_all_features(context)

    def parse_context(self, context):
        """Parse all GeoJSON files in a context dict into structured data.

        Returns a dict with 'features' (list of parsed feature dicts) and
        'metadata' (dict of filename -> collection-level metadata).
        """
        features, metadata = self.parse_all_features(context)
        return {"features": features, "metadata": metadata}

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        features = parsed["features"]
        metadata = parsed["metadata"]
        geom_types = {}
        prop_keys = set()
        for f in features:
            gt = f.get("geometry_type", "None")
            geom_types[gt] = geom_types.get(gt, 0) + 1
            prop_keys.update(f.get("properties", {}).keys())
        return {
            "Features": len(features),
            "Geometry Types": dict(geom_types),
            "Property Keys": len(prop_keys),
            "Files": len(metadata),
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

        ref_parsed = self.parse_context(reference_context)
        ref_features, ref_metadata = ref_parsed["features"], ref_parsed["metadata"]
        gen_parsed = self.parse_context(generated_context)
        gen_features, gen_metadata = gen_parsed["features"], gen_parsed["metadata"]

        if debug:
            print(f"Reference features: {len(ref_features)}, Generated features: {len(gen_features)}")

        # Compute component scores
        coverage = compute_feature_coverage(ref_features, gen_features)
        property_acc = compute_property_accuracy(ref_features, gen_features)
        coord_acc = compute_coordinate_accuracy(ref_features, gen_features)
        ordering = compute_ordering_score(ref_features, gen_features)
        metadata_score = compute_metadata_score(ref_metadata, gen_metadata)

        # Combined score:
        # coverage² gates everything, property accuracy is most critical,
        # coordinates matter, ordering and metadata are secondary
        secondary_avg = (coord_acc + ordering + metadata_score) / 3.0
        score = (coverage ** 2) * property_acc * math.sqrt(secondary_avg) if secondary_avg > 0 else 0.0

        eval_obj = {
            "score": score,
            "coverage": coverage,
            "property_accuracy": property_acc,
            "coordinate_accuracy": coord_acc,
            "ordering": ordering,
            "metadata_score": metadata_score,
            "ref_count": len(ref_features),
            "gen_count": len(gen_features),
        }
        if debug:
            print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

    def render_context_visual(self, context, outfile):
        """Render GeoJSON features to a PNG map plot using matplotlib."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        context = self.preprocess_context(context)
        parsed = self.parse_context(context)
        features = parsed["features"]
        if not features:
            return None

        fig, ax = plt.subplots(1, 1, figsize=(10, 8))

        def _plot_coords(coords, geom_type, label=None):
            """Recursively extract and plot coordinates."""
            if geom_type == "Point":
                if isinstance(coords, list) and len(coords) >= 2:
                    ax.scatter(coords[0], coords[1], s=40, zorder=5)
                    if label:
                        ax.annotate(
                            label, (coords[0], coords[1]),
                            textcoords="offset points", xytext=(5, 5),
                            fontsize=7, clip_on=True,
                        )
            elif geom_type == "MultiPoint":
                for pt in coords:
                    _plot_coords(pt, "Point", label=None)
                if label and coords:
                    _plot_coords(coords[0], "Point", label=label)
            elif geom_type == "LineString":
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                ax.plot(xs, ys, linewidth=1.5)
                if label and xs:
                    ax.annotate(
                        label, (xs[0], ys[0]),
                        textcoords="offset points", xytext=(5, 5),
                        fontsize=7, clip_on=True,
                    )
            elif geom_type == "MultiLineString":
                for line in coords:
                    _plot_coords(line, "LineString", label=None)
                if label and coords and coords[0]:
                    _plot_coords(coords[0], "LineString", label=label)
            elif geom_type == "Polygon":
                for ring in coords:
                    xs = [c[0] for c in ring]
                    ys = [c[1] for c in ring]
                    ax.fill(xs, ys, alpha=0.3)
                    ax.plot(xs, ys, linewidth=1)
                if label and coords and coords[0]:
                    cx = sum(c[0] for c in coords[0]) / len(coords[0])
                    cy = sum(c[1] for c in coords[0]) / len(coords[0])
                    ax.annotate(
                        label, (cx, cy),
                        fontsize=7, ha="center", clip_on=True,
                    )
            elif geom_type == "MultiPolygon":
                for poly in coords:
                    _plot_coords(poly, "Polygon", label=None)
                if label and coords and coords[0] and coords[0][0]:
                    _plot_coords(coords[0], "Polygon", label=label)

        for feat in features:
            geom_type = feat.get("geometry_type")
            coords = feat.get("coordinates")
            if not geom_type or coords is None:
                continue
            props = feat.get("properties", {})
            label = props.get("name") or props.get("id") or props.get("title") or ""
            if isinstance(label, dict):
                label = next(iter(label.values()), "")
            label = str(label)[:30] if label else None
            _plot_coords(coords, geom_type, label)

        ax.set_aspect("equal")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title("GeoJSON Features")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        out_path = outfile + ".png"
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        return out_path


if __name__ == "__main__":
    # Self-test: load basic_state and evaluate against itself
    import sys

    sample_id = sys.argv[1] if len(sys.argv) > 1 else "geodata1"
    sample_folder = f"samples/{sample_id}/"

    with open(os.path.join(sample_folder, "sample.json"), "r") as f:
        sample = json.load(f)

    start_state = [s for s in sample["states"] if s["state_id"] == sample["start_state"]][0]
    context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))

    task = TaskGeodata()
    result = task.evaluate_context(sample_id, context, start_state, debug=True)

    print(f"\nSelf-evaluation score: {result.get('score', 'N/A')}")
    if result.get("score") == 1.0:
        print("\033[92m✓ Perfect self-evaluation\033[0m")
    else:
        print(f"\033[91m✗ Self-evaluation not 1.0: {result}\033[0m")
