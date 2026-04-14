# <img src="../assets/domain_icons/makefile.svg" width="28" height="28" style="vertical-align: middle;"> Makefile

**Category:** Code &amp; Configuration
**File format:** `.mk`
**Summary:** Build system files with targets, dependencies, and shell recipes
**Work environments released:** 5 / 6

GNU Makefile build systems define targets with prerequisite dependencies and multi-line shell recipes that orchestrate project compilation, testing, packaging, and deployment. This domain tests an LLM's ability to manipulate structured build logic — splitting and merging sections, externalizing variables and tool references, converting between formats, and preserving the precise interplay of phony declarations, pattern rules, conditional directives, and recipe commands.

**Domain implementation:** [`domain_makefile.py`](../domains/domain_makefile.py)

---

## Evaluation

The Makefile domain evaluator parses build system transformations using GNU make's `-p` flag to normalize Makefile content. Six component scores assess reconstruction quality:

- **Target coverage (25%)** — Are all original targets present? (Jaccard similarity on target names)
- **Dependency accuracy (25%)** — Are dependency lists preserved for matched targets?
- **Recipe accuracy (30%)** — Are shell recipe commands correct? (Sequence matching on normalized recipes, stripping `@` and `-` prefixes)
- **Variable score (15%)** — Are variable definitions preserved? (Coverage and value accuracy)
- **Phony score (5%)** — Are `.PHONY` declarations intact? (Jaccard similarity)
- **Pattern rule score** — Bonus/penalty when pattern rules are present (Jaccard on stem patterns)

**Score formula:** Weighted linear sum of all six components.

---

## Example Work Environment: `makefile1`

