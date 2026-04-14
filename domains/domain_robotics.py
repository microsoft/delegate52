from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# URDF XML Parser
# ---------------------------------------------------------------------------

def parse_urdf(content):
    """Parse a URDF XML string into a structured dict.

    Returns a dict with:
        robot_name   : str
        links        : list of link dicts
        joints       : list of joint dicts
        materials    : list of material dicts (top-level)
        transmissions: list of transmission dicts
        gazebos      : list of gazebo element dicts
        parse_error  : str or None
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        # Try repairing mismatched closing tags (common LLM error)
        repaired = _repair_xml_tags(content)
        try:
            root = ET.fromstring(repaired)
        except ET.ParseError as e:
            return _empty_parse_result(str(e))

    if root.tag != 'robot':
        return _empty_parse_result(f"Root tag is '{root.tag}', expected 'robot'")

    result = {
        'robot_name': root.get('name', ''),
        'links': [],
        'joints': [],
        'materials': [],
        'transmissions': [],
        'gazebos': [],
        'parse_error': None,
    }

    for child in root:
        tag = child.tag.lower()
        if tag == 'link':
            result['links'].append(_parse_link(child))
        elif tag == 'joint':
            result['joints'].append(_parse_joint(child))
        elif tag == 'material':
            result['materials'].append(_parse_material(child))
        elif tag == 'transmission':
            result['transmissions'].append(_parse_transmission(child))
        elif tag == 'gazebo':
            result['gazebos'].append(_parse_gazebo(child))

    return result


def _empty_parse_result(error_msg=None):
    return {
        'robot_name': '',
        'links': [],
        'joints': [],
        'materials': [],
        'transmissions': [],
        'gazebos': [],
        'parse_error': error_msg,
    }


def _repair_xml_tags(content):
    """Repair mismatched XML closing tags to match their opening counterparts.

    Handles common LLM errors:
    - Wrong case in closing tag (</hardware_interface> for <hardwareInterface>)
    - Content leaked into closing tag (</hardware_interface/EffortJointInterface>)
    - Typos in closing tag (</mechanchanicalReduction> for <mechanicalReduction>)
    - Wrong closing tag name (</mu2> for <mu1>)
    """
    stack = []
    result = []
    pos = 0

    pattern = re.compile(
        r'(<!--.*?-->|<\?.*?\?>)'          # group 1: comments / processing instructions
        r'|<([a-zA-Z_][\w.-]*)\b([^>]*)/>'  # group 2,3: self-closing tag
        r'|<([a-zA-Z_][\w.-]*)\b([^>]*)>'   # group 4,5: opening tag
        r'|</([^>]+)>'                        # group 6: closing tag (permissive)
    , re.DOTALL)

    for m in pattern.finditer(content):
        result.append(content[pos:m.start()])

        if m.group(1):      # comment or PI — pass through
            result.append(m.group(0))
        elif m.group(2):    # self-closing tag — pass through
            result.append(m.group(0))
        elif m.group(4):    # opening tag — push to stack
            stack.append(m.group(4))
            result.append(m.group(0))
        elif m.group(6):    # closing tag — check against stack
            close_name = m.group(6).strip()
            if stack:
                expected = stack[-1]
                if close_name != expected:
                    result.append(f'</{expected}>')
                else:
                    result.append(m.group(0))
                stack.pop()
            else:
                result.append(m.group(0))

        pos = m.end()

    result.append(content[pos:])
    return ''.join(result)


def _parse_origin(elem):
    """Parse an <origin> element into xyz and rpy lists."""
    if elem is None:
        return None
    xyz_str = elem.get('xyz', '0 0 0')
    rpy_str = elem.get('rpy', '0 0 0')
    try:
        xyz = [float(x) for x in xyz_str.split()]
    except (ValueError, AttributeError):
        xyz = [0.0, 0.0, 0.0]
    try:
        rpy = [float(x) for x in rpy_str.split()]
    except (ValueError, AttributeError):
        rpy = [0.0, 0.0, 0.0]
    return {'xyz': xyz, 'rpy': rpy}


def _parse_inertial(elem):
    """Parse an <inertial> element."""
    if elem is None:
        return None
    result = {'origin': None, 'mass': 0.0, 'inertia': {}}

    origin_el = elem.find('origin')
    if origin_el is not None:
        result['origin'] = _parse_origin(origin_el)

    mass_el = elem.find('mass')
    if mass_el is not None:
        try:
            result['mass'] = float(mass_el.get('value', '0'))
        except ValueError:
            result['mass'] = 0.0

    inertia_el = elem.find('inertia')
    if inertia_el is not None:
        for attr in ['ixx', 'ixy', 'ixz', 'iyy', 'iyz', 'izz']:
            try:
                result['inertia'][attr] = float(inertia_el.get(attr, '0'))
            except ValueError:
                result['inertia'][attr] = 0.0

    return result


def _parse_geometry(elem):
    """Parse a <geometry> element."""
    if elem is None:
        return None
    for child in elem:
        tag = child.tag.lower()
        if tag == 'box':
            size_str = child.get('size', '0 0 0')
            try:
                size = [float(x) for x in size_str.split()]
            except ValueError:
                size = [0.0, 0.0, 0.0]
            return {'type': 'box', 'size': size}
        elif tag == 'cylinder':
            try:
                length = float(child.get('length', '0'))
                radius = float(child.get('radius', '0'))
            except ValueError:
                length, radius = 0.0, 0.0
            return {'type': 'cylinder', 'length': length, 'radius': radius}
        elif tag == 'sphere':
            try:
                radius = float(child.get('radius', '0'))
            except ValueError:
                radius = 0.0
            return {'type': 'sphere', 'radius': radius}
        elif tag == 'mesh':
            filename = child.get('filename', '')
            scale_str = child.get('scale', '')
            scale = None
            if scale_str:
                try:
                    scale = [float(x) for x in scale_str.split()]
                except ValueError:
                    scale = None
            return {'type': 'mesh', 'filename': filename, 'scale': scale}
    return None


def _parse_visual_or_collision(elem):
    """Parse a <visual> or <collision> element."""
    if elem is None:
        return None
    result = {'origin': None, 'geometry': None}

    origin_el = elem.find('origin')
    if origin_el is not None:
        result['origin'] = _parse_origin(origin_el)

    geom_el = elem.find('geometry')
    if geom_el is not None:
        result['geometry'] = _parse_geometry(geom_el)

    # For visual elements, also check for material
    mat_el = elem.find('material')
    if mat_el is not None:
        result['material'] = _parse_material(mat_el)
    
    return result


def _parse_material(elem):
    """Parse a <material> element."""
    if elem is None:
        return None
    result = {'name': elem.get('name', '')}
    color_el = elem.find('color')
    if color_el is not None:
        rgba_str = color_el.get('rgba', '')
        try:
            result['rgba'] = [float(x) for x in rgba_str.split()]
        except ValueError:
            result['rgba'] = []
    texture_el = elem.find('texture')
    if texture_el is not None:
        result['texture'] = texture_el.get('filename', '')
    return result


def _parse_link(elem):
    """Parse a <link> element."""
    result = {
        'name': elem.get('name', ''),
        'inertial': None,
        'visuals': [],
        'collisions': [],
    }

    inertial_el = elem.find('inertial')
    if inertial_el is not None:
        result['inertial'] = _parse_inertial(inertial_el)

    for vis in elem.findall('visual'):
        parsed = _parse_visual_or_collision(vis)
        if parsed:
            result['visuals'].append(parsed)

    for col in elem.findall('collision'):
        parsed = _parse_visual_or_collision(col)
        if parsed:
            result['collisions'].append(parsed)

    return result


def _parse_joint(elem):
    """Parse a <joint> element."""
    result = {
        'name': elem.get('name', ''),
        'type': elem.get('type', ''),
        'parent': '',
        'child': '',
        'origin': None,
        'axis': None,
        'limit': None,
        'dynamics': None,
    }

    parent_el = elem.find('parent')
    if parent_el is not None:
        result['parent'] = parent_el.get('link', '')

    child_el = elem.find('child')
    if child_el is not None:
        result['child'] = child_el.get('link', '')

    origin_el = elem.find('origin')
    if origin_el is not None:
        result['origin'] = _parse_origin(origin_el)

    axis_el = elem.find('axis')
    if axis_el is not None:
        xyz_str = axis_el.get('xyz', '0 0 1')
        try:
            result['axis'] = [float(x) for x in xyz_str.split()]
        except ValueError:
            result['axis'] = [0.0, 0.0, 1.0]

    limit_el = elem.find('limit')
    if limit_el is not None:
        result['limit'] = {}
        for attr in ['lower', 'upper', 'effort', 'velocity']:
            try:
                result['limit'][attr] = float(limit_el.get(attr, '0'))
            except (ValueError, TypeError):
                result['limit'][attr] = 0.0

    dynamics_el = elem.find('dynamics')
    if dynamics_el is not None:
        result['dynamics'] = {}
        for attr in ['damping', 'friction']:
            try:
                result['dynamics'][attr] = float(dynamics_el.get(attr, '0'))
            except (ValueError, TypeError):
                result['dynamics'][attr] = 0.0

    return result


def _parse_transmission(elem):
    """Parse a <transmission> element."""
    result = {
        'name': elem.get('name', ''),
        'type': '',
        'joint_name': '',
        'actuator_name': '',
    }

    type_el = elem.find('type')
    if type_el is not None and type_el.text:
        result['type'] = type_el.text.strip()

    joint_el = elem.find('joint')
    if joint_el is not None:
        result['joint_name'] = joint_el.get('name', '')

    actuator_el = elem.find('actuator')
    if actuator_el is not None:
        result['actuator_name'] = actuator_el.get('name', '')

    return result


def _parse_gazebo(elem):
    """Parse a <gazebo> element (Gazebo-specific extensions)."""
    result = {
        'reference': elem.get('reference', ''),
        'plugins': [],
        'properties': {},
    }

    for child in elem:
        tag = child.tag.lower()
        if tag == 'plugin':
            result['plugins'].append({
                'name': child.get('name', ''),
                'filename': child.get('filename', ''),
            })
        elif child.text and child.text.strip():
            result['properties'][tag] = child.text.strip()

    return result


def parse_all_urdf(context):
    """Parse all .urdf files in a context dict, return merged structures."""
    all_links = []
    all_joints = []
    all_materials = []
    all_transmissions = []
    all_gazebos = []
    robot_name = ''

    for filename, content in sorted(context.items()):
        if filename.endswith('.urdf'):
            parsed = parse_urdf(content)
            if parsed['parse_error']:
                continue
            if not robot_name:
                robot_name = parsed['robot_name']
            all_links.extend(parsed['links'])
            all_joints.extend(parsed['joints'])
            all_materials.extend(parsed['materials'])
            all_transmissions.extend(parsed['transmissions'])
            all_gazebos.extend(parsed['gazebos'])

    return {
        'robot_name': robot_name,
        'links': all_links,
        'joints': all_joints,
        'materials': all_materials,
        'transmissions': all_transmissions,
        'gazebos': all_gazebos,
    }


# ---------------------------------------------------------------------------
# Comparison / scoring helpers
# ---------------------------------------------------------------------------

def _float_close(a, b, tol=1e-4):
    """Check if two floats are close."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) < tol


