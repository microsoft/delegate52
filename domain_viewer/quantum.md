# <img src="../assets/domain_icons/quantum.svg" width="28" height="28" style="vertical-align: middle;"> Quantum

**Category:** Science &amp; Engineering
**File format:** `.qasm`
**Summary:** OpenQASM 3.0 quantum circuits with subroutines, constants, qubit registers, and gate operations
**Work environments released:** 6 / 6

OpenQASM 3.0 quantum circuit files describe quantum error correction programs using the [OpenQASM](https://openqasm.com/) specification. Each program consists of qubit register declarations, constant definitions, extern classical function declarations, gate definitions, and subroutines implementing quantum algorithms. This domain tests an LLM's ability to manipulate structured quantum programs — splitting into modules, extracting documentation, refactoring subroutines, renaming constants, merging registers, and reordering definitions while preserving circuit semantics.

**Domain implementation:** [`domain_quantum.py`](../domains/domain_quantum.py)

---

## Evaluation

The quantum domain evaluator parses OpenQASM 3.0 programs into AST-based structured representations and scores reconstruction quality across five dimensions:

- **Subroutine accuracy** (65%) — Are all subroutines present with correct signatures, body content, and gate operation sequences? (Missing subroutines score 0; combines signature similarity, body SequenceMatcher, and gate sequence matching)
- **Constant accuracy** (10%) — Are named constants preserved with correct values? (Name-based F1 with value matching)
- **Qubit declaration accuracy** (10%) — Are qubit registers declared with correct names and sizes?
- **Extern declaration accuracy** (10%) — Are extern function declarations preserved with correct signatures?
- **Gate definition accuracy** (5%) — Are custom gate definitions present with correct parameters and bodies?

**Score formula:** `weighted_sum × multiplier` (multiplicative penalties when major sections are completely absent: subroutines ×0.2, constants ×0.6, qubit declarations ×0.7)

---

## Example Work Environment: `quantum1`

**Document:** Rotated Surface Code QEC (d=3, Shor Syndrome Measurement)
**Source:** [unitaryfoundation/ucc-ft](https://github.com/unitaryfoundation/ucc-ft) (AGPL-3.0 License)
**Size:** 285 lines · 2,366 tokens

### Seed Document Excerpt (`rotated_surface_code.qasm`)

```qasm
// Rotated surface code gadgets written in QASM
OPENQASM 3.0;
include "stdgates.inc";

////////////////////////////////////////////////////////////////////////////////
// Conventions
// For the rotated surface code, we follow the convention in the Julia sample code.
// The qubits are laid out on a grid, where qubits are numbered in row major order,
// and start with $X$ stabilizer in the top-left plaquette. The layout for
// the $d=3$ code is below:
// ---
//          Z
//     q0 •───• q1 ──• q2
//        │ X │  Z   |    X
//     q3 •───• q4 ──• q5
//  X     │ Z │  X   |
//     q6 •───• q7 ──• q8
//                 Z
// ---
//
// Note that rotating the above layout by 90 degrees swaps X and Z stabilizers

////////////////////////////////////////////////////////////////////////////////
// Code parameters
const uint d = 3;
const uint data_size = d * d;
const uint cat_size = d+1;
const uint verify_size = 1;
const uint num_syndromes = (d*d-1)/2;

////////////////////////////////////////////////////////////////////////////////
// Quantum state registers - QASM3 spec requires these be defined as globals
// TODO -- Rewrite with qubits as d x d grid versus flattened register
qubit[data_size] state; // the logical qubit
qubit[cat_size] cat;    // qubits prepared in cat state for syndrome measurement
qubit verify;           // used to FT verify cat state preparation

////////////////////////////////////////////////////////////////////////////////
//  State Preparation
//  The "standard" state preparation where stabilizers are repeatedly measured
//  until the state stabilizes. Afterwards, the code state is corrected in to
//  the logical-0 state based on the MWPM matched error.


////////////////////////////////////////////////////////////////////////////////
// External classical subroutines

// Calls into a classical MWPM function to determine if error occurred
// Takes in distance, syndrome measurement outcomes and returns whether to apply correction for that syndrome
extern mwpm_full_x(uint, bit[num_syndromes]) -> bit[data_size];
extern mwpm_full_z(uint, bit[num_syndromes], bit) -> bit[data_size];
```
<sup>Showing 50 of 285 lines. The full program contains 5 constants, 3 qubit registers, 3 extern declarations, and 5 subroutines implementing cat state preparation, X/Z stabilizer measurement, logical-Z measurement, and state preparation.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Modular Code Split** | Split this into modules for the team — `qec_declarations.qasm` for constants, qubit registers, and externs (keep the ASCII qubit layout comment there), `syndrome_extraction.qasm` for prepare_cat and all the stabilizer/logical-Z measurement defs, `state_preparation.qasm` for prepare_state. Main `rotated_surface_code.qasm` should just have the OpenQASM version, stdgates, and includes for the three modules in dependency order. | Combine all the QASM modules into a single `rotated_surface_code.qasm`, inline each include. | split & merge, classification |
| 2 | **Documentation Extraction** | Pull out the qubit layout ASCII art, stabilizer indexing convention, rotate() explanation, Shor syndrome measurement overview, and extern function docs into a `surface_code_geometry.md` reference. Write the stabilizer index formulas in LaTeX math. Replace those comment blocks with cross-references to the md file. | Inline all the documentation from `surface_code_geometry.md` back into `rotated_surface_code.qasm` as comment blocks — ASCII layout and conventions at the top, extern docs above extern declarations, stabilizer measurement overview above the measurement defs. Delete `surface_code_geometry.md`. | context expansion, format knowledge |
| 3 | **Measurement Refactoring** | The three measurement subroutines (`rotated_surface_z_m`, `rotated_surface_x_m`, `rotated_surface_lz_m`) all end with the same cat-parity extraction loop — H, measure, H, XOR over the cat register. Extract it into a subroutine `measure_cat_parity(uint num_qubits) -> bit` and call it from all three. | Inline `measure_cat_parity` into its three call sites in `rotated_surface_z_m`, `rotated_surface_x_m`, and `rotated_surface_lz_m`, then remove the definition. | format knowledge |
| 4 | **Named Boundary Constants** | The stabilizer measurement subroutines use `(d-1)/2` and `d*(d-1)/2` repeatedly. Define named constants — `stabs_per_col` for `(d-1)/2`, `inside_end` for `d*(d-1)/2` — alongside the other code parameters, then use them throughout `rotated_surface_z_m` and `rotated_surface_x_m`. | Inline the named boundary constants `stabs_per_col` and `inside_end` back to their raw expressions `(d-1)/2` and `d*(d-1)/2` everywhere they appear in the measurement subroutines, and remove their const declarations from the code parameters section. | string manipulation, numerical reasoning |
| 5 | **Register Unification** | Merge the three qubit registers (`state`, `cat`, `verify`) into one flat register `qubit[data_size + cat_size + verify_size] qreg`. Define offset constants `STATE_OFFSET`, `CAT_OFFSET`, `VERIFY_OFFSET` and update every qubit reference to use offset-based access into `qreg`. Save the register-to-offset-to-size mapping in `register_mapping.txt`. | Split `qreg` back into separate named registers using `register_mapping.txt`. Replace all offset-indexed references with named register access, remove the offset constants. Delete `register_mapping.txt`. | split & merge, string manipulation, referencing |
| 6 | **Alphabetical Reordering** | Reorder all subroutine definitions alphabetically by name. Add a comment header before each documenting call dependencies using `// @calls:` and `// @calledby:` tags. Keep all non-subroutine code in place. Write the pre-reorder subroutine sequence to `original_order.txt`, one name per line. | Restore the subroutine definitions to the ordering listed in `original_order.txt`. Strip all `// @calls:` and `// @calledby:` annotation lines from the subroutine headers. Delete `original_order.txt`. | sorting, context expansion |
