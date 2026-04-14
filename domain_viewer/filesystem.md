# <img src="../assets/domain_icons/filesystem.svg" width="28" height="28" style="vertical-align: middle;"> Filesystem

**Category:** Code &amp; Configuration
**File format:** `.txt`
**Summary:** File tree listings with modes, sizes, timestamps, and directory paths
**Work environments released:** 6 / 6

Filesystem listings use a custom tree format inspired by `ls -lR` output, where each line contains mode bits, file size, and path. Mode fields use 6-digit octal codes (040000=directory, 100644=regular file, 100755=executable), sizes are in bytes (directories show `-`), and paths reflect the full repository structure. This domain tests an LLM's ability to manipulate structured file metadata — reorganizing directory layouts, converting formats, adjusting permissions, and performing arithmetic on file sizes across hundreds of entries.

**Domain implementation:** [`domain_filesystem.py`](../domains/domain_filesystem.py)

---

## Evaluation

The filesystem domain evaluator parses entries into structured records (mode, size, path) and scores reconstruction quality across four dimensions:

- **Path coverage (30%)** — Are all original file and directory paths present? (Uses Jaccard similarity)
- **Type accuracy (25%)** — Are entries correctly classified as directory, file, or executable?
- **Size accuracy (25%)** — Are file sizes correct? (Compares as `min/max` ratio for matched files)
- **Mode accuracy (20%)** — Are permission bits preserved exactly?

**Score formula:** `0.3 × path_coverage + 0.25 × type_accuracy + 0.25 × size_accuracy + 0.2 × mode_accuracy`

---

## Example Work Environment: `filesystem1`