def _origin_similarity(o1, o2):
    """Score similarity of two origins (xyz + rpy)."""
    if o1 is None and o2 is None:
        return 1.0
    if o1 is None or o2 is None:
        return 0.0

    xyz_score = 1.0
    rpy_score = 1.0

    xyz1, xyz2 = o1.get('xyz', [0, 0, 0]), o2.get('xyz', [0, 0, 0])
    if len(xyz1) == 3 and len(xyz2) == 3:
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(xyz1, xyz2)))
        if dist < 1e-6:
            xyz_score = 1.0
        elif dist < 1e-3:
            xyz_score = 0.95
        elif dist < 0.01:
            xyz_score = 0.7
        elif dist < 0.1:
            xyz_score = 0.3
        else:
            xyz_score = 0.0

    rpy1, rpy2 = o1.get('rpy', [0, 0, 0]), o2.get('rpy', [0, 0, 0])
    if len(rpy1) == 3 and len(rpy2) == 3:
        rdist = math.sqrt(sum((a - b) ** 2 for a, b in zip(rpy1, rpy2)))
        if rdist < 1e-6:
            rpy_score = 1.0
        elif rdist < 1e-3:
            rpy_score = 0.95
        elif rdist < 0.01:
            rpy_score = 0.7
        elif rdist < 0.1:
            rpy_score = 0.3
        else:
            rpy_score = 0.0

    return 0.5 * xyz_score + 0.5 * rpy_score


