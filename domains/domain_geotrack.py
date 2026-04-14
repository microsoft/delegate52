from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, math, ujson as json
import gpxpy

# Garmin TrackPointExtension namespace
GARMIN_TPX_NS = '{http://www.garmin.com/xmlschemas/TrackPointExtension/v1}'


def parse_gpx(content):
    """Parse GPX content string into a gpxpy GPX object. Returns None on failure."""
    try:
        return gpxpy.parse(content)
    except Exception as e:
        print(f"\033[91mGPX parsing error: {e}\033[0m")
        return None


def parse_all_gpx(context):
    """Parse all .gpx files from a context dict, return a merged list of structures."""
    waypoints = []
    tracks = []
    for filename, content in sorted(context.items()):
        if filename.endswith('.gpx'):
            gpx = parse_gpx(content)
            if gpx is None:
                continue
            for wpt in gpx.waypoints:
                waypoints.append(extract_waypoint(wpt, filename))
            for trk in gpx.tracks:
                tracks.append(extract_track(trk, filename))
    return waypoints, tracks


def extract_extension_temp(point):
    """Extract ambient temperature from Garmin TrackPointExtension."""
    for ext in point.extensions:
        tag = ext.tag
        if 'TrackPointExtension' in tag:
            for child in ext:
                if 'atemp' in child.tag:
                    try:
                        return float(child.text)
                    except (ValueError, TypeError):
                        pass
    return None


def extract_waypoint(wpt, source_file=None):
    """Extract a structured waypoint dict from a gpxpy waypoint."""
    return {
        'name': (wpt.name or '').strip(),
        'lat': wpt.latitude,
        'lon': wpt.longitude,
        'elevation': wpt.elevation,
        'description': (wpt.description or '').strip(),
        'link': wpt.link if hasattr(wpt, 'link') and wpt.link else None,
        'link_text': wpt.link_text if hasattr(wpt, 'link_text') and wpt.link_text else None,
        'source_file': source_file,
    }


def extract_trackpoint(pt):
    """Extract a structured trackpoint dict."""
    return {
        'lat': pt.latitude,
        'lon': pt.longitude,
        'elevation': pt.elevation,
        'time': pt.time.isoformat() if pt.time else None,
        'atemp': extract_extension_temp(pt),
    }


def extract_track(trk, source_file=None):
    """Extract a structured track dict from a gpxpy track."""
    segments = []
    for seg in trk.segments:
        points = [extract_trackpoint(pt) for pt in seg.points]
        segments.append(points)
    return {
        'name': (trk.name or '').strip(),
        'segments': segments,
        'source_file': source_file,
    }


def waypoint_fingerprint(wpt):
    """Create a fingerprint for matching waypoints."""
    return wpt['name'].lower().strip()


def coord_distance(lat1, lon1, lat2, lon2):
    """Simple Euclidean distance in degrees (sufficient for scoring, not navigation)."""
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


def compute_waypoint_coverage_score(ref_wpts, gen_wpts):
    """Jaccard similarity of waypoints by name."""
    if not ref_wpts and not gen_wpts:
        return 1.0
    if not ref_wpts or not gen_wpts:
        return 0.0
    ref_fps = {waypoint_fingerprint(w) for w in ref_wpts}
    gen_fps = {waypoint_fingerprint(w) for w in gen_wpts}
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 0.0


def compute_waypoint_accuracy_score(ref_wpts, gen_wpts):
    """Measure accuracy of matched waypoints (coordinates, description)."""
    if not ref_wpts and not gen_wpts:
        return 1.0
    if not ref_wpts or not gen_wpts:
        return 0.0

    ref_by_fp = {waypoint_fingerprint(w): w for w in ref_wpts}
    gen_by_fp = {waypoint_fingerprint(w): w for w in gen_wpts}
    matched = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched:
        return 0.0

    scores = []
    for fp in matched:
        rw = ref_by_fp[fp]
        gw = gen_by_fp[fp]
        pts = 0.0
        total = 0.0

        # Coordinate accuracy (within ~0.001 degree ≈ 100m)
        total += 1.0
        dist = coord_distance(rw['lat'], rw['lon'], gw['lat'], gw['lon'])
        if dist < 0.0001:
            pts += 1.0
        elif dist < 0.001:
            pts += 0.8
        elif dist < 0.01:
            pts += 0.3
        # else 0

        # Description accuracy
        if rw['description'] or gw['description']:
            total += 1.0
            ref_desc = rw['description'].lower()
            gen_desc = gw['description'].lower()
            if ref_desc == gen_desc:
                pts += 1.0
            elif ref_desc and gen_desc:
                pts += SequenceMatcher(None, ref_desc, gen_desc).ratio() * 0.8

        scores.append(pts / total if total > 0 else 1.0)

    return sum(scores) / len(scores) if scores else 0.0


