# <img src="../assets/domain_icons/jobboard.svg" width="28" height="28" style="vertical-align: middle;"> Jobboard

**Category:** Everyday
**File format:** `.txt`
**Summary:** Job board listings with titles, requirements, salaries, and descriptions
**Work environments released:** 6 / 6

Plain-text job board files contain structured listings for open positions. Each job entry includes a unique ID, title, company, location, employment type, salary (annual or hourly), a skills list, and a posted date. Entries are separated by `---` lines, with a header containing board metadata and a footer with totals. This domain tests an LLM's ability to manipulate structured personnel data — splitting by compensation bands or geography, converting between text and JSON formats, normalizing salaries, and performing classification over dozens of listings.

**Domain implementation:** [`domain_jobboard.py`](../domains/domain_jobboard.py)

---

## Evaluation

The jobboard domain evaluator parses job listings into structured records (job ID, title, company, location, type, salary, skills, posted date) and scores reconstruction quality across four dimensions:

- **Job coverage (20%)** — Are all original job IDs present? (Uses Jaccard similarity on job ID sets)
- **Field accuracy (55%)** — Are individual fields preserved correctly? (Uses Hungarian algorithm matching with weighted field similarity: title 15%, company 15%, location 15%, type 10%, salary 25%, skills 15%, posted 5%)
- **Sequence score (15%)** — Are jobs in the correct order? (Compares ordering of matched pairs)
- **Count factor (10%)** — Are there the right number of jobs? (Penalizes missing or extra listings)

Salary comparison normalizes hourly rates to annual using 2080 hours/year and uses ratio-based similarity. Skills comparison uses Jaccard on the skill set (order-independent).

**Score formula:** `coverage² × accuracy × √((sequence + count) / 2)`

---

## Example Work Environment: `jobboard1`

