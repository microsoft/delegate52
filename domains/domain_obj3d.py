from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json


# ---------------------------------------------------------------------------
# OBJ Parser
# ---------------------------------------------------------------------------

def parse_obj_content(content):
    """Parse Wavefront OBJ content into a structured representation.

    Returns a dict with:
      - comments: list of comment strings
      - mtllib: list of mtl library filenames
      - groups: list of group dicts, each containing:
          - name: group name (str)
          - material: material name or None
          - smooth: smooth shading group ID or None
          - vertices: list of (x, y, z) float tuples (local to this group)
          - normals: list of (x, y, z) float tuples (local to this group)
          - texcoords: list of (u, v[, w]) float tuples (local to this group)
          - faces: list of face tuples, each face is a tuple of vertex specs
                   where each vertex spec is (v_local_idx, vt_local_idx|None, vn_local_idx|None)
      - vertex_count: total number of vertices
      - normal_count: total number of normals
      - texcoord_count: total number of texture coordinates
      - face_count: total number of faces
    """
    lines = content.splitlines()

    result = {
        "comments": [],
        "mtllib": [],
        "groups": [],
        "vertex_count": 0,
        "normal_count": 0,
        "texcoord_count": 0,
        "face_count": 0,
    }

    # Global counters for index remapping
    global_v_offset = 0   # how many vertices seen before current group
    global_vn_offset = 0
    global_vt_offset = 0

    current_group = None
    current_material = None
    current_smooth = None

    def _flush_group():
        nonlocal global_v_offset, global_vn_offset, global_vt_offset
        if current_group is not None:
            result["groups"].append(current_group)
            global_v_offset += len(current_group["vertices"])
            global_vn_offset += len(current_group["normals"])
            global_vt_offset += len(current_group["texcoords"])

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("#"):
            result["comments"].append(line[1:].strip())
            continue

        parts = line.split()
        keyword = parts[0]

        if keyword == "mtllib":
            result["mtllib"].extend(parts[1:])

        elif keyword in ("g", "o"):
            _flush_group()
            name = " ".join(parts[1:]) if len(parts) > 1 else "default"
            current_group = {
                "name": name,
                "material": current_material,
                "smooth": current_smooth,
                "vertices": [],
                "normals": [],
                "texcoords": [],
                "faces": [],
            }

        elif keyword == "usemtl":
            material_name = " ".join(parts[1:])
            current_material = material_name
            if current_group is not None:
                current_group["material"] = material_name

        elif keyword == "s":
            current_smooth = parts[1] if len(parts) > 1 else None
            if current_group is not None:
                current_group["smooth"] = current_smooth

        elif keyword == "v" and len(parts) >= 4:
            if current_group is None:
                current_group = {
                    "name": "default",
                    "material": current_material,
                    "smooth": current_smooth,
                    "vertices": [],
                    "normals": [],
                    "texcoords": [],
                    "faces": [],
                }
            try:
                current_group["vertices"].append(tuple(float(x) for x in parts[1:4]))
            except ValueError:
                pass
            result["vertex_count"] += 1

        elif keyword == "vn" and len(parts) >= 4:
            if current_group is None:
                current_group = {
                    "name": "default",
                    "material": current_material,
                    "smooth": current_smooth,
                    "vertices": [],
                    "normals": [],
                    "texcoords": [],
                    "faces": [],
                }
            try:
                current_group["normals"].append(tuple(float(x) for x in parts[1:4]))
            except ValueError:
                pass
            result["normal_count"] += 1

        elif keyword == "vt":
            if current_group is None:
                current_group = {
                    "name": "default",
                    "material": current_material,
                    "smooth": current_smooth,
                    "vertices": [],
                    "normals": [],
                    "texcoords": [],
                    "faces": [],
                }
            try:
                current_group["texcoords"].append(tuple(float(x) for x in parts[1:]))
            except ValueError:
                pass
            result["texcoord_count"] += 1

        elif keyword == "f":
            if current_group is None:
                current_group = {
                    "name": "default",
                    "material": current_material,
                    "smooth": current_smooth,
                    "vertices": [],
                    "normals": [],
                    "texcoords": [],
                    "faces": [],
                }
            face = []
            try:
                for vert_spec in parts[1:]:
                    # Possible formats: v, v/vt, v/vt/vn, v//vn
                    # Strip non-numeric chars (except '-') that LLMs sometimes inject
                    indices = vert_spec.split("/")
                    cleaned = [re.sub(r"[^\d\-]", "", idx) for idx in indices]
                    v_idx = int(cleaned[0]) - global_v_offset  # make local (1-based local)
                    vt_idx = None
                    vn_idx = None
                    if len(cleaned) >= 2 and cleaned[1]:
                        vt_idx = int(cleaned[1]) - global_vt_offset
                    if len(cleaned) >= 3 and cleaned[2]:
                        vn_idx = int(cleaned[2]) - global_vn_offset
                    face.append((v_idx, vt_idx, vn_idx))
                current_group["faces"].append(tuple(face))
                result["face_count"] += 1
            except (ValueError, IndexError):
                pass

    # Flush last group
    _flush_group()

    return result