def flatten_trackpoints(tracks):
    """Flatten all trackpoints from all tracks/segments into a single list with metadata."""
    points = []
    for trk in tracks:
        for seg_idx, seg in enumerate(trk['segments']):
            for pt in seg:
                points.append({
                    **pt,
                    'track_name': trk['name'],
                    'seg_idx': seg_idx,
                })
    return points


def compute_track_structure_score(ref_tracks, gen_tracks):
    """Score preservation of track/segment structure."""
    if not ref_tracks and not gen_tracks:
        return 1.0
    if not ref_tracks or not gen_tracks:
        return 0.0

    # Track count match
    track_count_ratio = 1.0 - abs(len(ref_tracks) - len(gen_tracks)) / max(len(ref_tracks), len(gen_tracks))

    # Match tracks by name
    ref_names = [t['name'].lower().strip() for t in ref_tracks]
    gen_names = [t['name'].lower().strip() for t in gen_tracks]
    name_match = SequenceMatcher(None, ref_names, gen_names).ratio()

    # Segment structure match — compare segment counts per matched track
    ref_by_name = {t['name'].lower().strip(): t for t in ref_tracks}
    gen_by_name = {t['name'].lower().strip(): t for t in gen_tracks}
    matched_names = set(ref_by_name.keys()) & set(gen_by_name.keys())

    seg_scores = []
    for name in matched_names:
        rt = ref_by_name[name]
        gt = gen_by_name[name]
        ref_seg_count = len(rt['segments'])
        gen_seg_count = len(gt['segments'])
        if ref_seg_count == 0 and gen_seg_count == 0:
            seg_scores.append(1.0)
        elif ref_seg_count == 0 or gen_seg_count == 0:
            seg_scores.append(0.0)
        else:
            # Compare segment point counts as a sequence
            ref_counts = [len(s) for s in rt['segments']]
            gen_counts = [len(s) for s in gt['segments']]
            count_sim = SequenceMatcher(None, ref_counts, gen_counts).ratio()
            seg_scores.append(count_sim)

    seg_structure = sum(seg_scores) / len(seg_scores) if seg_scores else 0.0

    return 0.4 * track_count_ratio + 0.3 * name_match + 0.3 * seg_structure


def compute_trackpoint_score(ref_tracks, gen_tracks):
    """Score trackpoint data preservation (coordinates, elevation, time, temperature)."""
    ref_pts = flatten_trackpoints(ref_tracks)
    gen_pts = flatten_trackpoints(gen_tracks)

    if not ref_pts and not gen_pts:
        return 1.0
    if not ref_pts or not gen_pts:
        return 0.0

    # Use sequence matching on (lat, lon) tuples to find correspondences
    ref_coords = [(round(p['lat'], 5), round(p['lon'], 5)) for p in ref_pts]
    gen_coords = [(round(p['lat'], 5), round(p['lon'], 5)) for p in gen_pts]

    # Sequence similarity for ordering
    coord_seq_sim = SequenceMatcher(None, ref_coords, gen_coords).ratio()

    # Point-by-point matching via SequenceMatcher to find matching blocks
    matcher = SequenceMatcher(None, ref_coords, gen_coords)
    matched_pairs = []
    for block in matcher.get_matching_blocks():
        for i in range(block.size):
            matched_pairs.append((ref_pts[block.a + i], gen_pts[block.b + i]))

    if not matched_pairs:
        # No coordinate matches at all — score based on count ratio
        count_ratio = min(len(ref_pts), len(gen_pts)) / max(len(ref_pts), len(gen_pts))
        return count_ratio * 0.1  # Very low score

    # For matched points, check elevation, time, temperature accuracy
    ele_scores = []
    time_scores = []
    temp_scores = []

    for rp, gp in matched_pairs:
        # Elevation
        if rp['elevation'] is not None or gp['elevation'] is not None:
            if rp['elevation'] is not None and gp['elevation'] is not None:
                ele_diff = abs(rp['elevation'] - gp['elevation'])
                if ele_diff < 0.5:
                    ele_scores.append(1.0)
                elif ele_diff < 2.0:
                    ele_scores.append(0.7)
                elif ele_diff < 10.0:
                    ele_scores.append(0.3)
                else:
                    ele_scores.append(0.0)
            else:
                ele_scores.append(0.0)

        # Timestamp
        if rp['time'] is not None or gp['time'] is not None:
            if rp['time'] is not None and gp['time'] is not None:
                time_scores.append(1.0 if rp['time'] == gp['time'] else 0.3)
            else:
                time_scores.append(0.0)

        # Temperature
        if rp['atemp'] is not None or gp['atemp'] is not None:
            if rp['atemp'] is not None and gp['atemp'] is not None:
                temp_diff = abs(rp['atemp'] - gp['atemp'])
                if temp_diff < 0.1:
                    temp_scores.append(1.0)
                elif temp_diff < 1.0:
                    temp_scores.append(0.7)
                else:
                    temp_scores.append(0.3)
            else:
                temp_scores.append(0.0)

    # Coverage: fraction of reference points matched
    coverage = len(matched_pairs) / len(ref_pts)

    # Average per-field scores
    avg_ele = sum(ele_scores) / len(ele_scores) if ele_scores else 1.0
    avg_time = sum(time_scores) / len(time_scores) if time_scores else 1.0
    avg_temp = sum(temp_scores) / len(temp_scores) if temp_scores else 1.0

    # Weighted combination
    field_accuracy = 0.4 * avg_ele + 0.4 * avg_time + 0.2 * avg_temp
    
    # Final: coverage^2 gates, then field accuracy and sequence similarity
    return (coverage ** 2) * (0.6 * field_accuracy + 0.4 * coord_seq_sim)


