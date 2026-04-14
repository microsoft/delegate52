# <img src="../assets/domain_icons/accounting.svg" width="28" height="28" style="vertical-align: middle;"> Accounting

**Category:** Structured Records
**File format:** `.ledger`
**Summary:** Ledger-cli financial records with transactions, postings, and account balances
**Work environments released:** 6 / 6

Accounting ledger files use the [Ledger-cli](https://www.ledger-cli.org/) plain-text double-entry bookkeeping format. Each transaction consists of a date and payee, one or more account postings with amounts, and optional comments (e.g., receipt references). This domain tests an LLM's ability to manipulate structured financial data — splitting, merging, reformatting, and performing arithmetic on monetary amounts across dozens of transactions.

**Domain implementation:** [`domain_accounting.py`](../domains/domain_accounting.py)

---

## Evaluation

The accounting domain evaluator parses transactions into structured records (date, payee, postings, amounts, comments) and scores reconstruction quality across four dimensions:

- **Transaction coverage** — Are all original transactions present? (Uses Hungarian matching for optimal alignment)
- **Posting accuracy** — Are account names preserved correctly?
- **Amount accuracy** — Are monetary values correct? (Compares as `min/max` ratio)
- **Comment preservation** — Are receipt references and notes intact?

**Score formula:** `coverage² × posting × amount × (0.5 + 0.5 × √comment)`

---

## Example Work Environment: `accounting1`

**Document:** Hack Club Expense Ledger
**Source:** [hackclub/ledger](https://github.com/hackclub/ledger) (ODC-By License)
**Size:** 341 lines · 3,959 tokens

### Seed Document Excerpt (`hack_club.ledger`)

```ledger
2016/06/01 Walgreens
    Expenses:Operating:Office:Supplies                   $9.40
    Liabilities:Reimbursement:Zach Latta
    ; Receipt: fcef14fb0a69f18ad19f2e883df6808b.jpeg

2016/06/01 Stripe
    Assets:Wells Fargo:Checking                        $202.00
    Income:Website Donations
    ; Receipt: 68ea19d1309c945f6388ee3e0385ec1e.pdf

2016/06/01 Max Wofford
    Expenses:Operating:Staff:Salary                    $858.06
    Assets:Wells Fargo:Checking
    ; Receipt: 034231682cca7916ccc353a8d6e875d5.pdf

2016/06/01 Jessica Kwok
    Expenses:Operating:Staff:Salary                  $2,800.00
    Assets:Wells Fargo:Checking
    ; Receipt: d547e48d591e8d4d0cce2bb20335e776.pdf

2016/06/02 Uber
    Expenses:Operating:Transportation:Ground             $6.55
    Liabilities:Reimbursement:Zach Latta
    ; Receipt: ab130e448190717360cbb45ffb99ac70.pdf

2016/06/02 Office Depot
    Expenses:Operating:Office:Supplies                  $56.08
    Liabilities:Reimbursement:Max Wofford
    ; Receipt: 2abae5ae6925af2a7e33a4842ed1f586.jpeg

2016/06/03 Google
    Expenses:Operating:Software                         $28.00
    Assets:Wells Fargo:Checking
    ; Receipt: 85d83bb6a67cac4cb0372de340701753.pdf

2016/06/06 Uber
    Expenses:Operating:Transportation:Ground             $4.75
    Liabilities:Reimbursement:Max Wofford
    ; Receipt: 109a3bb25ed4a19ad82afeae5150e4d6.pdf

2016/06/06 Garaje
    Expenses:Operating:Food                             $25.00
    Liabilities:Reimbursement:Max Wofford
    ; Receipt: e72183e32f305df36a063856ba0e6c91.png

2016/06/06 Instacart
    ; Food for Hack Camp
    Expenses:Operating:Food                             $46.56
    Liabilities:Reimbursement:Gemma Busoni
    ; Receipt: e0afe9eff2d1a6940afc16a6b3d322f1.png
```
<sup>Showing 50 of 341 lines. The full ledger contains 64 transactions spanning Q2–Q3 2016, covering expenses, income, reimbursements, and bank transfers.</sup>

---

### Edit Tasks (10 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Person Split** | Split this ledger by the person who needs to be reimbursed (like `zach_latta.ledger`). Transactions that don't involve reimbursements should go into `other.ledger`. | Merge all these ledger files into a single `accounting.ledger`, sorted by date. | split & merge, classification, sorting |
| 2 | **Category Split** | Split the ledger into separate files by expense category (like `food.ledger`, etc). Non-expense transactions like income or bank stuff can go in `other.ledger`. | Merge all these category ledger files into a single `accounting.ledger` file. Order all transactions by date. | split & merge, classification, sorting |
| 3 | **CSV Conversion** | Convert this ledger to a CSV file called `ledger.csv`. Include columns for date, payee, account, amount, notes, and receipt. | Convert this CSV back to ledger format. Output `accounting.ledger`. | format knowledge |
| 4 | **Beancount Conversion** | Convert this ledger file to Beancount format. Save it as `ledger.beancount`. | Convert this Beancount file to ledger format. Output `accounting.ledger`. | format knowledge |
| 5 | **Receipt Manifest** | Extract all the receipt references into a separate `receipts.csv` file with columns: id, date, payee, filename. In the ledger, replace each receipt comment with just a reference number like `; Receipt: #001`. | Replace the numbered receipt references in the ledger with the actual filenames from `receipts.csv`. Output just `accounting.ledger`. | referencing, format knowledge |
| 6 | **Flatten Accounts** | Flatten the account hierarchy to use shorter names. Instead of things like `Expenses:Operating:Transportation:Ground` just use `Ground Transportation`. Save a mapping of the original account names to the new ones in `tag_hierarchy.json`. | Expand the short account names to their full hierarchical names using the mapping in `tag_hierarchy.json`. Output just `accounting.ledger` and delete `tag_hierarchy.json`. | string manipulation, referencing |
| 7 | **EUR Conversion** | Convert all the dollar amounts to euros using a rate of 0.89 and add a comment at the very top of the file noting the conversion rate used. | Convert the euro amounts to dollars. Use the conversion rate noted in the comment at the top of the file, then remove that comment. | numerical reasoning |
| 8 | **Website Export** | We're a non-profit and want to put our finances on our website for transparency. Create `accounting.html`, `accounting.js`, and `accounting.css` that displays our ledger in a nice browsable format. Copy the transaction data into the JS file. | Extract the ledger data from these web files and output it as `accounting.ledger` in standard ledger format. | format knowledge, context expansion |
| 9 | **Fund Accounting** | Split the ledger into project-based fund files (`hack_camp.ledger`, `staffing.ledger`, `marketing.ledger`, `banking.ledger`, `general_ops.ledger`). Create a `sequence_map.json` to preserve ordering. | Merge all the fund ledger files into a single `hack_club.ledger`. Use `sequence_map.json` to determine the correct transaction ordering, then delete it. | split & merge, classification, sorting |
| 10 | **Reimbursement Claims** | Tag every transaction with a stable ID (`[TXN:HC-YYYYMMDD-NNN]`). Reorder the ledger into reimbursement claim sections. Create `reimbursement_claims.json` and `txn_order.json`. | Strip the `[TXN:...]` suffixes and section header comments. Use `txn_order.json` to reorder transactions by their recorded position index. | string manipulation, classification, sorting, context expansion |
