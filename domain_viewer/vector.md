# <img src="../assets/domain_icons/vector.svg" width="28" height="28" style="vertical-align: middle;"> Vector

**Category:** Creative &amp; Media
**File format:** `.svg`
**Summary:** SVG vector graphics with shapes, text labels, groups, and styling
**Work environments released:** 3 / 6

SVG (Scalable Vector Graphics) files encode complex visual documents — diagrams, floor plans, state machines — as structured XML with shapes, paths, text labels, groups, and inline CSS styling. Each element carries positional attributes, stroke/fill colors, and hierarchical grouping that conveys semantic structure. This domain tests an LLM's ability to manipulate structured graphical markup — recoloring, annotating, reordering, splitting, and extending SVG elements while preserving visual and structural fidelity.

**Domain implementation:** [`domain_vector.py`](../domains/domain_vector.py)

---

## Evaluation

The vector domain evaluator parses SVG documents into structural components using Python's `xml.etree.ElementTree` and scores reconstruction quality across six dimensions:

- **Group coverage** — Are all semantic groups present? (80% Jaccard on group IDs + 20% element count ratio)
- **Text accuracy** — Are text labels preserved correctly? (Greedy matching on normalized text content)
- **Visual fidelity** — Are colors correct? (Exact matching on fill, stroke, opacity — no partial credit for wrong colors)
- **Spatial accuracy** — Are position and dimension attributes correct? (Numeric tolerance comparison)
- **Structure score** — Is the group hierarchy preserved? (Jaccard on group IDs + membership Jaccard) / 2
- **Metadata comparison** — Are root SVG attributes (width, height, viewBox) preserved?

**Score formula:** `group_coverage × text_accuracy × √((visual_fidelity×2 + spatial_accuracy + structure_score) / 4)` with metadata penalty multiplier if below 0.5

---

## Example Work Environment: `vector2`

**Document:** Microwave Oven State Machine Diagram
**Source:** [davidmoten/state-machine](https://github.com/davidmoten/state-machine) (Apache-2.0 License)
**Size:** 353 lines · 4,798 tokens

### Seed Document Excerpt (`state_diagram.svg`)

```xml
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!-- Created with Inkscape (http://www.inkscape.org/) -->

<svg
   xmlns:dc="http://purl.org/dc/elements/1.1/"
   xmlns:cc="http://creativecommons.org/ns#"
   xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
   xmlns:svg="http://www.w3.org/2000/svg"
   xmlns="http://www.w3.org/2000/svg"
   xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
   xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
   width="744.09448819"
   height="1052.3622047"
   id="svg2"
   version="1.1">
  <defs id="defs4">
    <marker orient="auto" refY="0.0" refX="0.0" id="Arrow2Lend"
       style="overflow:visible;">
      <path id="path3909"
         style="fill-rule:evenodd;stroke-width:0.62500000;stroke-linejoin:round;"
         d="M 8.7185878,4.0337352 L -2.2072895,0.016013256 ..." />
    </marker>
  </defs>
  <g inkscape:label="Layer 1" inkscape:groupmode="layer" id="layer1">
    <rect
       style="fill:#ffffe0;stroke:#000000;stroke-width:0.901..."
       id="rect2985" width="163.15919" height="79.20269"
       x="275.77652" y="203.1423" ry="18.182745" />
    <text xml:space="preserve"
       style="font-size:40px;font-style:normal;..."
       x="299.00516" y="244.28076" id="text3755">
      <tspan id="tspan3757" x="299.00516" y="244.28076"
         style="font-size:16px">Ready to Cook</tspan>
    </text>
    <rect style="fill:#ffffe0;stroke:#000000;..." id="rect2985-1"
       width="116.83009" height="79.340607"
       x="522.42267" y="202.50894" ry="18.182745" />
    <!-- ... state boxes for Cooking, Cooking Complete, Door Open,
         Cooking Interrupted; transition paths with Arrow2Lend markers;
         event labels (doorClosed, buttonPressed, timerTimesOut, doorOpened);
         legend items (Event, State, Transition) ... -->
  </g>
</svg>
```
<sup>Showing an abbreviated excerpt of 353 lines. The full SVG contains 5 state boxes (Ready to Cook, Cooking, Cooking Complete, Door Open, Cooking Interrupted), 7 transition paths with arrow markers, event label texts, and a 3-item legend.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Timing Annotations** | Add timing annotations to each transition label showing response time in milliseconds: doorClosed [150ms], doorOpened [200ms], buttonPressed [100ms], timerTimesOut [30000ms]. Insert an XML comment before the closing svg tag computing the maximum single-cycle time. | Remove all the [Xms] timing annotations from transition labels, restoring the bare event names. Delete the MAX_CYCLE_TIME XML comment near the end of the file. | numerical reasoning |
| 2 | **Category Color-Coding** | Color-code each state box by its operational category (idle → #c8e6c9, active → #bbdefb, terminal → #e1bee7, safety → #ffcdd2, alert → #ffe0b2). Insert an ORIGINAL_FILLS comment recording the prior values. | Restore all five state rectangle fill colors to #ffffe0 as recorded in the ORIGINAL_FILLS comment, then remove that comment entirely. | referencing |
| 3 | **Case Conversion** | Convert all camelCase event labels to SCREAMING_SNAKE_CASE. Also change the italic green legend labels: Event → EVENT, State → STATE, Transition → TRANSITION. | Convert all SCREAMING_SNAKE_CASE event names back to camelCase. Change legend labels back too: EVENT → Event, STATE → State, TRANSITION → Transition. | string manipulation |
| 4 | **Topological Reorder** | Reorder elements inside the layer1 group by topological traversal of the state machine starting from Door Open. Group each state's rect, text, and invisible rect together; then place transition paths, event labels, legend items. Add ELEM_ORDER comment listing original sequence. | Restore element ordering inside layer1 to the sequence listed in the ELEM_ORDER comment. Remove the ELEM_ORDER comment. | sorting, referencing |
| 5 | **Legend Split** | Split the SVG into two files: state_diagram.svg keeps the main state machine, legend.svg gets the 6 legend elements. Add SPLIT_LEGEND / SPLIT_MAIN comments as cross-references. | Merge legend.svg back into state_diagram.svg. Append legend elements in the order listed in the SPLIT_LEGEND comment. Remove both comments. | split & merge, referencing |
| 6 | **UML Entry/Exit Actions** | Add UML-style entry and exit action tspan lines below each state name (font-size 10px italic). Add an initial pseudo-state filled black circle with an arrow path to Door Open. | Remove all entry/ and exit/ action tspan lines from state text elements. Remove the initial pseudo-state circle and its arrow path. | context expansion |
