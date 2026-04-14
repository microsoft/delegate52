# <img src="../assets/domain_icons/python.svg" width="28" height="28" style="vertical-align: middle;"> Python

**Category:** Code &amp; Configuration
**File format:** `.py`
**Summary:** Python code with functional test evaluation for correctness
**Work environments released:** 7 / 7

Python source code files implementing data analysis pipelines, statistical computations, and report generation. The context consists of one or more `.py` files with imports, functions, classes, and procedural logic. This domain tests an LLM's ability to refactor Python code — splitting, merging, changing paradigms, and swapping dependencies — while preserving functional behavior verified by an automated test suite.

**Domain implementation:** [`domain_python.py`](../domains/domain_python.py)

---

## Evaluation

The Python domain evaluator runs a test suite (`testing.py`) that verifies the generated code produces exactly the same output as the original. A successful refactoring must pass all functional tests — the output must be identical regardless of the internal code structure.

- **Functional correctness** — Does the refactored code produce the same output as the original when executed?
- **Test pass rate** — What fraction of functional tests pass?

**Score formula:** Based on functional test pass rate — output must be identical to the reference.

---

## Example Work Environment: `python1`

**Document:** LAMP Code Analysis Script
**Source:** [arxiv.org/abs/2409.14509](https://arxiv.org/abs/2409.14509) (CC-BY-4.0 License)
**Size:** 149 lines · 1,921 tokens

### Seed Document Excerpt (`code_analysis.py`)

```python
import json, numpy as np, Levenshtein, argparse
from collections import Counter

model_clean_names = {"gpt4o": "GPT-4o", "claude3.5-sonnet": "Claude3.5-S", "llama370B": "Llama3-70b"}

parser = argparse.ArgumentParser()
parser.add_argument("--data_path", type=str, default="LAMP.json")
parser.add_argument("--output_path", type=str, default="findings.json")
args = parser.parse_args()
with open(args.data_path, "r") as f:
    data = json.load(f)
sources = sorted(list(set([d["source"] for d in data])))

RESULTS = {}
RESULTS["sources"] = sources

for d in data:
    if d["type"] != "Literary Fiction":
        d["type"] = "Creative NonFiction"
    for edit in d["fine_grained_edits"]:
        edit["categorization"] = edit["categorization"].replace("/ ", "/").replace(" (Unnecessary ornamental and overly verbose)", "")
        char_diff = len(edit["editedText"]) - len(edit["originalText"])
        if char_diff > 40:
            edit['type'] = "Insert"
        elif char_diff < -40 or edit["originalText"] == "":
            edit['type'] = "Delete"
        else:
            edit["type"] = "Replace"

    d["editor"] = d["id"].split("_")[0]
    d["creativity_pre_score"] = int(d["creativity_scores"][0])
    d["creativity_post_score"] = int(d["creativity_scores"][1])
    d["creativity_diff_score"] = d["creativity_post_score"] - d["creativity_pre_score"]
editors = sorted(list(set([d["editor"] for d in data])))
RESULTS["editors"] = editors

# Get the distributions of creativity scores per editor
editor_scores = {editor: [] for editor in editors}
editor_pre_scores = {editor: [] for editor in editors}
editor_post_scores = {editor: [] for editor in editors}

for d in data:
    editor_scores[d["editor"]].append(d["creativity_pre_score"])
    editor_scores[d["editor"]].append(d["creativity_post_score"])
    editor_pre_scores[d["editor"]].append(d["creativity_pre_score"])
    editor_post_scores[d["editor"]].append(d["creativity_post_score"])

# print avg and std of creativity scores per editor
editor_means, editor_stds = {}, {}
for editor in editors:
    editor_means[editor] = np.mean(editor_scores[editor])
    editor_stds[editor] = np.std(editor_scores[editor])
```
<sup>Showing 55 of 149 lines. The full script computes z-score normalizations, edit categorization statistics, Levenshtein distance analysis, and generates a JSON report of findings.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Pandas Conversion** | Use pandas for the data processing instead, keeping the logic and output exactly the same. | Remove pandas and do it with basic python, keeping the logic and output exactly the same. | format knowledge |
| 2 | **File Split** | Split into 4 files: `config.py` (constants and argparse setup), `preprocessing.py` (data loading, type cleaning, editor extraction, z-score calculation), `analysis.py` (all analysis functions), and `main.py` (orchestration and output writing). The output should be exactly the same. | Consolidate into a single `code_analysis.py` file, inlining all the code sequentially. The output should be exactly the same. | split & merge |
| 3 | **Function Refactor** | Refactor the code to use functions for each analysis step, called sequentially from a main block. Keep all code in one file, output should be exactly the same. | Inline all function bodies into the main script body so the logic flows sequentially without any function definitions. The output should be exactly the same. | format knowledge |
| 4 | **OOP Refactor** | Refactor to use a class-based approach with an `AnalysisPipeline` class that has methods for each analysis step and stores data as instance attributes. Keep all code in one file, output should be exactly the same. | Remove the `AnalysisPipeline` class and implement all logic directly in the script body using plain variables. The output should be exactly the same. | format knowledge |
| 5 | **Template Assembly** | Extract all inline section-header strings into an `OUTPUT_TEMPLATES` dictionary near the top of the file, keyed by snake_case section name. Consolidate all scattered `RESULTS[key]` assignments into a single results-assembly block at the bottom before `json.dump`. Add an `# assembly_order: [...]` comment listing the RESULTS keys in their original assignment order. Print statements should reference `OUTPUT_TEMPLATES`. The output should be exactly the same. | Inline the `OUTPUT_TEMPLATES` entries back into their print statements as literal strings. Move each `RESULTS[key]` assignment back to right after its data is computed, following the `# assembly_order` comment. Remove the `OUTPUT_TEMPLATES` dictionary, the consolidated results block, and the `assembly_order` comment. The output should be exactly the same. | string manipulation |
| 6 | **DAG Pipeline** | Refactor into a declarative pipeline. Define a `PIPELINE` list of step dicts at the top, each with keys: `id` (snake_case name), `needs` (list of dependency step ids), and `run` (function reference). Write a generic `run_pipeline(steps, ctx)` that topologically sorts steps by needs, executes each run function with a shared ctx dict, and collects results. Convert each analysis section into a standalone function that reads/writes ctx. The `PIPELINE` list should encode actual data dependencies. Keep all print statements, output should be exactly the same. | Flatten the pipeline back into a linear script. Inline each step function body in execution order, replace ctx dict reads/writes with direct variable usage. Remove the `PIPELINE` list, `run_pipeline` function, and all step dicts. The output should be exactly the same. | format knowledge |
