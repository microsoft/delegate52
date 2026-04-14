from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import xml.etree.ElementTree as ET
import os, re, math, ujson as json

XSPF_NS = "http://xspf.org/ns/0/"
NS = {"xspf": XSPF_NS}


def parse_xspf_tracks(content):
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        print(f"\033[91mXSPF parsing error: {e}\033[0m")
        return []
    
    tracks = []
    tracklist = root.find(f"{{{XSPF_NS}}}trackList")
    if tracklist is None:
        return []
    
    for track_el in tracklist.findall(f"{{{XSPF_NS}}}track"):
        track = {
            "title": "",
            "creator": "",
            "album": "",
            "annotation": "",
            "year": "",
            "label": "",
            "rotation": "",
            "local": False,
            "request": False,
        }
        
        # Basic fields
        title_el = track_el.find(f"{{{XSPF_NS}}}title")
        if title_el is not None and title_el.text:
            track["title"] = title_el.text.strip()
        
        creator_el = track_el.find(f"{{{XSPF_NS}}}creator")
        if creator_el is not None and creator_el.text:
            track["creator"] = creator_el.text.strip()
        
        album_el = track_el.find(f"{{{XSPF_NS}}}album")
        if album_el is not None and album_el.text:
            track["album"] = album_el.text.strip()
        
        annotation_el = track_el.find(f"{{{XSPF_NS}}}annotation")
        if annotation_el is not None and annotation_el.text:
            track["annotation"] = annotation_el.text.strip()
        
        # Meta fields
        for meta_el in track_el.findall(f"{{{XSPF_NS}}}meta"):
            rel = meta_el.get("rel", "")
            val = meta_el.text.strip() if meta_el.text else ""
            
            if rel == "year":
                track["year"] = val
            elif rel == "label":
                track["label"] = val
            elif rel == "rotation":
                track["rotation"] = val
            elif rel == "local":
                track["local"] = val.lower() == "true"
            elif rel == "request":
                track["request"] = val.lower() == "true"
        
        tracks.append(track)
    
    return tracks


def parse_all_xspf_tracks(context):
    all_tracks = []
    for filename, content in context.items():
        if filename.endswith(".xspf"):
            tracks = parse_xspf_tracks(content)
            all_tracks.extend(tracks)
    return all_tracks


def track_fingerprint(track):
    # Use title + creator as unique identifier
    title = track["title"].lower().strip()
    creator = track["creator"].lower().strip()
    return f"{title}|{creator}"


def compute_track_coverage_score(ref_tracks, gen_tracks):
    if not ref_tracks and not gen_tracks:
        return 1.0
    if not ref_tracks or not gen_tracks:
        return 0.0
    
    ref_fps = {track_fingerprint(t) for t in ref_tracks}
    gen_fps = {track_fingerprint(t) for t in gen_tracks}
    
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def compute_track_metadata_score(ref_tracks, gen_tracks):
    if not ref_tracks and not gen_tracks:
        return 1.0
    if not ref_tracks or not gen_tracks:
        return 0.0
    
    ref_by_fp = {track_fingerprint(t): t for t in ref_tracks}
    gen_by_fp = {track_fingerprint(t): t for t in gen_tracks}
    
    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0
    
    field_scores = []
    for fp in matched_fps:
        ref_track = ref_by_fp[fp]
        gen_track = gen_by_fp[fp]
        
        score = 0.0
        total = 0.0
        
        # Album (important)
        ref_album = ref_track["album"].lower().strip()
        gen_album = gen_track["album"].lower().strip()
        if ref_album or gen_album:
            total += 2.0
            if ref_album == gen_album:
                score += 2.0
            elif ref_album and gen_album:
                score += SequenceMatcher(None, ref_album, gen_album).ratio() * 1.5
        
        # Year
        if ref_track["year"] or gen_track["year"]:
            total += 1.0
            if ref_track["year"] == gen_track["year"]:
                score += 1.0
        
        # Label
        ref_label = ref_track["label"].lower().strip()
        gen_label = gen_track["label"].lower().strip()
        if ref_label or gen_label:
            total += 1.0
            if ref_label == gen_label:
                score += 1.0
            elif ref_label and gen_label:
                score += SequenceMatcher(None, ref_label, gen_label).ratio() * 0.5
        
        # Rotation
        if ref_track["rotation"] or gen_track["rotation"]:
            total += 0.5
            if ref_track["rotation"].lower() == gen_track["rotation"].lower():
                score += 0.5
        
        # Boolean flags (local, request)
        if ref_track["local"] or gen_track["local"]:
            total += 0.25
            if ref_track["local"] == gen_track["local"]:
                score += 0.25
        
        if ref_track["request"] or gen_track["request"]:
            total += 0.25
            if ref_track["request"] == gen_track["request"]:
                score += 0.25
        
        field_scores.append(score / total if total > 0 else 1.0)
    
    return sum(field_scores) / len(field_scores) if field_scores else 0.0


def compute_annotation_score(ref_tracks, gen_tracks):
    if not ref_tracks and not gen_tracks:
        return 1.0
    if not ref_tracks or not gen_tracks:
        return 0.0
    
    ref_by_fp = {track_fingerprint(t): t for t in ref_tracks}
    gen_by_fp = {track_fingerprint(t): t for t in gen_tracks}
    
    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0
    
    annotation_scores = []
    for fp in matched_fps:
        ref_ann = ref_by_fp[fp]["annotation"].strip()
        gen_ann = gen_by_fp[fp]["annotation"].strip()
        
        if not ref_ann and not gen_ann:
            annotation_scores.append(1.0)
        elif not ref_ann or not gen_ann:
            annotation_scores.append(0.0)
        else:
            annotation_scores.append(SequenceMatcher(None, ref_ann, gen_ann).ratio())
    
    return sum(annotation_scores) / len(annotation_scores) if annotation_scores else 1.0


