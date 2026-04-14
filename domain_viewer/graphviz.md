# <img src="../assets/domain_icons/graphviz.svg" width="28" height="28" style="vertical-align: middle;"> Graphviz

**Category:** Code &amp; Configuration
**File format:** `.dot`
**Summary:** DOT graph diagrams with nodes, edges, subgraphs, and styling
**Work environments released:** 5 / 6

Graphviz DOT files describe directed and undirected graphs using a declarative syntax of nodes, edges, subgraphs, and rich attribute sets (colors, shapes, labels, URLs). This domain tests an LLM's ability to manipulate graph structure — converting between diagram languages, splitting and merging subgraphs, extracting and reintegrating metadata, and reasoning about architectural dependencies across dozens of interconnected nodes.

**Domain implementation:** [`domain_graphviz.py`](../domains/domain_graphviz.py)

---

## Evaluation

The Graphviz domain evaluator parses DOT diagrams using the `pydot` library and scores reconstruction quality across six dimensions:

- **Node coverage** — Are all original nodes present? (Jaccard similarity on node IDs)
- **Node attribute accuracy** — Are label, shape, colors, style, URL, and tooltip preserved? (Weighted matching)
- **Edge coverage** — Are all original edges present? (Jaccard on source-target pairs)
- **Edge attribute accuracy** — Are arrowhead, color, style, and label correct? (Weighted matching)
- **Subgraph score** — Are nodes assigned to the correct subgraphs? (Membership matching)
- **Global settings score** — Are graph-level attributes preserved?

**Score formula:** `node_coverage² × node_accuracy × edge_coverage × √((edge_accuracy + subgraph_score) / 2)`, with a penalty multiplier if global settings score is below 0.5.

---

## Example Work Environment: `graphviz1`

