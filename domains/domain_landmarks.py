from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import xml.etree.ElementTree as ET
import os, math, re, ujson as json

KML_NS = {'kml': 'http://www.opengis.net/kml/2.2'}


def preprocess_kml(content):
    """Normalize raw KML string to fix common LLM syntax errors before XML parsing."""
    # 1. Fix parenthesis-as-space in tag attributes: <SchemaData(schemaUrl=... -> <SchemaData schemaUrl=...
    content = re.sub(r'<(\w+)\((\w+=)', r'<\1 \2', content)
    # 1b. Fix closing parenthesis after quoted attr in tags: attr="val")> -> attr="val">
    content = re.sub(r'"\)\s*>', '">', content)
    # 2. Convert HTML <br> variants to space (not valid XML)
    content = re.sub(r'<br\s*/?>', ' ', content, flags=re.IGNORECASE)
    # 3. Fix broken CDATA: <![CDATA> -> <![CDATA[  and unclosed ]]> 
    content = content.replace('<![CDATA>', '<![CDATA[')
    # 4. Escape bare & (not already an XML entity)
    content = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[\da-fA-F]+;)', '&amp;', content)
    return content


def parse_kml_placemarks(content):
    content = preprocess_kml(content)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        print(f"\033[91mKML parsing error: {e}\033[0m")
        return []
    
    placemarks = []
    for pm in root.findall('.//kml:Placemark', KML_NS):
        placemark = {
            'id': pm.get('id', ''),
            'name': (pm.findtext('kml:name', '', KML_NS) or '').strip(),
            'coordinates': None,
            'address': None,
            'overview': None,
            'opening_hours': None,
        }
        
        # Parse coordinates
        coords_text = pm.findtext('.//kml:coordinates', '', KML_NS)
        if coords_text:
            coords_text = coords_text.strip()
            parts = coords_text.split(',')
            if len(parts) >= 2:
                try:
                    placemark['coordinates'] = (float(parts[0]), float(parts[1]))
                except ValueError:
                    pass
        
        # Parse ExtendedData/SchemaData (case-insensitive field matching)
        for simple_data in pm.findall('.//kml:SimpleData', KML_NS):
            field_name = (simple_data.get('name', '') or '').upper()
            value = (simple_data.text or '').strip()
            if field_name == 'ADDRESS':
                placemark['address'] = value
            elif field_name == 'OVERVIEW':
                placemark['overview'] = value
            elif field_name == 'OPENING_HOURS':
                placemark['opening_hours'] = value
            elif field_name == 'ID' and not placemark['id']:
                placemark['id'] = value
        
        placemarks.append(placemark)
    return placemarks


def parse_geojson_features(content):
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"\033[91mGeoJSON parsing error: {e}\033[0m")
        return []
    
    features = data.get('features', [])
    placemarks = []
    for f in features:
        props = f.get('properties', {}) or {}
        coords = (f.get('geometry') or {}).get('coordinates', [])
        
        placemark = {
            'id': props.get('id', ''),
            'name': (props.get('name', '') or '').strip(),
            'coordinates': (coords[0], coords[1]) if len(coords) >= 2 else None,
            'address': props.get('address') or props.get('ADDRESS'),
            'overview': props.get('overview') or props.get('OVERVIEW'),
            'opening_hours': props.get('opening_hours') or props.get('OPENING_HOURS'),
        }
        placemarks.append(placemark)
    return placemarks


def parse_all_placemarks(context):
    all_placemarks = []
    for filename, content in context.items():
        if filename.endswith('.kml'):
            placemarks = parse_kml_placemarks(content)
            all_placemarks.extend(placemarks)
        elif filename.endswith('.geojson') or filename.endswith('.json'):
            placemarks = parse_geojson_features(content)
            all_placemarks.extend(placemarks)
    return all_placemarks


def normalize_placemark_name(name):
    """Strip common LLM-added prefixes and suffixes from placemark names.
    
    Patterns handled:
      - ID prefix with separator: 'TOK_poi_1 — 烏森神社' -> '烏森神社'
      - Numeric prefix: '18 烏森神社' -> '烏森神社'
      - Parenthetical suffix (romanization): '烏森神社 (Karasumori Jinja)' -> '烏森神社'
    """
    name = name.strip()
    # Strip prefix: word/id tokens followed by em-dash/en-dash/hyphen separator
    name = re.sub(r'^[\w.]+\s*[—–-]\s*', '', name).strip()
    # Strip leading numeric-only prefix (e.g., '18 Name')
    name = re.sub(r'^\d+\s+', '', name).strip()
    # Strip trailing parenthetical (romanization/translation)
    name = re.sub(r'\s*\([^)]+\)\s*$', '', name).strip()
    return name


