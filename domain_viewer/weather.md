# <img src="../assets/domain_icons/weather.svg" width="28" height="28" style="vertical-align: middle;"> Weather

**Category:** Science &amp; Engineering
**File format:** `.txt`
**Summary:** ICAO METAR/TAF aviation weather bulletin with observations and terminal forecasts
**Work environments released:** 6 / 6

Aviation weather bulletins contain METAR surface observations and TAF terminal aerodrome forecasts in standard ICAO coding. Each METAR line encodes station ID, observation time, wind, visibility, sky conditions, temperature/dewpoint, altimeter setting, and coded remarks (automated indicators, sea-level pressure, precise T-groups). TAF blocks provide multi-period wind and visibility forecasts with change groups (FM, TEMPO, BECMG, PROB30). This domain tests an LLM's ability to parse, reformat, sort, split, and merge structured meteorological data — including unit conversions, flight-category classification, and geographic regrouping.

**Domain implementation:** [`domain_weather.py`](../domains/domain_weather.py)

---

## Evaluation

The weather domain evaluator parses METAR/SPECI reports using the `metar` Python library and TAF forecasts with a custom regex-based parser. Scoring uses weighted components across four dimensions:

- **METAR coverage** — Are all original observations present? (Jaccard similarity on station+time fingerprints)
- **METAR field accuracy** — Are individual fields correct? (wind 20%, visibility 15%, sky 15%, weather 10%, temp/dewpoint 15%, altimeter 10%, remarks 15%)
- **TAF coverage & accuracy** — Are all forecasts present with correct headers (30%) and group-by-group field comparison (70%)?
- **Auxiliary scores** — Sequence preservation (SequenceMatcher on METAR fingerprints) and header similarity

METAR and TAF weights are proportional to their counts.

**Score formula:** `coverage² × field_accuracy × √auxiliary`

---

## Example Work Environment: `weather1`