def _geometry_similarity(g1, g2):
    """Score similarity of two geometries."""
    if g1 is None and g2 is None:
        return 1.0
    if g1 is None or g2 is None:
        return 0.0
    if g1['type'] != g2['type']:
        return 0.0

    gtype = g1['type']
    if gtype == 'mesh':
        # Compare filenames (extract basename for comparison)
        fn1 = g1.get('filename', '').rsplit('/', 1)[-1].lower()
        fn2 = g2.get('filename', '').rsplit('/', 1)[-1].lower()
        name_sim = SequenceMatcher(None, fn1, fn2).ratio()
        scale_sim = 1.0
        s1, s2 = g1.get('scale'), g2.get('scale')
        if s1 is not None and s2 is not None and len(s1) == len(s2):
            diffs = [abs(a - b) for a, b in zip(s1, s2)]
            if all(d < 1e-6 for d in diffs):
                scale_sim = 1.0
            else:
                scale_sim = max(0, 1.0 - sum(diffs))
        elif (s1 is None) != (s2 is None):
            scale_sim = 0.5
        return 0.8 * name_sim + 0.2 * scale_sim
    elif gtype == 'box':
        s1, s2 = g1.get('size', []), g2.get('size', [])
        if len(s1) == 3 and len(s2) == 3:
            return 1.0 if all(_float_close(a, b) for a, b in zip(s1, s2)) else 0.3
        return 0.0
    elif gtype == 'cylinder':
        l_ok = _float_close(g1.get('length', 0), g2.get('length', 0))
        r_ok = _float_close(g1.get('radius', 0), g2.get('radius', 0))
        return (0.5 * l_ok + 0.5 * r_ok)
    elif gtype == 'sphere':
        return 1.0 if _float_close(g1.get('radius', 0), g2.get('radius', 0)) else 0.3
    return 0.0


