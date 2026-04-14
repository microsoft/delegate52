# <img src="../assets/domain_icons/hamradio.svg" width="28" height="28" style="vertical-align: middle;"> Ham Radio

**Category:** Structured Records
**File format:** `.adi`
**Summary:** ADIF amateur radio QSO logs with contact records, signal reports, and geographic data
**Work environments released:** 5 / 6

ADIF (Amateur Data Interchange Format) log files record amateur radio contacts (QSOs) with structured per-contact fields: callsign, frequency, band, mode, signal reports (RST), operator name, QTH location, Maidenhead grid squares, DXCC entity, CQ/ITU zones, QSL confirmation tracking, and contest exchange comments. This domain tests an LLM's ability to manipulate richly structured radio contact records — splitting by band or zone, converting between amateur radio formats (ADIF, Cabrillo, CSV), parsing embedded contest exchanges, and preserving field-level accuracy across dozens of ADIF tags per QSO.

**Domain implementation:** [`domain_hamradio.py`](../domains/domain_hamradio.py)

---

## Evaluation

The ham radio domain evaluator parses ADIF QSO records into structured dictionaries using the `adif_io` library and scores reconstruction quality across three dimensions:

- **QSO coverage** — Are all original QSO records present? (Uses fingerprint matching on CALL + QSO_DATE + TIME_ON + BAND with Hungarian matching)
- **Field accuracy** — Are field values preserved correctly? (Weighted comparison: core fields 3×, signal fields 2×, geographic/contact fields 1.5×, metadata 1×; frequency tolerance, case-insensitive RST/gridsquare/band matching)
- **Ordering** — Are QSOs in the correct sequence?

**Score formula:** `coverage² × (0.50 + 0.35 × field_accuracy + 0.15 × ordering)`

---

## Example Work Environment: `hamradio1`