**Document:** Linux Kernel Architecture Diagram
**Source:** [makelinux/linux_kernel_map](https://github.com/makelinux/linux_kernel_map/blob/HEAD/Linux_kernel_diagram.dot) (GPL-3.0 License)
**Size:** 630 lines · 4,386 tokens

### Seed Document Excerpt (`linux_kernel.dot`)

```dot
digraph "Linux_kernel_diagram" {
	fontname="Helvetica,Arial,sans-serif"
	node [fontname="Helvetica,Arial,sans-serif"]
	edge [fontname="Helvetica,Arial,sans-serif"]
	graph [
		newrank = true,
		nodesep = 0.3,
		ranksep = 0.2,
		overlap = true,
		splines = false,
	]
	node [
		fixedsize = false,
		fontsize = 24,
		height = 1,
		shape = box,
		style = "filled,setlinewidth(5)",
		width = 2.2
	]
	edge [
		arrowhead = none,
		arrowsize = 0.5,
		labelfontname = "Ubuntu",
		weight = 10,
		style = "filled,setlinewidth(5)"
	]
	subgraph system {
		node [color = "#e27dd6ff"]
		edge [color = "#e27dd6ff"]
		system_ [
			fixedsize = true,
			height = 0,
			shape = point,
			style = invis,
			shape = point
		]
		system [
			URL = "https://en.wikibooks.org/wiki/The_Linux_Kernel/System",
			fillcolor = white,
			fixedsize = true,
			height = 0.6,
			row = func,
			width = 2]
		system -> system_ [
			arrowhead = "",
			row = func];
		SCI [
			URL = "https://en.wikibooks.org/wiki/The_Linux_Kernel/Syscalls",
			fillcolor = "#d9e7ee",
			fixedsize = true,
			label = "System calls",
			row = usr,
			shape = ellipse]
		sysfs [
			fillcolor = "#b2d3e4",
```
<sup>Showing 55 of 630 lines. The full diagram contains ~80 nodes organized into subgraphs by subsystem (system, networking, processing, memory, storage, human interface), with edges representing dependencies and data flow across architectural layers.</sup>

---

### Edit Tasks (11 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Mermaid Conversion** | Convert this DOT diagram to Mermaid flowchart format as diagram.mmd. Since Mermaid doesn't support all DOT attributes, store the DOT-specific attributes in a separate metadata.json file keyed by node and edge IDs so nothing is lost. | Convert the Mermaid diagram to Graphviz DOT format as linux_kernel.dot. Use metadata.json to restore all the DOT-specific attributes. | format knowledge, referencing |
| 2 | **D2 Conversion** | Convert this Graphviz DOT file to D2 diagram language, preserving all metadata. Output as diagram.d2. | Convert this D2 diagram to Graphviz DOT format as linux_kernel.dot, preserving all attributes and structure exactly. | format knowledge |
| 3 | **Subsystem Split** | Split this diagram into separate DOT files by major subsystem: system.dot, networking.dot, processing.dot, memory.dot, storage.dot, human_interface.dot. Put edges that cross between subsystems in cross_edges.json (with source, target, and all edge attributes). Put the global graph settings and any nodes not in a major subsystem into global_settings.dot. | Merge all the subsystem DOT files into a single linux_kernel.dot. Use cross_edges.json to add the edges between subsystems. Include the global settings from global_settings.dot. Reconstruct the original subgraph structure. | split & merge, classification |
| 4 | **Layer Split** | Split this diagram by architectural layer using the 'row' attribute. Create separate files for each layer: layer_func.dot, layer_usr.dot, layer_virtual.dot, layer_bridges.dot, layer_logical.dot, layer_hwi.dot, layer_chip.dot. Include nodes without a row attribute in layer_other.dot. Put cross-layer edges in cross_layer_edges.json with full edge attributes. Include a manifest.json mapping layer names to their files and vertical ordering. | Merge all the layer files into a single linux_kernel.dot. Use the manifest.json for ordering and cross_layer_edges.json to reconnect edges between layers. Reconstruct the original subgraph structure grouping nodes by their functional subsystem (system, networking, processing, memory, storage, human interface). | split & merge, classification |
| 5 | **Citation Extraction** | Extract all URL and tooltip attributes from the diagram into a citations.csv file with columns: node_id, url, tooltip. Remove these attributes from the nodes and output the cleaned diagram as diagram.dot. | Read citations.csv and add the URL and tooltip attributes to the corresponding nodes in diagram.dot. Output as linux_kernel.dot. | referencing |
| 6 | **Theme Extraction** | Extract the color scheme from this diagram. Create diagram_mono.dot with all color attributes (fillcolor, color, fontcolor) removed. Then create three theme files: theme1.json with the original colors keyed by node/edge ID, theme2.json with an alternative blue-green professional palette, and theme3.json with a high-contrast accessibility-friendly palette. | Apply theme1.json to diagram_mono.dot, restoring fillcolor, color, and fontcolor attributes to each node and edge. Output as linux_kernel.dot. | referencing, context expansion |
| 7 | **CSV Conversion** | Convert this DOT diagram to a tabular format. Create nodes.csv with columns for all node attributes. Create edges.csv with columns for all edge attributes. Create subgraphs.csv listing each subgraph with its default node/edge attributes. Create settings.json for the global graph configuration. | Construct the DOT diagram from the tabular data. Use settings.json for global attributes, subgraphs.csv for the subgraph structure, nodes.csv for all nodes, and edges.csv for all edges. Output as linux_kernel.dot. | format knowledge |
| 8 | **JSON Conversion** | Convert this DOT file to a structured JSON representation as graph.json. Include a 'settings' object for global graph attributes, a 'nodes' array with all node definitions and their attributes, an 'edges' array with all edge definitions and attributes, and a 'subgraphs' array capturing the hierarchical subgraph structure with their local defaults. | Convert graph.json to DOT format as linux_kernel.dot, reconstructing the full graph structure exactly as specified in the JSON. | format knowledge |
| 9 | **Undirected Conversion** | Convert this directed graph to an undirected graph. Output as diagram.dot. | Turn this undirected graph into a directed graph by using your knowledge of operating system architecture: data and control generally flow from user space interfaces down through virtual subsystems, bridges, logical layers, hardware interfaces, to hardware. Output as linux_kernel.dot with proper directed edges. | domain knowledge |
| 10 | **API Gateway Insertion** | Insert diamond-shaped API gateway nodes at every edge crossing between the user space interfaces row and the virtual subsystems row. Label each gateway with an appropriate Linux syscall family name (sys_open, sys_socket, sys_fork, sys_mmap, sys_ioctl, sys_read) and give them a light gray fillcolor. Reroute the existing cross-layer edges through these new gateway nodes, keeping the same subsystem edge colors. Save the replaced direct-edge connections with all their attributes in gateway_edges.json. Output the modified diagram as diagram.dot. | Remove all diamond-shaped API gateway nodes from diagram.dot and reconnect the direct edges between user space interface nodes and virtual subsystem nodes using gateway_edges.json. Output as linux_kernel.dot. | domain knowledge |
| 11 | **Layout Scaffolding Extraction** | Strip all invisible layout scaffolding from this diagram: invisible anchor nodes (shape=point, style=invis), invisible edges (style=invis), rank-constraint subgraphs (rank=same groups), and layout-only edges connecting to anchor points. Store every removed element in layout_overrides.json with full attribute detail. Output the semantic-only diagram as diagram.dot. | Re-inject the layout scaffolding into diagram.dot using layout_overrides.json. Restore invisible anchor nodes, rank groups, layout edges, and all positioning constraints. Output as linux_kernel.dot. | referencing |