def _inertial_similarity(i1, i2):
    """Score similarity of two inertial elements."""
    if i1 is None and i2 is None:
        return 1.0
    if i1 is None or i2 is None:
        return 0.0

    # Mass comparison
    m1, m2 = i1.get('mass', 0), i2.get('mass', 0)
    if _float_close(m1, m2, tol=1e-6):
        mass_score = 1.0
    elif max(abs(m1), abs(m2)) > 0:
        mass_score = max(0, 1.0 - abs(m1 - m2) / max(abs(m1), abs(m2), 1e-9))
    else:
        mass_score = 1.0

    # Origin comparison
    origin_score = _origin_similarity(i1.get('origin'), i2.get('origin'))

    # Inertia tensor comparison
    inr1, inr2 = i1.get('inertia', {}), i2.get('inertia', {})
    inertia_scores = []
    for attr in ['ixx', 'ixy', 'ixz', 'iyy', 'iyz', 'izz']:
        v1 = inr1.get(attr, 0.0)
        v2 = inr2.get(attr, 0.0)
        if _float_close(v1, v2, tol=1e-8):
            inertia_scores.append(1.0)
        else:
            denom = max(abs(v1), abs(v2), 1e-9)
            inertia_scores.append(max(0, 1.0 - abs(v1 - v2) / denom))
    inertia_score = sum(inertia_scores) / len(inertia_scores) if inertia_scores else 1.0

    return 0.4 * mass_score + 0.3 * origin_score + 0.3 * inertia_score


def compute_link_coverage_score(ref_links, gen_links):
    """Jaccard similarity of links by name."""
    if not ref_links and not gen_links:
        return 1.0
    if not ref_links or not gen_links:
        return 0.0
    ref_names = {l['name'].lower().strip() for l in ref_links}
    gen_names = {l['name'].lower().strip() for l in gen_links}
    intersection = len(ref_names & gen_names)
    union = len(ref_names | gen_names)
    return intersection / union if union > 0 else 0.0


