# <img src="../assets/domain_icons/landmarks.svg" width="28" height="28" style="vertical-align: middle;"> Landmarks

**Category:** Everyday
**File format:** `.kml`
**Summary:** KML/GeoJSON points of interest with coordinates, addresses, and descriptions
**Work environments released:** 6 / 6

KML landmark files use the [OGC KML](https://www.ogc.org/standard/kml/) geospatial markup format to represent points of interest. Each placemark contains a name, geographic coordinates, and ExtendedData fields (address, overview description, opening hours) stored in a SchemaData structure. This domain tests an LLM's ability to manipulate structured geospatial data — splitting by category or accessibility, converting between formats, reorganizing by district or distance, and extracting structured fields across dozens of placemarks.

**Domain implementation:** [`domain_landmarks.py`](../domains/domain_landmarks.py)

---

## Evaluation

The landmarks domain evaluator parses KML and GeoJSON files, then scores reconstruction quality across four dimensions:

- **Placemark coverage** — Are all original placemarks present? (Jaccard similarity on name fingerprints)
- **Field accuracy** — Are name, address, overview, and opening hours preserved? (Levenshtein sequence matching)
- **Coordinate accuracy** — Are GPS coordinates correct? (Precision tolerance of ~11 meters / 0.0001°)
- **Ordering score** — Are placemarks in the correct sequence? (By placemark ID)

**Score formula:** `coverage² × accuracy × √((coord + ordering) / 2)`

---

## Example Work Environment: `landmarks1`

**Document:** Singapore Tourist Attractions
**Source:** [data.gov.sg](https://data.gov.sg/collections/1621/view) (Singapore Open Data Licence)
**Size:** 397 lines · 4,539 tokens

### Seed Document Excerpt (`attractions.kml`)

```xml
<?xml version='1.0' encoding='UTF-8'?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
<name>TOURISM</name>
<visibility>1</visibility>
<Schema name="TOURISM" id="kml_schema_ft_TOURISM">
<SimpleField type="xsd:string" name="ADDRESS">
<displayName>ADDRESS</displayName>
</SimpleField>
<SimpleField type="xsd:string" name="OVERVIEW">
<displayName>OVERVIEW</displayName>
</SimpleField>
<SimpleField type="xsd:string" name="OPENING_HOURS">
<displayName>OPENING_HOURS</displayName>
</SimpleField>
</Schema>
<Folder id="kml_ft_TOURISM">
<name>TOURISM</name>
<Placemark id="poi_1">
<name>National Gallery Singapore</name>
<ExtendedData>
<SchemaData schemaUrl="#kml_schema_ft_TOURISM">
<SimpleData name="ADDRESS">1 St Andrew's Road</SimpleData>
<SimpleData name="OVERVIEW">Take in the region's newest and largest museum of modern Singapore and Southeast Asian art housed within two of Singapore's awe-inspiring national monuments.</SimpleData>
<SimpleData name="OPENING_HOURS">Effective from 24 November 2015, Sunday to Thursday and public holidays,10am - 7pm ,Friday to Saturday and eve of public holidays, 10am - 10pm</SimpleData>
</SchemaData>
</ExtendedData>
<Point>
<coordinates>103.85136,1.29,0.0</coordinates>
</Point>
</Placemark>
<Placemark id="poi_2">
<name>Sultan Mosque (Masjid Sultan) Singapore</name>
<ExtendedData>
<SchemaData schemaUrl="#kml_schema_ft_TOURISM">
<SimpleData name="ADDRESS">3 Muscat Street</SimpleData>
<SimpleData name="OVERVIEW">Also known as Masjid Sultan, the impressive Sultan Mosque in historic Kampong Glam is the focal point for Singapore's Muslim community.</SimpleData>
<SimpleData name="OPENING_HOURS">Monday to Sunday:9.30am - 12pm and 2pm - 4pm ,Friday:2.30pm - 4pm</SimpleData>
</SchemaData>
</ExtendedData>
<Point>
<coordinates>103.85917,1.302,0.0</coordinates>
</Point>
</Placemark>
<Placemark id="poi_3">
<name>Sri Mariamman Temple: Hindu Temple in Singapore</name>
<ExtendedData>
<SchemaData schemaUrl="#kml_schema_ft_TOURISM">
<SimpleData name="ADDRESS">244 South Bridge Road</SimpleData>
<SimpleData name="OVERVIEW">Located in Chinatown, the Sri Mariamman Temple dates back to 1827 and is the oldest Hindu temple in Singapore.</SimpleData>
<SimpleData name="OPENING_HOURS">Daily from 7am - 12pm, and 6pm - 9pm</SimpleData>
</SchemaData>
</ExtendedData>
<Point>
<coordinates>103.84538,1.282,0.0</coordinates>
</Point>
</Placemark>
<Placemark id="poi_4">
<name>Armenian Church in Singapore</name>
<ExtendedData>
<SchemaData schemaUrl="#kml_schema_ft_TOURISM">
<SimpleData name="ADDRESS">60 Hill Street</SimpleData>
<SimpleData name="OVERVIEW">The oldest Christian church in Singapore is an architectural masterpiece from the early 19th century.</SimpleData>
<SimpleData name="OPENING_HOURS">Daily, 9am -6pm</SimpleData>
</SchemaData>
</ExtendedData>
<Point>
<coordinates>103.84966,1.293,0.0</coordinates>
</Point>
</Placemark>
```
<sup>Showing 4 of 30 placemarks. The full KML contains 30 Singapore tourist attractions with coordinates, addresses, overviews, and opening hours.</sup>

---

### Edit Tasks (9 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Accessibility Split** | I'm traveling with my elderly grandparents who have mobility issues. Split the attractions into accessible.kml (likely wheelchair-friendly) and limited_access.kml (likely challenging). | Merge accessible.kml and limited_access.kml into a single attractions.kml, ordered by placemark ID. | split & merge, classification, domain knowledge |
| 2 | **Distance Sort** | My hotel is near Gardens by the Bay at coordinates (103.86361, 1.282). Sort the attractions from closest to farthest from that location. | Sort the attractions by their placemark ID number. | numerical reasoning, sorting |
| 3 | **Category Split** | Split the attractions into separate files by category: religious.kml, museums.kml, landmarks.kml, outdoor.kml, and other.kml. | Merge all category files into a single attractions.kml. Sort placemarks by ID number and put everything in a single TOURISM folder. | split & merge, classification |
| 4 | **GeoJSON Conversion** | Convert this KML to GeoJSON format as attractions.geojson. Keep all metadata as feature properties. | Convert to KML as attractions.kml using ExtendedData/SchemaData structure. | format knowledge |
| 5 | **District Organization** | Organize the attractions into KML folders by Singapore district: Civic District, Chinatown, Kampong Glam, Little India, Marina Bay, and Other. | Flatten the district folder structure to a single TOURISM folder. Keep placemarks ordered by their ID. | classification |
| 6 | **Evening Split** | I'm at a work conference and only free after 6pm on weekdays. Split into evening_friendly.kml and daytime_only.kml. | Merge evening_friendly.kml and daytime_only.kml into attractions.kml, ordered by placemark ID. | split & merge, classification |
| 7 | **Guide Extraction** | Using ONLY the placemarks in `attractions.kml` as the source of truth, create two new files: 1) `guide.md`: a travel guide with one section per attraction, organized alphabetically by attraction name. Each section should include the attraction name as a heading and its ADDRESS / OVERVIEW / OPENING_HOURS values if present. 2) `coordinates.csv`: a CSV with header `id,name,longitude,latitude`, containing one row per placemark from `attractions.kml`. Do not incorporate, merge, or copy content from any other files in the workspace. | Reconstruct attractions.kml from guide.md and coordinates.csv using Schema and ExtendedData/SchemaData structure, ordered by placemark ID. | format knowledge, context expansion |
| 8 | **LookAt & Latitude Sort** | Add a &lt;LookAt&gt; element to every Placemark using its coordinates — altitude 0, heading 0, tilt 60, range 300, altitudeMode relativeToGround. Re-sort placemarks south-to-north by latitude. | Remove all &lt;LookAt&gt; elements and sort placemarks by their ID number. | numerical reasoning, sorting |
| 9 | **Contact Field Extraction** | Add new Schema fields CONTACT_EMAIL, CONTACT_PHONE, CONTACT_URL. Extract any contact info from OPENING_HOURS into those fields. Rename OPENING_HOURS to OPENING_HOURS_RAW and add OPENING_HOURS_CLEAN with just the schedule info. | Remove CONTACT_EMAIL, CONTACT_PHONE, CONTACT_URL from Schema and all Placemarks. Rename OPENING_HOURS_RAW to OPENING_HOURS and drop OPENING_HOURS_CLEAN. | string manipulation, domain knowledge |
