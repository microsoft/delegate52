# <img src="../assets/domain_icons/geodata.svg" width="28" height="28" style="vertical-align: middle;"> Geodata

**Category:** Structured Records
**File format:** `.geojson`
**Summary:** GeoJSON geographic feature collections with coordinates, properties, and metadata
**Work environments released:** 3 / 6

GeoJSON files conform to [RFC 7946](https://datatracker.ietf.org/doc/html/rfc7946) and represent geographic features as structured FeatureCollection objects. Each Feature contains a geometry (points, lines, polygons with coordinates) and a properties object holding arbitrary metadata. This domain tests an LLM's ability to manipulate geographic data — splitting by classification, converting formats, computing distances, clustering by proximity, and annotating features while preserving coordinate precision and nested property structures.

**Domain implementation:** [`domain_geodata.py`](../domains/domain_geodata.py)

---

## Evaluation

The geodata domain evaluator parses FeatureCollection structures using Python's `json` module and scores reconstruction quality across five dimensions:

- **Feature coverage** — Are all original features present? (Jaccard on feature fingerprints keyed by `id` property)
- **Property accuracy** — Are all properties preserved correctly? (Recursive comparison including nested objects, strings via SequenceMatcher, numbers via ratio similarity)
- **Coordinate accuracy** — Are geographic coordinates precise? (Centroid comparison for Points with tolerance tiers: <0.0001° = perfect, <0.001° = 0.9, <0.01° = 0.5)
- **Feature ordering** — Are features in the correct sequence? (SequenceMatcher on fingerprint sequences)
- **Metadata score** — Are collection-level attributes preserved? (type, crs, bbox)

**Score formula:** `coverage² × property_accuracy × √(mean(coord_accuracy, ordering, metadata))`

---

## Example Work Environment: `geodata1`

**Document:** Bexhill Heritage Landmarks
**Source:** [Dr-Mx/bexhill-osm](https://github.com/Dr-Mx/bexhill-osm/blob/master/web/tour/itemThenNow/thennow.geojson) (GPL-2.0 License)
**Size:** 526 lines · 4,536 tokens

### Seed Document Excerpt (`landmarks.geojson`)

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "id": "kincardine",
        "date": "1960",
        "imgcaption": {
          "1": "Kincardine, Brassey Road",
          "2": "Now in 2024",
          "3": "Then in 1960 | Bexhill Museum"
        },
        "desc": "This Victorian house still has many of its period features and can easily be missed today as it has become an extension of the Normanhurst Care Home."
      },
      "geometry": {
        "type": "Point",
        "coordinates": [
          0.47839,
          50.83874
        ]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "id": "stgeorge",
        "date": "1920",
        "imgcaption": {
          "1": "St George's Theatre, Town Hall Square",
          "2": "Now in 2022",
          "3": "Then in c1920 | Bexhill Museum"
        },
        "desc": "Designed by J.B. Wall for the adjacent Castle Hotel (now The Town House). Opening in 1910 it was originally called the Bijou Cinema. Later taken over by a new operator and renamed New Palace Theatre in 1915. In 1917 it was renamed St. Georges Cinema. In 1949, again under new owners, it was renamed Savoy Cinema. The cinema was closed in 1954 and was used as a shop until its demolition in 1993."
      },
      "geometry": {
        "type": "Point",
        "coordinates": [
          0.47061,
          50.84125
        ]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "id": "riposo",
        "date": "1930",
        "imgcaption": {
          "1": "Riposo Hotel, De La Warr Parade",
          "2": "Now in 2021",
          "3": "Then in c1930 | Bexhill Museum"
        },
        "desc": "This Neo-Gothic hotel sat on the corner of Dorset Road South between 1901-1961. It served 39 rooms, mostly to keen golfers on The Links course to the east. Today demolished and replaced with Cavendish Court."
      },
```
<sup>Showing 55 of 526 lines. The full GeoJSON contains 26 heritage landmarks from Bexhill-on-Sea, East Sussex, UK, each with Point geometry, historical dates, nested image captions, and rich descriptive narratives.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Era Split** | Split the landmarks into separate GeoJSON files by historical era based on the date field: Victorian (before 1901), Edwardian (1901–1913), Interwar (1914–1938), and WWII/Postwar (1939 onward). For approximate dates like "1900s" or "1960s" use the leading year. Add a `manifest.json` with the full feature ordering by id and which era file each landmark went to. | Merge all the era GeoJSON files back into a single `landmarks.geojson` FeatureCollection, using the ordering in `manifest.json` to place features in the correct sequence. Drop the manifest and individual era files. | split & merge, classification, sorting |
| 2 | **Heritage Classification** | Split the landmarks into separate GeoJSON files based on heritage function: entertainment, residential/hospitality, transport/infrastructure, civic/commercial. Categorize each feature from its description and create a `feature_order.csv` with columns position, id, category. | Merge all the category GeoJSON files back into a single `landmarks.geojson` FeatureCollection. Use `feature_order.csv` to restore the feature ordering by position number. Drop the CSV and category files. | split & merge, classification, sorting |
| 3 | **Flatten & Annotate** | Flatten the `imgcaption` objects — promote each numbered entry to a top-level property like `caption_1`, `caption_2`, etc. Add an `original_order` property (0-indexed) to each feature. Infer a `status` property from the description — use "standing", "demolished", "ruin", or "converted". Sort features chronologically by date (oldest first). | Re-nest the `caption_N` properties into an `imgcaption` object with numbered string keys. Reorder features by `original_order` ascending. Remove the `status` and `original_order` properties. | string manipulation, domain knowledge, sorting |
| 4 | **Walking Tour** | Reorganize as a walking tour. Sort features by nearest-neighbor starting from the southernmost landmark. Add properties: `tour_stop` (1–26), `original_position`, `walking_notes` (direction hint), and `distance_from_previous` (haversine meters). Prepend each desc with `[Stop N — Xm]`. | Strip the walking tour formatting. Remove `tour_stop`, `walking_notes`, `distance_from_previous`, and `original_position` properties. Remove the `[Stop ...]` prefix from each desc. Reorder features by `original_position`. | sorting, context expansion, numerical reasoning |
| 5 | **CSV Conversion** | Convert the GeoJSON into a flat CSV (`landmarks.csv`) with columns: id, lat, lon, date, desc, caption_1–caption_5. Extract lat/lon from geometry and flatten `imgcaption`. Create a `collection_metadata.json` storing the GeoJSON structure info and a schema mapping each CSV column to its property path. | Reconstruct a GeoJSON FeatureCollection (`landmarks.geojson`) from the CSV and metadata. Each row becomes a Feature with Point geometry; `imgcaption` is re-nested from caption columns. | format knowledge, string manipulation |
| 6 | **Proximity Clusters** | Cluster landmarks by proximity into 3–5 groups with descriptive names based on Bexhill geography (e.g., `seafront.geojson`, `town_centre.geojson`). Add `cluster_centroid` and `distance_to_centroid` (haversine meters) properties. Create a `clusters.json` manifest with each cluster's name, centroid, member IDs, and an `original_ordering` array. | Merge all cluster GeoJSON files back into `landmarks.geojson`. Use `original_ordering` in `clusters.json` to restore feature sequence. Strip `cluster_centroid` and `distance_to_centroid` properties. | topic modeling, split & merge, numerical reasoning, sorting |
