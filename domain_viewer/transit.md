# <img src="../assets/domain_icons/transit.svg" width="28" height="28" style="vertical-align: middle;"> Transit

**Category:** Everyday
**File format:** `.txt`
**Summary:** GTFS transit feed with routes, stops, trips, and schedules
**Work environments released:** 4 / 6

GTFS (General Transit Feed Specification) feeds are the standard format for publishing public transit schedules. A feed consists of multiple interlinked CSV files — agencies, routes, stops, trips, stop times, calendars, fare attributes, and fare rules — each with defined primary keys and foreign key relationships. This domain tests an LLM's ability to manipulate structured, relational tabular data — splitting, merging, reformatting, denormalizing, and preserving referential integrity across a multi-file transit dataset.

**Domain implementation:** [`domain_transit.py`](../domains/domain_transit.py)

---

## Evaluation

The transit domain evaluator parses all GTFS CSV files into structured representations, matching rows by their GTFS-defined primary keys (e.g., `trip_id` for trips, `(trip_id, stop_sequence)` for stop_times). Scoring uses a multiplicative formula where row preservation is the dominant signal, multiplied by a quality factor:

- **Row preservation** — Are all reference rows present with correct field values? (Recall-based, weighted by file size)
- **File presence** (35%) — Are all expected GTFS files present?
- **Stop times ordering** (25%) — Do stop_times within each trip preserve the correct stop sequence?
- **Referential integrity** (15%) — Are GTFS foreign key relationships intact? (e.g., `stop_times.stop_id` → `stops.stop_id`, `trips.route_id` → `routes.route_id`)
- **Row count** (15%) — Are there missing or extra rows?
- **Header accuracy** (10%) — Are column headers preserved correctly?

**Score formula:** `row_preservation × (0.35 × file_presence + 0.25 × order + 0.15 × referential_integrity + 0.15 × row_count + 0.10 × headers)`

---

## Example Work Environment: `transit1`

