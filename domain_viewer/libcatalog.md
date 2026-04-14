# <img src="../assets/domain_icons/libcatalog.svg" width="28" height="28" style="vertical-align: middle;"> Library Catalog

**Category:** Structured Records
**File format:** `.xml`
**Summary:** MARCXML library catalog records with bibliographic data
**Work environments released:** 4 / 6

MARCXML library catalog files use the [MARC 21](https://www.loc.gov/marc/) XML serialization for machine-readable bibliographic records. Each record consists of a 24-character leader encoding material type and encoding level, control fields (001–009) with fixed-length metadata like control numbers and dates, and data fields (010+) with indicators and coded subfields carrying titles, authors, subjects, publishers, and holdings information. This domain tests an LLM's ability to manipulate structured cataloging data — splitting and merging collections, converting between MARC formats, reorganizing fields, and performing string and numerical transformations on bibliographic metadata across multiple records.

**Domain implementation:** [`domain_libcatalog.py`](../domains/domain_libcatalog.py)

---

## Evaluation

The library catalog domain evaluator parses MARCXML records using `pymarc` and scores reconstruction quality across four dimensions:

- **Record coverage** — Are all original records present? (Uses Jaccard similarity on 001 control numbers)
- **Leader accuracy** — Are the 24-character MARC leaders preserved? (Character-level comparison)
- **Control field accuracy** — Are control fields (001–009) preserved? (Tag-level exact/fuzzy matching)
- **Data field accuracy** — Are data fields (010+) preserved with correct indicators and subfields? (Field-count-weighted per-tag greedy matching using SequenceMatcher)

**Score formula:** `coverage × (0.05 × leader + 0.05 × control_fields + 0.90 × data_fields)`

---

## Example Work Environment: `libcatalog2`

**Document:** NIST NCSTAR Building Safety Investigation Reports
**Source:** [usgpo/cataloging-records](https://github.com/usgpo/cataloging-records) (US government works — public domain)
**Size:** 264 lines · 4,934 tokens

### Seed Document Excerpt (`catalog.xml`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<collection xmlns:ns0="http://www.loc.gov/MARC21/slim" xmlns="http://www.loc.gov/MARC21/slim" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.loc.gov/MARC21/slim http://www.loc.gov/standards/marcxml/schema/MARC21slim.xsd">
  <ns0:record>
    <ns0:leader>01910aam a2200433Ii 4500</ns0:leader>
    <ns0:controlfield tag="001">001079091</ns0:controlfield>
    <ns0:controlfield tag="005">20181120173213.0</ns0:controlfield>
    <ns0:controlfield tag="008">131125s2014    mdu     ot   f000 0 eng d</ns0:controlfield>
    <ns0:datafield tag="024" ind1="8" ind2=" ">
      <ns0:subfield code="a">GOVPUB-C13-a0ac8adb5269166f1b1e230423cf79ec</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="035" ind1=" " ind2=" ">
      <ns0:subfield code="a">(OCoLC)863997930</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="040" ind1=" " ind2=" ">
      <ns0:subfield code="a">NBS</ns0:subfield>
      <ns0:subfield code="b">eng</ns0:subfield>
      <ns0:subfield code="e">pn</ns0:subfield>
      <ns0:subfield code="e">rda</ns0:subfield>
      <ns0:subfield code="c">NBS</ns0:subfield>
      <ns0:subfield code="d">GPO</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="074" ind1=" " ind2=" ">
      <ns0:subfield code="a">0244 (online)</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="086" ind1="0" ind2=" ">
      <ns0:subfield code="a">C 13.2:3</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="090" ind1=" " ind2=" ">
      <ns0:subfield code="a">TH443</ns0:subfield>
      <ns0:subfield code="b">.N35 no.3 2013</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="245" ind1="0" ind2="0">
      <ns0:subfield code="a">Final report, National Institute of Standards and Technology (NIST) :</ns0:subfield>
      <ns0:subfield code="b">technical investigation of the May 22, 2011 tornado in Joplin, Missouri /</ns0:subfield>
      <ns0:subfield code="c">Erica D. Kuligowski, Franklin T. Lombardo, Long T. Phan, Marc L. Levitan, David P. Jorgensen .</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="264" ind1=" " ind2="1">
      <ns0:subfield code="a">Gaithersburg, MD :</ns0:subfield>
      <ns0:subfield code="b">U.S. Dept. of Commerce, National Institute of Standards and Technology,</ns0:subfield>
      <ns0:subfield code="c">2014.</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="300" ind1=" " ind2=" ">
      <ns0:subfield code="a">1 online resource (494 pages) :</ns0:subfield>
      <ns0:subfield code="b">illustrations (color).</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="336" ind1=" " ind2=" ">
      <ns0:subfield code="a">text</ns0:subfield>
      <ns0:subfield code="2">rdacontent</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="337" ind1=" " ind2=" ">
      <ns0:subfield code="a">computer</ns0:subfield>
      <ns0:subfield code="2">rdamedia</ns0:subfield>
    </ns0:datafield>
    <ns0:datafield tag="338" ind1=" " ind2=" ">
      <ns0:subfield code="a">online resource</ns0:subfield>
      <ns0:subfield code="2">rdacarrier</ns0:subfield>
    </ns0:datafield>
```
<sup>Showing 50 of 264 lines. The full collection contains 2 NIST NCSTAR investigation report records covering the 2011 Joplin tornado and WTC 7 structural analysis, with MARC fields for government document classification, series statements, subject headings, and electronic access URLs.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **URL Referencing** | Extract all URLs from the 856 $u subfields into a `url_registry.tsv` file with tab-separated columns: ref_id (URL-001, URL-002, etc.), control_number, ind1, ind2, url. Assign ref_ids in document order. In `catalog.xml`, replace each URL value in 856 $u with its corresponding ref_id token. | Restore each 856 $u reference token (URL-001, etc.) in `catalog.xml` with the actual URL from `url_registry.tsv`. Delete `url_registry.tsv`. | referencing |
| 2 | **Contributor Index** | Convert all personal name entries in 100 and 700 fields from inverted MARC form (Last, First M.) to direct display order (First M. Last). Create a `contributors.tsv` with tab-separated columns: display_name, original_form, marc_tag, record_control_numbers. | Convert all personal names in 100 and 700 fields back to inverted MARC form using the original_form column in `contributors.tsv`. Delete `contributors.tsv`. | string manipulation, referencing |
| 3 | **Temporal Classification** | Classify each record by publication era. Extract the publication year from 008 positions 7–10 and compute years elapsed since 2025. Add a 991 local field with decade label, years since publication, age category, and position. Sort records by publication year ascending. | Reorder the records by the position number stored in 991 $d. Remove all 991 fields. | numerical reasoning, classification, sorting |
| 4 | **Topic Enrichment** | Enrich the catalog records with topic metadata. Add LCSH-style 650 subject heading fields where missing, add 520 summary fields with synthesized abstracts, and merge consecutive 500 note fields using ' -- ' delimiter. | Split each merged 500 note field back into separate fields. Remove all 520 summary fields. Remove added 650 subject heading fields. | topic modeling, context expansion |
| 5 | **Abbreviated Responsibility** | Apply the AACR2 'rule of three' to the 245 $c statement of responsibility: if more than 3 names, keep only the first 3 and append ' [et al.]'. Save complete text in `responsibility_statements.txt`. | Replace each 245 $c that contains '[et al.]' with the full text from `responsibility_statements.txt`. Delete `responsibility_statements.txt`. | constraint satisfaction, referencing |
| 6 | **Series Split** | Split `catalog.xml` into individual MARCXML collection files named by NCSTAR report number (e.g., `ncstar_3.xml`). Create `index.txt` with position, control_number, ncstar_number, and filename. | Merge the per-report files back into a single `catalog.xml` ordered by `index.txt` position. Delete `index.txt` and the individual files. | split & merge, sorting |