# ---------------------------------------------------------------------------
# MTL Parser
# ---------------------------------------------------------------------------

def parse_mtl_content(content):
    """Parse Wavefront MTL content into a dict of material definitions.

    Returns a dict mapping material_name -> properties dict:
      - Ka, Kd, Ks: (r, g, b) float tuples
      - Ns: float (specular exponent)
      - Ni: float (index of refraction)
      - d: float (dissolve / transparency)
      - illum: int (illumination model)
      - map_Kd, map_Ka, map_Ks, map_Ns, map_d, map_bump: texture filenames
      - Ke: (r, g, b) emissive color
    """
    materials = {}
    current_name = None

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        keyword = parts[0]

        if keyword == "newmtl":
            current_name = " ".join(parts[1:])
            materials[current_name] = {}

        elif current_name is not None:
            props = materials[current_name]
            if keyword in ("Ka", "Kd", "Ks", "Ke") and len(parts) >= 4:
                try:
                    props[keyword] = tuple(float(x) for x in parts[1:4])
                except ValueError:
                    pass
            elif keyword == "Ns" and len(parts) >= 2:
                try:
                    props[keyword] = float(parts[1])
                except ValueError:
                    pass
            elif keyword == "Ni" and len(parts) >= 2:
                try:
                    props[keyword] = float(parts[1])
                except ValueError:
                    pass
            elif keyword == "d" and len(parts) >= 2:
                try:
                    props[keyword] = float(parts[1])
                except ValueError:
                    pass
            elif keyword == "illum" and len(parts) >= 2:
                try:
                    props[keyword] = int(parts[1])
                except ValueError:
                    pass
            elif keyword.startswith("map_") and len(parts) >= 2:
                props[keyword] = " ".join(parts[1:])

    return materials


# ---------------------------------------------------------------------------
# Scoring Helpers
# ---------------------------------------------------------------------------

def _jaccard(set_a, set_b):
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _color_distance(c1, c2):
    """Euclidean distance between two RGB tuples (values in 0-1)."""
    if c1 is None or c2 is None:
        return 1.0 if (c1 is None) != (c2 is None) else 0.0
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))


def _color_similarity(c1, c2):
    """Similarity between two RGB tuples: 1.0 = identical, 0.0 = max distance."""
    max_dist = math.sqrt(3)  # max possible distance in 0-1 RGB space
    dist = _color_distance(c1, c2)
    return max(0.0, 1.0 - dist / max_dist)


def _float_similarity(a, b, tolerance=0.01):
    """Similarity between two floats: 1.0 if within tolerance, decays otherwise."""
    if a is None and b is None:
        return 1.0
    if a is None or b is None:
        return 0.0
    diff = abs(a - b)
    if diff <= tolerance:
        return 1.0
    return max(0.0, 1.0 - diff / max(abs(a), abs(b), 1.0))


