# <img src="../assets/domain_icons/audiosyn.svg" width="28" height="28" style="vertical-align: middle;"> Audiosyn

**Category:** Creative &amp; Media
**File format:** `.csd`
**Summary:** CSound audio synthesis with instruments, function tables, and score events
**Work environments released:** 2 / 6

CSound CSD files use a unified XML-like format containing orchestral instrument definitions, function table declarations, and score events for digital audio synthesis. Each file defines instruments (signal processing chains with opcodes), function tables (waveforms via GEN routines), and score events (note triggers with p-field parameters and carry notation). This domain tests an LLM's ability to manipulate structured audio synthesis code — converting pitch notations, reorganizing score sections, extracting reusable components, and performing arithmetic on timing and frequency values across interconnected instrument and score blocks.

**Domain implementation:** [`domain_audiosyn.py`](../domains/domain_audiosyn.py)

---

## Evaluation

The Audiosyn evaluator parses CSD files into structured representations and scores reconstruction quality across multiple dimensions:

- **Instrument coverage & accuracy** — Are all instrument definitions present with correct IDs and body code? (Uses Jaccard ID coverage and SequenceMatcher body accuracy)
- **Score event coverage & accuracy** — Are all i-statement note events preserved? (Uses fingerprint-based coverage, SequenceMatcher accuracy, and ratio-of-bigrams sequence score)
- **Function tables** — Are f-statement table definitions (table number, GEN routine, args) correct?
- **Header settings** — Are sr, ksmps, nchnls, 0dbfs values preserved?
- **Comments & sequence** — Are section header comments and event ordering intact?

**Score formula:** `core × √(aux_mean)`, where `core = instr_gate^0.5 × event_gate^0.5` (each gate = `coverage^2.5 × accuracy`) and aux averages function tables (25%), settings (15%), comments (25%), event sequence (25%), and raw text (10%).

---

## Example Work Environment: `audiosyn1`

**Document:** Xanadu — CSound Guitar Chord Composition
**Source:** [csound/csound](https://github.com/csound/csound/blob/master/examples/xanadu.csd) (LGPL-2.1 License)
**Size:** 230 lines · 3,253 tokens

### Seed Document Excerpt (`xanadu.csd`)

```csound
<CsoundSynthesizer>
<CsOptions>
csound  -R -W -f -d -o dac
</CsOptions>
<CsInstruments>
sr          =           48000
ksmps       =           128
nchnls      =           2
;--------------------------------------------------------
;Instrument 1 : plucked strings chorused left/right and
;       pitch-shifted and delayed taps thru exponential
;       functions, and delayed.
;--------------------------------------------------------

            instr       1
ishift      =           .00666667               ;shift it 8/1200.
ipch        =           cpspch(p5)              ;convert parameter 5 to cps.
ioct        =           octpch(p5)              ;convert parameter 5 to oct.
kvib        oscili      1/120, ipch/50, 1       ;vibrato
ag          pluck       2000, cpsoct(ioct+kvib), 1000, 1, 1
agleft      pluck       2000, cpsoct(ioct+ishift), 1000, 1, 1
agright     pluck       2000, cpsoct(ioct-ishift), 1000, 1, 1
af1         expon       .1, p3, 1.0             ;exponential from 0.1 to 1.0
af2         expon       1.0, p3, .1             ;exponential from 1.0 to 0.1
adump       delayr      2.0                     ;set delay line of 2.0 sec
atap1       deltapi     af1                     ;tap delay line with kf1 func.
atap2       deltapi     af2                     ;tap delay line with kf2 func.
ad1         deltap      2.0                     ;delay 2 sec.
ad2         deltap      1.1                     ;delay 1.1 sec.
            delayw      ag                      ;put ag signal into delay line.
            out        agleft+atap1+ad1, agright+atap2+ad2
            endin
;-------------------------------------------------------------
;Instrument 2 : plucked strings chorused left/right and
;       pitch-shifted with fixed delayed taps.
;------------------------------------------------------------

            instr       2
ishift      =           .00666667               ;shift it 8/1200.
ipch        =           cpspch(p5)              ;convert parameter 5 to cps.
ioct        =           octpch(p5)              ;convert parameter 5 to oct.
kvib        oscili      1/120, ipch/50, 1       ;vibrato
ag          pluck       1000, cpsoct(ioct+kvib), 1000, 1, 1
agleft      pluck       1000, cpsoct(ioct+ishift), 1000, 1, 1
agright     pluck       1000, cpsoct(ioct-ishift), 1000, 1, 1
adump       delayr      0.3                     ;set delay line of 0.3 sec
ad1         deltap      0.1                     ;delay 100 msec.
ad2         deltap      0.2                     ;delay 200 msec.
            delayw      ag                      ;put ag sign into del line.
            out        agleft+ad1, agright+ad2
            endin
```
<sup>Showing 51 of 230 lines. The full CSD contains 3 instruments, 3 function tables (sine, cosine, Bessel), and 84 score events across 7 guitar chord sections.</sup>

---

### Edit Tasks (7 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Pitch Conversion** | Switch pitch notation from octave.pitch-class to MIDI note numbers — update all p5 values in the score and replace cpspch/octpch with cpsmidinn/octmidinn in the instruments. | Switch pitch notation from MIDI note numbers to CSound octave.pitch-class format — update all p5 values and replace cpsmidinn/octmidinn with cpspch/octpch. | format knowledge |
| 2 | **Chord Grouping** | Reorganize the score by chord progression step — merge each chord's i3 and i1/i2 events into unified sections with separator comments showing chord name and start time. | Restructure the score into two instrument-based blocks — first all i3 events grouped by chord, then all i1/i2 events grouped by chord, each with chord name comments. | sorting |
| 3 | **UDO Extraction** | Extract the shared pluck+vibrato+chorus code from instr 1 and 2 into a UDO called PluckChorus. Pull the ishift detune constant to a global gi_shift variable. Have all 3 instruments reference these. | Inline the PluckChorus UDO back into instruments 1 and 2. Move gi_shift back to local ishift variables. Remove the UDO definition and global variable. | format knowledge |
| 4 | **Carry Expansion** | Expand all carry notation dots into explicit values. Annotate each note's comment with frequency in Hz and semitone interval from the first note in that chord group. | Restore carry notation in the i-statements. Remove the parenthetical frequency and semitone annotations from all note comments. | context expansion, numerical reasoning |
| 5 | **Table Modernization** | Move f-table definitions from the score into the orchestra header as ftgen globals (giSine, giCosine, giBesselLn). Replace hardcoded table number references with named variables. | Convert ftgen globals back into f-statement definitions in the score section. Replace named table variable references with numeric table numbers. | format knowledge, string manipulation |
| 6 | **Chord Spawner** | Collapse each chord group into a single spawner event. Add instrument 10 (plucked arpeggiator with strum offset) and instrument 30 (FM chord launcher) using event_i delegation. | Remove spawner instruments 10 and 30. Expand each spawner event back into individual note events with carry notation. | context expansion |
| 7 | **Tempo Beats** | Add a t-statement at 120 BPM and convert all explicit p2/p3 values from absolute seconds to beats. Leave carry dots unchanged. | Remove the t-statement and convert all explicit p2/p3 values from beats back to absolute seconds. Leave carry dots unchanged. | numerical reasoning |