**Document:** Tech Data Jobs Board (US)
**Source:** [lukebarousse/data_jobs](https://huggingface.co/datasets/lukebarousse/data_jobs) (Apache-2.0 License)
**Size:** 559 lines · 3,359 tokens

### Seed Document Excerpt (`jobboard.txt`)

```txt
DATA JOBS BOARD - Tech Industry Openings
==========================================
Last Updated: 2023-12-15
Region: United States
Categories: Data Engineering, Data Analysis, Data Science
==========================================

[JOB-0001] Data Engineer
Company: Amino
Location: United States
Type: Full-time
Salary: $165,000/year
Skills: python, postgresql, elasticsearch, snowflake, aws, databricks, spark, airflow
Posted: 2023-07-05

---

[JOB-0002] Data Engineer
Company: CAPITAL DISTRICT PHYSICIANS HEALTH PLAN INC
Location: Albany, NY
Type: Full-time
Salary: $98,000/year
Skills: sql, powershell, shell, go, sql server, oracle, aws, linux
Posted: 2023-04-12

---

[JOB-0003] Data Engineer
Company: Hays
Location: Atlanta, GA
Type: Full-time
Salary: $81/hour
Skills: python, go, assembly, sql, shell, sql server, db2, aws
Posted: 2023-02-22

---

[JOB-0004] Data Engineer
Company: AMD
Location: Austin, TX
Type: Full-time
Salary: $128,700/year
Skills: java, html, css, python, go, groovy, shell, mongodb
Posted: 2023-02-24

---

[JOB-0005] Data Engineer
Company: Incedo Inc
Location: South San Francisco, CA
Type: Full-time
Salary: $110,000/year
Skills: sql, python, aws, oracle, redshift, pyspark, sap
Posted: 2023-03-06
```
<sup>Showing 50 of 559 lines. The full board contains 55 job postings across Data Engineering, Data Analysis, and Data Science categories spanning 2023.</sup>

---

### Edit Tasks (10 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Salary Band Split** | Split these jobs into salary band files: `entry_level.txt` (under $70k yearly), `mid_level.txt` ($70k–120k), `senior_level.txt` ($120k–170k), `executive.txt` (above $170k). Convert hourly to annual using 2080 hours for classification. Create `bands.csv` with columns job_id, original_salary, annual_equivalent, band. | Merge all the salary band files into a single `jobboard.txt`. Use `bands.csv` to restore the original salary format for each job. Order by job ID. Keep the standard job board header and footer. | numerical reasoning, classification, split & merge |
| 2 | **Skills Matrix** | Extract all the skills into a `skills_matrix.csv` where rows are job IDs and columns are each unique skill (1 if required, 0 if not). Keep a simplified `jobs_summary.txt` with just the job ID, title, company, type, location, posted date, and salary. | Reconstruct the full job listings. Use `skills_matrix.csv` to add a Skills line to each job in `jobs_summary.txt`. Output as `jobboard.txt` with the standard header/footer and delete the CSV. | context expansion |
| 3 | **Geographic Split** | Split into: `west_coast.txt`, `east_coast.txt`, `midwest.txt`, `south.txt`, `remote.txt` (jobs marked Anywhere or Remote). Create `region_assignments.csv` with job_id, location, region columns. | Merge all regional job files into `jobboard.txt`. Use `region_assignments.csv` to order jobs by their original job ID. Include the standard header and footer and delete the CSV. | split & merge, classification |
| 4 | **ATS JSON Conversion** | Convert to ATS import format. Output `requisitions.json` as an array of objects with structure: {job_id, title, company, location: {city, state, is_remote}, compensation: {amount, period, annual_equivalent}, skills, posted_date, employment_type}. | Convert the ATS JSON to standard job board text format. Output `jobboard.txt` with header and footer. Each job uses the multi-line format with ID, title, company, location, type, salary, skills, posted date. | format knowledge |
| 5 | **Company Anonymization** | Replace all company names with anonymous codes like `[COMPANY_A]`, `[COMPANY_B]`, etc. Create `company_legend.csv` with columns code, company_name. | Replace all the anonymous company codes with real company names using `company_legend.csv`. Output the updated `jobboard.txt` and discard the CSV. | referencing |
| 6 | **Tech Stack Grouping** | Reorganize jobs into: `python_data.txt`, `sql_analytics.txt`, `cloud_infra.txt`, `bi_tools.txt`. Each job goes into exactly one file by dominant stack. Create `stack_assignments.csv` with job_id, assigned_stack. | Merge all the tech stack files into `jobboard.txt`. Use `stack_assignments.csv` to restore the original job ID ordering. Include standard header and footer. | split & merge, classification |
| 7 | **Salary Normalization** | Normalize all compensation to annual salary — convert hourly rates using 2080 hours/year. Replace the Salary line with `Salary: $XXX,XXX/year` for all jobs. Create `conversion_log.csv` with job_id, original_salary, was_converted. | Restore the original salary formats. Use `conversion_log.csv` — for jobs where was_converted is true, convert back to hourly. Discard the log. | numerical reasoning |
| 8 | **Profile Matching** | Split jobs into `must_apply.txt`, `potential.txt`, and `not_relevant.txt` for a mid-level data analyst with Python, SQL, Excel, Tableau skills seeking $90k–140k remote or California roles. Save profile in `candidate_profile.txt`. | Merge all three job files into `jobboard.txt` ordered by job ID. Discard the candidate profile. | classification, topic modeling |
| 9 | **COL Adjustment** | Adjust all salaries for cost of living using SF Bay Area as baseline (1.0). Apply factors: NYC ~0.95, Boston ~0.85, Austin/Dallas ~0.65, remote ~0.70. Replace Salary with `Adjusted Salary: $XXX,XXX/year`. Save factors in `col_factors.csv`. | Convert the adjusted salaries back to raw salaries using `col_factors.csv`. Change "Adjusted Salary" to "Salary". Discard the factors file. | numerical reasoning |
| 10 | **Market Position** | For each role category, compute the median annual salary. Add a Market Position line: "Above Market" (>115% median), "Below Market" (<85%), or "At Market". Reorder by role category then market position. Save `market_analysis.csv` with audit columns. | Strip the Market Position line from every job. Use `original_position` in `market_analysis.csv` to restore original order. Output `jobboard.txt` with standard header/footer and discard the CSV. | numerical reasoning, classification, sorting |