def _vertex_distance(v1, v2):
    """Euclidean distance between two 3D vertices."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


def compute_group_coverage(ref_groups, gen_groups):
    """Compute Jaccard coverage on group names."""
    ref_names = {g["name"].lower() for g in ref_groups}
    gen_names = {g["name"].lower() for g in gen_groups}
    return _jaccard(ref_names, gen_names)


def compute_group_accuracy(ref_groups, gen_groups):
    """Compare matched groups: material assignment, vertex count, face count.

    Returns a score 0-1 based on the quality of matched groups.
    """
    ref_by_name = {g["name"].lower(): g for g in ref_groups}
    gen_by_name = {g["name"].lower(): g for g in gen_groups}

    matched_names = set(ref_by_name.keys()) & set(gen_by_name.keys())
    if not matched_names:
        return 0.0

    total_score = 0.0
    for name in matched_names:
        rg = ref_by_name[name]
        gg = gen_by_name[name]

        # Material match (0 or 1)
        mat_match = 1.0 if (rg["material"] or "").lower() == (gg["material"] or "").lower() else 0.0

        # Vertex count similarity
        rv, gv = len(rg["vertices"]), len(gg["vertices"])
        v_sim = min(rv, gv) / max(rv, gv) if max(rv, gv) > 0 else 1.0

        # Face count similarity
        rf, gf = len(rg["faces"]), len(gg["faces"])
        f_sim = min(rf, gf) / max(rf, gf) if max(rf, gf) > 0 else 1.0

        group_score = 0.4 * mat_match + 0.3 * v_sim + 0.3 * f_sim
        total_score += group_score

    return total_score / len(matched_names)


def compute_vertex_accuracy(ref_groups, gen_groups):
    """Compare vertex positions for matched groups.

    For each matched group, sort vertices and compare pairwise with tolerance.
    """
    ref_by_name = {g["name"].lower(): g for g in ref_groups}
    gen_by_name = {g["name"].lower(): g for g in gen_groups}

    matched_names = set(ref_by_name.keys()) & set(gen_by_name.keys())
    if not matched_names:
        return 0.0

    total_score = 0.0
    total_weight = 0.0

    for name in matched_names:
        rg = ref_by_name[name]
        gg = gen_by_name[name]
        ref_verts = rg["vertices"]
        gen_verts = gg["vertices"]

        if not ref_verts and not gen_verts:
            total_score += 1.0
            total_weight += 1.0
            continue
        if not ref_verts or not gen_verts:
            total_weight += max(len(ref_verts), len(gen_verts))
            continue

        weight = len(ref_verts)
        total_weight += weight

        # Sort vertices for order-independent comparison (within a group)
        ref_sorted = sorted(ref_verts)
        gen_sorted = sorted(gen_verts)

        # Match by nearest neighbor
        matched = 0.0
        gen_used = [False] * len(gen_sorted)
        for rv in ref_sorted:
            best_sim = 0.0
            best_j = -1
            for j, gv in enumerate(gen_sorted):
                if gen_used[j]:
                    continue
                dist = _vertex_distance(rv, gv)
                # Tolerance: perfect if dist < 0.001, zero at dist > 1.0
                if dist < 0.001:
                    sim = 1.0
                elif dist < 1.0:
                    sim = 1.0 - dist
                else:
                    sim = 0.0
                if sim > best_sim:
                    best_sim = sim
                    best_j = j
            if best_j >= 0:
                gen_used[best_j] = True
                matched += best_sim

        total_score += matched

    return total_score / total_weight if total_weight > 0 else 1.0


def compute_face_accuracy(ref_groups, gen_groups):
    """Compare face topology for matched groups.

    For each matched group, compare face vertex index patterns (local indices).
    Faces are compared as sets of vertex index tuples (order within face matters,
    but face ordering within group does not).
    """
    ref_by_name = {g["name"].lower(): g for g in ref_groups}
    gen_by_name = {g["name"].lower(): g for g in gen_groups}

    matched_names = set(ref_by_name.keys()) & set(gen_by_name.keys())
    if not matched_names:
        return 0.0

    total_score = 0.0
    total_weight = 0.0

    for name in matched_names:
        rg = ref_by_name[name]
        gg = gen_by_name[name]
        ref_faces = rg["faces"]
        gen_faces = gg["faces"]

        if not ref_faces and not gen_faces:
            total_score += 1.0
            total_weight += 1.0
            continue
        if not ref_faces or not gen_faces:
            total_weight += max(len(ref_faces), len(gen_faces))
            continue

        weight = len(ref_faces)
        total_weight += weight

        # Normalize faces: extract just position indices for comparison
        def normalize_face(face):
            return tuple(v[0] for v in face)

        ref_normalized = set(normalize_face(f) for f in ref_faces)
        gen_normalized = set(normalize_face(f) for f in gen_faces)

        # Also check reversed winding as equivalent
        ref_with_reverse = set()
        for f in ref_normalized:
            ref_with_reverse.add(f)
            ref_with_reverse.add(tuple(reversed(f)))

        matched = len(ref_normalized & gen_normalized)
        # Also count matches with reversed winding
        reverse_matched = len(ref_with_reverse & gen_normalized)
        best_matched = max(matched, reverse_matched // 2)  # don't double-count

        total_score += min(best_matched, len(ref_faces))

    return total_score / total_weight if total_weight > 0 else 1.0


def compute_material_accuracy(ref_materials, gen_materials):
    """Compare MTL material definitions.

    For matched materials, compare Ka, Kd, Ks, Ns, d, illum properties.
    Returns (coverage, accuracy) tuple.
    """
    ref_names = set(ref_materials.keys())
    gen_names = set(gen_materials.keys())

    # Case-insensitive matching
    ref_lower = {k.lower(): k for k in ref_names}
    gen_lower = {k.lower(): k for k in gen_names}

    coverage = _jaccard(set(ref_lower.keys()), set(gen_lower.keys()))
    matched_lower = set(ref_lower.keys()) & set(gen_lower.keys())

    if not matched_lower:
        return coverage, 0.0

    total_accuracy = 0.0
    for name_lower in matched_lower:
        ref_props = ref_materials[ref_lower[name_lower]]
        gen_props = gen_materials[gen_lower[name_lower]]

        # Compare color properties
        color_scores = []
        for prop in ("Ka", "Kd", "Ks", "Ke"):
            ref_c = ref_props.get(prop)
            gen_c = gen_props.get(prop)
            if ref_c is not None or gen_c is not None:
                color_scores.append(_color_similarity(ref_c, gen_c))

        # Compare scalar properties
        scalar_scores = []
        for prop in ("Ns", "Ni", "d"):
            ref_v = ref_props.get(prop)
            gen_v = gen_props.get(prop)
            if ref_v is not None or gen_v is not None:
                scalar_scores.append(_float_similarity(ref_v, gen_v, tolerance=0.01))

        # Compare illum model (exact match)
        illum_score = 1.0
        ref_illum = ref_props.get("illum")
        gen_illum = gen_props.get("illum")
        if ref_illum is not None or gen_illum is not None:
            illum_score = 1.0 if ref_illum == gen_illum else 0.0

        all_scores = color_scores + scalar_scores + [illum_score]
        if all_scores:
            total_accuracy += sum(all_scores) / len(all_scores)
        else:
            total_accuracy += 1.0

    accuracy = total_accuracy / len(matched_lower)
    return coverage, accuracy


def compute_group_order_score(ref_groups, gen_groups):
    """Compare the ordering of groups using SequenceMatcher."""
    ref_names = [g["name"].lower() for g in ref_groups]
    gen_names = [g["name"].lower() for g in gen_groups]
    if not ref_names and not gen_names:
        return 1.0
    if not ref_names or not gen_names:
        return 0.0
    return SequenceMatcher(None, ref_names, gen_names).ratio()


# ---------------------------------------------------------------------------
# Task Class
# ---------------------------------------------------------------------------

class DomainObj3d(DomainBase):
    supports_visual = True

    def __init__(self, prompt_file="prompts/domain_documents.txt"):
        super().__init__(prompt_file)
        self.sample_type = "obj3d"
        self.summary = "Wavefront OBJ/MTL 3D models with vertices, faces, groups, and materials"
        self.description = "Wavefront OBJ 3D models"
        self.file_format = [".obj", ".mtl"]
        self.domain_parser = "custom"
        self.category = "creative"

    def parse_context(self, context):
        """Parse OBJ/MTL context (dict of filename->content) into a structured dict.

        Returns a dict with:
          - obj_parsed: result of parse_obj_content (or None if no .obj file)
          - materials: result of parse_mtl_content (or {} if no .mtl file)
          - obj_filename: name of the .obj file (or None)
          - mtl_filename: name of the .mtl file (or None)
        """
        obj_content = None
        mtl_content = None
        obj_filename = None
        mtl_filename = None
        for fn, content in context.items():
            if fn.lower().endswith(".obj"):
                obj_content = content
                obj_filename = fn
            elif fn.lower().endswith(".mtl"):
                mtl_content = content
                mtl_filename = fn

        result = {
            "obj_parsed": parse_obj_content(obj_content) if obj_content else None,
            "materials": parse_mtl_content(mtl_content) if mtl_content else {},
            "obj_filename": obj_filename,
            "mtl_filename": mtl_filename,
        }
        return result

    def compute_domain_statistics(self, context):
        """Compute domain-specific statistics from the OBJ/MTL context."""
        parsed = self.parse_context(context)
        stats = {}

        obj = parsed["obj_parsed"]
        if obj is not None:
            stats["Groups"] = len(obj["groups"])
            stats["Vertices"] = obj["vertex_count"]
            stats["Normals"] = obj["normal_count"]
            stats["Texcoords"] = obj["texcoord_count"]
            stats["Faces"] = obj["face_count"]
            if obj["mtllib"]:
                stats["MTL Libraries"] = len(obj["mtllib"])

        materials = parsed["materials"]
        if materials:
            stats["Materials"] = len(materials)

        return stats

    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}

        # Load reference context
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)

        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(
            os.path.join(sample_folder, start_state["solution_folder"])
        )

        # Parse both contexts using parse_context
        ref_parsed_ctx = self.parse_context(reference_context)
        gen_parsed_ctx = self.parse_context(generated_context)

        ref_parsed = ref_parsed_ctx["obj_parsed"]
        gen_parsed = gen_parsed_ctx["obj_parsed"]
        ref_materials = ref_parsed_ctx["materials"]
        gen_materials = gen_parsed_ctx["materials"]

        if ref_parsed is None:
            return {"error": "no_ref_obj", "score": 0.0}
        if gen_parsed is None:
            return {"error": "no_gen_obj", "score": 0.0}

        ref_groups = ref_parsed["groups"]
        gen_groups = gen_parsed["groups"]

        # Compute component scores
        group_coverage = compute_group_coverage(ref_groups, gen_groups)
        group_accuracy = compute_group_accuracy(ref_groups, gen_groups)
        vertex_accuracy = compute_vertex_accuracy(ref_groups, gen_groups)
        face_accuracy = compute_face_accuracy(ref_groups, gen_groups)
        mat_coverage, mat_accuracy = compute_material_accuracy(ref_materials, gen_materials)
        group_order = compute_group_order_score(ref_groups, gen_groups)

        # Combined material score
        material_score = 0.5 * mat_coverage + 0.5 * mat_accuracy

        # Final score formula:
        # group_coverage^2 * vertex_accuracy * face_accuracy * sqrt(mean(group_accuracy, material_score, group_order))
        auxiliary_mean = (group_accuracy + material_score + group_order) / 3.0
        score = (group_coverage ** 2) * vertex_accuracy * face_accuracy * math.sqrt(max(auxiliary_mean, 0.0))

        eval_obj = {
            "score": round(score, 4),
            "group_coverage": round(group_coverage, 4),
            "group_accuracy": round(group_accuracy, 4),
            "vertex_accuracy": round(vertex_accuracy, 4),
            "face_accuracy": round(face_accuracy, 4),
            "material_coverage": round(mat_coverage, 4),
            "material_accuracy": round(mat_accuracy, 4),
            "material_score": round(material_score, 4),
            "group_order": round(group_order, 4),
            "ref_groups": len(ref_groups),
            "gen_groups": len(gen_groups),
            "ref_vertices": ref_parsed["vertex_count"],
            "gen_vertices": gen_parsed["vertex_count"],
            "ref_faces": ref_parsed["face_count"],
            "gen_faces": gen_parsed["face_count"],
            "ref_materials": len(ref_materials),
            "gen_materials": len(gen_materials),
        }

        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

    def render_context_visual(self, context, outfile):
        """Render OBJ/MTL context to a PNG image using matplotlib 3D."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        import numpy as np

        parsed_ctx = self.parse_context(context)
        obj = parsed_ctx["obj_parsed"]
        if obj is None:
            return None
        materials = parsed_ctx["materials"]

        polygons = []
        face_colors = []
        all_verts = []
        default_color = (0.6, 0.6, 0.8)

        for group in obj["groups"]:
            verts = group["vertices"]
            mat_name = group["material"]
            color = default_color
            if mat_name and mat_name in materials:
                kd = materials[mat_name].get("Kd")
                if kd:
                    color = tuple(min(1.0, max(0.0, c)) for c in kd)

            for face in group["faces"]:
                poly = []
                for v_idx, _, _ in face:
                    if 1 <= v_idx <= len(verts):
                        poly.append(verts[v_idx - 1])
                if len(poly) >= 3:
                    polygons.append(poly)
                    face_colors.append(color)
            all_verts.extend(verts)

        if not polygons or not all_verts:
            return None

        all_verts = np.array(all_verts)
        fig = plt.figure(figsize=(6, 6), dpi=150)
        ax = fig.add_subplot(111, projection="3d")

        pc = Poly3DCollection(polygons, alpha=0.9, edgecolors="#333", linewidths=0.2)
        pc.set_facecolor(face_colors)
        ax.add_collection3d(pc)

        mins = all_verts.min(axis=0)
        maxs = all_verts.max(axis=0)
        center = (mins + maxs) / 2
        span = (maxs - mins).max() / 2 * 1.1
        if span == 0:
            span = 1.0
        ax.set_xlim(center[0] - span, center[0] + span)
        ax.set_ylim(center[1] - span, center[1] + span)
        ax.set_zlim(center[2] - span, center[2] + span)
        ax.set_axis_off()

        out_path = outfile + ".png"
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
        return out_path


