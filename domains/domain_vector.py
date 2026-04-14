from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
from xml.etree import ElementTree as ET


SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

# Namespaces to strip during parsing (tool-specific metadata)
IGNORE_NS_PREFIXES = [
    "http://sodipodi.sourceforge.net",
    "http://www.inkscape.org",
    "http://purl.org/dc/",
    "http://creativecommons.org",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns",
]


def _strip_ns(tag):
    """Strip namespace URI from an element tag, returning just the local name."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _get_ns(tag):
    """Get namespace URI from an element tag."""
    if "{" in tag and "}" in tag:
        return tag.split("{", 1)[1].split("}", 1)[0]
    return ""


def _is_ignored_ns(tag):
    """Check if an element belongs to an ignored namespace (tool metadata)."""
    ns = _get_ns(tag)
    for prefix in IGNORE_NS_PREFIXES:
        if ns.startswith(prefix):
            return True
    return False


def _normalize_text(text):
    """Normalize whitespace in text content."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def _normalize_style(style_str):
    """Parse a CSS style string into a normalized dict."""
    if not style_str:
        return {}
    result = {}
    for part in style_str.split(";"):
        part = part.strip()
        if ":" in part:
            key, val = part.split(":", 1)
            result[key.strip().lower()] = val.strip()
    return result


def _color_normalize(color):
    """Normalize CSS color values for comparison."""
    if not color:
        return ""
    color = color.strip().lower()
    # Normalize hex colors: #abc -> #aabbcc
    m = re.match(r'^#([0-9a-f])([0-9a-f])([0-9a-f])$', color)
    if m:
        color = f"#{m.group(1)*2}{m.group(2)*2}{m.group(3)*2}"
    return color


def _numeric_close(a, b, tolerance=0.5):
    """Check if two numeric values are close enough."""
    try:
        fa, fb = float(a), float(b)
        return abs(fa - fb) <= tolerance
    except (ValueError, TypeError):
        return a == b


# ---------------------------------------------------------------------------
# SVG Element Extraction
# ---------------------------------------------------------------------------

def _extract_element_info(elem):
    """Extract a structured representation of an SVG element.
    
    Returns a dict with:
      - tag: local element name (rect, circle, text, path, etc.)
      - id: element id attribute if present
      - text: combined text content (for text/tspan elements)
      - attrs: dict of relevant attributes (position, size, style, color, etc.)
      - children_count: number of child elements
    """
    tag = _strip_ns(elem.tag)
    info = {
        "tag": tag,
        "id": elem.get("id", ""),
        "text": "",
        "attrs": {},
        "children_count": 0,
    }
    
    # Extract text content for text elements
    if tag in ("text", "tspan", "title", "desc"):
        parts = []
        if elem.text:
            parts.append(elem.text.strip())
        for child in elem:
            child_tag = _strip_ns(child.tag)
            if child_tag == "tspan" and child.text:
                parts.append(child.text.strip())
            if child.tail:
                parts.append(child.tail.strip())
        info["text"] = _normalize_text(" ".join(parts))
    
    # Collect relevant attributes
    POSITION_ATTRS = {"x", "y", "x1", "y1", "x2", "y2", "cx", "cy",
                      "width", "height", "r", "rx", "ry", "d",
                      "points", "transform", "viewBox"}
    STYLE_ATTRS = {"fill", "stroke", "stroke-width", "opacity",
                   "font-size", "font-family", "font-weight", "font-style",
                   "text-anchor", "stroke-dasharray", "stroke-linecap",
                   "stroke-linejoin", "fill-opacity", "stroke-opacity"}
    MARKER_ATTRS = {"marker-end", "marker-start", "marker-mid",
                    "markerWidth", "markerHeight", "refX", "refY", "orient"}
    
    relevant = POSITION_ATTRS | STYLE_ATTRS | MARKER_ATTRS | {"id", "class"}
    
    for attr_name, attr_val in elem.attrib.items():
        # Strip namespace from attribute names
        clean_name = _strip_ns(attr_name) if "}" in attr_name else attr_name
        if clean_name in relevant:
            info["attrs"][clean_name] = attr_val
    
    # Also parse style attribute into individual properties
    if "style" in elem.attrib:
        style_dict = _normalize_style(elem.attrib["style"])
        for k, v in style_dict.items():
            if k in STYLE_ATTRS and k not in info["attrs"]:
                info["attrs"][k] = v
    
    info["children_count"] = sum(1 for _ in elem if not _is_ignored_ns(_.tag))
    
    return info