def compute_link_accuracy_score(ref_links, gen_links):
    """Score accuracy of matched links (inertial, visual, collision)."""
    if not ref_links and not gen_links:
        return 1.0
    if not ref_links or not gen_links:
        return 0.0

    ref_by_name = {l['name'].lower().strip(): l for l in ref_links}
    gen_by_name = {l['name'].lower().strip(): l for l in gen_links}
    matched = set(ref_by_name.keys()) & set(gen_by_name.keys())
    if not matched:
        return 0.0

    scores = []
    for name in matched:
        rl = ref_by_name[name]
        gl = gen_by_name[name]

        # Inertial similarity
        inertial_sim = _inertial_similarity(rl.get('inertial'), gl.get('inertial'))

        # Visual geometry similarity
        rv = rl.get('visuals', [])
        gv = gl.get('visuals', [])
        if not rv and not gv:
            vis_sim = 1.0
        elif not rv or not gv:
            vis_sim = 0.0
        else:
            # Compare first visual geometries
            vis_scores = []
            for i in range(min(len(rv), len(gv))):
                rg = rv[i].get('geometry')
                gg = gv[i].get('geometry')
                vis_scores.append(_geometry_similarity(rg, gg))
                # Also compare visual origins
                vis_scores.append(_origin_similarity(rv[i].get('origin'), gv[i].get('origin')))
            vis_sim = sum(vis_scores) / len(vis_scores) if vis_scores else 0.0
            # Penalize count mismatch
            if len(rv) != len(gv):
                vis_sim *= min(len(rv), len(gv)) / max(len(rv), len(gv))

        # Collision geometry similarity
        rc = rl.get('collisions', [])
        gc = gl.get('collisions', [])
        if not rc and not gc:
            col_sim = 1.0
        elif not rc or not gc:
            col_sim = 0.0
        else:
            col_scores = []
            for i in range(min(len(rc), len(gc))):
                rg = rc[i].get('geometry')
                gg = gc[i].get('geometry')
                col_scores.append(_geometry_similarity(rg, gg))
            col_sim = sum(col_scores) / len(col_scores) if col_scores else 0.0
            if len(rc) != len(gc):
                col_sim *= min(len(rc), len(gc)) / max(len(rc), len(gc))

        link_score = 0.4 * inertial_sim + 0.35 * vis_sim + 0.25 * col_sim
        scores.append(link_score)

    # Coverage penalty: unmatched links pull score down
    coverage = len(matched) / max(len(ref_by_name), len(gen_by_name))
    return (sum(scores) / len(scores)) * coverage


def compute_joint_coverage_score(ref_joints, gen_joints):
    """Jaccard similarity of joints by name."""
    if not ref_joints and not gen_joints:
        return 1.0
    if not ref_joints or not gen_joints:
        return 0.0
    ref_names = {j['name'].lower().strip() for j in ref_joints}
    gen_names = {j['name'].lower().strip() for j in gen_joints}
    intersection = len(ref_names & gen_names)
    union = len(ref_names | gen_names)
    return intersection / union if union > 0 else 0.0