def placemark_fingerprint(pm):
    # Always use name for semantic matching (IDs are arbitrary identifiers)
    # Name normalization (prefix/suffix stripping) is handled by preprocess_context
    return pm['name'].lower().strip()


def compute_placemark_coverage(ref_pms, gen_pms):
    if not ref_pms and not gen_pms:
        return 1.0
    if not ref_pms or not gen_pms:
        return 0.0
    
    ref_fps = {placemark_fingerprint(p) for p in ref_pms}
    gen_fps = {placemark_fingerprint(p) for p in gen_pms}
    
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def normalize_text(text):
    if not text:
        return ''
    # Normalize unicode, whitespace, and common encoding issues
    text = text.replace('\u2019', "'").replace('\u2018', "'")
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2013', '-').replace('\u2014', '-')
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def compute_field_accuracy(ref_pms, gen_pms):
    if not ref_pms and not gen_pms:
        return 1.0
    if not ref_pms or not gen_pms:
        return 0.0
    
    ref_by_fp = {placemark_fingerprint(p): p for p in ref_pms}
    gen_by_fp = {placemark_fingerprint(p): p for p in gen_pms}
    
    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0
    
    field_scores = []
    for fp in matched_fps:
        ref_pm = ref_by_fp[fp]
        gen_pm = gen_by_fp[fp]
        
        score = 0.0
        total = 0.0
        
        # Compare name (weight: 1.0)
        ref_name = normalize_text(ref_pm['name'])
        gen_name = normalize_text(gen_pm['name'])
        if ref_name or gen_name:
            total += 1.0
            if ref_name == gen_name:
                score += 1.0
            else:
                score += SequenceMatcher(None, ref_name, gen_name).ratio() * 0.7
        
        # Compare address (weight: 1.0)
        ref_addr = normalize_text(ref_pm.get('address', ''))
        gen_addr = normalize_text(gen_pm.get('address', ''))
        if ref_addr or gen_addr:
            total += 1.0
            if ref_addr == gen_addr:
                score += 1.0
            elif ref_addr and gen_addr:
                score += SequenceMatcher(None, ref_addr, gen_addr).ratio() * 0.7
        
        # Compare overview (weight: 1.0, more lenient for long text)
        ref_over = normalize_text(ref_pm.get('overview', ''))
        gen_over = normalize_text(gen_pm.get('overview', ''))
        if ref_over or gen_over:
            total += 1.0
            if ref_over == gen_over:
                score += 1.0
            elif ref_over and gen_over:
                score += SequenceMatcher(None, ref_over, gen_over).ratio() * 0.8
        
        # Compare opening_hours (weight: 1.0)
        ref_hours = normalize_text(ref_pm.get('opening_hours', ''))
        gen_hours = normalize_text(gen_pm.get('opening_hours', ''))
        if ref_hours or gen_hours:
            total += 1.0
            if ref_hours == gen_hours:
                score += 1.0
            elif ref_hours and gen_hours:
                score += SequenceMatcher(None, ref_hours, gen_hours).ratio() * 0.7
        
        field_scores.append(score / total if total > 0 else 1.0)
    
    return sum(field_scores) / len(field_scores) if field_scores else 0.0


def compute_coordinate_accuracy(ref_pms, gen_pms):
    if not ref_pms and not gen_pms:
        return 1.0
    if not ref_pms or not gen_pms:
        return 0.0
    
    ref_by_fp = {placemark_fingerprint(p): p for p in ref_pms}
    gen_by_fp = {placemark_fingerprint(p): p for p in gen_pms}
    
    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0
    
    coord_scores = []
    for fp in matched_fps:
        ref_pm = ref_by_fp[fp]
        gen_pm = gen_by_fp[fp]
        
        ref_coords = ref_pm.get('coordinates')
        gen_coords = gen_pm.get('coordinates')
        
        if ref_coords is None and gen_coords is None:
            coord_scores.append(1.0)
        elif ref_coords is None or gen_coords is None:
            coord_scores.append(0.0)
        else:
            # Calculate distance in degrees (approximate)
            lon_diff = abs(ref_coords[0] - gen_coords[0])
            lat_diff = abs(ref_coords[1] - gen_coords[1])
            
            # Score based on precision - allow small rounding differences
            # 0.0001 degree ≈ 11 meters, which is acceptable GPS precision
            if lon_diff < 0.0001 and lat_diff < 0.0001:
                coord_scores.append(1.0)
            elif lon_diff < 0.001 and lat_diff < 0.001:
                coord_scores.append(0.9)
            elif lon_diff < 0.01 and lat_diff < 0.01:
                coord_scores.append(0.5)
            else:
                coord_scores.append(0.0)
    
    return sum(coord_scores) / len(coord_scores) if coord_scores else 0.0


