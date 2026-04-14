# <img src="../assets/domain_icons/molecule.svg" width="28" height="28" style="vertical-align: middle;"> Molecule

**Category:** Science & Engineering
**File format:** `.sdf`
**Summary:** MDL SDF molecule files with V2000 connection tables and data properties
**Work environments released:** 6 / 6

SDF (Structure-Data File) records use the [MDL V2000](https://en.wikipedia.org/wiki/Chemical_table_file#SDF) format for representing molecular structures. Each molecule record consists of a header, a connection table (atom coordinates, element types, and bonds), and optional data properties (e.g., compound IDs, SMILES, molecular weight). This domain tests an LLM's ability to manipulate chemical structure data — splitting multi-molecule files, reordering by computed properties, extracting and reinserting metadata, and converting between property naming conventions.

**Domain implementation:** [`domain_molecule.py`](../domains/domain_molecule.py)

---

## Evaluation

The molecule domain evaluator parses SDF files using RDKit and scores reconstruction quality across four dimensions:

- **Molecule coverage** — Are all reference molecules present? (Matches by PUBCHEM_COMPOUND_CID, then SMILES, then molecule name)
- **Structure accuracy** — Are molecular graphs correct? (Canonical SMILES comparison; Maximum Common Substructure fallback for partial credit)
- **Property accuracy** — Are SDF data properties preserved? (Key coverage 40% + value accuracy 60%, with numeric tolerance for floats)
- **Molecule order** — Are compounds in the correct sequence? (SequenceMatcher on identifier sequences)

**Score formula:** `coverage × (0.50 × structure + 0.35 × property + 0.15 × order)`

---

## Example Work Environment: `molecule1`

**Document:** PubChem Small Molecule Collection
**Source:** [PubChem (NCBI)](https://pubchem.ncbi.nlm.nih.gov/) (Public Domain — U.S. Government Work, NIH/NCBI)
**Size:** 254 lines · 4,896 tokens

### Seed Document Excerpt (`molecules.sdf`)

```sdf
18087
  -OEChem-02132612272D

 11 11  0     0  0  0  0  0  0999 V2000
    2.0000    0.8100    0.0000 Cl  0  0  0  0  0  0  0  0  0  0  0  0
    5.4641    0.8100    0.0000 Cl  0  0  0  0  0  0  0  0  0  0  0  0
    3.7321    1.8100    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
    3.7321   -1.1900    0.0000 N   0  0  0  0  0  0  0  0  0  0  0  0
    2.8660   -0.6900    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    4.5981   -0.6900    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    2.8660    0.3100    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    4.5981    0.3100    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    3.7321    0.8100    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    2.0000   -1.1900    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    5.4641   -1.1900    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
  1  7  1  0  0  0  0
  2  8  1  0  0  0  0
  3  9  2  0  0  0  0
  4  5  1  0  0  0  0
  4  6  1  0  0  0  0
  5  7  2  0  0  0  0
  5 10  1  0  0  0  0
  6  8  2  0  0  0  0
  6 11  1  0  0  0  0
  7  9  1  0  0  0  0
  8  9  1  0  0  0  0
M  END
> <PUBCHEM_COMPOUND_CID>
18087

> <PUBCHEM_CACTVS_HBOND_ACCEPTOR>
2

> <PUBCHEM_CACTVS_HBOND_DONOR>
1

> <PUBCHEM_IUPAC_OPENEYE_NAME>
3,5-dichloro-2,6-dimethyl-1H-pyridin-4-one

> <PUBCHEM_XLOGP3_AA>
2.6

> <PUBCHEM_EXACT_MASS>
190.9904692

> <PUBCHEM_MOLECULAR_FORMULA>
C7H7Cl2NO

> <PUBCHEM_MOLECULAR_WEIGHT>
192.04

> <PUBCHEM_SMILES>
CC1=C(C(=O)C(=C(N1)C)Cl)Cl
```
<sup>Showing first molecule record (Clopidol, CID 18087) of 4. The full SDF contains 4 PubChem compounds: Clopidol, Carvone, Diuron, and DEET, each with a V2000 connection table and 10–11 data properties.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Per-compound Split** | Split `molecules.sdf` into individual SDF files for docking prep — one file per compound, named by CID like `CID_18087.sdf`. Also create `library_index.csv` with columns `order,cid,name,formula`, listing the compounds in their current sequence. | Merge the individual `CID_*.sdf` files referenced by `library_index.csv` into a single `molecules.sdf` file. Use `library_index.csv` to order the compounds by the `order` column, then delete `library_index.csv`. | split & merge, format knowledge, sorting |
| 2 | **MW Ranking** | Sort the SDF by molecular weight ascending for SAR ranking. Annotate each mol block's comment line with its MW rank and current file position, formatted like `MW Rank 1/4 \| entry #2`. | Reorder compounds by their entry # tags (ascending) and clear all annotations from the comment lines. | numerical reasoning, sorting |
| 3 | **Functional Class Split** | Split `molecules.sdf` into two files by functional class — put the agricultural chemicals (Clopidol and Diuron) into `agricultural.sdf`, and the consumer-use chemicals (Carvone and DEET) into `consumer.sdf`. Also generate a `classification.txt` manifest listing each compound's CID, class, and its record position from the source file. | Combine `agricultural.sdf` and `consumer.sdf` into a single `molecules.sdf`, ordering the compounds according to the source positions listed in `classification.txt`. Drop the two class files and the classification manifest. | split & merge, classification, sorting |
| 4 | **Property Key Standardization** | Rename the PUBCHEM_ property keys to shorter standardized names (e.g., PUBCHEM_COMPOUND_CID → CID, PUBCHEM_MOLECULAR_WEIGHT → MW). Reorder properties within each molecule by category: identification first, then physical, then computed descriptors. Write a `property_mapping.txt` listing each long→short mapping with its category and position number. | Expand the short property keys in the SDF to their full PUBCHEM_ names using the mapping in `property_mapping.txt`, and reorder the fields according to the position numbers listed in that file. Drop `property_mapping.txt`. | string manipulation, sorting |
| 5 | **Property Table Split** | Extract all SDF data properties into a separate `properties.csv` with columns `CID,Property,Value` — one row per property per compound, preserving property order. Strip the data blocks from `molecules.sdf` so it contains only connection tables and `$$$$` delimiters. | Merge `properties.csv` back into `molecules.sdf` — for each compound, re-insert the data properties as SDF data field blocks after `M  END`, in CSV order. Remove `properties.csv`. | split & merge, format knowledge |
| 6 | **TPSA / Lipinski Sorting** | Sort the molecules by TPSA descending for oral absorption screening. Add a `DRUG_LIKENESS` property to each molecule block evaluating Lipinski Rule of Five — check MW<500, HBD≤5, HBA≤10, LogP<5. Mark each criterion PASS or FAIL with the value in parentheses, or N/A if missing. Include the compound's entry position. | Reorder the molecules by their entry position number ascending as listed in the `DRUG_LIKENESS` annotation, then remove the `DRUG_LIKENESS` property from every molecule block. | numerical reasoning, sorting, constraint satisfaction |
