# <img src="../assets/domain_icons/genealogy.svg" width="28" height="28" style="vertical-align: middle;"> Genealogy

**Category:** Structured Records
**File format:** `.ged`
**Summary:** GEDCOM family tree data with individuals, relationships, and events
**Work environments released:** 2 / 6

GEDCOM (Genealogical Data Communication) files encode family trees in a hierarchical tagged structure. Individual records contain names, gender, and vital events (birth, death); family records link spouses and children with marriage events; and cross-references establish relationship networks. This domain tests an LLM's ability to parse, transform, and reconstruct structured genealogical data — splitting family branches, converting between formats, normalizing names, and preserving the web of cross-references that ties individuals to families.

**Domain implementation:** [`domain_genealogy.py`](../domains/domain_genealogy.py)

---

## Evaluation

The genealogy domain evaluator parses GEDCOM files using python-gedcom and scores reconstruction quality across four dimensions:

- **Individual coverage** — Are all individuals present? (Jaccard similarity on name + birth year)
- **Individual accuracy** — Are fields (name, gender, birth/death dates and places) preserved correctly?
- **Relationship score** — Are family pairs (spouse links) and parent-child relationships intact?
- **Event score** — Are marriage dates and places preserved?

**Score formula:** `0.30 × individual_coverage × individual_accuracy + 0.35 × relationship + 0.20 × event + 0.15 × metadata`

---

## Example Work Environment: `genealogy5`

**Document:** Computer Science Scholars Genealogy
**Source:** [Academic Tree — CS](https://academictree.org/computerscience/tree.php?pid=184226) (CC-BY 3.0 License)
**Size:** 388 lines · 3,413 tokens

### Seed Document Excerpt (`cs_scholars.ged`)

```gedcom
0 HEAD
1 SOUR AcademicTree.org
2 NAME Academic Genealogy
1 DATE 03 FEB 2026
1 CHAR UTF-8
1 NOTE Academic Genealogy
1 GEDC
2 VERS 5.5.1
2 FORM LINEAGE-LINKED
0 @SUBM@ SUBM
1 NAME Academic Tree Parser
0 @I87513@ INDI
1 NAME Friedrich /JuliusRichelot/
2 GIVN Friedrich
2 SURN JuliusRichelot
1 EDUC Friedrich JuliusRichelotUniversität Königsberg (MathTree)
0 @I25615@ INDI
1 NAME Otto /Hesse/
2 GIVN Otto
2 SURN Hesse
1 EDUC Otto HesseTechnische Hochschule München (Physics Tree)
0 @I160728@ INDI
1 NAME Carl /GottfriedNeumann/
2 GIVN Carl
2 SURN GottfriedNeumann
1 EDUC Carl GottfriedNeumannUniversität Leipzig (MathTree)
0 @I25614@ INDI
1 NAME Carl Gustav /JacobJacobi/
2 GIVN Carl Gustav
2 SURN JacobJacobi
1 EDUC Carl Gustav JacobJacobi (MathTree)
0 @I160729@ INDI
1 NAME Wilhelm /Scheibner/
2 GIVN Wilhelm
2 SURN Scheibner
1 EDUC Wilhelm ScheibnerUniversität Leipzig (MathTree)
0 @I160727@ INDI
1 NAME William /EdwardStory/
2 GIVN William
2 SURN EdwardStory
1 EDUC William EdwardStoryClark University (MathTree)
0 @I160726@ INDI
1 NAME Solomon /Lefschetz/
2 GIVN Solomon
2 SURN Lefschetz
1 EDUC Solomon LefschetzPrinceton (MathTree)
0 @I757889@ INDI
1 NAME Henry /Wallman/
2 GIVN Henry
2 SURN Wallman
1 EDUC Henry WallmanMIT (MathTree)
```
<sup>Showing 50 of 388 lines. The full GEDCOM contains individual records for computer science scholars across multiple institutions, linked by advisor–student family records.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Institution Split** | Split by institution into separate GEDCOMs: `mit.ged`, `uc_berkeley.ged`, `princeton.ged`, `michigan.ged`, and `other.ged` for the rest. Create `advisor_links.csv` with columns student_id, advisor_id, student_file, advisor_file for cross-file advising. | Merge all institution files into `cs_scholars.ged`. Use `advisor_links.csv` to recreate FAM records across institutions. | split & merge, classification |
| 2 | **JSON Conversion** | Convert to `scholars.json` with array of objects: id, name, institution, advisor_id, student_ids. | Convert to GEDCOM `cs_scholars.ged`. Use IDs from JSON. Institution as EDUC, advisor-student as FAM (advisor=HUSB, student=CHIL). | format knowledge |
| 3 | **DOT Graph Export** | Convert `cs_scholars.ged` into `lineage.dot` (directed graph with nodes labeled "Name\nInstitution", edges from advisor to student) and `ged_metadata.json` (HEAD/SUBM blocks, individual fields, family records, individual order). | Convert `lineage.dot` and `ged_metadata.json` back into `cs_scholars.ged` in GEDCOM 5.5.1 format, reconstructing all blocks verbatim from the metadata. | format knowledge, referencing, numerical reasoning |
| 4 | **Generation Split** | Count academic generations from root advisors (no advisor themselves). Split into `gen1.ged`, `gen2.ged`, `gen3.ged`, etc. Create `edges.csv` with columns advisor_id, student_id, advisor_gen, student_gen. | Merge all generation files into `cs_scholars.ged`. Use `edges.csv` to recreate the cross-generation FAM records. | split & merge, classification, numerical reasoning |
| 5 | **Education Parsing** | Parse the EDUC fields (where person name is jammed with institution and optional tree source). Extract just the institution into EDUC, add level-2 `_TREE` tag with the tree annotation. Sort INDI records by institution alphabetically. Create `educ_raw.json` mapping each ID to raw EDUC string and position. | Set each INDI's EDUC to the raw string from `educ_raw.json`, drop `_TREE` sub-tags, reorder INDI records by their position value. Delete `educ_raw.json`. | string manipulation, sorting, referencing |
| 6 | **Name Normalization** | Fix concatenated name fields where SURN values have middle names glued to the surname. Split GIVN and SURN properly, update NAME to match. For records with empty names, extract from EDUC. Create `name_corrections.json` mapping each ID to pre-edit values. | Use `name_corrections.json` to restore each INDI's NAME, GIVN, SURN to recorded values. Entries with `was_empty` should have NAME set to empty and GIVN/SURN cleared. Delete `name_corrections.json`. | string manipulation, referencing |
