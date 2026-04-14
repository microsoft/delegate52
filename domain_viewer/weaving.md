# <img src="../assets/domain_icons/weaving.svg" width="28" height="28" style="vertical-align: middle;"> Weaving

**Category:** Creative & Media
**File format:** `.wif`
**Summary:** WIF (Weaving Information File) draft patterns with threading, tieup, treadling, and color data
**Work environments released:** 0 / 6

WIF weaving drafts use the INI-style [Weaving Information File](https://www.mhsoft.com/wif/wif1-1.htm) format standardized for handweaving draft exchange. Each file encodes a complete loom setup — threading (warp-thread-to-shaft mappings), tieup (treadle-to-shaft-set bindings), treadling (row-to-treadle sequences), color tables, and yarn properties. This domain tests an LLM's ability to manipulate structured textile pattern data, including converting between tieup/treadling and liftplan representations, reordering shafts, and transforming color palettes.

**Domain implementation:** [`domain_weaving.py`](../domains/domain_weaving.py)

---

## Evaluation

The weaving domain evaluator parses WIF drafts into structured records and scores reconstruction quality across five weighted components:

- **Threading accuracy (30%)** — Are warp-thread-to-shaft mappings correctly preserved? (Exact key-value match)
- **Treadling accuracy (30%)** — Are weft-row-to-treadle mappings correct? (Exact key-value match)
- **Tieup accuracy (20%)** — Are treadle-to-shaft-set bindings preserved? (Compared with sorted shaft lists)
- **Color table accuracy (10%)** — Are color entries correct? (Euclidean distance in 0–999 RGB space, normalized)
- **Parameters accuracy (10%)** — Are loom settings (Shafts, Treadles, Rising Shed) and yarn properties (Threads, Units, Color, Spacing, Thickness) exact matches?

**Score formula:** `0.30 × threading + 0.30 × treadling + 0.20 × tieup + 0.10 × color_table + 0.10 × parameters`
