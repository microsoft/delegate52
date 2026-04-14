# <img src="../assets/domain_icons/obj3d.svg" width="28" height="28" style="vertical-align: middle;"> Obj3d

**Category:** Creative & Media
**File format:** `.obj`, `.mtl`
**Summary:** Wavefront OBJ/MTL 3D models with vertices, faces, groups, and materials
**Work environments released:** 6 / 6

Wavefront OBJ files define 3D geometry using vertices, faces, groups, and material references, while companion MTL files specify material properties (diffuse/specular colors, shininess, illumination model). This domain tests an LLM's ability to manipulate structured 3D model data — splitting and merging geometry by material or component, converting between formats, computing normals, renumbering vertex indices, and reasoning about bounding-box arithmetic across groups and materials.

**Domain implementation:** [`domain_obj3d.py`](../domains/domain_obj3d.py)

---

## Evaluation

The obj3d domain evaluator parses OBJ files into groups with per-group local vertices, faces, and material assignments, and MTL files into material-name → property dictionaries. Reconstruction quality is scored across six dimensions:

- **Group coverage** — Are all original groups present? (Jaccard similarity on case-insensitive group names)
- **Group accuracy** — Do matched groups have the correct material (40%), vertex count (30%), and face count (30%)?
- **Vertex accuracy** — Are vertex positions preserved? (Nearest-neighbor matching within groups with distance tolerance)
- **Face accuracy** — Are face index tuples correct? (Set comparison with reversed winding support)
- **Material accuracy** — Are material properties preserved? (Color similarity + scalar property matching + illum exact match)
- **Group order** — Is the group ordering maintained? (SequenceMatcher on group name sequences)

**Score formula:** `group_coverage² × vertex_accuracy × face_accuracy × √(mean(group_accuracy, material_score, group_order))`

---

## Example Work Environment: `obj3d1`

**Document:** Art of Illusion Fireplace
**Source:** [ralic/sweethome-3d](https://github.com/ralic/sweethome-3d/tree/master/3DModels/contributions/contributions/fireplace2) (Free Art License 1.3)
**Size:** 440 lines · 4,276 tokens

### Seed Document Excerpt (`fireplace.obj`)

```obj
#Produced by Art of Illusion 2.7.2, Wed Nov 11 17:45:28 PST 2009
mtllib fireplace.mtl
s 0
g hearth
usemtl bricks
v -2.345 -0.485 0.6
v 2.455 -0.485 0.6
v 2.455 -0.485 -0.9
v -2.345 -0.485 -0.9
v -2.345 -0.385 0.6
v 2.455 -0.385 0.6
v 2.455 -0.385 -0.9
v -2.345 -0.385 -0.9
v 0.055 -0.435 0.6
v 2.455 -0.435 -0.15
v 0.055 -0.435 -0.9
v -2.345 -0.435 -0.15
v 0.055 -0.485 -0.15
v 0.055 -0.385 -0.15
f 2 1 13
f 3 2 13
f 4 3 13
f 1 4 13
f 2 3 10
f 3 7 10
f 7 6 10
f 6 2 10
f 1 2 9
f 2 6 9
f 6 5 9
f 5 1 9
f 4 1 12
f 1 5 12
f 5 8 12
f 8 4 12
f 5 6 14
f 6 7 14
f 7 8 14
f 8 5 14
f 3 4 11
f 4 8 11
f 8 7 11
f 7 3 11
s 0
g left_sdie
usemtl bricks
v -2.34 -0.395 -0.87
v -1.44 -0.395 -0.87
v -1.44 -0.395 -0.97
v -2.34 -0.395 -0.97
v -2.34 2.405 -0.87
v -1.44 2.405 -0.87
v -1.44 2.405 -0.97
v -2.34 2.405 -0.97
v -1.89 1.005 -0.87
```
<sup>Showing 50 of 413 lines. The full model contains 10 named groups (hearth, left_sdie, right_side, top_brass, bottom_brass, gray, middle_brass, right_white_trim, top_white_trim, mantle), 140 vertices, and 240 triangular faces.</sup>

### Seed Document Excerpt (`fireplace.mtl`)

```mtl
#Produced by Art of Illusion 2.7.2, Wed Nov 11 17:45:28 PST 2009
newmtl darkgray
Kd 0.41 0.41 0.4
Ks 0 0 0
Ka 0 0 0
illum 1
newmtl brass
Kd 0.83 0.7 0
Ks 1 1 1
Ka 0 0 0
illum 2
Ns 129
newmtl Default_Texture
Kd 1 1 1
Ks 0 0 0
Ka 0 0 0
illum 1
newmtl bricks
Kd 0.6 0.23 0.23
Ks 0 0 0
Ka 0 0 0
illum 1
newmtl white
Kd 1 1 1
Ks 1 1 1
Ka 0 0 0
illum 2
Ns 129
```
<sup>5 materials: bricks, brass, darkgray, Default_Texture, white — with varying illumination models (illum 1 matte, illum 2 glossy).</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Material Split** | Split the fireplace OBJ into separate OBJ files grouped by material, named after the material. Keep the MTL file as-is. Also create a manifest.txt listing each group name and its file, in the same order the groups appear in the OBJ, so they can be reassembled later. | Merge all the per-material OBJ files back into a single fireplace.obj using the group order from manifest.txt. Remove manifest.txt since it's no longer needed. | split & merge, classification, sorting |
| 2 | **JSON Conversion** | Convert the OBJ and MTL into a single JSON file called fireplace.json — use top-level keys for metadata, materials, and groups (each with name, material, vertices as coordinate arrays, faces as index arrays). Remove the OBJ and MTL files. | Convert fireplace.json back into standard OBJ and MTL files — fireplace.obj and fireplace.mtl. Remove the JSON file. | format knowledge |
| 3 | **Component Merge** | Reorganize the fireplace by merging individual parts into functional components: left/right sides → firebox, brass/gray/right_white_trim → decorative_trim, hearth → base, mantle + top_white_trim → shelf. Add `# [source: groupname]` comments before each subpart's vertices. Create a component_map.csv documenting each group name, its new component, material, and position order. | Split into the individual part groups from component_map.csv, in the CSV's position order. The `# [source: ...]` comments mark the subgroup boundaries. Remove component_map.csv and the marker comments. | split & merge, classification, sorting |
| 4 | **Normal Generation** | Calculate a face normal for every triangular face. Within each group, deduplicate identical normals and add `vn` lines after vertex blocks. Update faces from `f v v v` to `f v//vn v//vn v//vn`. Sort all groups alphabetically and write the ordering to group_order.txt. | Remove all vn lines and convert faces from `f v//vn v//vn v//vn` to plain `f v v v`. Reorder groups per group_order.txt, then delete that file. | numerical reasoning, string manipulation, sorting |
| 5 | **PBR Upgrade** | Upgrade materials to PBR: rename (bricks → rough_brick, brass → polished_brass, etc.), add Ni, d, Ke properties, adjust Ns per roughness, set illum 2 for all. Save a material_mapping.csv with original and PBR properties. | Simplify materials using material_mapping.csv: rename to original names, restore original Kd/Ks/Ka/illum/Ns values, strip Ni/d/Ke lines. Delete material_mapping.csv. | string manipulation, referencing |
| 6 | **Inventory Sort** | Create parts_inventory.csv (bounding boxes, dimensions per group) and material_summary.csv. Reorder groups by bounding-box volume ascending, add `# inventory_order: N` comments preserving original positions. | Reorder groups by inventory_order comments, remove those comment lines, and delete both CSV files. | numerical reasoning, sorting, context expansion |
