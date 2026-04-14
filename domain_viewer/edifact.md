# <img src="../assets/domain_icons/edifact.svg" width="28" height="28" style="vertical-align: middle;"> EDIFACT

**Category:** Structured Records
**File format:** `.edi`
**Summary:** UN/EDIFACT supply chain messages (ORDERS, ORDRSP, INVOIC, DESADV, PRICAT)
**Work environments released:** 4 / 6

EDIFACT interchange files use the [UN/EDIFACT](https://unece.org/trade/uncefact/introducing-unedifact) standard for electronic data interchange in international trade. Each interchange contains envelope segments (UNA/UNB/UNZ), functional groups (UNG/UNE), and messages (UNH/UNT) with structured line items identified by EAN codes, quantities, prices, and availability status codes. This domain tests an LLM's ability to manipulate complex segment-based trade messages — splitting, converting, enriching, and reformatting EDIFACT structures while maintaining envelope integrity and segment counts.

**Domain implementation:** [`domain_edifact.py`](../domains/domain_edifact.py)

---

## Evaluation

The EDIFACT domain evaluator parses messages into structured representations using the `pydifact` library and scores reconstruction quality across four dimensions:

- **Message coverage** — Are all ORDRSP messages present? (Matched by order reference RFF+ON, squared as gate)
- **Header accuracy** — Are message type, dates, references, NAD parties, and currency preserved? (20%)
- **Item coverage** — Are all line items present? (Multiplicative gate with exponent 1.2)
- **Item detail accuracy** — Are matched items correct? (80% — EAN 20%, description 20%, quantities 25%, price 15%, availability code 10%, reference 10%)

**Score formula:** `msg_coverage² × item_coverage^1.2 × (0.20 × header + 0.80 × item_detail)`

---

## Example Work Environment: `edifact1`

**Document:** Baker & Taylor Library Book Order Response
**Source:** [evergreen-library-system/Evergreen](https://github.com/evergreen-library-system/Evergreen/blob/main/Open-ILS/src/edi_translator/data/BakerAndTaylor/edifact_sample.ordrsp.edi) (GPL-2.0 License)
**Size:** 331 lines · 3,624 tokens

### Seed Document Excerpt (`order_response.edi`)

```edifact
UNA:+.? '
UNB+UNOC:3+1556150:31B+8888888:31B+070618:1556+2045'
UNG+ORDRSP+1556150:31B+8888888:31B+070618:1556+604+UN+D:96A'
UNH+723+ORDRSP:D:96A:UN'
BGM+231+582822+29+AC'
DTM+137:20070618:102'
RFF+ON:E07158FIC'
NAD+BY+8888888::31B'
NAD+SU+1556150::31B'
NAD+BY+8888888::91'
CUX+2:USD:9'
LIN+1+5+9781576734131:EN'
IMD+F+BST+:::LACY, AL THINGS NOT SEEN'
QTY+21:4'
QTY+12:4'
QTY+85:0'
FTX+LIN++01:8B:28'
PRI+AAB:10.99::SRP'
RFF+LI:4639/1'
LIN+2+5+9781590529966:EN'
IMD+F+BST+:::LACY, AL FINAL JUSTICE'
QTY+21:1'
QTY+12:1'
QTY+85:0'
FTX+LIN++01:8B:28'
PRI+AAB:14.99::SRP'
RFF+LI:4639/2'
LIN+3+5+9780374502003:EN'
IMD+F+BST+:::MALAMUD, B NATURAL'
QTY+21:5'
QTY+12:5'
QTY+85:0'
FTX+LIN++01:8B:28'
PRI+AAB:14::SRP'
RFF+LI:4639/3'
LIN+4+24+9780307263964:EN'
IMD+F+BST+:::SCOTT, PAU RAJ QUARTET THE JEWEL IN'
QTY+21:2'
QTY+12:0'
QTY+83:2'
FTX+LIN++03:8B:28'
PRI+AAB:32.5::SRP'
RFF+LI:4639/4'
LIN+5+5+9780743219600:EN'
IMD+F+BST+:::JAMES, P.  SHROUD FOR A NIGHTINGALE'
QTY+21:4'
QTY+12:4'
QTY+85:0'
FTX+LIN++01:8B:28'
PRI+AAB:14::SRP'
RFF+LI:4639/6'
```
<sup>Showing 51 of 331 lines. The full interchange contains 2 ORDRSP messages: PO E07158FIC (Fiction, 18 line items) and PO E07159ANF (Adult Non-Fiction, 20 line items), with varied fulfillment statuses and prices ranging $9.95–$40.00.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **PO-based Split** | Split `order_response.edi` into one file per order response message, named by PO number (e.g., `E07158FIC.edi`). Each file should be a valid standalone EDIFACT interchange with UNB/UNG/UNE/UNZ enveloping. Create `interchange_manifest.txt` recording the interchange control reference, functional group reference, and ordered list of message PO numbers. | Merge the individual `.edi` files into a single `order_response.edi` interchange, combining both messages in one functional group. Use `interchange_manifest.txt` for the control references and message ordering, then delete the manifest file. | split & merge, format knowledge, sorting |
| 2 | **Fulfillment Status Regrouping** | Reorganize line items in each ORDRSP message by fulfillment status — fully dispatched first, then partially shipped, then fully backordered. Within each group sort by SRP price ascending, breaking ties by ISBN. Renumber LIN positions sequentially. | Reorder line items in each ORDRSP message by their RFF+LI reference, ascending by the numeric suffix after the slash. Renumber LIN positions sequentially. | classification, sorting |
| 3 | **Status Code Annotation + Author Sort** | For each line item, add an FTX+AAA segment after FTX+LIN explaining the availability status code in plain English. Add a MOA+203 segment after each PRI with the line extension (ordered qty × unit price). Sort line items within each message alphabetically by author surname from the IMD field. | Remove all FTX+AAA and MOA+203 segments from the line items, and reorder items by LIN number within each message. | context expansion, numerical reasoning, sorting |
| 4 | **Proforma Invoice Conversion** | Convert these ORDRSP messages into proforma INVOIC format. Change message type from ORDRSP to INVOIC in UNH and UNG. Change BGM code from 231 to 325. For each line item, add MOA+203 after PRI with dispatched qty × unit price. In each UNS+S section, add MOA+86 and MOA+79 as the sum of line MOA+203 amounts. Update UNT counts. | Reformat these INVOIC proforma messages as ORDRSP order responses. Change message type to ORDRSP in UNH and UNG, change BGM code from 325 to 231. Strip all MOA segments and update UNT counts. | numerical reasoning, format knowledge |
| 5 | **Functional Group Unwrapping** | Strip the UNG/UNE functional group wrapper from this interchange. Add an RFF+ABO segment in each message header after the existing RFF line to preserve the group reference. Update UNZ and UNT counts. | Re-wrap both messages in a UNG/UNE functional group envelope. Use the group reference from the RFF+ABO segments to build UNG/UNE. Remove the RFF+ABO segments and update UNZ and UNT counts. | format knowledge |
| 6 | **IMD Field Splitting** | Split each IMD+F+BST segment into IMD+F+BAU (author) and IMD+F+BTI (title). Parse the author (up to and including the abbreviated given name) into BAU, and the title into BTI. Place BAU then BTI where BST was. Update UNT counts. | Merge each consecutive IMD+F+BAU and IMD+F+BTI pair into a single IMD+F+BST segment, concatenating author and title with a single space between them. Update UNT counts. | string manipulation, format knowledge |
