# <img src="../assets/domain_icons/geotrack.svg" width="28" height="28" style="vertical-align: middle;"> Geotrack

**Category:** Structured Records
**File format:** `.gpx`
**Summary:** GPX (GPS Exchange Format) files with tracks, waypoints, elevation, timestamps, and sensor extensions
**Work environments released:** 6 / 6

GPX files use the [GPS Exchange Format](https://www.topografix.com/gpx.asp) XML schema to record geographic data — waypoints with names and descriptions, tracks composed of timed coordinate sequences, and optional sensor extensions like Garmin ambient temperature. This domain tests an LLM's ability to manipulate hierarchical XML structures, preserve precise numeric coordinates and timestamps, and handle namespace-qualified extensions across track splitting, format conversions, and structural transformations.

**Domain implementation:** [`domain_geotrack.py`](../domains/domain_geotrack.py)

---

## Evaluation

The geotrack domain evaluator parses GPX files using `gpxpy` into waypoints and tracks, then scores reconstruction quality across four dimensions:

- **Waypoint coverage** (10%) — Are all waypoints present? (Jaccard similarity on waypoint names)
- **Waypoint accuracy** (10%) — Are coordinates, descriptions, and links preserved for matched waypoints?
- **Track structure** (15%) — Are track names, counts, and segment structures correct?
- **Trackpoint data** (65%) — Are coordinates, elevation, timestamps, and temperature extensions preserved? (Uses SequenceMatcher on coordinate sequences with per-point field scoring)

**Score formula:** `0.10 × wpt_coverage + 0.10 × wpt_accuracy + 0.15 × trk_structure + 0.65 × trk_points`

Trackpoint coverage is gated quadratically — missing points severely impact the score.

---

## Example Work Environment: `geotrack1`

**Document:** Berkeley Test Walks
**Source:** [dret/GPXQuery](https://github.com/dret/GPXQuery/blob/master/demo.gpx) (GPL-2.0 License)
**Size:** 306 lines · 3,817 tokens

### Seed Document Excerpt (`berkeley_walks.gpx`)

```xml
<?xml version='1.0' encoding='UTF-8'?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="1.1" creator="dret" xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd http://www.garmin.com/xmlschemas/TrackPointExtension/v1 http://www.garmin.com/xmlschemas/TrackPointExtensionv1.xsd">
  <wpt lat="37.878123" lon="-122.268701">
    <name>Walgreens</name>
    <desc>The Walgreens drugstore on Shattuck Avenue. This used to be the "Elephant Pharmacy" before they closed in 2009.</desc>
    <link href="http://www.walgreens.com/locator/walgreens-1607+shattuck+ave-berkeley-ca-94709/id=13858">
      <text>Walgreens Store Locator</text>
    </link>
  </wpt>
  <wpt lat="37.878411" lon="-122.267708">
    <name>Berkeley Rose School</name>
    <desc>A small local school inspired by Waldorf education. Started in 2008, it now has a preschool, two kindergartens, and three grades.</desc>
  </wpt>
  <trk>
    <name>Berkeley Test Walk #1</name>
    <trkseg>
      <trkpt lon="-122.267946" lat="37.878524">
        <ele>78.4</ele>
        <time>2015-12-19T17:22:23.000Z</time>
        <extensions>
          <gpxtpx:TrackPointExtension>
            <gpxtpx:atemp>26.0</gpxtpx:atemp>
          </gpxtpx:TrackPointExtension>
        </extensions>
      </trkpt>
      <trkpt lon="-122.267872" lat="37.878276">
        <ele>77.4</ele>
        <time>2015-12-19T17:22:41.000Z</time>
        <extensions>
          <gpxtpx:TrackPointExtension>
            <gpxtpx:atemp>25.0</gpxtpx:atemp>
          </gpxtpx:TrackPointExtension>
        </extensions>
      </trkpt>
      <trkpt lon="-122.267848" lat="37.878070">
        <ele>76.4</ele>
        <time>2015-12-19T17:23:02.000Z</time>
        <extensions>
          <gpxtpx:TrackPointExtension>
            <gpxtpx:atemp>25.0</gpxtpx:atemp>
          </gpxtpx:TrackPointExtension>
        </extensions>
      </trkpt>
      <trkpt lon="-122.267791" lat="37.877688">
        <ele>75.4</ele>
        <time>2015-12-19T17:23:24.000Z</time>
        <extensions>
          <gpxtpx:TrackPointExtension>
            <gpxtpx:atemp>25.0</gpxtpx:atemp>
          </gpxtpx:TrackPointExtension>
        </extensions>
      </trkpt>
```
<sup>Showing 49 of 306 lines. The full GPX file contains 2 waypoints, 2 tracks ("Berkeley Test Walk #1" and "#2") with 4 segments, and 31 trackpoints recording two walks in Berkeley, CA from December 2015.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Per-Track Split** | Split this GPX into separate files per track, named walk_1.gpx, walk_2.gpx etc. Assign each waypoint to the geographically closest track's file. Keep the same namespace declarations. | Merge these individual walk GPX files back into a single file called berkeley_walks.gpx. List all waypoints first (ordered by longitude, westernmost first), then the tracks ordered by walk number. | split & merge, classification, sorting |
| 2 | **CSV Export** | Export this GPX to CSV files for spreadsheet analysis. Trackpoints go in one CSV with track name and segment number columns, waypoints in a separate CSV. Preserve the GPX metadata like creator and version as comments at the top. | Convert these CSV files into a single GPX 1.1 XML file called berkeley_walks.gpx. Reconstruct the track/segment hierarchy from the track_name and segment columns, and use Garmin trackpoint extensions for the temperature readings. | format knowledge |
| 3 | **Track Consolidation** | Consolidate all walk tracks into a single chronological track. Merge segments where the time gap is under 2 minutes, start a new segment at longer gaps. Add waypoint markers at absorbed segment boundaries noting the pause location. Include the existing track names and segment structure in the track description. | Split this consolidated track into separate named walk tracks. The track description has the track names and segment point counts, and the segment break waypoints mark where to place segment boundaries within each walk. Drop the consolidation metadata and marker waypoints. | constraint satisfaction, context expansion |
| 4 | **Elevation Annotation** | For each track, compute elevation stats (total gain, total loss, min, max, average elevation) and add them as extensions in the track element. Convert the standalone waypoints to route points — create a route per track, assign each waypoint to the geographically closest track's route as rtept elements, and remove the top-level wpt entries. | Strip out the elevation statistics extensions from each track. Extract all route points from the route elements and put them as top-level waypoints (wpt elements), preserving their names, descriptions, and links. Delete the route elements. | numerical reasoning, constraint satisfaction |
| 5 | **Fahrenheit Conversion** | Convert all temperature readings to Fahrenheit and rename each track to the date its trackpoints fall on (YYYY-MM-DD format). Store the current track names in each track's description element. | Switch the temperature values to Celsius. Set each track's name from its current description text, then remove the description elements from the tracks. | numerical reasoning, string manipulation |
| 6 | **Trail Report** | Turn this GPX into a publishable trail report. Create berkeley_trail_report.md replacing the GPX file. At the top, a YAML code block with the GPX metadata (version, creator, namespace URIs, schema locations). Then a "Points of Interest" section with each waypoint as a subsection — coordinates, description, and any links in markdown syntax. For each walk, a section with walk name, summary line (date, elevation range, temp range), then each segment's trackpoints in a pipe-delimited table in a fenced code block. Keep all numeric values and timestamps exactly as-is. | Convert this trail report into a GPX 1.1 file named berkeley_walks.gpx. Reconstruct the GPX root from the YAML metadata block with all namespaces and schema locations. Each waypoint subsection becomes a wpt element with name, lat/lon, desc, and link. Each walk section becomes a trk, each segment table a trkseg with trkpt elements including ele, time, and Garmin TrackPointExtension atemp. Preserve all values and timestamps exactly. | format knowledge, context expansion |