if __name__ == "__main__":
    print("=" * 60)
    print("MESH EVALUATOR TESTS")
    print("=" * 60)

    # Test OBJ parsing
    test_obj = """# Test model
mtllib test.mtl
g box1
usemtl red
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 1.0 1.0 0.0
v 0.0 1.0 0.0
f 1 2 3
f 1 3 4
g box2
usemtl blue
v 2.0 0.0 0.0
v 3.0 0.0 0.0
v 3.0 1.0 0.0
v 2.0 1.0 0.0
f 5 6 7
f 5 7 8
"""
    parsed = parse_obj_content(test_obj)
    assert len(parsed["groups"]) == 2, f"Expected 2 groups, got {len(parsed['groups'])}"
    assert parsed["groups"][0]["name"] == "box1"
    assert parsed["groups"][0]["material"] == "red"
    assert len(parsed["groups"][0]["vertices"]) == 4
    assert len(parsed["groups"][0]["faces"]) == 2
    assert parsed["groups"][1]["name"] == "box2"
    assert parsed["groups"][1]["material"] == "blue"
    assert parsed["vertex_count"] == 8
    assert parsed["face_count"] == 4
    print("OBJ parse test: PASS")

    # Test face index localization
    g1_faces = parsed["groups"][0]["faces"]
    g2_faces = parsed["groups"][1]["faces"]
    # Group 1 faces should reference local indices 1-4
    for face in g1_faces:
        for v_idx, _, _ in face:
            assert 1 <= v_idx <= 4, f"Group 1 face index {v_idx} out of local range"
    # Group 2 faces should reference local indices 1-4 (remapped from global 5-8)
    for face in g2_faces:
        for v_idx, _, _ in face:
            assert 1 <= v_idx <= 4, f"Group 2 face index {v_idx} out of local range: {face}"
    print("Face index localization test: PASS")

    # Test MTL parsing
    test_mtl = """# Test materials
newmtl red
Ka 0.0 0.0 0.0
Kd 1.0 0.0 0.0
Ks 0.5 0.5 0.5
Ns 100.0
illum 2
newmtl blue
Ka 0.0 0.0 0.0
Kd 0.0 0.0 1.0
Ks 0.3 0.3 0.3
Ns 50.0
illum 1
"""
    materials = parse_mtl_content(test_mtl)
    assert len(materials) == 2
    assert "red" in materials
    assert "blue" in materials
    assert materials["red"]["Kd"] == (1.0, 0.0, 0.0)
    assert materials["blue"]["Kd"] == (0.0, 0.0, 1.0)
    assert materials["red"]["Ns"] == 100.0
    assert materials["blue"]["illum"] == 1
    print("MTL parse test: PASS")

    # Test self-evaluation (perfect match)
    assert compute_group_coverage(parsed["groups"], parsed["groups"]) == 1.0
    assert compute_group_accuracy(parsed["groups"], parsed["groups"]) == 1.0
    assert compute_vertex_accuracy(parsed["groups"], parsed["groups"]) == 1.0
    assert compute_face_accuracy(parsed["groups"], parsed["groups"]) == 1.0
    mc, ma = compute_material_accuracy(materials, materials)
    assert mc == 1.0 and ma == 1.0
    assert compute_group_order_score(parsed["groups"], parsed["groups"]) == 1.0
    print("Self-evaluation (perfect match) test: PASS")

    # Test with actual sample if it exists
    task = TaskObj3d()
    sample_dir = "samples/obj3d1/basic_state"
    if os.path.exists(sample_dir):
        ref_ctx = build_context_from_folder(sample_dir)
        target_state = {"state_id": "basic_state"}
        result = task.evaluate_context("obj3d1", ref_ctx, target_state)
        print(f"Self-eval score: {result.get('score')}")
        assert result.get("score") == 1.0, f"Self-eval not 1.0: {result}"
        print("Sample self-evaluation test: PASS")
    else:
        print("Sample not yet created; skipping sample self-eval test")

    # Test ablation: remove one group
    reduced_groups = parsed["groups"][:1]  # only box1
    cov = compute_group_coverage(parsed["groups"], reduced_groups)
    assert cov < 1.0, f"Coverage should drop, got {cov}"
    print(f"Ablation (remove 1/2 groups): coverage={cov:.2f}")

    # Test ablation: change material
    modified_mtl = dict(materials)
    modified_mtl["red"] = dict(materials["red"])
    modified_mtl["red"]["Kd"] = (0.0, 1.0, 0.0)  # green instead of red
    mc2, ma2 = compute_material_accuracy(materials, modified_mtl)
    assert ma2 < 1.0, f"Material accuracy should drop, got {ma2}"
    print(f"Ablation (change color): mat_accuracy={ma2:.2f}")

    print("\nAll tests passed!")
