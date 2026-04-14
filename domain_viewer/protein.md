# <img src="../assets/domain_icons/protein.svg" width="28" height="28" style="vertical-align: middle;"> Protein

**Category:** Science &amp; Engineering
**File format:** `.pdb`
**Summary:** PDB protein structure files with atomic coordinates, sequence, and annotations
**Work environments released:** 6 / 6

PDB (Protein Data Bank) structure files use a fixed-width column format to represent macromolecular crystal structures. Each file contains header metadata (HEADER, TITLE, COMPND, SOURCE), sequence records (SEQRES), secondary structure annotations (HELIX, SHEET), disulfide bonds (SSBOND), crystallographic parameters (CRYST1, ORIGX, SCALE), and coordinate records (ATOM/HETATM) with per-atom positions, occupancies, and temperature factors. This domain tests an LLM's ability to manipulate structured scientific data — renumbering residues, splitting and merging coordinate sets, converting between formats, and performing arithmetic on crystallographic and B-factor values across hundreds of atom records.

**Domain implementation:** [`domain_protein.py`](../domains/domain_protein.py)

---

## Evaluation

The protein domain evaluator uses Biopython (`Bio.PDB.PDBParser`) for robust ATOM/HETATM parsing combined with lightweight custom parsers for annotation records, and scores reconstruction quality across seven dimensions:

- **Atom coverage** — Are all original atoms present? (Jaccard overlap on `(chainID, resSeq, resName, atomName)` fingerprints)
- **Coordinate accuracy** — Are atomic positions correct? (Average distance-based score for matched atoms; perfect ≤ 0.01 Å, zero at ≥ 2.0 Å)
- **B-factor accuracy** — Are temperature factors preserved? (Tolerance-based scoring; perfect ≤ 0.01, zero at ≥ 20.0 difference)
- **SEQRES score** — Are sequence records intact? (SequenceMatcher on per-chain residue sequences)
- **Secondary structure** — Are helix/sheet annotations preserved? (Jaccard on annotation sets)
- **Disulfide bonds** — Are SSBOND records correct? (Jaccard on normalized bond pairs)
- **Metadata** — Are crystallographic and header fields intact? (CRYST1 unit cell parameters, space group, resolution, header fields)

**Score formula:** `atom_coverage × (0.34 × coordinate + 0.13 × bfactor + 0.20 × seqres + 0.13 × secondary_structure + 0.07 × ssbond + 0.13 × metadata)`

---

## Example Work Environment: `protein1`