def parse_svg_elements(content):
    """Parse SVG content into a list of element info dicts.
    
    Extracts all visible SVG elements (shapes, text, groups, defs, markers)
    while ignoring tool-specific metadata namespaces.
    
    Returns:
        elements: list of element info dicts
        groups: dict mapping group id -> list of child element fingerprints
        defs: dict mapping def id -> element info
        text_elements: list of text elements with their content
        metadata: dict of top-level SVG attributes (viewBox, width, height)
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        return None, None, None, None, None
    
    elements = []
    groups = {}
    defs_elements = {}
    text_elements = []
    
    # Extract SVG root metadata
    metadata = {
        "width": root.get("width", ""),
        "height": root.get("height", ""),
        "viewBox": root.get("viewBox", ""),
    }
    
    def walk(elem, parent_group_id=None):
        """Recursively walk the SVG tree, extracting element info."""
        if _is_ignored_ns(elem.tag):
            return
        
        tag = _strip_ns(elem.tag)
        
        # Skip metadata, sodipodi, rdf elements
        if tag in ("metadata", "namedview", "RDF", "Work", "format", "type", "title"):
            return
        
        info = _extract_element_info(elem)
        
        # Track groups
        if tag == "g":
            group_id = elem.get("id", f"_anon_g_{len(groups)}")
            groups[group_id] = []
            for child in elem:
                if not _is_ignored_ns(child.tag):
                    child_info = _extract_element_info(child)
                    groups[group_id].append(_element_fingerprint(child_info))
                    walk(child, group_id)
            info["attrs"]["_group_id"] = group_id
            elements.append(info)
            return  # children already processed
        
        # Track defs
        if tag == "defs":
            for child in elem:
                child_tag = _strip_ns(child.tag)
                child_id = child.get("id", "")
                if child_id:
                    defs_elements[child_id] = _extract_element_info(child)
                # Also recurse into defs children (markers, patterns, etc.)
                for grandchild in child:
                    gc_id = grandchild.get("id", "")
                    if gc_id:
                        defs_elements[gc_id] = _extract_element_info(grandchild)
            elements.append(info)
            return
        
        # Track text elements
        if tag in ("text", "tspan") and info["text"]:
            text_elements.append(info)
        
        elements.append(info)
        
        # Recurse into children (for non-group, non-defs elements)
        for child in elem:
            walk(child, parent_group_id)
    
    # Walk SVG children (skip root svg element itself)
    for child in root:
        walk(child)
    
    return elements, groups, defs_elements, text_elements, metadata


def _element_fingerprint(info):
    """Create a fingerprint for matching elements across reference and generated."""
    # Primary: tag + id
    if info["id"]:
        return f"{info['tag']}#{info['id']}"
    # Secondary: tag + text content (for text elements)
    if info["text"]:
        return f"{info['tag']}:{info['text'][:50].lower()}"
    # Tertiary: tag + key position attributes
    pos_parts = []
    for attr in ["x", "y", "cx", "cy", "x1", "y1"]:
        if attr in info["attrs"]:
            pos_parts.append(f"{attr}={info['attrs'][attr]}")
    if pos_parts:
        return f"{info['tag']}@{','.join(pos_parts[:3])}"
    return f"{info['tag']}"


# ---------------------------------------------------------------------------
# Scoring Functions
# ---------------------------------------------------------------------------

def compute_group_coverage(ref_groups, gen_groups, ref_elements, gen_elements):
    """Compute coverage at the group level (semantic units) + element count penalty.
    
    Groups are the primary semantic units in SVG (rooms, sections, etc.).
    This scores at that granularity rather than individual primitives.
    """
    if not ref_groups and not gen_groups:
        return 1.0
    if not ref_groups or not gen_groups:
        return 0.0
    
    ref_ids = set(ref_groups.keys())
    gen_ids = set(gen_groups.keys())
    
    # Jaccard on group IDs
    intersection = len(ref_ids & gen_ids)
    union = len(ref_ids | gen_ids)
    group_jaccard = intersection / union if union > 0 else 1.0
    
    # Also penalise if overall element count is very different
    # (catches cases where ungrouped elements are missing)
    if ref_elements and gen_elements:
        ratio = min(len(gen_elements), len(ref_elements)) / max(len(gen_elements), len(ref_elements))
        count_factor = max(ratio, 0.5)  # floor at 0.5 so it doesn't dominate
    else:
        count_factor = 0.0 if (ref_elements or gen_elements) else 1.0
    
    # Blend: mostly group-level, with a small element-count adjustment
    return 0.8 * group_jaccard + 0.2 * count_factor


def compute_text_accuracy(ref_text_elements, gen_text_elements):
    """Compare text labels using Hungarian-style matching on text content."""
    if not ref_text_elements and not gen_text_elements:
        return 1.0
    if not ref_text_elements or not gen_text_elements:
        return 0.0
    
    ref_texts = [_normalize_text(e["text"]).lower() for e in ref_text_elements if e["text"]]
    gen_texts = [_normalize_text(e["text"]).lower() for e in gen_text_elements if e["text"]]
    
    if not ref_texts and not gen_texts:
        return 1.0
    if not ref_texts or not gen_texts:
        return 0.0
    
    # Match reference texts to generated texts greedily by similarity
    used_gen = set()
    total_score = 0.0
    
    for ref_t in ref_texts:
        best_score = 0.0
        best_idx = -1
        for j, gen_t in enumerate(gen_texts):
            if j in used_gen:
                continue
            if ref_t == gen_t:
                score = 1.0
            else:
                score = SequenceMatcher(None, ref_t, gen_t).ratio()
            if score > best_score:
                best_score = score
                best_idx = j
        if best_idx >= 0:
            used_gen.add(best_idx)
            total_score += best_score
    
    # Penalize missing and extra texts
    max_count = max(len(ref_texts), len(gen_texts))
    return total_score / max_count if max_count > 0 else 1.0


def _build_fingerprint_lookup(elements):
    """Build a dict mapping fingerprint -> element info."""
    lookup = {}
    for e in elements:
        fp = _element_fingerprint(e)
        if fp not in lookup:
            lookup[fp] = e
    return lookup


def compute_visual_fidelity(ref_elements, gen_elements):
    """Dedicated color/visual score: compare fill and stroke for every matched element.
    
    Colors carry semantic meaning in diagrams (room types, categories, severity).
    A wrong color is scored as 0 — no partial credit.
    """
    if not ref_elements and not gen_elements:
        return 1.0
    if not ref_elements or not gen_elements:
        return 0.0
    
    ref_by_fp = _build_fingerprint_lookup(ref_elements)
    gen_by_fp = _build_fingerprint_lookup(gen_elements)
    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0
    
    COLOR_ATTRS = ('fill', 'stroke', 'opacity', 'fill-opacity', 'stroke-opacity')
    color_correct = 0
    color_total = 0
    
    for fp in matched_fps:
        ref_attrs = ref_by_fp[fp]['attrs']
        gen_attrs = gen_by_fp[fp]['attrs']
        for attr in COLOR_ATTRS:
            ref_val = ref_attrs.get(attr, '')
            gen_val = gen_attrs.get(attr, '')
            if ref_val or gen_val:
                color_total += 1
                if attr in ('fill', 'stroke'):
                    if _color_normalize(ref_val) == _color_normalize(gen_val):
                        color_correct += 1
                    # else: 0 — wrong color, no partial credit
                else:
                    if ref_val == gen_val:
                        color_correct += 1
    
    return color_correct / color_total if color_total > 0 else 1.0


def compute_spatial_accuracy(ref_elements, gen_elements):
    """Compare position/dimension attributes of matched elements.
    
    Focuses on spatial attributes (x, y, width, height, etc.) and
    non-color style attributes (font-size, text-anchor, etc.).
    """
    if not ref_elements and not gen_elements:
        return 1.0
    if not ref_elements or not gen_elements:
        return 0.0
    
    ref_by_fp = _build_fingerprint_lookup(ref_elements)
    gen_by_fp = _build_fingerprint_lookup(gen_elements)
    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0
    
    # Attributes scored here (everything EXCEPT fill/stroke/opacity — those are in visual_fidelity)
    SKIP_ATTRS = {'fill', 'stroke', 'opacity', 'fill-opacity', 'stroke-opacity'}
    NUMERIC_ATTRS = {'x', 'y', 'cx', 'cy', 'x1', 'y1', 'x2', 'y2',
                     'width', 'height', 'r', 'rx', 'ry',
                     'font-size', 'stroke-width'}
    PATH_ATTRS = {'d', 'points', 'transform'}
    
    attr_scores = []
    for fp in matched_fps:
        ref_attrs = ref_by_fp[fp]['attrs']
        gen_attrs = gen_by_fp[fp]['attrs']
        
        ref_keys = {k for k in ref_attrs if not k.startswith('_') and k not in SKIP_ATTRS}
        gen_keys = {k for k in gen_attrs if not k.startswith('_') and k not in SKIP_ATTRS}
        all_keys = ref_keys | gen_keys
        
        if not all_keys:
            attr_scores.append(1.0)
            continue
        
        key_score = 0.0
        for key in all_keys:
            ref_val = ref_attrs.get(key, '')
            gen_val = gen_attrs.get(key, '')
            
            if ref_val == gen_val:
                key_score += 1.0
            elif key in NUMERIC_ATTRS:
                if _numeric_close(ref_val, gen_val, tolerance=1.0):
                    key_score += 1.0
                elif _numeric_close(ref_val, gen_val, tolerance=5.0):
                    key_score += 0.7
            elif key in PATH_ATTRS:
                if ref_val and gen_val:
                    key_score += SequenceMatcher(None, ref_val, gen_val).ratio()
            else:
                if ref_val and gen_val:
                    if ref_val.lower() == gen_val.lower():
                        key_score += 1.0
                    else:
                        key_score += SequenceMatcher(None, ref_val.lower(), gen_val.lower()).ratio() * 0.7
        
        attr_scores.append(key_score / len(all_keys))
    
    return sum(attr_scores) / len(attr_scores) if attr_scores else 0.0


def compute_structure_score(ref_groups, gen_groups):
    """Compare group structure (which elements are in which groups)."""
    if not ref_groups and not gen_groups:
        return 1.0
    if not ref_groups or not gen_groups:
        return 0.0
    
    ref_ids = set(ref_groups.keys())
    gen_ids = set(gen_groups.keys())
    
    # Coverage of group IDs
    intersection = len(ref_ids & gen_ids)
    union = len(ref_ids | gen_ids)
    id_coverage = intersection / union if union > 0 else 1.0
    
    # For matched groups, compare membership
    matched_ids = ref_ids & gen_ids
    if not matched_ids:
        return id_coverage * 0.5
    
    membership_scores = []
    for gid in matched_ids:
        ref_members = set(ref_groups[gid])
        gen_members = set(gen_groups[gid])
        if not ref_members and not gen_members:
            membership_scores.append(1.0)
        elif not ref_members or not gen_members:
            membership_scores.append(0.0)
        else:
            m_inter = len(ref_members & gen_members)
            m_union = len(ref_members | gen_members)
            membership_scores.append(m_inter / m_union if m_union > 0 else 1.0)
    
    avg_membership = sum(membership_scores) / len(membership_scores)
    return (id_coverage + avg_membership) / 2.0


def compute_metadata_score(ref_meta, gen_meta):
    """Compare top-level SVG attributes (viewBox, width, height)."""
    if not ref_meta and not gen_meta:
        return 1.0
    if not ref_meta or not gen_meta:
        return 0.0
    
    score = 0.0
    count = 0
    
    for key in ("width", "height", "viewBox"):
        ref_val = ref_meta.get(key, "")
        gen_val = gen_meta.get(key, "")
        if ref_val or gen_val:
            count += 1
            if ref_val == gen_val:
                score += 1.0
            elif ref_val and gen_val:
                # Try numeric comparison for width/height
                if key in ("width", "height"):
                    try:
                        # Strip units
                        ref_num = float(re.sub(r'[^0-9.]', '', ref_val))
                        gen_num = float(re.sub(r'[^0-9.]', '', gen_val))
                        if abs(ref_num - gen_num) < 1.0:
                            score += 1.0
                        elif abs(ref_num - gen_num) / max(ref_num, 1) < 0.05:
                            score += 0.8
                    except ValueError:
                        score += SequenceMatcher(None, ref_val, gen_val).ratio()
                else:
                    score += SequenceMatcher(None, ref_val, gen_val).ratio()
    
    return score / count if count > 0 else 1.0


# ---------------------------------------------------------------------------
# Main parsing entry point
# ---------------------------------------------------------------------------

def parse_svg_from_context(context):
    """Parse all SVG files in a context dict, merging results."""
    all_elements = []
    all_groups = {}
    all_defs = {}
    all_text = []
    metadata = {}
    
    for filename, content in context.items():
        if not filename.endswith('.svg'):
            continue
        result = parse_svg_elements(content)
        if result[0] is None:
            continue
        elems, groups, defs_elems, text_elems, meta = result
        all_elements.extend(elems)
        all_groups.update(groups)
        all_defs.update(defs_elems)
        all_text.extend(text_elems)
        if not metadata:
            metadata = meta
    
    return all_elements, all_groups, all_defs, all_text, metadata


# ---------------------------------------------------------------------------
# Task Class
# ---------------------------------------------------------------------------

class DomainVector(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "vector"
        self.summary = "SVG vector graphics with shapes, text labels, groups, and styling"
        self.description = "SVG vector graphics"
        self.file_format = [".svg"]
        self.domain_parser = "xml.etree"
        self.category = "creative"

    def preprocess_context(self, context):
        """Normalize raw SVG content before parsing.

        Fixes common LLM syntax issues that cause XML parse failures:
        1. Escape bare '&' characters to '&amp;' (excluding existing entities)
        2. Remove bare-attribute self-closing tags like <title removed/>
        3. Strip markdown code fences wrapping SVG content
        """
        fixed = {}
        for filename, content in context.items():
            if not filename.endswith('.svg'):
                fixed[filename] = content
                continue

            # Strip markdown code fences (```xml ... ``` or ```svg ... ```)
            content = re.sub(r'^\s*```(?:xml|svg|html)?\s*\n', '', content)
            content = re.sub(r'\n\s*```\s*$', '', content)

            # Escape bare '&' that are not part of a valid XML entity reference.
            # Valid entity refs: &amp; &lt; &gt; &quot; &apos; or numeric &#123; &#x1F;
            content = re.sub(r'&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);)', '&amp;', content)

            # Remove bare-attribute self-closing tags like <title removed/>
            # These are invalid XML — a bare word is not a valid attribute.
            # Convert e.g. <title removed/> to <title/>
            content = re.sub(r'<(\w+)\s+\w+/>', r'<\1/>', content)

            fixed[filename] = content
        return fixed

    def parse_context(self, context):
        """Parse all SVG files in context into a structured dict.

        Returns a dict with keys:
          - elements: list of element info dicts
          - groups: dict mapping group id -> list of child fingerprints
          - defs: dict mapping def id -> element info
          - text_elements: list of text elements with content
          - metadata: dict of top-level SVG attributes
        """
        context = self.preprocess_context(context)
        elements, groups, defs_elems, text_elems, metadata = parse_svg_from_context(context)
        return {
            "elements": elements,
            "groups": groups,
            "defs": defs_elems,
            "text_elements": text_elems,
            "metadata": metadata,
        }

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        elements = parsed["elements"]
        groups = parsed["groups"]
        defs_elems = parsed["defs"]
        text_elems = parsed["text_elements"]
        if elements is None:
            return {"Elements": 0}
        
        tag_counts = {}
        for e in elements:
            tag = e["tag"]
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        return {
            "Elements": len(elements),
            "Groups": len(groups),
            "Text Labels": len(text_elems),
            "Defs": len(defs_elems),
            "Element Types": ", ".join(sorted(tag_counts.keys())),
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
        ref_elements, ref_groups, ref_text, ref_meta = ref_parsed["elements"], ref_parsed["groups"], ref_parsed["text_elements"], ref_parsed["metadata"]
        gen_parsed = self.parse_context(generated_context)
        gen_elements, gen_groups, gen_text, gen_meta = gen_parsed["elements"], gen_parsed["groups"], gen_parsed["text_elements"], gen_parsed["metadata"]
        
        if ref_elements is None:
            return {"score": 0.0, "error": "Failed to parse reference SVG"}
        if gen_elements is None:
            return {"score": 0.0, "error": "Failed to parse generated SVG"}
        
        if debug:
            print(f"Reference: {len(ref_elements)} elements, {len(ref_groups)} groups, {len(ref_text)} text labels")
            print(f"Generated: {len(gen_elements)} elements, {len(gen_groups)} groups, {len(gen_text)} text labels")
        
        # Compute component scores
        group_coverage = compute_group_coverage(ref_groups, gen_groups, ref_elements, gen_elements)
        text_accuracy = compute_text_accuracy(ref_text, gen_text)
        visual_fidelity = compute_visual_fidelity(ref_elements, gen_elements)
        spatial_accuracy = compute_spatial_accuracy(ref_elements, gen_elements)
        structure_score = compute_structure_score(ref_groups, gen_groups)
        metadata_score = compute_metadata_score(ref_meta, gen_meta)
        
        # Multiplicative formula (like CityPOI/StarCatalog):
        # Coverage and text GATE the score (missing content = big penalty).
        # Visual, spatial, and structure are secondary — averaged under a sqrt.
        # Metadata penalises only if very wrong (< 0.5).
        #
        # coverage × text × √( (visual×2 + spatial + structure) / 4 )
        #
        # This ensures:
        #  - Missing 1/10 groups → coverage ~0.9 → ~10% gating penalty
        #  - Missing text labels  → text ~0.82 → another ~18% penalty
        #  - Wrong colors → visual drops → meaningful sqrt penalty
        secondary = (visual_fidelity * 2 + spatial_accuracy + structure_score) / 4.0
        secondary_factor = math.sqrt(secondary) if secondary > 0 else 0.0
        
        score = group_coverage * text_accuracy * secondary_factor
        
        # Metadata penalty: only kicks in if metadata is significantly wrong
        if metadata_score < 0.5:
            score *= (0.5 + metadata_score)  # at worst halves the score
        
        eval_obj = {
            "score": score,
            "group_coverage": group_coverage,
            "text_accuracy": text_accuracy,
            "visual_fidelity": visual_fidelity,
            "spatial_accuracy": spatial_accuracy,
            "structure_score": structure_score,
            "metadata_score": metadata_score,
            "ref_element_count": len(ref_elements),
            "gen_element_count": len(gen_elements),
            "ref_text_count": len(ref_text),
            "gen_text_count": len(gen_text),
        }
        
        if debug:
            print(f"\033[94m{eval_obj}\033[0m")
        
        return eval_obj

    def render_context_visual(self, context, outfile):
        """Render SVG context to a PNG image using cairosvg."""
        import cairosvg

        # Preprocess to fix common LLM issues before rendering
        context = self.preprocess_context(context)

        # Find the (first) SVG file in the context
        svg_content = None
        for fname, content in context.items():
            if fname.endswith('.svg'):
                svg_content = content
                break
        if svg_content is None:
            return None

        out_path = outfile + '.png'
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        cairosvg.svg2png(bytestring=svg_content.encode('utf-8'), write_to=out_path)
        return out_path


if __name__ == "__main__":
    # Test the parser and self-evaluation
    from utils_context import build_context_from_folder
    
    context = build_context_from_folder("samples/vector1/basic_state")
    elements, groups, defs_elems, text_elems, metadata = parse_svg_from_context(context)
    
    if elements is None:
        print("Failed to parse SVG")
    else:
        print("=" * 60)
        print(f"SVG ELEMENTS ({len(elements)})")
        print("=" * 60)
        
        for e in elements:
            text_str = f' "{e["text"][:40]}"' if e["text"] else ""
            id_str = f' id={e["id"]}' if e["id"] else ""
            print(f"  {e['tag']:<12}{id_str}{text_str}")
        
        print(f"\nGroups: {list(groups.keys())}")
        print(f"Defs: {list(defs_elems.keys())}")
        print(f"Text elements: {len(text_elems)}")
        print(f"Metadata: {metadata}")
        
        # Self-evaluation test
        print("\n" + "=" * 60)
        print("SELF-EVALUATION TEST")
        print("=" * 60)
        
        task = TaskVector()
        sample_json_path = "samples/vector1/sample.json"
        if os.path.exists(sample_json_path):
            target_state = {"state_id": "basic_state"}
            result = task.evaluate_context("vector1", context, target_state, debug=True)
            print(f"\nFinal score: {result['score']}")
        else:
            print("No sample.json found yet, skipping evaluation test")