def compute_track_sequence_score(ref_tracks, gen_tracks):
    if not ref_tracks and not gen_tracks:
        return 1.0
    if not ref_tracks or not gen_tracks:
        return 0.0
    
    ref_seq = [track_fingerprint(t) for t in ref_tracks]
    gen_seq = [track_fingerprint(t) for t in gen_tracks]
    
    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


class DomainPlaylist(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "playlist"
        self.summary = "XSPF playlist files with track metadata, durations, and ordering"
        self.description = "XSPF media playlists"
        self.file_format = [".xspf"]
        self.domain_parser = "xml.etree"
        self.category = "everyday"
    
    def preprocess_context(self, context):
        """Normalize XSPF content before parsing.

        Fixes two common LLM issues:
        1. Unescaped '&' in text (e.g. 'R&B' -> 'R&amp;B')
        2. Root <xspf> element wrapping <playlist> (unwrap to <playlist> root)
        """
        cleaned = {}
        for filename, content in context.items():
            if filename.endswith(".xspf"):
                # Fix 1: Escape bare '&' that aren't already XML entities
                content = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#)', '&amp;', content)

                # Fix 2: If root is <xspf ...>, unwrap to the inner <playlist>
                try:
                    root = ET.fromstring(content)
                    if root.tag == f"{{{XSPF_NS}}}xspf":
                        playlist_el = root.find(f"{{{XSPF_NS}}}playlist")
                        if playlist_el is not None:
                            # Re-serialize the inner <playlist> element as the new root
                            # Copy the namespace if not already present
                            if 'xmlns' not in playlist_el.attrib:
                                playlist_el.set('xmlns', XSPF_NS)
                            content = ET.tostring(playlist_el, encoding='unicode', xml_declaration=True)
                except ET.ParseError:
                    pass  # Let downstream parsing report the error

            cleaned[filename] = content
        return cleaned

    def parse_all_tracks(self, context):
        return parse_all_xspf_tracks(context)
    
    def parse_context(self, context):
        context = self.preprocess_context(context)
        return {"tracks": self.parse_all_tracks(context)}
    
    def compute_domain_statistics(self, context):
        tracks = self.parse_context(context)["tracks"]
        creators = set(t.get('creator', '') for t in tracks if t.get('creator'))
        albums = set(t.get('album', '') for t in tracks if t.get('album'))
        with_annotation = sum(1 for t in tracks if t.get('annotation'))
        return {
            "Tracks": len(tracks),
            "Artists": len(creators),
            "Albums": len(albums),
            "With Notes": with_annotation,
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
        
        ref_tracks = self.parse_context(reference_context)["tracks"]
        gen_tracks = self.parse_context(generated_context)["tracks"]
        
        if debug:
            print(f"Reference tracks: {len(ref_tracks)}, Generated tracks: {len(gen_tracks)}")
        
        # Compute component scores
        coverage_score = compute_track_coverage_score(ref_tracks, gen_tracks)
        metadata_score = compute_track_metadata_score(ref_tracks, gen_tracks)
        annotation_score = compute_annotation_score(ref_tracks, gen_tracks)
        sequence_score = compute_track_sequence_score(ref_tracks, gen_tracks)
        
        # Multiplicative scoring: coverage gates everything
        # coverage^2 × metadata × sqrt((annotation + sequence) / 2)
        secondary_avg = (annotation_score + sequence_score) / 2.0
        score = (coverage_score ** 2) * metadata_score * math.sqrt(secondary_avg) if secondary_avg > 0 else 0.0
        
        eval_obj = {
            "score": score,
            "track_coverage_score": coverage_score,
            "track_metadata_score": metadata_score,
            "annotation_score": annotation_score,
            "sequence_score": sequence_score,
            "ref_track_count": len(ref_tracks),
            "gen_track_count": len(gen_tracks),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


if __name__ == "__main__":
    # Test the parser
    with open("samples/playlist1/basic_state/kexp_playlist.xspf", "r") as f:
        content = f.read()
    
    tracks = parse_xspf_tracks(content)
    
    print("=" * 60)
    print(f"TRACKS ({len(tracks)})")
    print("=" * 60)
    
    for i, track in enumerate(tracks[:10], 1):
        ann_marker = " [+ann]" if track["annotation"] else ""
        meta_markers = []
        if track["rotation"]:
            meta_markers.append(track["rotation"])
        if track["local"]:
            meta_markers.append("local")
        if track["request"]:
            meta_markers.append("request")
        meta_str = f" ({', '.join(meta_markers)})" if meta_markers else ""
        
        print(f"{i:2d}. {track['creator'][:25]:<25} - {track['title'][:30]:<30}{ann_marker}{meta_str}")
    
    if len(tracks) > 10:
        print(f"... and {len(tracks) - 10} more tracks")
    
    # Count stats
    with_annotations = sum(1 for t in tracks if t["annotation"])
    with_rotation = sum(1 for t in tracks if t["rotation"])
    with_local = sum(1 for t in tracks if t["local"])
    with_request = sum(1 for t in tracks if t["request"])
    
    print(f"\nStats: {with_annotations} with annotations, {with_rotation} with rotation, {with_local} local, {with_request} requests")