**Document:** Altamont Corridor Express GTFS Feed
**Source:** [aickin/visualize-density](https://github.com/aickin/visualize-density) (Public Domain)
**Size:** 130 lines · 3,369 tokens

### Seed Document Excerpt (`stop_times.txt`, `stops.txt`, `trips.txt`)

```
stop_times.txt:
trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign,pickup_type,drop_off_type,shape_dist_traveled,timepoint
"1","4:20:00","4:20:00","3400001","1",,"0","0",,1
"1","4:39:00","4:39:00","3400002","2",,"0","0",,1
"1","4:51:00","4:51:00","3400003","3",,"0","0",,1
"1","5:20:00","5:20:00","3400004","4",,"0","0",,1
"1","5:25:00","5:25:00","3400005","5",,"0","0",,1
"1","5:33:00","5:33:00","3400006","6",,"0","0",,1
"1","5:55:00","5:55:00","3400007","7",,"0","0",,1
"1","6:13:00","6:13:00","3400008","8",,"0","0",,1
"1","6:20:00","6:20:00","3400009","9",,"0","0",,1
"1","6:32:00","6:32:00","3400010","10",,"0","0",,1

stops.txt:
stop_id,stop_code,stop_name,stop_lat,stop_lon,zone_id,stop_desc,stop_url,location_type,parent_station,stop_timezone,wheelchair_boarding
"3400001","3400001",SKT STOCKTON STATION,37.957058,-121.278948,"57002","","","","","",""
"3400002","3400002",LAT LATHROP/MANTECA STATION,37.797908,-121.263664,"57003","","","","","",""
"3400003","3400003",TRC TRACY STATION,37.696468,-121.433869,"57004","","","","","",""
"3400004","3400004",VAR VASCO ROAD STATION,37.7013875182,-121.7193829951,"57005","","","","","",""
"3400005","3400005",LVA LIVERMORE STATION,37.6851052949,-121.7674951738,"57005","","","","","",""
"3400006","3400006",PLD PLEASANTON STATION,37.6575485374,-121.8829617257,"57005","","","","","",""
"3400007","3400007",FMT FREMONT STATION,37.5585585499,-122.0075983747,"57006","","","","","",""
"3400008","3400008",GAC GREAT AMERICA STATION,37.4063980804,-121.9666714969,"57007","","","","","",""
"3400009","3400009",SCC SANTA CLARA STATION,37.352892,-121.936346,"57007","","","","","",""
"3400010","3400010",SJD SAN JOSE STATION,37.329568326,-121.9031883625,"57007","","","","","",""

trips.txt:
route_id,service_id,trip_id,trip_headsign,direction_id,block_id,shape_id,trip_short_name,bikes_allowed,wheelchair_accessible
ACE,72777,1,San Jose,0,,,ACE 1,,
ACE,72777,3,San Jose,0,,,ACE 3,,
ACE,72777,5,San Jose,0,,,ACE 5,,
ACE,72777,7,San Jose,0,,,ACE 7,,
ACE,72777,4,Stockton,1,,,ACE 4,,
ACE,72777,6,Stockton,1,,,ACE 6,,
ACE,72777,8,Stockton,1,,,ACE 8,,
ACE,72777,10,Stockton,1,,,ACE 10,,
```
<sup>Showing selected files. The full feed contains 9 GTFS files (130 lines): agency, routes, stops, trips, stop_times, calendar, directions, fare_attributes, and fare_rules covering 1 route, 10 stations, 8 trips, and 80 stop times.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Direction Split** | Split the schedule by direction — create separate westbound and eastbound files for trips and stop_times. Add a timetable_index.txt mapping each direction_id to its name, corresponding filenames, and a merge_position for which direction's block comes first. Keep other files as they are. | Consolidate the per-direction files back into unified trips.txt and stop_times.txt — use merge_position in timetable_index.txt to determine block order. Drop the per-direction files and timetable_index.txt. | split & merge, classification, sorting |
| 2 | **Fare Matrix** | Consolidate fare_attributes.txt and fare_rules.txt into a single fare_matrix.txt — a zone-to-zone price grid with origin zone rows and destination zone columns. Blank cells where no fare exists. Add # comment lines at the top with the shared fare attributes and a fare_id=price mapping line. Delete fare_attributes.txt and fare_rules.txt. | Expand fare_matrix.txt back into fare_attributes.txt and fare_rules.txt. Read the fare_id-to-price mapping and shared attributes from the # comments. One row per fare_id in attributes sorted ascending. One row per filled matrix cell in rules, fare_id looked up from price, route_id and contains_id empty, sorted by fare_id then origin_id. Delete fare_matrix.txt. | format knowledge, sorting |
| 3 | **Timetable Grid** | Reformat stop_times.txt as a printed station timetable. Rows = stations in geographic order, columns = trip numbers. Split into WESTBOUND and EASTBOUND sections. Add metadata comment lines at the top documenting uniform GTFS field defaults. Include stop_ids next to station names. Use pipe-delimited columns with a header row of trip IDs. | Convert the printed timetable in stop_times.txt back to standard GTFS stop_times.txt CSV format — one row per trip-stop with all standard columns. Reconstruct field values from the metadata comments. List WB trip stops first (ascending trip_id), then EB trips (ascending trip_id), stops in stop_sequence order within each trip. | format knowledge, sorting |
| 4 | **Stop Denormalization** | Inline stop details into stop_times — for each row, add stop_name, stop_lat, stop_lon, zone_id, and stop_code from stops.txt. Then sort all rows chronologically by arrival_time across trips. Add an orig_row column recording each row's 1-based position pre-sort. Remove stops.txt. | Extract the inlined stop columns back out of stop_times.txt into a separate stops.txt keyed on stop_id. Remove the inlined columns. Re-sort by orig_row to restore trip-grouped order, then drop orig_row. | format knowledge, sorting |
| 5 | **Per-Station Schedule** | Reorganize the GTFS feed into per-station schedule files. For each stop, create a station file named by its code (e.g., `SKT.txt`, `LAT.txt`) containing all stop-time rows for that station with joined fields from stop_times, trips, and stops. Delete stop_times.txt, stops.txt, trips.txt, and directions.txt. Create feed_index.txt to record row ordering. | Reassemble the GTFS feed from the per-station files. Use feed_index.txt to reconstruct stops.txt, trips.txt, stop_times.txt, and directions.txt in correct order. Delete the per-station files and feed_index.txt. | split & merge, format knowledge, sorting |
| 6 | **Feed Config Merge** | Combine agency.txt, calendar.txt, routes.txt, and directions.txt into a single feed_config.txt using INI-style sections. For single-row tables, list each column as key = value. For multi-row tables, include a CSV block. Remove the four source files. | Split feed_config.txt back into separate GTFS CSV files: agency.txt, calendar.txt, routes.txt, directions.txt. Each INI section becomes its own CSV. Delete feed_config.txt. | format knowledge, split & merge |
