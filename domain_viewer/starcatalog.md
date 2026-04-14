# <img src="../assets/domain_icons/starcatalog.svg" width="28" height="28" style="vertical-align: middle;"> Star Catalog

**Category:** Science &amp; Engineering
**File format:** `.xml`
**Summary:** VOTable astronomical catalog data with XML schema and tabular records
**Work environments released:** 6 / 6

VOTable star catalog files use the [IVOA VOTable](https://www.ivoa.net/documents/VOTable/) XML standard for astronomical data interchange. Each file contains RESOURCE elements with metadata (IVOID, creator, citation), COOSYS coordinate-system definitions, TABLE elements with typed FIELD definitions (including UCD, datatype, unit, precision), and TABLEDATA rows of star records. This domain tests an LLM's ability to manipulate structured scientific XML — splitting and merging resources, regrouping fields, normalizing tables, computing summary statistics, and classifying rows by astrophysical properties.

**Domain implementation:** [`domain_starcatalog.py`](../domains/domain_starcatalog.py)

---

## Evaluation

The star catalog domain evaluator parses VOTable XML using `xml.etree.ElementTree` and scores reconstruction quality across six dimensions:

- **Field coverage (15%)** — Are all FIELD elements present? (Jaccard similarity on field names)
- **Field attribute accuracy (10%)** — Are datatype, UCD, unit, and arraysize correct for matched fields?
- **Row coverage (20%)** — Are all data rows present? (Jaccard on primary-key IDs)
- **Row accuracy (35%)** — Are cell values correct? (Numeric tolerance for float/double types)
- **Metadata score (10%)** — Are RESOURCE description, COOSYS attributes, and TABLE description preserved?
- **Row order score (10%)** — Is the original row ordering maintained? (Sequence matching on IDs)

**Score formula:** Weighted linear sum of all six components.

---

## Example Work Environment: `starcatalog1`

**Document:** Hipparcos Stellar Catalog Excerpt (HIP 70001-70030)
**Source:** [CDS VizieR I/239](https://cdsarc.cds.unistra.fr/viz-bin/cat/I/239) (Public domain (ESA) and VizieR free for scientific use)
**Size:** 96 lines · 3,952 tokens

### Seed Document Excerpt (`hipparcos_excerpt.xml`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<VOTABLE version="1.4" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns="http://www.ivoa.net/xml/VOTable/v1.3"
  xsi:schemaLocation="http://www.ivoa.net/xml/VOTable/v1.3 http://www.ivoa.net/xml/VOTable/v1.3">
<RESOURCE ID="yCat_1239" name="I/239" type="results">
  <DESCRIPTION>The Hipparcos and Tycho Catalogues (ESA 1997)</DESCRIPTION>
  <INFO name="ivoid" value="ivo://cds.vizier/i/239">
    IVOID of underlying data collection  </INFO>
  <INFO name="creator" value="ESA 1997">
    First author or institution  </INFO>
  <INFO name="cites" value="1997HIP...C......0E">
    Article or Data origin sources  </INFO>

  <COOSYS ID="H_1991.250" system="ICRS" epoch="1991.250"/>
  <TABLE ID="I_239_hip_main" name="I/239/hip_main">
    <DESCRIPTION>The Hipparcos Main Catalogue</DESCRIPTION>

    <FIELD name="HIP" ucd="meta.id;meta.main" datatype="int" width="6">
      <DESCRIPTION>Identifier (HIP number) (H1)</DESCRIPTION>
    </FIELD>
    <FIELD name="RAhms" ucd="pos.eq.ra" datatype="char" arraysize="11">
      <DESCRIPTION>Right ascension in h m s, ICRS (J1991.25) (H3)</DESCRIPTION>
    </FIELD>
    <FIELD name="DEdms" ucd="pos.eq.dec" datatype="char" arraysize="11">
      <DESCRIPTION>Declination in deg ' ", ICRS (J1991.25) (H4)</DESCRIPTION>
    </FIELD>
    <FIELD name="Vmag" ucd="phot.mag;em.opt.V" datatype="float" width="5" precision="2" unit="mag">
      <DESCRIPTION>? Magnitude in Johnson V (H5)</DESCRIPTION>
    </FIELD>
    <FIELD name="Plx" ucd="pos.parallax.trig" datatype="float" width="7" precision="2" unit="mas">
      <DESCRIPTION>? Trigonometric parallax (H11)</DESCRIPTION>
    </FIELD>
    <FIELD name="pmRA" ucd="pos.pm;pos.eq.ra" datatype="double" width="8" precision="2" unit="mas/yr">
      <DESCRIPTION>*? Proper motion mu_alpha.cos(delta), ICRS(H12)</DESCRIPTION>
    </FIELD>
    <FIELD name="pmDE" ucd="pos.pm;pos.eq.dec" datatype="double" width="8" precision="2" unit="mas/yr">
      <DESCRIPTION>*? Proper motion mu_delta, ICRS (H13)</DESCRIPTION>
    </FIELD>
    <FIELD name="B-V" ucd="phot.color;em.opt.B;em.opt.V" datatype="float" width="6" precision="3" unit="mag">
      <DESCRIPTION>? Johnson B-V colour (H37)</DESCRIPTION>
    </FIELD>
    <FIELD name="SpType" ucd="src.spType" datatype="char" arraysize="12*">
      <DESCRIPTION>Spectral type (H76)</DESCRIPTION>
    </FIELD>
    <FIELD name="e_Plx" ucd="stat.error;pos.parallax" datatype="float" width="6" precision="2" unit="mas">
      <DESCRIPTION>? Standard error in Plx (H16)</DESCRIPTION>
    </FIELD>
<DATA><TABLEDATA>
<TR><TD>70001</TD><TD>14 19 26.51</TD><TD>-75 10 45.3</TD><TD>7.72</TD><TD>5.20</TD><TD>-28.62</TD><TD>-14.78</TD><TD>0.059</TD><TD>B9/B9.5V</TD><TD>0.66</TD></TR>
<TR><TD>70002</TD><TD>14 19 26.96</TD><TD>-00 00 48.0</TD><TD>7.79</TD><TD>0.47</TD><TD>-18.92</TD><TD>-6.96</TD><TD>1.314</TD><TD>K2</TD><TD>0.99</TD></TR>
<TR><TD>70003</TD><TD>14 19 27.24</TD><TD>+37 36 36.2</TD><TD>8.09</TD><TD>7.56</TD><TD>-48.37</TD><TD>-33.18</TD><TD>0.920</TD><TD>G7III</TD><TD>0.94</TD></TR>
<TR><TD>70004</TD><TD>14 19 27.66</TD><TD>-04 06 20.1</TD><TD>9.92</TD><TD>-2.39</TD><TD>0.22</TD><TD>0.55</TD><TD>1.648</TD><TD>M3</TD><TD>1.92</TD></TR>
<TR><TD>70005</TD><TD>14 19 28.35</TD><TD>-24 15 40.8</TD><TD>9.08</TD><TD>3.36</TD><TD>-14.47</TD><TD>0.58</TD><TD>0.944</TD><TD>G8IV</TD><TD>1.21</TD></TR>
```
<sup>Showing 50 of 96 lines. The full catalog contains 30 star records (HIP 70001–70030) with coordinates, photometry, parallax, proper motion, and spectral types.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Spectral Class Split** | Split this catalog into two RESOURCE blocks by stellar temperature: one for early-type stars (spectral classes B, A, F) and one for late-type stars (G, K, M). Classify each star by the leading letter of its SpType field; put entries with missing spectral type in the late-type group. Each RESOURCE should have a DESCRIPTION indicating which spectral classes it covers. Keep the catalog INFO elements and COOSYS in the first RESOURCE only. | Merge the two spectral-class RESOURCE blocks into a single RESOURCE with one TABLE. Combine all rows, sorted by HIP number ascending. RESOURCE DESCRIPTION 'The Hipparcos and Tycho Catalogues (ESA 1997)', TABLE ID='I_239_hip_main', name='I/239/hip_main', DESCRIPTION 'The Hipparcos Main Catalogue'. Include all the catalog INFO elements and COOSYS in the RESOURCE. | split & merge, classification, sorting |
| 2 | **Semantic Field Grouping** | Reorganize the VOTable to use GROUP elements for semantic field grouping. Create three groups: 'Positional' (RAhms, DEdms), 'Kinematics' (Plx, e_Plx, pmRA, pmDE), and 'Photometry' (Vmag, B-V, SpType). HIP stays outside any group as the row identifier. Reorder fields and data to follow group order. Each GROUP should have a name and description attribute. | Remove all GROUP elements and reorder fields to: HIP, RAhms, DEdms, Vmag, Plx, pmRA, pmDE, B-V, SpType, e_Plx. | string manipulation |
| 3 | **Table Normalization** | Normalize this into two tables inside the same RESOURCE. The first table (ID='astrometry') should have fields HIP, RAhms, DEdms, Plx, e_Plx, pmRA, pmDE with rows sorted by parallax descending. The second table (ID='photometry') should have fields HIP, Vmag, B-V, SpType with rows sorted by Vmag ascending. Keep all resource-level metadata. Add a DESCRIPTION to each table saying what data domain it covers. | Join the astrometry and photometry tables into one TABLE on the HIP key. Field order: HIP, RAhms, DEdms, Vmag, Plx, pmRA, pmDE, B-V, SpType, e_Plx. Sort rows by HIP ascending. TABLE ID='I_239_hip_main', name='I/239/hip_main', description 'The Hipparcos Main Catalogue'. Keep all field attributes exactly as they are. | split & merge, sorting |
| 4 | **Hemisphere Split** | Using only the rows from `hipparcos_excerpt.xml`, split that catalog into two new observing-list files by hemisphere: create `targets_north.xml` containing stars with declination >= 0° and `targets_south.xml` containing stars with declination < 0°. In each new file, sort the table rows by Vmag ascending (brightest first). Each output must be a complete standalone VOTable. | Merge the two hemisphere files into a single hipparcos_excerpt.xml with all rows sorted by HIP number ascending. TABLE ID='I_239_hip_main', name='I/239/hip_main', DESCRIPTION 'The Hipparcos Main Catalogue'. Keep all RESOURCE-level metadata. | split & merge, numerical reasoning, sorting |
| 5 | **Summary Statistics** | Add PARAM elements inside the TABLE with summary statistics. Compute minimum, maximum, and median for each of Vmag, Plx, pmRA, pmDE, B-V, and e_Plx. Name them like stat_Vmag_min, stat_Vmag_max, stat_Vmag_median, etc., with datatype matching the corresponding field. Then sort all data rows by B-V color index ascending. | Remove all the stat PARAM elements from the TABLE. Re-sort the data rows by HIP number ascending. | numerical reasoning, sorting |
| 6 | **Distance Bin Split** | Create two TABLE elements inside the RESOURCE: 'nearby' for stars with Plx >= 5 mas and 'distant' for stars with Plx < 5 mas (including negative values). Give each TABLE a name attribute matching those labels and an INFO child element stating the parallax range it covers. Sort rows within each TABLE by right ascension. Preserve the RESOURCE-level metadata. | Merge the two distance-bin TABLEs into a single TABLE with ID 'I_239_hip_main', name 'I/239/hip_main', and description 'The Hipparcos Main Catalogue'. Remove the per-bin INFO elements that describe parallax ranges. Sort all rows by HIP number ascending. Keep all RESOURCE-level metadata intact. | split & merge, numerical reasoning, classification, sorting |
