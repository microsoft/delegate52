# <img src="../assets/domain_icons/aviation.svg" width="28" height="28" style="vertical-align: middle;"> Aviation

**Category:** Science &amp; Engineering
**File format:** `.txt`
**Summary:** ICAO NOTAM bulletin with military exercises, obstacles, aerodrome ops, and navigation aid notices
**Work environments released:** 0 / 6

Aviation NOTAM (Notice to Air Missions) bulletins use the standard ICAO format, where each entry contains a structured header (ID, type, Q-line with FIR/Q-code/traffic/scope/altitudes/coordinates), location, validity period, optional schedule, free-text description, and metadata (created timestamp, source). This domain tests an LLM's ability to parse, transform, and reconstruct highly structured aviation safety notices with strict field-level formatting requirements.

**Domain implementation:** [`domain_aviation.py`](../domains/domain_aviation.py)

---

## Evaluation

The Aviation domain evaluator parses ICAO NOTAMs into structured entries with 20+ fields (ID, type, replaced_id, Q-line components, location, validity times, schedule, free text, altitudes, created timestamp, source) using a custom regex-based parser. Entries are matched by NOTAM ID fingerprint (e.g. "A1348/20"). Five component scores are computed:

- **NOTAM coverage** — Are all original NOTAMs present? (Jaccard on ID fingerprints, squared as gate)
- **Header accuracy** — Weighted comparison of 9 structured fields (type, replaced_id, location, qcode, valid_from, valid_to, schedule, lower_alt, upper_alt)
- **Text accuracy** — SequenceMatcher on the E) free-text field
- **Q-line accuracy** — SequenceMatcher on the full Q) line
- **Metadata accuracy** — Weighted combination of created timestamp and source similarity

**Score formula:** `coverage² × content_accuracy × √((metadata + sequence) / 2)` where `content_accuracy = 0.30×header + 0.45×text + 0.25×q_line`