**Document:** NE US Aviation Weather Bulletin
**Source:** [NOAA Aviation Weather Center](https://aviationweather.gov/api/data/metar) (Public Domain — US Government Work)
**Size:** 136 lines · 3,445 tokens

### Seed Document Excerpt (`bulletin.txt`)

```
AVIATION WEATHER BULLETIN
DTG: 141700Z FEB 2026
REGION: US NORTHEAST / GREAT LAKES
STATIONS: KPHL KBWI KBOS KDCA KLGA KEWR KPIT KJFK KORD KCLE

============================================================
METAR / SPECI OBSERVATIONS
============================================================

METAR KPHL 141654Z 24009KT 10SM BKN085 06/M05 A3011 RMK AO2 SLP196 T00561050
METAR KPHL 141554Z 24010KT 10SM SCT075 BKN090 04/M06 A3014 RMK AO2 SLP204 T00391056
METAR KPHL 141454Z 22008KT 10SM SCT090 02/M06 A3014 RMK AO2 SLP206 T00171061 58006
METAR KPHL 141354Z 22009KT 10SM SCT100 00/M06 A3014 RMK SLP207 T00001061
METAR KPHL 141254Z 24009KT 10SM SCT055 BKN110 M01/M07 A3016 RMK AO2 SLP212 VIRGA T10111067
METAR KPHL 141154Z 23010KT 10SM SCT037 BKN047 OVC060 M01/M06 A3016 RMK AO2 SLP212 VCSH 60000 T10111061 11011 21039 55000

METAR KBWI 141654Z 26009KT 10SM FEW085 FEW250 09/M04 A3012 RMK AO2 SLP200 T00891044 $
METAR KBWI 141554Z 24006KT 10SM FEW080 07/M07 A3015 RMK AO2 SLP210 T00671067
METAR KBWI 141454Z 25009KT 10SM FEW090 03/M07 A3016 RMK AO2 SLP213 T00331072 58001
METAR KBWI 141354Z 24006KT 10SM FEW090 01/M08 A3017 RMK AO2 SLP217 T00061078
METAR KBWI 141254Z 00000KT 10SM FEW080 SCT100 M02/M08 A3016 RMK AO2 SLP214 T10221083
METAR KBWI 141154Z 21003KT 10SM FEW080 BKN100 M04/M09 A3016 RMK AO2 SLP215 T10441089 11028 21061 56004

METAR KBOS 141654Z 27009KT 10SM FEW065 BKN075 01/M07 A3000 RMK AO2 SLP158 T00111072
METAR KBOS 141554Z 26009KT 10SM FEW065 OVC075 01/M07 A3002 RMK AO2 SLP164 T00061072
METAR KBOS 141454Z 26011KT 10SM SCT065 BKN080 00/M08 A3003 RMK AO2 SLP168 T00001083 58007
METAR KBOS 141354Z 26011KT 10SM SCT065 BKN080 M01/M09 A3005 RMK AO2 SLP173 T10061094
METAR KBOS 141254Z 26011KT 10SM SCT060 BKN080 M01/M10 A3004 RMK AO2 SLP173 T10111100
METAR KBOS 141154Z 26008KT 10SM SCT065 BKN080 M02/M10 A3005 RMK AO2 SLP175 T10171100 11011 21022 53008
```
<sup>Showing 30 of 136 lines. The full bulletin contains 62 METAR/SPECI observations across 10 stations (including SPECI reports for KCLE with 1/4SM HZ, COR reports for KLGA and KJFK, and maintenance indicators), followed by 10 TAF forecasts with FM/PROB30 change groups.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Chronological Reorder** | Reorganize the METAR/SPECI section so all observations are listed by observation time, newest first, regardless of station. Remove the blank-line separations between station blocks. For reports at the same time, order alphabetically by station ICAO code. Add a comment line at the top of the METAR section. | Regroup the METAR/SPECI reports by station, one blank line between each station's block. Station order should follow the STATIONS line in the header. Within each station block, keep reports newest first. Remove the sorted-chronologically comment line. | sorting |
| 2 | **Per-Station Split** | Split the bulletin into per-station files, one for each ICAO code (e.g. KPHL.txt, KBOS.txt). Each file should have that station's METAR/SPECI obs followed by its TAF block. Create a bulletin_index.txt with the bulletin header and the station ordering for the METAR section and TAF section separately. | Merge the per-station files into a single bulletin.txt using bulletin_index.txt for the header and section orderings, with dividers between sections. Add END OF BULLETIN footer. | split & merge, classification, sorting |
| 3 | **METAR Table (Imperial/Metric)** | Reformat the METAR/SPECI observations into a markdown table with columns for type, station, time, wind, visibility, weather, clouds, temp (°F), dewpoint (°F), QNH (hPa), remarks, and flags. Convert temperatures to Fahrenheit using precise T-group values and altimeter from inHg to hPa. | Convert the METAR observation table back into standard METAR/SPECI coded report lines. Convert temperatures back to Celsius and QNH back to inHg altimeter. Group reports by station following the header station order. | numerical reasoning, format knowledge |
| 4 | **Flight Category Tags** | For each METAR/SPECI line, append a flight category tag (VFR, MVFR, IFR, or LIFR). Within each station block, sort reports by category severity (LIFR first); break ties by observation time newest first. | Strip the flight category tags from every METAR/SPECI line. Re-sort reports within each station block by observation time, newest first. | classification, sorting |
| 5 | **Metro Area Grouping** | Reorganize the bulletin by metropolitan area (Boston, NYC Metro, DC/Mid-Atlantic, Great Lakes) instead of individual stations. Under each metro heading, put that metro's METARs then TAFs. Add a station-to-metro mapping block and a TAF-ORDER line preserving the original TAF sequence. | Remove the metro-area section headings and mapping block, merging into two flat sections: METAR/SPECI observations and TAFs. Restore station-based grouping per the STATIONS header. TAFs follow the sequence from the TAF-ORDER line. | classification, context expansion |
| 6 | **Observations/Forecasts Split** | Split bulletin.txt into observations.txt (all METAR/SPECI reports sorted by time newest-first, ties broken alphabetically) and forecasts.txt (all TAFs sorted alphabetically by ICAO, with a TAF-ORDER comment preserving original sequence). Include the bulletin header in both files. | Merge observations.txt and forecasts.txt into a single bulletin.txt. Group METARs by station per the STATIONS header, newest first in each block. TAFs follow the TAF-ORDER comment sequence. Remove TAF-ORDER comment and deduplicate the header. Add END OF BULLETIN footer. | split & merge, sorting |