def compute_joint_accuracy_score(ref_joints, gen_joints):
    """Score accuracy of matched joints (type, parent, child, origin, axis, limits)."""
    if not ref_joints and not gen_joints:
        return 1.0
    if not ref_joints or not gen_joints:
        return 0.0

    ref_by_name = {j['name'].lower().strip(): j for j in ref_joints}
    gen_by_name = {j['name'].lower().strip(): j for j in gen_joints}
    matched = set(ref_by_name.keys()) & set(gen_by_name.keys())
    if not matched:
        return 0.0

    scores = []
    for name in matched:
        rj = ref_by_name[name]
        gj = gen_by_name[name]
        pts = 0.0
        total = 0.0

        # Joint type match (critical)
        total += 2.0
        if rj['type'].lower() == gj['type'].lower():
            pts += 2.0

        # Parent link match
        total += 1.0
        if rj['parent'].lower().strip() == gj['parent'].lower().strip():
            pts += 1.0

        # Child link match
        total += 1.0
        if rj['child'].lower().strip() == gj['child'].lower().strip():
            pts += 1.0

        # Origin accuracy
        total += 1.0
        pts += _origin_similarity(rj.get('origin'), gj.get('origin'))

        # Axis accuracy
        if rj.get('axis') is not None or gj.get('axis') is not None:
            total += 1.0
            if rj.get('axis') and gj.get('axis') and len(rj['axis']) == 3 and len(gj['axis']) == 3:
                if all(_float_close(a, b) for a, b in zip(rj['axis'], gj['axis'])):
                    pts += 1.0
                else:
                    # Partial credit for close axes
                    dot = sum(a * b for a, b in zip(rj['axis'], gj['axis']))
                    mag1 = math.sqrt(sum(a ** 2 for a in rj['axis']))
                    mag2 = math.sqrt(sum(a ** 2 for a in gj['axis']))
                    if mag1 > 0 and mag2 > 0:
                        cos_sim = abs(dot / (mag1 * mag2))
                        pts += cos_sim * 0.8

        # Limit accuracy
        if rj.get('limit') is not None or gj.get('limit') is not None:
            total += 1.0
            if rj.get('limit') and gj.get('limit'):
                limit_scores = []
                for attr in ['lower', 'upper', 'effort', 'velocity']:
                    v1 = rj['limit'].get(attr, 0)
                    v2 = gj['limit'].get(attr, 0)
                    if _float_close(v1, v2, tol=1e-3):
                        limit_scores.append(1.0)
                    else:
                        denom = max(abs(v1), abs(v2), 1e-9)
                        limit_scores.append(max(0, 1.0 - abs(v1 - v2) / denom))
                pts += sum(limit_scores) / len(limit_scores)

        scores.append(pts / total if total > 0 else 1.0)

    coverage = len(matched) / max(len(ref_by_name), len(gen_by_name))
    return (sum(scores) / len(scores)) * coverage


def compute_transmission_score(ref_trans, gen_trans):
    """Score transmission element preservation."""
    if not ref_trans and not gen_trans:
        return 1.0
    if not ref_trans or not gen_trans:
        return 0.0

    ref_names = {t['name'].lower().strip() for t in ref_trans}
    gen_names = {t['name'].lower().strip() for t in gen_trans}
    coverage = len(ref_names & gen_names) / len(ref_names | gen_names) if ref_names | gen_names else 1.0

    # Check accuracy for matched transmissions
    ref_by_name = {t['name'].lower().strip(): t for t in ref_trans}
    gen_by_name = {t['name'].lower().strip(): t for t in gen_trans}
    matched = ref_names & gen_names
    if not matched:
        return coverage * 0.5

    acc_scores = []
    for name in matched:
        rt = ref_by_name[name]
        gt = gen_by_name[name]
        pts = 0.0
        # Type match
        if rt.get('type', '').lower() == gt.get('type', '').lower():
            pts += 1.0
        # Joint name match
        if rt.get('joint_name', '').lower() == gt.get('joint_name', '').lower():
            pts += 1.0
        # Actuator name match
        if rt.get('actuator_name', '').lower() == gt.get('actuator_name', '').lower():
            pts += 1.0
        acc_scores.append(pts / 3.0)

    accuracy = sum(acc_scores) / len(acc_scores)
    return coverage * accuracy