class DomainGeotrack(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "geotrack"
        self.summary = "GPX (GPS Exchange Format) files with tracks, waypoints, elevation, timestamps, and sensor extensions"
        self.description = "GPX tracks and waypoints"
        self.file_format = [".gpx"]
        self.domain_parser = "gpxpy"
        self.category = "records"

    def parse_gpx_context(self, context):
        """Parse all GPX files in the context into waypoints and tracks."""
        return parse_all_gpx(context)

    def parse_context(self, context):
        """Parse all GPX files in the context into a structured dict.

        Args:
            context: dict of filename -> content

        Returns:
            dict with keys 'waypoints' (list) and 'tracks' (list)
        """
        waypoints, tracks = parse_all_gpx(context)
        return {'waypoints': waypoints, 'tracks': tracks}

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        waypoints, tracks = parsed['waypoints'], parsed['tracks']
        total_points = sum(
            len(pt) for trk in tracks for pt in trk['segments']
        )
        total_segments = sum(len(trk['segments']) for trk in tracks)
        return {
            "Waypoints": len(waypoints),
            "Tracks": len(tracks),
            "Segments": total_segments,
            "Trackpoints": total_points,
        }

    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {"score": None}

        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)

        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(
            os.path.join(sample_folder, start_state["solution_folder"])
        )

        ref_parsed = self.parse_context(reference_context)
        ref_wpts, ref_tracks = ref_parsed['waypoints'], ref_parsed['tracks']
        gen_parsed = self.parse_context(generated_context)
        gen_wpts, gen_tracks = gen_parsed['waypoints'], gen_parsed['tracks']

        if debug:
            print(f"Ref: {len(ref_wpts)} waypoints, {len(ref_tracks)} tracks")
            print(f"Gen: {len(gen_wpts)} waypoints, {len(gen_tracks)} tracks")

        # Component scores
        wpt_coverage = compute_waypoint_coverage_score(ref_wpts, gen_wpts)
        wpt_accuracy = compute_waypoint_accuracy_score(ref_wpts, gen_wpts)
        trk_structure = compute_track_structure_score(ref_tracks, gen_tracks)
        trk_points = compute_trackpoint_score(ref_tracks, gen_tracks)

        # Combined: waypoints (20%), track structure (15%), trackpoint data (65%)
        # Trackpoint data is weighted heavily since that's the bulk of GPX content
        score = 0.10 * wpt_coverage + 0.10 * wpt_accuracy + 0.15 * trk_structure + 0.65 * trk_points

        eval_obj = {
            "score": score,
            "waypoint_coverage_score": wpt_coverage,
            "waypoint_accuracy_score": wpt_accuracy,
            "track_structure_score": trk_structure,
            "trackpoint_data_score": trk_points,
            "ref_waypoints": len(ref_wpts),
            "gen_waypoints": len(gen_wpts),
            "ref_tracks": len(ref_tracks),
            "gen_tracks": len(gen_tracks),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
