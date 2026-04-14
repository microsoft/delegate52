# <img src="../assets/domain_icons/satellite.svg" width="28" height="28" style="vertical-align: middle;"> Satellite

**Category:** Science &amp; Engineering
**File format:** `.tle`
**Summary:** TLE (Two-Line Element) satellite orbital data files
**Work environments released:** 6 / 6

TLE satellite orbital data files use the NORAD [Two-Line Element](https://en.wikipedia.org/wiki/Two-line_element_set) fixed-width format for tracking Earth-orbiting objects. Each entry consists of three lines: a satellite name (24 chars), line 1 (catalog number, international designator, epoch, drag terms), and line 2 (Keplerian orbital elements — inclination, RAAN, eccentricity, argument of perigee, mean anomaly, and mean motion). This domain tests an LLM's ability to manipulate structured scientific data — parsing fixed-width fields, performing orbital calculations, classifying satellites by regime, and converting between TLE and tabular formats.

**Domain implementation:** [`domain_satellite.py`](../domains/domain_satellite.py)

---

## Evaluation

The satellite domain evaluator parses fixed-width 3LE entries (name line + line 1 + line 2) and compares field values across five dimensions:

- **Satellite name** — Is the satellite name preserved correctly? (Case-insensitive, trimmed)
- **Identity fields** — Are catalog number, classification, and international designator intact?
- **Epoch** — Are epoch year and fractional day values correct?
- **Orbital elements** — Are inclination, RAAN, eccentricity, argument of perigee, mean anomaly, and mean motion preserved? (50% of total weight)
- **Drag & derivatives** — Are BSTAR, mean motion derivatives, and revolution number correct?

Entries are matched using the Hungarian algorithm on catalog number (70%) and name similarity (30%). Missing entries score 0 against the reference. The final score combines field accuracy with an order factor and extra-entry penalty.

**Score formula:** `0.10 × name + 0.10 × identity + 0.15 × epoch + 0.50 × orbital + 0.15 × drag`

---

## Example Work Environment: `satellite1`

**Document:** Earth Observation Satellite Catalog
**Source:** [CelesTrak Earth Resources](https://celestrak.org/NORAD/elements/gp.php?GROUP=earth-resources&FORMAT=tle) (Public domain — US government work)
**Size:** 93 lines · 2,688 tokens

### Seed Document Excerpt (`satellites.tle`)

```tle
SCD 1                   
1 22490U 93009B   26044.92331660  .00000466  00000+0  76381-4 0  9998
2 22490  24.9684 248.6255 0041796 273.5201 218.2999 14.46053409743258
TERRA                   
1 25994U 99068A   26045.22578913  .00000517  00000+0  11458-3 0  9999
2 25994  97.9644  99.5508 0001074 232.2326 197.5159 14.60989012391659
AQUA                    
1 27424U 02022A   26045.49181080  .00001181  00000+0  24577-3 0  9991
2 27424  98.4131  12.4422 0001317  49.4301  60.2593 14.61918761265344
IRS-P6 (RESOURCESAT-1)  
1 28051U 03046A   26045.55487442  .00000418  00000+0  15418-3 0  9999
2 28051  98.2097  87.9790 0064050 351.4070 165.9713 14.36103012162921
AURA                    
1 28376U 04026A   26045.48187005  .00001133  00000+0  24037-3 0  9994
2 28376  98.3271   1.0416 0001196  67.7135 292.4192 14.61091661148294
RESURS-DK 1             
1 29228U 06021A   26045.12637428  .00002341  00000+0  13991-3 0  9997
2 29228  69.9340 297.9712 0004042 196.9226 163.1806 15.12606211 83964
ARIRANG-2 (KOMPSAT-2)   
1 29268U 06031A   26045.52933135  .00000410  00000+0  85544-4 0  9999
2 29268  97.8286 235.9013 0015741 101.5720 343.2285 14.64567132 43526
COSMO-SKYMED 1          
1 31598U 07023A   26045.52858617  .00004011  00000+0  35965-3 0  9993
2 31598  97.8853 236.3781 0001142  94.4299 265.7052 14.96347099 11442
TERRASAR-X              
1 31698U 07026A   26043.56893060  .00001279  00000+0  64077-4 0  9990
2 31698  97.4458  53.0499 0001762  81.7447 278.3988 15.19155408 34307
WORLDVIEW-1 (WV-1)      
1 32060U 07041A   26045.33219412  .00008895  00000+0  36894-3 0  9997
2 32060  97.3807 166.8597 0001547 205.2126 154.9036 15.24097988 24168
RADARSAT-2              
1 32382U 07061A   26045.51879905  .00000009  00000+0  20529-4 0  9993
2 32382  98.5813  54.1883 0001160  83.1201 277.0113 14.29981438948423
THEOS                   
1 33396U 08049A   26045.51585105  .00000189  00000+0  10875-3 0  9993
2 33396  98.5761 106.6932 0001111  83.6201 276.5102 14.20112600900552
YAOGAN-4                
1 33446U 08061A   26045.37369242  .00001382  00000+0  17669-3 0  9993
2 33446  97.9232 339.8763 0015790 108.4509 251.8422 14.82904384927467
GOSAT (IBUKI)           
1 33492U 09002A   26044.31982967  .00000411  00000+0  80996-4 0  9994
2 33492  98.0759 157.0521 0001579  91.4675 268.6710 14.67546917913290
OCEANSAT-2              
1 35931U 09051A   26045.52870840 -.00000204  00000+0 -11371-3 0  9990
2 35931  98.2263  44.6750 0016183 220.4185 139.5781 13.99638751862170
```
<sup>Showing 48 of 93 lines. The full TLE file contains 31 Earth observation satellites spanning 11 countries (USA, ESA, India, Japan, Korea, France, Germany, Canada, Thailand, Brazil, Iran), launch years 1993–2025, and inclinations from 24.97° to 98.79°.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Orbit Regime Split** | Split the satellites listed in `satellites.tle` into separate TLE files by orbit regime. Put sun-synchronous entries (inclination 96–102°) into `sso.tle`, high-inclination non-SSO (60–96°) into `high_inc.tle`, and low-inclination (<60°) into `low_inc.tle`. In each of those output files, insert a comment line `# SEQ: N` immediately before each satellite's name line, where N is that entry's 1-based position in `satellites.tle` at the time you split it. Do not include any satellites from other files. | Merge `sso.tle`, `high_inc.tle`, and `low_inc.tle` into a single `satellites.tle`. Use the `# SEQ: N` comments to restore the entries to the correct ascending order, then remove all `# SEQ:` comment lines from the final merged file. | split & merge, classification, sorting |
| 2 | **Altitude Sort** | Sort entries by mean motion descending. Before each entry, insert a comment with orbital period in minutes (1440/mean_motion, 2 decimals) and approximate circular orbit altitude in km (round to integer). Include the entry's current sequence number (1-based). Format: `# [Seq N] Period: XX.XX min \| Alt: XXX km` | Strip all comment lines and reorder entries by Seq number ascending. | numerical reasoning, sorting |
| 3 | **Decade Catalog** | Reorganize by launch decade (from international designator year). Add decade section headers (format: `# ===== <DECADE> LAUNCHES =====`). Within each decade, sort entries alphabetically by satellite name. Before each entry, insert a comment `# Catalog Order: N` with its current 1-based position. | Flatten into a single TLE listing. Reorder entries by ascending Catalog Order number, then remove all comment lines. No blank lines between entries. | classification, sorting |
| 4 | **CSV Coplanar** | Convert the TLE file into `satellites.csv`. Columns: Seq (1-based position in current listing), Name, NORAD_ID, Classification, Intl_Designator, Epoch_Year, Epoch_Day, Mean_Motion_Dot, Mean_Motion_DDot, BSTAR, Ephemeris_Type, Element_Set_Num, Checksum_L1, Inclination, RAAN, Eccentricity, Arg_Perigee, Mean_Anomaly, Mean_Motion, Rev_Number, Checksum_L2. Sort by inclination ascending then RAAN ascending. | Convert this CSV to standard 3LE format (`satellites.tle`). Name line padded to 24 chars, lines 1 and 2 per NORAD fixed-width spec. Order by Seq column. | format knowledge, sorting |
| 5 | **Orbit Cards** | Convert TLE entries into human-readable orbit cards sorted alphabetically by name. Each card should show labeled Keplerian elements, drag terms, and identity fields. Include a `[Pos:NN]` tag with each entry's current position. Output as `orbit_cards.txt`. | Convert orbit cards to standard NORAD 3LE format in `satellites.tle`. Compute line checksums. Order entries by `[Pos:NN]` tags. | format knowledge, context expansion, sorting |
| 6 | **Agency Split** | Partition `satellites.tle` into per-agency TLE files. `usa_nasa.tle` for TERRA, AQUA, AURA, WORLDVIEW-1, LANDSAT 8, LANDSAT 9, ICESAT-2, SWOT. `esa_copernicus.tle` for SENTINEL-1A, SENTINEL-2A, SENTINEL-2B, SENTINEL-5P, BIOMASS. `india_isro.tle` for IRS-P6, OCEANSAT-2, RESOURCESAT-2A. `asia_pacific.tle` for ARIRANG-2, THEOS, YAOGAN-4, GOSAT, FORMOSAT-5, ALOS-4. `europe_other.tle` for COSMO-SKYMED 1, TERRASAR-X, TANDEM-X, RADARSAT-2, PLEIADES 1A, SPOT 6. `other.tle` for the rest. Preserve relative ordering within each file. Add `# Entry: N` before each entry with its 1-indexed source position. Generate `manifest.txt` listing each file's satellites and entry numbers. | Merge all agency TLE files into `satellites.tle` using `manifest.txt` and `# Entry` comments to restore ordering. Remove the `# Entry` comments. Delete `manifest.txt`. | split & merge, classification, sorting |
