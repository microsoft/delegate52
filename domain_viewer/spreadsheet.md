# <img src="../assets/domain_icons/spreadsheet.svg" width="28" height="28" style="vertical-align: middle;"> Spreadsheet

**Category:** Structured Records
**File format:** `.csv`
**Summary:** Tabular CSV data with rows, columns, and structured values
**Work environments released:** 6 / 6

CSV spreadsheet files contain structured tabular data with rows, columns, headers, and typed values. This domain tests an LLM's ability to reshape, convert, split, merge, sort, and classify tabular data — including pivot/unpivot operations, format conversions (Markdown, JSON, double-entry accounting), acronym/abbreviation encoding, and star-schema normalization. Correctly handling row ordering, header preservation, and numerical values across these transformations is central to the challenge.

**Domain implementation:** [`domain_spreadsheet.py`](../domains/domain_spreadsheet.py)

---

## Evaluation

The spreadsheet domain evaluator parses CSV files into structured records (headers and rows) and scores reconstruction quality across four dimensions:

- **Row preservation (50%)** — Are all original rows present? (Uses Jaccard set similarity on normalized row tuples)
- **Order score (25%)** — Are rows in the correct order? (Uses tie-tolerant sequence matching with optional group keys)
- **Header score (15%)** — Are column names preserved correctly? (Exact match, order-tolerant, Jaccard fallback)
- **Count score (10%)** — Does the row count match?

**Score formula:** `0.50 × row_preservation + 0.25 × order + 0.15 × header + 0.10 × count`

---

## Example Work Environment: `spreadsheet1`