**Document:** Alpha-Conotoxin PNIA Crystal Structure
**Source:** [RCSB PDB 1PEN](https://files.rcsb.org/download/1PEN.pdb) (CC0-1.0 License)
**Size:** 149 lines · 5,226 tokens

### Seed Document Excerpt (`structure.pdb`)

```pdb
HEADER    NEUROTOXIN                              29-JAN-96   1PEN              
TITLE     ALPHA-CONOTOXIN PNI1                                                  
COMPND    MOL_ID: 1;                                                            
COMPND   2 MOLECULE: ALPHA-CONOTOXIN PNIA;                                      
COMPND   3 CHAIN: A;                                                            
COMPND   4 ENGINEERED: YES                                                      
SOURCE    MOL_ID: 1;                                                            
SOURCE   2 ORGANISM_SCIENTIFIC: CONUS PENNACEUS;                                
SOURCE   3 ORGANISM_TAXID: 37335                                                
KEYWDS    NEUROTOXIN, ACETYLCHOLINE RECEPTOR, POSTSYNAPTIC, ANTAGONIST,         
KEYWDS   2 ACETYLCHOLINE RECEPTOR INHIBITOR                                     
EXPDTA    X-RAY DIFFRACTION                                                     
AUTHOR    S.-H.HU,J.GEHRMANN,L.W.GUDDAT,P.F.ALEWOOD,D.J.CRAIK,J.L.MARTIN        
JRNL        AUTH   S.H.HU,J.GEHRMANN,L.W.GUDDAT,P.F.ALEWOOD,D.J.CRAIK,          
JRNL        AUTH 2 J.L.MARTIN                                                   
JRNL        TITL   THE 1.1 A CRYSTAL STRUCTURE OF THE NEURONAL ACETYLCHOLINE    
JRNL        TITL 2 RECEPTOR ANTAGONIST, ALPHA-CONOTOXIN PNIA FROM CONUS         
JRNL        TITL 3 PENNACEUS.                                                   
JRNL        REF    STRUCTURE                     V.   4   417 1996              
JRNL        REFN                   ISSN 0969-2126                               
JRNL        PMID   8740364                                                      
JRNL        DOI    10.1016/S0969-2126(96)00047-0                                
REMARK   2                                                                      
REMARK   2 RESOLUTION.    1.10 ANGSTROMS.                                       
SEQRES   1 A   17  GLY CYS CYS SER LEU PRO PRO CYS ALA ALA ASN ASN PRO          
SEQRES   2 A   17  ASP TYR CYS NH2                                              
HELIX    1   1 LEU A    5  ASN A   11  1                                   7    
SSBOND   1 CYS A    2    CYS A    8                          1555   1555  2.03  
SSBOND   2 CYS A    3    CYS A   16                          1555   1555  2.03  
LINK         C   CYS A  16                 N   NH2 A  17     1555   1555  1.32  
CRYST1   15.000   19.800   16.500  90.00 113.40  90.00 P 1 21 1      2          
ORIGX1      1.000000  0.000000  0.000000        0.00000                         
ORIGX2      0.000000  1.000000  0.000000        0.00000                         
ORIGX3      0.000000  0.000000  1.000000        0.00000                         
SCALE1      0.066667  0.000000  0.028849        0.00000                         
SCALE2      0.000000  0.050505  0.000000        0.00000                         
SCALE3      0.000000  0.000000  0.066037        0.00000                         
ATOM      1  N   GLY A   1      -4.788  -8.935   3.453  1.00 11.53           N  
ATOM      2  CA  GLY A   1      -4.218 -10.294   3.312  1.00  9.54           C  
ATOM      3  C   GLY A   1      -3.815 -10.534   1.870  1.00  8.53           C  
ATOM      4  O   GLY A   1      -4.276  -9.836   0.965  1.00  7.01           O  
ATOM      5  N   CYS A   2      -3.045 -11.594   1.654  1.00  7.14           N  
ATOM      6  CA  CYS A   2      -2.531 -11.945   0.337  1.00  7.39           C  
ATOM      7  C   CYS A   2      -3.485 -11.922  -0.844  1.00  7.12           C  
ATOM      8  O   CYS A   2      -3.228 -11.263  -1.853  1.00  6.44           O  
ATOM      9  CB  CYS A   2      -1.895 -13.333   0.377  1.00  7.78           C  
ATOM     10  SG  CYS A   2      -1.016 -13.752  -1.158  1.00  7.15           S  
ATOM     11  N   CYS A   3      -4.598 -12.627  -0.709  1.00  6.77           N  
ATOM     12  CA  CYS A   3      -5.522 -12.758  -1.819  1.00  5.78           C  
ATOM     13  C   CYS A   3      -6.265 -11.517  -2.287  1.00  6.25           C  
ATOM     14  O   CYS A   3      -6.832 -11.513  -3.382  1.00  8.04           O  
ATOM     15  CB  CYS A   3      -6.440 -13.958  -1.589  1.00  6.91           C  
ATOM     16  SG  CYS A   3      -5.492 -15.451  -1.114  1.00  7.26           S  
```
<sup>Showing 50 of 149 lines. The full PDB file contains 109 ATOM + 1 HETATM records for a 17-residue alpha-conotoxin (chain A), with 2 disulfide bonds, 1 helix, and crystallographic metadata at 1.10 Å resolution.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **0-Based Residue Renumbering** | Shift all residue sequence numbers to 0-based indexing. Make sure the HELIX, SSBOND, LINK, and TER records are updated to reflect the new numbering too. | Renumber all residues so numbering starts from 1 instead of 0. Update the HELIX, SSBOND, LINK, and TER annotation records to use the new residue numbers as well. | numerical reasoning |
| 2 | **Backbone/Sidechain Split** | Split the PDB into `backbone.pdb` (N, CA, C, O atoms for each residue, plus the terminal NH2 HETATM) and `sidechain.pdb` (all remaining atoms). `backbone.pdb` keeps all header and annotation records, `sidechain.pdb` gets just a CRYST1 record as header. Renumber atom serials from 1 in each file, and keep TER/END in both. | Merge `backbone.pdb` and `sidechain.pdb` into a single `structure.pdb`. For each residue, list backbone atoms first (N, CA, C, O) then sidechain atoms in standard PDB atom-name order, with one sequential serial numbering starting at 1. Keep all header and annotation records from `backbone.pdb`, drop the duplicate CRYST1 from `sidechain.pdb`. | split & merge, classification |
| 3 | **B-Factor Painting** | Replace all B-factor values with a feature code: 2.00 for residues in the alpha helix, 1.00 for cysteines in disulfide bonds not already in the helix, 0.00 for everything else. Store the original per-atom B-factors in a compact REMARK 900 lookup table (serial:value pairs, several per line). | Restore the original B-factors from the REMARK 900 lookup table into each ATOM/HETATM record, and remove the REMARK 900 section. | numerical reasoning, referencing, classification |
| 4 | **Sequence/Crystallographic Extraction** | Convert the SEQRES records to a FASTA file (`sequence.fasta`) — annotate any non-standard residues like NH2 in the FASTA header. Extract CRYST1, ORIGX/SCALE, and the REMARK 2 resolution line into `crystal_params.txt` with human-readable labels. Remove all extracted records from `structure.pdb`. | Merge `sequence.fasta` and `crystal_params.txt` into `structure.pdb`. Convert the one-letter sequence to SEQRES lines with three-letter residue codes (including non-standard residues from the FASTA header). Reconstruct CRYST1, ORIGX1-3, SCALE1-3, and REMARK 2 resolution record. Delete `sequence.fasta` and `crystal_params.txt`. | format knowledge, split & merge, context expansion |
| 5 | **B-Factor-Ranked TSV** | Split `structure.pdb` into two files: `atoms.tsv` with a header row and all ATOM/HETATM records as a tab-separated table (columns: record_type, serial, atom_name, res_name, chain_id, res_seq, x, y, z, occupancy, b_factor, element) sorted by B-factor descending, and `annotations.pdb` with all remaining records. Include a TER row at the end of the TSV with blank coordinate fields. | Reconstruct `structure.pdb` from `annotations.pdb` and `atoms.tsv`. Re-sort the atom rows by serial number, format each back into standard PDB fixed-width-column ATOM/HETATM records, and place them after the SCALE records. Add TER and END lines at the bottom. | split & merge, format knowledge, sorting |
| 6 | **Disulfide Loop Framework** | Create `framework_cysteines.pdb` with only the cysteine residues (Cys2, Cys3, Cys8, Cys16) and the two SSBOND records. Put loop 2 residues (Ser4 through Pro7) in `loop2.pdb`. Put loop 3 residues (Ala9 through Tyr15) in `loop3.pdb` with the HELIX record. Put terminal residues (Gly1, NH2 17) in `terminals.pdb` with the LINK record. Write an `assembly.txt` storing the residue-to-file mapping with original atom serial ranges, residue sequence order, and all header/crystallographic records verbatim. | Reassemble from the loop framework files into a single `structure.pdb`. Use `assembly.txt` to restore the original residue ordering, atom serial numbering, and all header/crystallographic records. Collect SSBOND, HELIX, and LINK records from their respective subfiles and place them in their standard PDB positions. | split & merge, classification, sorting |