**Document:** NAQP SSB Contest Log
**Source:** [dfannin/loggy](https://github.com/dfannin/loggy/blob/master/inputfiles/naqp-201701.adi) (BSD-3-Clause License)
**Size:** 127 lines · 3,517 tokens

### Seed Document Excerpt (`naqp_log.adi`)

```
ADIF export from CQRLOG for Linux version 2.0.4 (001)
Copyright (C) 2017 by Petr, OK2CQR and Martin, OK1RR

Internet: http://www.cqrlog.com

<ADIF_VER:5>2.2.1
<PROGRAMID:6>CQRLOG
<PROGRAMVERSION:11>2.0.4 (001)
<EOH>
<QSO_DATE:8>20170122<TIME_ON:4>0406<TIME_OFF:4>0406<CALL:5>W6AFA<MODE:3>SSB<FREQ:6>3.8097<BAND:3>80M<RST_SENT:2>59<RST_RCVD:2>59<NAME:9>Alexander<QTH:11>Studio City<QSL_SENT:1>Y<QSL_RCVD:1>N<GRIDSQUARE:6>DM04TC
<MY_GRIDSQUARE:6>CM97AQ<AWARD:23>TEN-TEN - 15816 - W6AFA<TX_PWR:3>100<APP_CQRLOG_DXCC:1>W<DXCC:3>291<COMMENT:12>naqp,alex,ca<ITUZ:1>6<CQZ:1>3<STATE:2>CA<CNTY:14>CA,Los Angeles<APP_CQRLOG_QSLS:1>E
<LOTW_QSL_SENT:1>Y
<LOTW_QSLSDATE:8>20170121
<CONT:2>NA
<EQSL_QSL_SENT:1>Y
<EQSL_QSLSDATE:8>20170121

<EOR>
<QSO_DATE:8>20170122<TIME_ON:4>0404<TIME_OFF:4>0404<CALL:5>N7KRN<MODE:3>SSB<FREQ:4>3.79<BAND:3>80M<RST_SENT:3>5na<RST_RCVD:2>59<NAME:9>Frederick<QTH:13>Camano Island<QSL_SENT:1>Y<QSL_RCVD:1>N<GRIDSQUARE:6>CN88RF
<MY_GRIDSQUARE:6>CM97AQ<TX_PWR:3>100<APP_CQRLOG_DXCC:1>W<DXCC:3>291<COMMENT:12>naqp,fred,wa<ITUZ:1>6<CQZ:1>3<STATE:2>WA<CNTY:9>WA,Island<APP_CQRLOG_QSLS:1>E
<LOTW_QSL_SENT:1>Y
<LOTW_QSLSDATE:8>20170121
<CONT:2>NA
<EQSL_QSL_SENT:1>Y
<EQSL_QSLSDATE:8>20170121

<EOR>
<QSO_DATE:8>20170122<TIME_ON:4>0403<TIME_OFF:4>0403<CALL:4>W6YX<MODE:3>SSB<FREQ:4>3.78<BAND:3>80M<RST_SENT:2>59<RST_RCVD:2>59<NAME:9>Standford<QTH:9>Palo Alto<QSL_SENT:1>Y<QSL_RCVD:1>N<GRIDSQUARE:6>CM87VK
<MY_GRIDSQUARE:6>CM97AQ<AWARD:49>ss,1125s,24,scv dxcc,593 cqp,56,63,scla TEN-TEN -<TX_PWR:3>100<APP_CQRLOG_DXCC:1>W<DXCC:3>291<COMMENT:12>naqp,mike,ca<NOTES:14>number 3, CCOS
<ITUZ:1>6<CQZ:1>3<STATE:2>CA<CNTY:14>CA,Santa Clara<APP_CQRLOG_QSLS:1>E
<LOTW_QSL_SENT:1>Y
<LOTW_QSLSDATE:8>20170121
<CONT:2>NA
<EQSL_QSL_SENT:1>Y
<EQSL_QSLSDATE:8>20170121

<EOR>
<QSO_DATE:8>20170122<TIME_ON:4>0346<TIME_OFF:4>0346<CALL:4>K6LA<MODE:3>SSB<FREQ:5>7.167<BAND:3>40M<RST_SENT:2>59<RST_RCVD:2>59<NAME:7>Kenneth<QTH:11>Los Angeles<QSL_SENT:1>Y<QSL_RCVD:1>N<GRIDSQUARE:6>DM04TA
<MY_GRIDSQUARE:6>CM97AQ<TX_PWR:3>100<APP_CQRLOG_DXCC:1>W<DXCC:3>291<COMMENT:11>naqp,ken,ca<ITUZ:1>6<CQZ:1>3<STATE:2>CA<CNTY:14>CA,Los Angeles<APP_CQRLOG_QSLS:1>E
<LOTW_QSL_SENT:1>Y
<LOTW_QSLSDATE:8>20170121
<CONT:2>NA
<EQSL_QSL_SENT:1>Y
<EQSL_QSLSDATE:8>20170121

<EOR>
```
<sup>Showing 4 of 13 QSO records. The full log contains 13 contacts from an NAQP SSB contest on January 22, 2017, across 80M (3 QSOs) and 40M (10 QSOs) bands, with rich per-QSO fields including callsign, frequency, grid square, signal reports, QSL tracking, and contest exchange comments.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Band Split** | Split the log by band (80m_log.adi, 40m_log.adi), each with a proper ADIF header. Create band_info.json recording the sequence position of every QSO (callsign + time as key) so it can be reassembled later. | Merge 80m_log.adi and 40m_log.adi into a single naqp_log.adi file. Use band_info.json to restore the QSO ordering. Keep a single ADIF header. | split & merge, classification, sorting |
| 2 | **Cabrillo Conversion** | Convert the ADIF to Cabrillo 3.0 as naqp_log.log (call KI6YMZ, name David, state CA, single-op low power all-band). For NX6T (missing NAME), derive name from COMMENT (format naqp,name,state). Create adif_metadata.json with all per-QSO ADIF fields Cabrillo can't represent, plus entry sequence number and ADIF file header info. | Convert this Cabrillo log to CQRLOG-style ADIF as naqp_log.adi. Use adif_metadata.json to restore all per-QSO fields Cabrillo doesn't carry and the ADIF file header. Order QSOs by entry sequence numbers in the metadata, not chronologically. NX6T had no NAME field in the ADIF — don't add one for that contact. | format knowledge, domain knowledge, sorting |
| 3 | **QSL Annotation** | Add a QSL_STATUS field to each QSO record — format as Sent:[methods]\|Rcvd:[methods or None] where methods are Bureau, LoTW, eQSL based on QSL_SENT, LOTW_QSL_SENT, EQSL_QSL_SENT and their _RCVD counterparts. Place QSL_STATUS right after QSL_RCVD. Sort the log by TIME_ON ascending. Save pre-sort ordering to position_map.json as a record_order array of callsigns. | Strip the QSL_STATUS field from every QSO record. Reorder the QSOs to match the callsign sequence in position_map.json and delete that file. | string manipulation, sorting |
| 4 | **CQ Zone Grouping** | Group QSOs by CQ zone into separate ADIF files (cqzone_N.adi naming), each with its own header. Sort QSOs by frequency ascending within each file. Save merge_order.json with the interleaved callsign sequence so the log can be reassembled. | Merge all the per-zone ADIF files into a single naqp_log.adi. Use merge_order.json to restore the QSO sequence. Use a single ADIF header. | split & merge, classification, sorting |
| 5 | **CSV Export** | Convert to CSV (naqp_qsos.csv), one row per QSO. Parse COMMENT (naqp,name,state format) into exchange_name and exchange_state columns. Sort by callsign alphabetically. ADIF header, overflow fields, and record positions go in metadata.json. | Convert CSV back to ADIF as naqp_log.adi. Use metadata.json to restore the ADIF header, supplementary per-QSO fields, and record ordering. Merge exchange_name and exchange_state back into COMMENT using naqp,name,state format. | format knowledge, domain knowledge, sorting |
| 6 | **Normalized Layout** | Reformat each QSO record so every ADIF tag is on its own line, fields in alphabetical order within each record. Sort QSOs by frequency ascending. Save layout.json with each QSO's current field order and the QSO ordering so the formatting can be fully recreated. | Restore the ADIF log formatting using layout.json. Put each QSO's fields back in their prior tag order and restore the QSO sequence. Remove layout.json. | string manipulation, sorting |