**Document:** Flask Repo File Structure
**Source:** [pallets/flask](https://github.com/pallets/flask/tree/798e006f435887adceb6aab9b57cde8e20276793) (BSD-3-Clause License)
**Size:** 295 lines · 3,714 tokens

### Seed Document Excerpt (`flask.txt`)

```text
# Flask Repository File Structure
# Repository: pallets/flask
# Branch: main
# Tree SHA: 798e006f435887adceb6aab9b57cde8e20276793

# Format: MODE SIZE PATH
# MODE: 100644=file, 100755=executable, 040000=directory
# SIZE: in bytes (directories show '-')

040000        - .devcontainer
100644      434 .devcontainer/devcontainer.json
100755      165 .devcontainer/on-create-command.sh
100644      233 .editorconfig
040000        - .github
040000        - .github/ISSUE_TEMPLATE
100644      615 .github/ISSUE_TEMPLATE/bug-report.md
100644      511 .github/ISSUE_TEMPLATE/config.yml
100644      416 .github/ISSUE_TEMPLATE/feature-request.md
100644      822 .github/pull_request_template.md
040000        - .github/workflows
100644      682 .github/workflows/lock.yaml
100644      983 .github/workflows/pre-commit.yaml
100644     1946 .github/workflows/publish.yaml
100644     1996 .github/workflows/tests.yaml
100644       74 .gitignore
100644      827 .pre-commit-config.yaml
100644      242 .readthedocs.yaml
100644    72935 CHANGES.rst
100644     1475 LICENSE.txt
100644     1639 README.md
040000        - docs
100644      634 docs/Makefile
040000        - docs/_static
100644   207889 docs/_static/debugger.png
100644     1999 docs/_static/flask-icon.svg
100644     3455 docs/_static/flask-logo.svg
100644     5311 docs/_static/flask-name.svg
100644    99654 docs/_static/pycharm-run-config.png
100644    21212 docs/api.rst
100644     7656 docs/appcontext.rst
100644     4709 docs/async-await.rst
100644    12559 docs/blueprints.rst
100644       45 docs/changes.rst
100644    16701 docs/cli.rst
100644     3386 docs/conf.py
100644    29011 docs/config.rst
100644      274 docs/contributing.rst
100644     3462 docs/debugging.rst
040000        - docs/deploying
100644     2364 docs/deploying/apache-httpd.rst
100644      673 docs/deploying/asgi.rst
```
<sup>Showing 50 of 295 lines. The full listing contains ~295 entries spanning the Flask repository: source code, documentation, examples, tests, and configuration files.</sup>

---

### Edit Tasks (9 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Permission Restriction** | Make all files in docs/ and examples/ read-only. Also restrict the .github/ directory itself to 040500. | Restore standard permissions for files in docs/ and examples/. Set .github/ directory to 040000. | numerical reasoning |
| 2 | **Hidden File Cleanup** | Move all entries whose path begins with `.` (hidden files/directories) into a `trash/` folder at the root, preserving relative path structure. Update `flask.txt` to reflect this reorganization. | Move everything currently under `trash/` back to the repository root, restoring the original hidden paths, then remove the `trash/` directory entry. | split & merge |
| 3 | **JSON Manifest Conversion** | Convert this to a JSON manifest file called `flask_manifest.json`. Structure it as an array of objects with fields: path, type, and size. Sort by path alphabetically. | Convert this JSON manifest back to the tree format. Output `flask.txt` with the header comment block, then lines in MODE SIZE PATH format. Sort by path with directories listed before their contents. | format knowledge, sorting |
| 4 | **Test Colocation** | Reorganize tests to be colocated with source. Move `tests/test_*.py` and `conftest.py` to `src/flask/`. Move `tests/static/` and `tests/templates/` accordingly. `tests/test_apps/` stays. | Centralize all tests. Move `test_*.py` and `conftest.py` files from `src/flask/` back to `tests/`. Restore `tests/static/` and `tests/templates/`. Keep `tests/test_apps/` where it is. | split & merge, classification |
| 5 | **Monorepo Conversion** | Convert to a monorepo layout. Create `packages/flask-core/`, `packages/flask-cli/`, `packages/flask-docs/`, and `packages/flask-examples/` with appropriate contents. Tests move under `packages/flask-core/tests/`. Keep root config files. | Flatten back to single package. Restore `src/flask/`, `docs/`, `examples/`, and `tests/` from the packages structure. Remove the `packages/` directory. | split & merge, classification |
| 6 | **Build Artifact Simulation** | Simulate a build. Add `dist/`, `__pycache__/` directories inside `src/flask/` and `tests/` with `.pyc` files, `docs/_build/` with `html/index.html`, and `.coverage` at root. | Clean the repository. Remove `dist/`, all `__pycache__/` directories and `.pyc` files, `docs/_build/`, and `.coverage`. | context expansion |
| 7 | **Large File Storage** | Move every file whose size is greater than 20,000 bytes into a new `lfs/` directory, preserving relative paths. Create `lfs_manifest.csv` listing each moved file with columns `original_path,lfs_path,size_bytes`, sorted by size descending. | Use `lfs_manifest.csv` to move files from `lfs/` back to their original locations. Delete `lfs/` and `lfs_manifest.csv`. | numerical reasoning, split & merge, sorting |
| 8 | **Docs Reference Reorg** | Reorganize the Sphinx docs. Move selected `.rst` files from `docs/` into a new `docs/reference/` subdirectory. Add a `docs/reference/index.rst`. Create `path_map.json` mapping old paths to new paths. | Flatten the docs reference section. Use `path_map.json` to move all `.rst` files from `docs/reference/` back to `docs/`. Delete `docs/reference/`, `docs/reference/index.rst`, and `path_map.json`. | referencing, split & merge |
| 9 | **Curriculum Extraction** | Extract teaching materials into a `curriculum/` tree. Move `docs/tutorial/` to `curriculum/lessons/`, `examples/` to `curriculum/exercises/`, and `tests/test_apps/` to `curriculum/demos/`. Create `curriculum_manifest.csv` with source-to-destination mapping and lesson ordering. | Use `curriculum_manifest.csv` to move files back to their original locations. Delete `curriculum/` and `curriculum_manifest.csv`. | split & merge, classification, sorting |
