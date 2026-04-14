# <img src="../assets/domain_icons/circuit.svg" width="28" height="28" style="vertical-align: middle;"> Circuit

**Category:** Science & Engineering
**File format:** `.cir`
**Summary:** SPICE circuit netlists with subcircuits, elements, models, and simulation directives
**Work environments released:** 4 / 6

SPICE netlists define electronic circuits in a text-based format with component declarations, subcircuit hierarchies, model references, and simulation directives. Each netlist consists of element lines (MOSFETs, resistors, capacitors), hierarchical subcircuit definitions, voltage/current sources for test stimuli, and analysis commands (`.tran`, `.ac`, `.dc`). This domain tests an LLM's ability to manipulate hierarchical circuit descriptions — splitting, merging, refactoring transistor parameters, and performing technology-aware transformations across complex VLSI designs.

**Domain implementation:** [`domain_circuit.py`](../domains/domain_circuit.py)

---

## Evaluation

The circuit domain evaluator parses netlists into structured representations using `spicelib` and scores reconstruction quality across multiple dimensions:

- **Subcircuit coverage** — Are all subcircuit definitions present? (F1-based matching)
- **Port accuracy** — Are subcircuit port lists correct?
- **Element accuracy** — Are internal MOSFET/component declarations preserved?
- **Instance accuracy** — Are top-level X-line instantiations correct?
- **Source accuracy** — Are voltage/current source definitions intact?
- **Parameter accuracy** — Are `.param` definitions preserved?

Additional scores for control blocks (5%) and directives (5%) use SequenceMatcher. Multiplicative penalties apply when major sections are entirely missing (×0.3 subcircuits, ×0.4 instances, ×0.7 sources).

**Score formula:** `weighted_sum × multiplier`

---

## Example Work Environment: `circuit1`

**Document:** 4-Bit Ripple Carry Adder with Flip-Flops (TSMC 180nm)
**Source:** [aravind-3105/VLSI-Project](https://github.com/aravind-3105/VLSI-Project) (MIT License)
**Size:** 276 lines · 4,476 tokens

### Seed Document Excerpt (`ripple_adder_ff.cir`)

```spice
* 4-Bit Ripple Carry Adder with D Flip-Flops (TSMC 180nm)
.include TSMC_180nm.txt
.param SUPPLY=1.8
.param LAMBDA=0.09u
.param width_N={20*LAMBDA}
.param width_P={40*LAMBDA}
.global gnd vdd

Vdd     vdd     gnd     'SUPPLY'
vd10     a1_d     0 pulse 1.8 0 0ns 100ps 100ps 5ns  30ns
vd_bar10 a1_d_bar 0 pulse 0 1.8 0ns 100ps 100ps 5ns  30ns

vd20    b1_d     0 pulse 1.8 0 0ns 100ps 100ps 10ns  30ns
vd_bar20 b1_d_bar 0 pulse 0 1.8 0ns 100ps 100ps 10ns  30ns

vd11     a2_d     0 pulse 1.8 0 0ns 100ps 100ps 5ns  30ns
vd_bar11 a2_d_bar 0 pulse 0 1.8 0ns 100ps 100ps 5ns  30ns

vd21     b2_d     0 pulse 1.8 0 0ns 100ps 100ps 10ns  30ns
vd_bar21 b2_d_bar 0 pulse 0 1.8 0ns 100ps 100ps 10ns  30ns

vd12     a3_d     0 pulse 1.8 0 0ns 100ps 100ps 5ns  30ns
vd_bar12 a3_d_bar 0 pulse 0 1.8 0ns 100ps 100ps 5ns  30ns

vd22     b3_d     0 pulse 1.8 0 0ns 100ps 100ps 10ns  30ns
vd_bar22 b3_d_bar 0 pulse 0 1.8 0ns 100ps 100ps 10ns  30ns

vd13     a4_d     0 pulse 1.8 0 0ns 100ps 100ps 5ns  30ns
vd_bar13 a4_d_bar 0 pulse 0 1.8 0ns 100ps 100ps 5ns  30ns

vd23     b4_d     0 pulse 1.8 0 0ns 100ps 100ps 10ns  30ns
vd_bar23 b4_d_bar 0 pulse 0 1.8 0ns 100ps 100ps 10ns  30ns

vd3 ci1 0 pulse 0 0 0ns 100ps 100ps 20ns 60ns



vclk   clk   0 pulse 0   1.8 0ns 100ps 100ps 20ns  40ns
vclk_bar clk_bar 0 pulse 1.8 0 0ns 100ps 100ps 20ns  40ns


.subckt xor_subckt a b y vdd gnd
*Top inverter
M1      a_bar       a       vdd     vdd  CMOSP   W={width_P}   L={2*LAMBDA}
+ AS={5*width_P*LAMBDA} PS={10*LAMBDA+2*width_P} AD={5*width_P*LAMBDA} PD={10*LAMBDA+2*width_P}
M2      a_bar       a       gnd     gnd  CMOSN   W={width_N}   L={2*LAMBDA}
+ AS={5*width_N*LAMBDA} PS={10*LAMBDA+2*width_N} AD={5*width_N*LAMBDA} PD={10*LAMBDA+2*width_N}
```
<sup>Showing 47 of 276 lines. The full netlist defines 7 subcircuits (XOR, NAND, NOR, half-adder, full-adder, D-latch, D-flip-flop), 4-bit adder instances, and simulation setup.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Library Extraction** | Pull out all subcircuit definitions into a separate `cell_library.cir` and add `.include cell_library.cir` to the main netlist. | Inline `cell_library.cir` into the main netlist at the `.include` line so everything is in a single file. Remove `cell_library.cir`. | split & merge |
| 2 | **Sim Extraction** | Move simulation setup (`.tran`, `.ic`, `.control`/`.endc`) into a separate `sim_setup.cir`. Main netlist keeps circuit structure and test vectors. | Merge `sim_setup.cir` back into the main netlist, placing `.tran`, `.ic`, and `.control` block before `.end`. Remove `sim_setup.cir`. | split & merge |
| 3 | **90nm Tech Port** | Port to TSMC 90nm—update LAMBDA, SUPPLY, `.include`, and pulse voltage levels to 1.2V. Save 180nm parameter values in `process_migration.txt`. | Port back to TSMC 180nm using values in `process_migration.txt` and update pulse source voltages. Remove `process_migration.txt`. | numerical reasoning, domain knowledge |
| 4 | **Gate Sizing** | Replace shared `width_N`/`width_P` with per-gate sizing params and update MOSFET W= references. Save defaults in `sizing_defaults.txt`. | Restore shared `width_N`/`width_P` params from `sizing_defaults.txt` and update all MOSFET W= references. Remove `sizing_defaults.txt`. | string manipulation |
| 5 | **Port Reordering** | Alphabetize ports in every `.subckt` definition and update all X instance lines to match. Save original port orders in `port_mapping.txt`. | Restore original `.subckt` port orders from `port_mapping.txt` and update instance lines to match. Remove `port_mapping.txt`. | sorting, string manipulation |
| 6 | **Latch Flattening** | Flatten latch into flipflop—expand latch instances to nand calls, remove latch `.subckt`. Save hierarchy info in `hierarchy_notes.txt`. | Re-extract latch `.subckt` using `hierarchy_notes.txt`, replace inlined nand calls in flipflop with latch instances. Remove it. | domain knowledge |
