# <img src="../assets/domain_icons/fonteng.svg" width="28" height="28" style="vertical-align: middle;"> Font Engineering

**Category:** Creative & Media
**File format:** `.fea`
**Summary:** OpenType feature (.fea) files for font engineering
**Work environments released:** 6 / 6

OpenType feature files define the typographic behavior of fonts — glyph substitutions, ligatures, positional adjustments, and script/language-specific overrides. Written in the [OpenType Feature File Specification](https://adobe-type-tools.github.io/afdko/OpenTypeFeatureFileSpecification.html) syntax, they consist of `languagesystem` declarations, `@`-prefixed glyph class definitions, `feature` blocks with substitution and positioning rules, and `table` blocks for font metadata. This domain tests an LLM's ability to restructure, split, inline, and reorganize these tightly interdependent declarations while preserving syntactic validity and semantic correctness.

**Domain implementation:** [`domain_fonteng.py`](../domains/domain_fonteng.py)

---

## Evaluation

The font engineering domain evaluator parses `.fea` files using `fontTools.feaLib.parser` into typed AST nodes and decomposes them into four structural components:

- **Language system coverage** — Are all `languagesystem` declarations present? (Jaccard similarity over script/language pairs)
- **Glyph class accuracy** — Are `@`-prefixed class definitions preserved? (Coverage × content similarity via `SequenceMatcher`)
- **Feature block accuracy** — Are feature blocks correctly reconstructed? (Coverage × fuzzy text comparison)
- **Table block accuracy** — Are table blocks intact? (Coverage × content similarity)

**Score formula:** Components weighted proportionally to their block count in the reference file, each scored as `coverage² × accuracy`. If the generated `.fea` fails to parse, the score is 0.

---

## Example Work Environment: `fonteng1`

**Document:** TeX Gyre Heros Regular OpenType Features
**Source:** [Kochise/win_portable](https://raw.githubusercontent.com/Kochise/win_portable/HEAD/Document/miktex/texmfs/install/doc/fonts/tex-gyre/qhvr.fea) (GUST Font License)
**Size:** 391 lines · 4,707 tokens

### Seed Document Excerpt (`qhvr.fea`)

```fea
# This file belongs to the TeX Gyre collection of fonts. The work is
# released under the GUST Font License. See the MANIFEST-TeX-Gyre-Heros.txt
# and README-TeX-Gyre-Heros.txt files for the details.
# For the most recent version of this license see
# http://www.gust.org.pl/fonts/licenses/GUST-FONT-LICENSE.txt or
# http://tug.org/fonts/licenses/GUST-FONT-LICENSE.txt

# This is a `feature file' used to generate texgyreheros-regular.otf
# with the Adobe Font Development Kit for OpenType
# (FDK v2.0 Aug 31 2006 build 21; the later version,
# FDK v2.0 May 5 2007 build 26, was not used because the resulting
# OTF files were apparently malformed -- something was wrong with
# the language information)

languagesystem DFLT dflt;
languagesystem latn dflt;
languagesystem latn AZE;
languagesystem latn CRT;
languagesystem latn MOL;
languagesystem latn NLD;
languagesystem latn PLK;
languagesystem latn ROM;
languagesystem latn TRK;
languagesystem cyrl dflt;

# complete features
table head{
  FontRevision 2.004;
} head;

@altsrc1=[# all alternates
at copyright fraction paragraph registered
epsilon mu pi phi rho theta
macron macron.cap Imacron imacron imacron.sc];
#
@altsrc2=[# "genuine" alternates
at copyright fraction paragraph registered];
#
@altsrc3=[# "Greek" alternates
epsilon mu pi phi rho theta];
#
@altsrc4=[# "Idris" alternates
macron macron.cap Imacron imacron imacron.sc];

@altres1=[# all alternates
at.alt copyright.alt fraction.alt paragraph.alt registered.alt
epsilon.alt mu.greek uni03D6 uni03D5 rho.alt uni03D1
macron.alt macron.cap.alt Imacron.alt imacron.alt imacron.alt.sc];
#
@altres2=[# "genuine" alternates
at.alt copyright.alt fraction.alt paragraph.alt registered.alt];
@altres3=[# "Greek" alternates
epsilon.alt mu.greek uni03D6 uni03D5 rho.alt uni03D1];
```
<sup>Showing 52 of 391 lines. The full file contains 9 languagesystem declarations (Latin, Cyrillic, Greek), ~35 glyph class definitions, 19 feature blocks (aalt, locl, cpsp, smcp, frac, figure styles, ligatures, stylistic alternates, size), and 3 table blocks (head, hhea, OS/2).</sup>

---

### Edit Tasks (7 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Category Split** | Split `qhvr.fea` into separate module files with numeric prefixes: `01_lang_and_classes.fea`, `02_core_layout_features.fea`, `03_figure_features.fea`, `04_stylistic_features.fea`, `05_tables.fea`. Remove the moved content from the original file. | Merge the split modules back into a single `qhvr.fea` by concatenating in numeric order, removing the category comment headers from each module. | split & merge, classification, sorting |
| 2 | **Language Reorganization** | Add a localization manifest comment block after the license header listing each language tag with its customized features. Sort language override blocks in the liga feature alphabetically by tag, adding descriptive comments above each. | Remove the localization manifest comment block and strip per-language descriptive comments from the liga feature. Restore the original language override block order: NLD, PLK, MOL, ROM, AZE, CRT, TRK. | context expansion, sorting |
| 3 | **Class Inlining** | Inline all `@class` references directly into feature block rules. Comment out the inlined class definitions but keep base classes used only within other class definitions. | Uncomment the commented-out glyph class definitions and replace the inline glyph lists in feature blocks with their `@class` references. | string manipulation |
| 4 | **Figure Lookup Extraction** | Replace figure-feature alias class pairs with named lookups in each figure feature block, using separate sub rules for base figure glyph classes. Add a comment block before the figure features summarizing the mappings. | Collapse named lookups in each figure feature — concatenate sub rule source classes into single `@<tag>1` aliases and targets into `@<tag>2`. Simplify each feature to `sub @<tag>1 by @<tag>2;`. Delete the figure mapping comment. | string manipulation, context expansion |
| 5 | **Feature Alphabetization** | Sort all feature blocks alphabetically by tag. Add a TOC comment block before the first feature listing each tag, a one-line description, and its original position number. | Rearrange feature blocks into the sequence specified by the position numbers in the TOC comment, then delete the TOC comment block entirely. | sorting, context expansion |
| 6 | **Salt Consolidation** | Consolidate `salt` and `ss01`–`ss04` into a unified `salt` feature with named lookups for each stylistic set. Each `ssNN` feature should reference the corresponding lookup from `salt`. Add a mapping table comment. | Expand the `salt` feature — remove named lookups, keeping just the top-level sub for `@altsrc1`/`@altres1`. Give `ss01`–`ss04` standalone sub rules using `@altsrcN`/`@altresN` directly. Drop the mapping table comment. | string manipulation, context expansion |
| 7 | **Lookup Extraction** | Extract all inline lookup definitions to top-level before the feature blocks, with comments noting which feature each came from. Replace inline definitions with `lookup <name>;` references. | Inline the standalone lookup definitions back into their respective feature blocks, replacing the first `lookup <name>;` reference. Remove the top-level lookup section and extracted-from comments. | string manipulation, context expansion |
