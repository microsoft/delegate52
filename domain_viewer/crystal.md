# <img src="../assets/domain_icons/crystal.svg" width="28" height="28" style="vertical-align: middle;"> Crystal

**Category:** Science & Engineering
**File format:** `.cif`
**Summary:** CIF crystallographic data with cell parameters, symmetry, atoms, and geometry
**Work environments released:** 3 / 6

CIF (Crystallographic Information File) documents describe crystal structures in a standardized text format maintained by the International Union of Crystallography. Each file contains a data block with unit cell parameters, space group symmetry, fractional atomic coordinates, displacement parameters, and interatomic geometry tables. This domain tests an LLM's ability to manipulate scientific crystallographic data — converting coordinate systems, expanding symmetry, migrating format versions, and transforming between CIF and other crystallography formats.

**Domain implementation:** [`domain_crystal.py`](../domains/domain_crystal.py)

---

## Evaluation

The crystal domain evaluator parses CIF blocks into structured representations using the `PyCifRW` library and scores reconstruction quality across eight weighted dimensions:

- **Cell parameters (5%)** — Are unit cell lengths (a, b, c) and angles (α, β, γ) preserved?
- **Symmetry (5%)** — Are space group name and symmetry operations correct?
- **Atom sites (30%)** — Are fractional coordinates, element types, occupancy, and thermal parameters accurate?
- **Anisotropic parameters (10%)** — Are displacement parameter tensors (U₁₁–U₂₃) preserved?
- **Bonds (20%)** — Are bond lengths and atom pair labels correct?
- **Angles (10%)** — Are bond angles and atom triplet labels correct?
- **Hydrogen bonds (10%)** — Are H-bond geometry (D–H···A distances, angles) intact?
- **Metadata (10%)** — Are formula, authors, and journal references preserved?

Geometry-dependent scores (aniso, bonds, angles, H-bonds) are scaled by atom recall to prevent artificially high scores when atoms are missing.

**Score formula:** linear weighted sum

---

## Example Work Environment: `crystal1`

**Document:** Cu(oxalurate) Complex (COD 4318422)
**Source:** [cod-developers/cod-tools](https://github.com/cod-developers/cod-tools) (Public Domain — COD)
**Size:** 285 lines · 4,492 tokens

### Seed Document Excerpt (`cu_oxalurate.cif`)

```
data_4318422
loop_
_publ_author_name
'Larry R. Falvello'
'Raquel Garde'
'Milagros Tom\'as'
_publ_section_title
;
 Flexible Square Supramolecular Rings with Hydrogen-Bonded Bushing in
 Solid-State Oxalurate Complexes: Versatility of the Oxalurate Ligand in
 Covalent and Noncovalent Binding
;
_journal_name_full               'Inorganic Chemistry'
_journal_page_first              4599
_journal_page_last               4604
_journal_volume                  41
_journal_year                    2002
_chemical_formula_sum            'C6 H14 Cu N4 O12'
_chemical_formula_weight         397.75
_chemical_name_systematic
; 
 ? 
;
_space_group_IT_number           2
_symmetry_cell_setting           triclinic
_symmetry_space_group_name_Hall  '-P 1'
_symmetry_space_group_name_H-M   'P -1'
_atom_sites_solution_hydrogens   difmap
_atom_sites_solution_primary     direct
_atom_sites_solution_secondary   difmap
_audit_creation_method           SHELXL-97
_cell_angle_alpha                72.69(2)
_cell_angle_beta                 83.39(2)
_cell_angle_gamma                71.266(16)
_cell_formula_units_Z            1
_cell_length_a                   5.2584(8)
_cell_length_b                   6.8332(15)
_cell_length_c                   10.314(2)
_cell_measurement_temperature    148(2)
_cell_volume                     334.99(12)
_computing_cell_refinement       'CAD4/PC V2.0 (Nonius, 1996)'
_computing_data_collection       'CAD4/PC V2.0 (Nonius, 1996)'
_computing_data_reduction        'XCAD4 (Harms, 1996)'
_computing_molecular_graphics    'SHELXTL Rel. 5.05/V (Siemens, 1996)'
_computing_publication_material  'SHELXL-97 (Sheldrick, 1997)'
_computing_structure_refinement  'SHELXL-97 (Sheldrick, 1997)'
_computing_structure_solution    'SHELXS-97 (Sheldrick, 1990)'
```
<sup>Showing 46 of 285 lines. The full CIF contains unit cell parameters, P −1 symmetry, 17 atom sites with anisotropic displacement parameters, bond lengths, bond angles, and hydrogen bond geometry for a copper(II) oxalurate complex.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Cartesian Conversion** | Convert fractional coordinates (_atom_site_fract_x/y/z) to Cartesian (_atom_site_Cartn_x/y/z), to 4 decimal places. Keep everything else unchanged. | Convert Cartesian coordinates back to fractional (_atom_site_fract_x/y/z), to 5 decimal places with ESDs where originally present. | numerical reasoning |
| 2 | **P1 Expansion** | Expand from P -1 to P 1 by applying symmetry operations. Create copies with '_i' suffixed labels. Update symmetry settings to P 1. | Collapse P 1 back to P -1 by removing all atoms with '_i' labels and their aniso entries. Restore P -1 symmetry settings and operations. | domain knowledge, context expansion |
| 3 | **CIF2 Migration** | Convert CIF1 to CIF2: use dot-separated tag names (e.g., _atom_site.label), triple-quote delimiters, and add audit.schema. | Convert CIF2 back to CIF1: underscore-separated tag names, single-quote delimiters, remove audit.schema. Keep all data identical. | format knowledge, string manipulation |
| 4 | **Structure Split** | Split CIF into structure.cif (cell, symmetry, atoms, aniso, scattering factors, metadata) and geometry.cif (bond, angle, H-bond loops). | Merge structure.cif and geometry.cif into cu_oxalurate.cif. Order: metadata, symmetry, atoms, aniso, scattering factors, bonds, angles, H-bonds. | split & merge |
| 5 | **Atom Relabeling** | Relabel all atoms with sequential numbering by element in order of appearance. Propagate label changes through all loops. | Relabel hydrogens to reflect parent atoms (H1→H1, H2→H2A, H2B, H5→H5A, H5B, H6→H6A, H6B). Update all loops consistently. | string manipulation |
| 6 | **SHELX Conversion** | Convert CIF to SHELX .res format. Use LATT 1 for P -1, SFAC order C H Cu N O. Encode full occupancy as 11, use U_iso for Uiso. | Convert SHELX .res back to CIF format. Create standard CIF loops for atom_site, symmetry, atom_type. Derive formula from UNIT card. | format knowledge, domain knowledge |
