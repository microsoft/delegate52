# <img src="../assets/domain_icons/earncall.svg" width="28" height="28" style="vertical-align: middle;"> Earncall

**Category:** Everyday
**File format:** `.txt`
**Summary:** Earnings call transcripts with speaker turns and Q&A sections
**Work environments released:** 6 / 6

Earnings call transcripts are plain-text records of quarterly conference calls between company executives and Wall Street analysts. Each speaker turn follows a "Speaker Name: content" format, with prepared remarks from the C-suite followed by an open Q&A session. This domain tests an LLM's ability to parse and reorganize speaker-attributed financial commentary — converting between formats, anonymizing metrics, splitting by speaker or topic, and performing arithmetic on dollar amounts, percentages, and basis points.

**Domain implementation:** [`domain_earncall.py`](../domains/domain_earncall.py)

---

## Evaluation

The earncall domain evaluator parses speaker turns and extracts financial metrics, then scores reconstruction quality across three dimensions:

- **Content matching (40%)** — Are speaker-attributed text segments preserved? (Uses sequence matching on per-speaker content)
- **Metrics preservation (35%)** — Are financial figures intact? (F1 score on extracted dollar amounts, percentages, and basis points)
- **Speaker sequence (25%)** — Is the turn order correct? (Sequence matching on speaker names)

**Score formula:** `0.40 × content + 0.35 × metrics + 0.25 × speaker_sequence`

---

## Example Work Environment: `earncall1`

**Document:** Agilent Technologies FY2020 Q4 Earnings
**Source:** [kurry/sp500_earnings_transcripts](https://huggingface.co/datasets/kurry/sp500_earnings_transcripts) (MIT License)
**Size:** 71 lines · 9,569 tokens

### Seed Document Excerpt (`agilent_earnings.txt`)

```text
Operator: Good afternoon, and welcome to the Agilent Technologies Fourth Quarter Earnings Conference Call. All lines have been placed on mute to prevent any background noise. After the speakers' remarks, there will be a question-and-answer session. [Operator Instructions] Thank you. And now, I'd like to introduce you to the host for today's conference, Ankur Dhingra, Vice President of Investor Relations. Sir, please go ahead.
Ankur Dhingra: Thank you, and welcome everyone to Agilent's fourth quarter and full-year conference call for fiscal year 2020. With me are Mike McMullen, Agilent's President and CEO; and Bob McMahon, Agilent's Senior Vice President and CFO. Joining in the Q&A after Bob's comments will be: Jacob Thaysen, President of Agilent's Life Sciences & Applied Markets Group; Sam Raha, President of Agilent's Diagnostics and Genomics Group; and Padraig McDonnell, President of Agilent CrossLab Group. This presentation is being webcast live. The news release, Investor presentation, and information to supplement today's discussion along with the recording of this webcast are made available on our Web site at investor.agilent.com. Today's comments by Mike and Bob will refer to non-GAAP financial measures. You will find the most directly comparable GAAP financial metrics and reconciliations on our Web site. Unless otherwise noted, all references to increases or decreases in financial metrics are year-over-year, and references to revenue growth are on a core basis. Core revenue growth excludes the impact of currency, and the acquisitions and divestitures completed within the past 12 months. Guidance is based on exchange rates as of October 31, 2020. We will also make forward-looking statements about the financial performance of the company. These statements are subject to risks and uncertainties, and are only valid as of today. The company assumes no obligation to update them. Please look at the company's recent SEC filings for a more complete picture of our risks and other factors. Also, as announced, we will hold our virtual investor day in a few weeks, on December 9. The event with include presentations from our CEO, CFO, and the three group Presidents, followed by a Q&A. We look forward to having you join us on December 9. And now, I would like to turn the call over to Mike.
Mike McMullen: Thanks, Ankur, and thanks to everyone for joining us on our call today. Today, I want to get straight to our quarterly results, because they tell a very compelling story. The Agilent team delivered a very strong close to 2020. We posted revenues of $1.48 billion during the quarter. Revenues are up 8% on a reported basis, and up 6% core. Operating margins are a healthy 24.9%. EPS of $0.98 is up 10% year-over-year. These numbers tell the story of a strong resilient company that's built for continued growth. Our better than expected results are due to the strength of our core business, along with signs of recovery in our end markets. Geographically, China continues to lead the way with double-digit growth. From an end-market view, both our pharmaceutical and food businesses grew double-digits. In addition, our chemical and energy business grew after two quarters of declines, exceeding our expectations. We also saw a rebound in U.S. sales during the quarter. Overall, COVID-19 tailwinds contributed just over two points of core growth. Achieving these results in the face of a global pandemic is a tribute to our team and the company we've built over the last five years. I couldn't be more pleased with the way the Agilent team has performed over the last quarter and throughout 2020.
```
<sup>Showing 3 of 71 lines (one per speaker turn). The full transcript continues with CFO Bob McMahon's prepared remarks and a multi-analyst Q&A session covering FY2021 guidance, NASD oligo manufacturing growth, biopharma strength, China demand, and chemical & energy recovery.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **JSON Conversion** | Convert this earnings call transcript to a structured JSON file (`transcript.json`) with metadata, participants, prepared_remarks, and qa_session arrays. | Convert this JSON transcript back to plain text. Each speaker turn as "Speaker Name: content". Save as `earnings.txt`. | format knowledge |
| 2 | **Metric Anonymization** | Anonymize every financial metric as `[M#]` and named entities as `[E#]` placeholders. Save lookup tables as `metrics.csv` and `entities.csv`. | Replace every `[M#]` and `[E#]` placeholder using the CSV lookup tables to restore the transcript. Delete the CSV files. | referencing, numerical reasoning |
| 3 | **Topic Q&A Split** | Reorganize the Q&A section by topic instead of by analyst. Keep prepared remarks in `remarks.txt`. Create topic files and `qa_schedule.txt` for ordering. | Merge back into a single `agilent_earnings.txt` using `remarks.txt` and `qa_schedule.txt` to restore the original analyst-ordered Q&A. | topic modeling, split & merge, classification, sorting |
| 4 | **EUR Conversion** | Convert all USD amounts to EUR at 1 USD = 0.847 EUR. Preserve decimal precision. Add a conversion note at the end. | Convert EUR amounts back to USD using the rate in the conversion note. Preserve precision. Remove the note. | numerical reasoning |
| 5 | **Cross-Referencing** | Add sequential turn IDs (T0001, T0002, …) and anchor tags for key topics (end-markets, geographies, guidance). Append an ANCHOR INDEX. | Strip all annotation markup (turn IDs, anchor tags, ANCHOR INDEX section) from the transcript. | referencing, string manipulation, topic modeling |
| 6 | **Speaker Split** | Split into per-speaker files (one per executive plus `operator.txt`, `analysts.txt`). Create `call_flow.csv` for turn order. | Reassemble from speaker files using `call_flow.csv` for ordering. Format as "Speaker Name: content". Save as `agilent_earnings.txt`. | split & merge, classification, sorting |