def extract_id_number(pm):
    # Extract numeric part from ID like "poi_1" -> 1
    pm_id = pm.get('id', '')
    match = re.search(r'(\d+)', pm_id)
    return int(match.group(1)) if match else float('inf')


def compute_ordering_score(ref_pms, gen_pms):
    if not ref_pms and not gen_pms:
        return 1.0
    if not ref_pms or not gen_pms:
        return 0.0
    
    # Sort both by ID number
    ref_sorted = sorted(ref_pms, key=extract_id_number)
    gen_sorted = sorted(gen_pms, key=extract_id_number)
    
    ref_seq = [placemark_fingerprint(p) for p in ref_sorted]
    gen_seq = [placemark_fingerprint(p) for p in gen_sorted]
    
    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


class DomainLandmarks(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "landmarks"
        self.summary = "KML/GeoJSON points of interest with coordinates, addresses, and descriptions"
        self.description = "KML geographic placemarks"
        self.file_format = [".kml"]
        self.domain_parser = "xml.etree"
        self.category = "everyday"
    
    def preprocess_context(self, context):
        """Normalize KML placemark names to strip LLM-added prefixes/suffixes."""
        result = {}
        for filename, content in context.items():
            if filename.endswith('.kml'):
                # Normalize <name> inside <Placemark> elements by stripping
                # ID prefixes and romanization suffixes
                def _normalize_name_tag(m):
                    raw = m.group(1)
                    cleaned = normalize_placemark_name(raw)
                    return f'<name>{cleaned}</name>'
                # Only normalize names inside Placemark blocks
                # Split by Placemark boundaries to avoid touching Document/Folder names
                parts = re.split(r'(<Placemark[^>]*>.*?</Placemark>)', content, flags=re.DOTALL)
                normalized_parts = []
                for part in parts:
                    if part.startswith('<Placemark'):
                        part = re.sub(r'<name>([^<]+)</name>', _normalize_name_tag, part)
                    normalized_parts.append(part)
                content = ''.join(normalized_parts)
            result[filename] = content
        return result

    def parse_all_placemarks(self, context):
        return parse_all_placemarks(context)

    def parse_context(self, context):
        context = self.preprocess_context(context)
        return {'placemarks': parse_all_placemarks(context)}
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        pms = parsed['placemarks']
        with_coords = sum(1 for p in pms if p.get('coordinates'))
        with_addr = sum(1 for p in pms if p.get('address'))
        with_hours = sum(1 for p in pms if p.get('opening_hours'))
        return {
            "Places": len(pms),
            "With Coords": with_coords,
            "With Address": with_addr,
            "With Hours": with_hours,
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
        
        ref_pms = self.parse_context(reference_context)['placemarks']
        gen_pms = self.parse_context(generated_context)['placemarks']
        
        if debug:
            print(f"Reference placemarks: {len(ref_pms)}, Generated placemarks: {len(gen_pms)}")
        
        # Compute component scores
        coverage_score = compute_placemark_coverage(ref_pms, gen_pms)
        accuracy_score = compute_field_accuracy(ref_pms, gen_pms)
        coord_score = compute_coordinate_accuracy(ref_pms, gen_pms)
        ordering_score = compute_ordering_score(ref_pms, gen_pms)
        
        # Combined score: coverage gates everything, accuracy is critical, coords/ordering secondary
        secondary_avg = (coord_score + ordering_score) / 2.0
        score = (coverage_score ** 2) * accuracy_score * math.sqrt(secondary_avg) if secondary_avg > 0 else 0.0
        
        eval_obj = {
            "score": score,
            "coverage_score": coverage_score,
            "accuracy_score": accuracy_score,
            "coord_score": coord_score,
            "ordering_score": ordering_score,
            "ref_count": len(ref_pms),
            "gen_count": len(gen_pms),
        }
        if debug:
            print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


if __name__ == "__main__":
    # Test the parser
    with open("samples/landmarks1/basic_state/attractions.kml", "r") as f:
        content = f.read()
    
    placemarks = parse_kml_placemarks(content)
    
    print("=" * 60)
    print(f"PLACEMARKS ({len(placemarks)})")
    print("=" * 60)
    
    for pm in placemarks:
        coords_str = f"({pm['coordinates'][0]:.5f}, {pm['coordinates'][1]:.5f})" if pm['coordinates'] else "-"
        addr_str = pm['address'][:30] + '...' if pm['address'] and len(pm['address']) > 30 else (pm['address'] or '-')
        print(f"{pm['id']:8} | {pm['name'][:40]:<40} | {coords_str:<20} | {addr_str}")