**Document:** Envoy AI Gateway Makefile
**Source:** [envoyproxy/ai-gateway](https://github.com/envoyproxy/ai-gateway/blob/main/Makefile) (Apache-2.0 License)
**Size:** 356 lines · 4,897 tokens

### Seed Document Excerpt (`ai_gateway.mk`)

```makefile
# Copyright Envoy AI Gateway Authors
# SPDX-License-Identifier: Apache-2.0
# The full text of the Apache license is available in the LICENSE file at
# the root of the repo.

# Read any local configuration. This is an optional, local git-ignored file that can be used
# to set any value commonly used for development. This helps not having to set the overrides
# in the command line every time.
-include .makerc

GO_TOOL := go tool -modfile=tools/go.mod

# This is the package that contains the version information for the build.
VERSION_STRING:=$(shell git describe --tags --long)
VERSION_PACKAGE := github.com/envoyproxy/ai-gateway/internal/version
GO_LDFLAGS += -X $(VERSION_PACKAGE).version=$(VERSION_STRING)

# This is the directory where the built artifacts will be placed.
OUTPUT_DIR ?= out

# Arguments for docker builds.
OCI_REGISTRY ?= docker.io/envoyproxy
OCI_REPOSITORY_PREFIX ?= ${OCI_REGISTRY}/ai-gateway
TAG ?= latest
ENABLE_MULTI_PLATFORMS ?= false
HELM_CHART_VERSION ?= v0.0.0-latest

# Arguments for go test. This can be used, for example, to run specific tests via
# `GO_TEST_ARGS="-run TestName/foo/etc -v -race"`.
GO_TEST_ARGS ?=
# Arguments for go test in e2e tests in addition to GO_TEST_ARGS, applicable to test-e2e, test-data-plane, etc.
GO_TEST_E2E_ARGS ?= -count=1 -timeout 30m

## help: Show this help info.
.PHONY: help
help:
	@echo "Envoy AI Gateway is an Open Source project for using Envoy Gateway to handle request traffic from application clients to GenAI services.\n"
	@echo "Usage:\n  make \033[36m<Target>\033[0m \n\nTargets:"
	@awk 'BEGIN {FS = ":.*##"; printf ""} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Precommit: Usually, targets here do not need to be run individually, but run `make precommit` to run all of them at once. CI will fail if `precommit` is not run before committing.

# This runs all necessary steps to prepare for a commit.
.PHONY: precommit
precommit: ## Run all necessary steps to prepare for a commit.
precommit: tidy spellcheck apigen codegen apidoc format lint editorconfig helm-test
```
<sup>Showing 50 of 356 lines. The full Makefile contains Go build tooling, Docker/Helm packaging, test targets, and CI/CD integration organized into Precommit, Testing, Common, and Helm sections.</sup>

---

### Edit Tasks (9 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Section Split** | This Makefile is getting too big. Split it into separate files by the `##@` section markers. Create `precommit.mk`, `testing.mk`, `common.mk`, and `helm.mk`. The main `ai_gateway.mk` should just keep the header comments, variables, and include statements. | Consolidate all the `.mk` include files back into the main Makefile, keeping the `##@` section headers. Remove the separate `.mk` files. | split & merge |
| 2 | **Help Extraction** | I want to generate documentation from this Makefile. Extract all the `##` help comments into a `MAKEFILE_HELP.md` organized by section. In `ai_gateway.mk`, replace each `##` comment with a numbered marker like `## [DOC:1]`, `## [DOC:2]` etc. | Inline the documentation from `MAKEFILE_HELP.md` back into `ai_gateway.mk`, replacing each `[DOC:N]` marker with the corresponding `##` comment. Delete `MAKEFILE_HELP.md`. | referencing |
| 3 | **Variable Externalization** | We need to share variables across multiple Makefiles in our monorepo. Extract all variable definitions (everything before the first target) into a `vars.mk` file and include it from `ai_gateway.mk`. | Inline all variables from `vars.mk` back into `ai_gateway.mk` at the top. Delete `vars.mk`. | split & merge |
| 4 | **JSON Conversion** | We're evaluating build system migrations. Convert this Makefile to a JSON format in `build_config.json` with sections for variables, targets (dependencies, recipes, phony status, help text), and pattern rules. | Convert the JSON build config back to a standard Makefile `ai_gateway.mk`. Include the `##@` section comments and `##` help annotations. | format knowledge |
| 5 | **Recipe Extraction** | The complex shell logic in some recipes is hard to maintain. Extract the recipes for `codegen`, `format`, `tidy`, and `check` targets into shell scripts in a `scripts/` folder and update `ai_gateway.mk` to call them. | Inline the shell scripts back into the Makefile recipes and delete the `scripts/` folder. | split & merge |
| 6 | **Podman Migration** | We're migrating from Docker to Podman. Replace all `docker` commands with their `podman` equivalents. Save a note in `container_runtime.txt` indicating this was converted from docker. | Switch back to Docker. Replace all `podman` commands with their `docker` equivalents. Delete `container_runtime.txt`. | string manipulation |
| 7 | **Tool Externalization** | Different team members have tools installed in different locations. Extract all tool references (`GO_TOOL`, `docker`, `helm` commands) into a `tools.mk` with variables like `DOCKER_CMD`, `HELM_CMD` etc. Include it from `ai_gateway.mk`. | Inline the tool definitions from `tools.mk` back into `ai_gateway.mk`, replacing variable references like `$(DOCKER_CMD)` with the actual commands. Delete `tools.mk`. | split & merge, string manipulation |
| 8 | **DAG Visualization** | We want to understand the dependency structure of our build targets. Analyze the target dependencies and generate a Graphviz DOT file (`deps.dot`) with the full dependency graph, grouping nodes by depth level. In the Makefile, reorder all targets in topological order and replace `##@` section headers with `##@ Depth N` headers. Above each target add a `# [DAG_DEPTH:N] [ORIG_POS:N]` comment. Move any mid-file variable definitions up into the variables section at the top. | Remove `deps.dot`. Strip all `# [DAG_DEPTH:...] [ORIG_POS:...]` annotations and use `ORIG_POS` values to restore target order. Replace `##@ Depth` headers with the original sections. Move mid-file variables back to their original positions. | sorting, context expansion |
| 9 | **Namespace Prefixing** | We're pulling this Makefile into a monorepo alongside other projects. Prefix every target name with `aigw-` and update all cross-references. Sort targets alphabetically within each `##@` section. Above each target add a `# [ORIG-SEC-POS:Section:N]` comment. Save a `namespace_map.json` with the prefix, the old-to-new target name mapping, and per-section ordering. | Strip the `aigw-` prefix from every target name and update all references. Use `namespace_map.json` and the `# [ORIG-SEC-POS:Section:N]` markers to restore target positions within each section. Remove the markers and delete `namespace_map.json`. | string manipulation, sorting, referencing |