**Document:** Municipal Budget Spreadsheet
**Source:** [City Expenditures — CA State Controller](https://bythenumbers.sco.ca.gov/Finance-Application/City-Expenditures/ju3w-4gxp) (Public Domain)
**Size:** 182 lines · 4,147 tokens

### Seed Document Excerpt (`budget.csv`)

```csv
Fiscal_Year,Category,Subcategory,Expense_Type,Amount
2021,Internal Service Fund,Operating Expenses,Personnel Services,2393866
2021,Internal Service Fund,Operating Expenses,Contractual Services,28348203
2021,Internal Service Fund,Operating Expenses,Materials and Supplies,5511
2021,Internal Service Fund,Operating Expenses,Depreciation and Amortization Expenses,377407
2021,Sewer Enterprise Fund,Operating Expenses,Transmission_Sewer Enterprise Fund,1053679
2021,Sewer Enterprise Fund,Operating Expenses,Treatment and Disposal_Sewer Enterprise Fund,7586489
2021,Sewer Enterprise Fund,Operating Expenses,Personnel Services_Sewer Enterprise Fund,8375757
2021,Sewer Enterprise Fund,Operating Expenses,General and Administrative Expenses_Sewer Enterprise Fund,1896622
2021,Sewer Enterprise Fund,Operating Expenses,Depreciation and Amortization Expenses_Sewer Enterprise Fund,4333564
2021,Sewer Enterprise Fund,Nonoperating Expenses,Interest Expense_Sewer Enterprise Fund,146855
2021,Solid Waste Enterprise Fund,Operating Expenses,Disposal Expenses,4840198
2021,Solid Waste Enterprise Fund,Operating Expenses,Disposal Expenses,2334892
2021,Solid Waste Enterprise Fund,Operating Expenses,Disposal Expenses,790799
2021,Solid Waste Enterprise Fund,Operating Expenses,Collection Expenses,5043291
2021,Solid Waste Enterprise Fund,Operating Expenses,Collection Expenses,3283135
2021,Solid Waste Enterprise Fund,Operating Expenses,Collection Expenses,397774
2021,Solid Waste Enterprise Fund,Operating Expenses,General and Administrative Expenses_Solid Waste Enterprise Fund,1118886
2021,Solid Waste Enterprise Fund,Operating Expenses,Depreciation and Amortization Expenses_Solid Waste Enterprise Fund,1890949
2021,Solid Waste Enterprise Fund,Nonoperating Expenses,Interest Expense_Solid Waste Enterprise Fund,109763
2021,Water Enterprise Fund,Operating Expenses,Water Supply Expenses,5453386
2021,Water Enterprise Fund,Operating Expenses,Pumping_Water Enterprise Fund,1864544
2021,Water Enterprise Fund,Operating Expenses,Treatment_Water Enterprise Fund,2464093
2021,Water Enterprise Fund,Operating Expenses,Transmission and Distribution_Water Enterprise Fund,1722379
2021,Water Enterprise Fund,Operating Expenses,Customer Accounting and Collection_Water Enterprise Fund,587157
2021,Water Enterprise Fund,Operating Expenses,Sales Promotion_Water Enterprise Fund,352338
2021,Water Enterprise Fund,Operating Expenses,Personnel Services_Water Enterprise Fund,14089317
2021,Water Enterprise Fund,Operating Expenses,General and Administrative Expenses_Water Enterprise Fund,5741412
2021,Water Enterprise Fund,Operating Expenses,Depreciation and Amortization Expenses_Water Enterprise Fund,3602246
2021,Water Enterprise Fund,Nonoperating Expenses,Interest Expense_Water Enterprise Fund,2201843
2021,Other Enterprise Fund,Operating Expenses,Personnel Services_Other Enterprise Fund,2991522
2021,Other Enterprise Fund,Operating Expenses,Contractual Services_Other Enterprise Fund,1735639
2021,Other Enterprise Fund,Operating Expenses,Materials and Supplies_Other Enterprise Fund,825060
2021,Other Enterprise Fund,Operating Expenses,Depreciation and Amortization Expenses_Other Enterprise Fund,1451649
2021,Other Enterprise Fund,Nonoperating Expenses,Interest Expense_Other Enterprise Fund,187473
2021,General Government and Public Safety,General Government,Legislative_Current Expenditures,1558318
2021,General Government and Public Safety,General Government,Management and Support_Current Expenditures,12630219
2021,General Government and Public Safety,Public Safety,Police_Current Expenditures,25817561
2021,General Government and Public Safety,Public Safety,Fire_Current Expenditures,19869446
2021,General Government and Public Safety,Public Safety,Animal Regulation_Current Expenditures,536555
2021,General Government and Public Safety,Public Safety,Street Lighting_Current Expenditures,269245
2021,General Government and Public Safety,Public Safety,Other Public Safety 1_Current Expenditures,2540911
2021,Transportation and Community Development,Transportation,Streets/Highways/Storm Drains_Current Expenditures,8490352
2021,Transportation and Community Development,Transportation,Parking Facility_Current Expenditures,2707101
2021,Transportation and Community Development,Transportation,Public Transit_Current Expenditures,797240
2021,Transportation and Community Development,Community Development,Planning_Current Expenditures,3315879
2021,Transportation and Community Development,Community Development,Housing_Current Expenditures,343649
2021,Transportation and Community Development,Community Development,Community Promotion_Current Expenditures,2262276
2021,Transportation and Community Development,Community Development,Other Community Development 1_Current Expenditures,3138856
2021,Health and Culture and Leisure,Culture and Leisure,Parks and Recreation_Current Expenditures,13457832
2021,Health and Culture and Leisure,Culture and Leisure,Libraries_Current Expenditures,1744751
```
<sup>Showing 50 of 182 lines. The full spreadsheet contains 181 data rows across 9 budget categories spanning fiscal years 2021–2023, covering enterprise funds, public safety, transportation, and debt service.</sup>

---

### Edit Tasks (10 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Pivot** | Pivot this budget data so fiscal years become columns and rows are unique Category+Subcategory+Expense_Type combos. Fill missing values with 0. Keep as CSV. | Unpivot this table to long format with columns Fiscal_Year, Category, Subcategory, Expense_Type, Amount. Skip rows where amount is 0. Order by fiscal year then by row order within each year. | format knowledge |
| 2 | **Category Split** | Split this budget CSV into separate files by Category. Name each file by category with spaces replaced by underscores (e.g. `Internal_Service_Fund.csv`). Keep row order within each file. | Merge all these category CSV files into `budget.csv` in specified category order. Single header row. | split & merge |
| 3 | **Markdown Conversion** | Convert this CSV to a Markdown table. | Convert this Markdown table to `budget.csv`. | format knowledge |
| 4 | **JSON Conversion** | Convert this CSV to JSON. Array of objects with column names as keys. | Convert this JSON to `budget.csv` with columns: Fiscal_Year, Category, Subcategory, Expense_Type, Amount. | format knowledge |
| 5 | **Amount Sort** | Sort all rows by Amount descending. Stable sort for ties. | Sort by Fiscal_Year ascending, then within each year group by Category in specified order. | sorting |
| 6 | **Acronym Encoding** | Replace Category and Subcategory values with 2–4 letter acronyms (e.g. ISF for Internal Service Fund). Output `budget.csv` with acronyms and `acronyms.csv` with columns Acronym, Full_Name. | Expand acronyms in Category and Subcategory using `acronyms.csv`. Output `budget.csv`, discard the acronyms file. | referencing, string manipulation |
| 7 | **Abbreviation** | Abbreviate words in the Expense_Type column using a detailed substitution table (36 abbreviation rules). Keep everything else exactly as-is. | Expand abbreviations in the Expense_Type column using the inverse substitution table, with special handling for context-dependent expansions. | string manipulation |
| 8 | **Tagged Split** | Add a Budget_Type column classifying each row by Expense_Type: PERSONNEL, SERVICES, MATERIALS, INFRASTRUCTURE, DEBT, or OTHER. Split into CSV files named by Budget_Type, keeping all columns. | Merge all 6 budget type files into `budget.csv`. Sort by Fiscal_Year ascending, within each year group by Category. Drop the Budget_Type column. | classification, split & merge, sorting |
| 9 | **Double-Entry Conversion** | Convert to double-entry accounting format. Assign hierarchical account codes, replace category columns with Account_Code, split Amount into Debit/Credit. Output `budget.csv`, `code_map.csv`, `row_sequence.csv`. | Join budget with code map on Account_Code, merge Debit/Credit into Amount, reorder by Row_Num. Output `budget.csv`, drop auxiliary files. | format knowledge, classification, sorting, referencing |
| 10 | **Star Schema Normalization** | Normalize into a star schema. Dimension tables: `categories.csv`, `subcategories.csv`, `expense_types.csv`. Fact table: `budget_facts.csv` with foreign keys and row_num. | Denormalize `budget_facts.csv` by joining with dimension tables. Sort by row_num then drop it. Output `budget.csv`, discard dimension files. | format knowledge, referencing |