def compute_gazebo_score(ref_gz, gen_gz):
    """Score Gazebo element preservation."""
    if not ref_gz and not gen_gz:
        return 1.0
    if not ref_gz or not gen_gz:
        return 0.0

    # Match by reference attribute
    ref_refs = {}
    gen_refs = {}
    for g in ref_gz:
        key = g.get('reference', '').lower().strip()
        ref_refs[key] = g
    for g in gen_gz:
        key = g.get('reference', '').lower().strip()
        gen_refs[key] = g

    all_keys = set(ref_refs.keys()) | set(gen_refs.keys())
    matched_keys = set(ref_refs.keys()) & set(gen_refs.keys())

    if not all_keys:
        return 1.0

    coverage = len(matched_keys) / len(all_keys)

    # Accuracy for matched elements
    acc_scores = []
    for key in matched_keys:
        rg = ref_refs[key]
        gg = gen_refs[key]
        pts = 0.0
        total = 0.0

        # Plugin match
        rp = {(p.get('name', ''), p.get('filename', '')) for p in rg.get('plugins', [])}
        gp = {(p.get('name', ''), p.get('filename', '')) for p in gg.get('plugins', [])}
        if rp or gp:
            total += 1.0
            if rp == gp:
                pts += 1.0
            elif rp & gp:
                pts += 0.5

        # Properties match
        r_props = rg.get('properties', {})
        g_props = gg.get('properties', {})
        all_prop_keys = set(r_props.keys()) | set(g_props.keys())
        if all_prop_keys:
            total += 1.0
            matching = sum(1 for k in all_prop_keys
                          if r_props.get(k, '').lower() == g_props.get(k, '').lower())
            pts += matching / len(all_prop_keys)

        acc_scores.append(pts / total if total > 0 else 1.0)

    accuracy = sum(acc_scores) / len(acc_scores) if acc_scores else 1.0
    return coverage * accuracy


# ---------------------------------------------------------------------------
# Task class
# ---------------------------------------------------------------------------

class DomainRobotics(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "robotics"
        self.summary = "URDF (Unified Robot Description Format) XML files describing robot models with links, joints, transmissions, and Gazebo simulation properties"
        self.description = "URDF robot descriptions"
        self.file_format = [".urdf"]
        self.domain_parser = "xml.etree"
        self.category = "science"

    def parse_context(self, context):
        """Parse all URDF files in the context and return a structured dict."""
        return parse_all_urdf(context)

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        joint_types = {}
        for j in parsed['joints']:
            jtype = j['type']
            joint_types[jtype] = joint_types.get(jtype, 0) + 1
        return {
            "Robot Name": parsed['robot_name'],
            "Links": len(parsed['links']),
            "Joints": len(parsed['joints']),
            "Joint Types": joint_types,
            "Transmissions": len(parsed['transmissions']),
            "Gazebo Elements": len(parsed['gazebos']),
            "Materials": len(parsed['materials']),
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

        ref = self.parse_context(reference_context)
        gen = self.parse_context(generated_context)

        if debug:
            print(f"Ref: {len(ref['links'])} links, {len(ref['joints'])} joints, "
                  f"{len(ref['transmissions'])} trans, {len(ref['gazebos'])} gazebo")
            print(f"Gen: {len(gen['links'])} links, {len(gen['joints'])} joints, "
                  f"{len(gen['transmissions'])} trans, {len(gen['gazebos'])} gazebo")

        # Component scores
        link_cov = compute_link_coverage_score(ref['links'], gen['links'])
        link_acc = compute_link_accuracy_score(ref['links'], gen['links'])
        joint_cov = compute_joint_coverage_score(ref['joints'], gen['joints'])
        joint_acc = compute_joint_accuracy_score(ref['joints'], gen['joints'])
        trans_score = compute_transmission_score(ref['transmissions'], gen['transmissions'])
        gazebo_score = compute_gazebo_score(ref['gazebos'], gen['gazebos'])

        # Weighted combination:
        # Links (coverage + accuracy): 35%
        # Joints (coverage + accuracy): 35%
        # Transmissions: 15%
        # Gazebo: 15%
        score = (0.15 * link_cov + 0.20 * link_acc +
                 0.15 * joint_cov + 0.20 * joint_acc +
                 0.15 * trans_score + 0.15 * gazebo_score)

        eval_obj = {
            "score": score,
            "link_coverage_score": link_cov,
            "link_accuracy_score": link_acc,
            "joint_coverage_score": joint_cov,
            "joint_accuracy_score": joint_acc,
            "transmission_score": trans_score,
            "gazebo_score": gazebo_score,
            "ref_links": len(ref['links']),
            "gen_links": len(gen['links']),
            "ref_joints": len(ref['joints']),
            "gen_joints": len(gen['joints']),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
