# <img src="../assets/domain_icons/json.svg" width="28" height="28" style="vertical-align: middle;"> JSON

**Category:** Code &amp; Configuration
**File format:** `.json`, `.yaml`
**Summary:** Generic JSON data transformations with nested structures
**Work environments released:** 6 / 6

JSON/YAML structured data files contain deeply nested objects, arrays, and scalar values used across configuration, APIs, and data exchange. This domain tests an LLM's ability to manipulate generic structured data — splitting, merging, restructuring key hierarchies, converting between formats, and performing precise transformations across nested JSON/YAML documents.

**Domain implementation:** [`domain_json.py`](../domains/domain_json.py)

---

## Evaluation

The JSON domain evaluator parses JSON/YAML files and scores reconstruction quality using deep recursive comparison across two dimensions:

- **Key coverage** — Are all original key paths present? (Jaccard similarity on flattened dot-notation paths like `a.b.c`, `a.b[0]`)
- **Value accuracy** — Are nested values correct? (Recursive comparison: dicts are key-order-independent, arrays are order-dependent, scalars require exact match with int/float equivalence)

**Score formula:** `0.3 × key_coverage + 0.7 × value_score`

---

## Example Work Environment: `json1`

**Document:** Grafana K8s API Server Dashboard
**Source:** [dotdc/grafana-dashboards-kubernetes](https://github.com/dotdc/grafana-dashboards-kubernetes/blob/master/dashboards/k8s-system-api-server.json) (Apache-2.0 License)
**Size:** 461 lines · 2,925 tokens

### Seed Document Excerpt (`grafana_k8s_api_server.json`)

```json
{
  "title": "Kubernetes / System / API Server",
  "uid": "k8s_system_apisrv",
  "description": "This is a modern API Server dashboard for your Kubernetes cluster(s). Made for kube-prometheus-stack and take advantage of the latest Grafana features. GitHub repository: https://github.com/dotdc/grafana-dashboards-kubernetes",
  "tags": [
    "Kubernetes",
    "Prometheus"
  ],
  "schemaVersion": 38,
  "__inputs": [
    {
      "name": "DS_PROMETHEUS",
      "type": "datasource"
    }
  ],
  "__requires": {
    "panels": [
      "timeseries",
      "stat"
    ]
  },
  "annotations": [
    {
      "name": "terraform",
      "iconColor": "#5c4ee5",
      "tags": [
        "terraform"
      ]
    },
    {
      "name": "oncall",
      "iconColor": "red",
      "tags": [
        "oncall"
      ]
    }
  ],
  "panels": [
    {
      "id": 42,
      "title": "API Server - Health Status",
      "type": "stat",
      "gridPos": {
        "h": 8,
        "w": 12,
        "x": 0,
        "y": 0
      },
      "targets": [
        {
          "expr": "up{cluster=~\"$cluster\", job=~\"$job\"}",
          "legendFormat": "{{ instance }}",
          "refId": "A"
        }
      ],
```
<sup>Showing 50 of 461 lines. The full dashboard contains panels for health status, HTTP request rates, latency percentiles, error tracking, and resource usage with PromQL queries.</sup>

---

### Edit Tasks (10 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Panel Type Split** | Split the Grafana dashboard into separate files by panel type: create `stat_panels.json` for stat panels, `timeseries_panels.json` for timeseries panels, `table_panels.json` for table panels, and `base.json` containing the dashboard metadata/config without any panels. | Merge `base.json`, `stat_panels.json`, `timeseries_panels.json`, and `table_panels.json` into a single `grafana_k8s_api_server.json` dashboard file. | split & merge, classification |
| 2 | **Row Organization** | Organize these panels into collapsible rows by their function — health status, HTTP requests, latency, errors, and resource usage. | Flatten the dashboard by removing all the row panels. | classification |
| 3 | **Queries Extracted** | Extract the PromQL queries into a separate `queries.json` file. Use markers like `[QUERY:42]` in the dashboard to reference them by panel ID. | Inline the queries from `queries.json` into the dashboard, replacing `[QUERY:N]` markers with the PromQL expressions. | referencing |
| 4 | **YAML Conversion** | Convert this to YAML format. | Convert this YAML dashboard to JSON format as `grafana_k8s_api_server.json`. | format knowledge |
| 5 | **Domain Split** | Split the dashboard into separate dashboards by metric type: `health.json`, `http_metrics.json`, `errors.json`, and `resources.json` with relevant panels, plus `base_config.json` containing shared dashboard configuration. | Merge `health.json`, `http_metrics.json`, `errors.json`, and `resources.json` into a single `grafana_k8s_api_server.json` dashboard, using the shared settings from `base_config.json`. | split & merge, classification |
| 6 | **Grid Percentage** | Convert `gridPos` to percentage-based values (0–100) instead of Grafana grid units. Store the grid-unit positions in a `layout.json` file. | Convert percentage-based `gridPos` to Grafana grid units using the positions in `layout.json`. | numerical reasoning, referencing |
| 7 | **Key Flattening** | Flatten nested objects in each panel to underscore-delimited keys, e.g. `gridPos.x` becomes `gridPos_x`, `fieldConfig.defaults.unit` becomes `fieldConfig_defaults_unit`. | Unflatten underscore-delimited keys into nested objects — `gridPos_x` becomes `gridPos.x`, `fieldConfig_defaults_unit` becomes `fieldConfig.defaults.unit`. | string manipulation |
| 8 | **Query-Centric** | Restructure so queries are top-level. Each query object should contain the panel info that uses it, instead of panels containing queries. | Restructure to panel-centric format where panels contain their queries, instead of queries containing panel info. | string manipulation |
| 9 | **Template-Driven** | Refactor to be template-driven. Add a `panelTemplates` map where each template holds shared defaults for similar panels. Rewrite each panel to carry only `templateId` plus fields that differ from the template. | Deep-merge each panel with its referenced template to produce full standalone panel objects, then drop `panelTemplates`. | referencing |
| 10 | **Keyed Label-Indexed** | Convert the panels array to a keyed object by panel ID (string keys), add `_panelOrder` to record the sequence. Extract PromQL label matchers into a `_labelFilterIndex` map with `{LF:...}` tokens. | Inline label matchers from `_labelFilterIndex` into the PromQL expressions, replacing `{LF:...}` tokens. Convert the keyed panels object to an array ordered by `_panelOrder`, then remove both index fields. | string manipulation, referencing, sorting |
