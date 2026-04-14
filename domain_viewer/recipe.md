# <img src="../assets/domain_icons/recipe.svg" width="28" height="28" style="vertical-align: middle;"> Recipe

**Category:** Everyday
**File format:** `.txt`
**Summary:** Cooking recipes with ingredients, quantities, steps, and timings
**Work environments released:** 1 / 6

Cooking recipe files use a structured plain-text format with numbered ingredients (quantity, unit, description), numbered preparation steps, and numbered chef's tips. Cross-references like `(See Tip N)` link steps to tips. This domain tests an LLM's ability to manipulate structured culinary data — splitting recipes by section, converting between formats, scaling quantities with unit conversion, and reorganizing by equipment station.

**Domain implementation:** [`domain_recipe.py`](../domains/domain_recipe.py)

---

## Evaluation

The recipe domain evaluator parses ingredients (with unit normalization), steps, and tips, then scores reconstruction quality across three dimensions:

- **Ingredient matching (40%)** — Are all original ingredients present with correct quantities? (Uses Hungarian algorithm with quantity similarity including unit normalization across metric/imperial)
- **Step accuracy (40%)** — Are preparation steps preserved in order with correct wording? (Compares concatenated step text using Levenshtein ratio, weighted by coverage)
- **Tips matching (20%)** — Are chef's tips intact? (Uses bipartite matching on tip descriptions)

**Score formula:** `0.4 × ingredients + 0.4 × steps + 0.2 × tips`

---

## Example Work Environment: `recipe1`

**Document:** Chocolate Eclair Recipe
**Source:** Original content (MIT License)
**Size:** 117 lines · 1,554 tokens

### Seed Document Excerpt (`recipe_eclair.txt`)

```text
# CHOCOLATE ECLAIR RECIPE (for 12 eclairs)

## INGREDIENTS

Ingredient 1: 250 mL water

Ingredient 2: 200 g Type 55 flour

Ingredient 3: 200 g butter

Ingredient 4: 1 pinch fine salt

Ingredient 5: 5 whole eggs

Ingredient 6: 500 mL whole milk

Ingredient 7: 100 g granulated sugar

Ingredient 8: 50 g custard powder

Ingredient 9: 150 g 70% dark couverture chocolate

Ingredient 10: 500 g white fondant

Ingredient 11: 2 tablespoons cocoa powder

## PREPARATION STEPS

Step 1: To make this chocolate eclair recipe, start by preparing the choux pastry ingredients.

Step 2: Choux pastry: Put the water, 100g of butter, and salt in a saucepan on the stove.

Step 3: Bring to a boil.

Step 4: Remove from heat and pour in the flour all at once.

Step 5: Mix with a spatula, taking care not to leave any lumps.

Step 6: You obtain a paste called "panade". Dry out the panade on the heat while stirring with the spatula, until it pulls away from the sides of the pan and forms a ball.

Step 7: Transfer the panade to the mixer bowl and stir for a few moments with the paddle attachment to let it cool down slightly.

Step 8: Incorporate 4 eggs to the panade one by one at low speed with the electric mixer. (See Tip 1)

Step 9: Transfer the resulting dough into a piping bag.

Step 10: Pipe the eclairs onto a baking sheet, arranging them in a staggered pattern. They should not exceed 12 to 13 cm in length. (See Tip 2)

Step 11: Bake in an oven preheated to 170 degrees Celsius until the dough is golden brown and the choux sound hollow. Once they're done, take them out of the oven and let cool. (See Tip 3)
```
<sup>Showing 50 of 117 lines. The full recipe covers choux pastry, chocolate pastry cream, chocolate icing, and assembly with 11 ingredients, 36 steps, and 8 tips.</sup>

---

### Edit Tasks (5 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Recipe Split** | Split this recipe into 4 files: `recipe_choux.txt`, `recipe_pastry_cream.txt`, `recipe_icing.txt`, and `recipe_assembly.txt`. Each file should have its own title, ingredients, steps, and tips sections. Distribute ingredients to where they're used; if shared, include in each with the appropriate portion. Renumber steps in each file from 1. Include an empty ingredients section if a file has none. | Merge the 4 recipe files into `recipe_eclair.txt` with the title 'CHOCOLATE ECLAIR RECIPE'. Combine in order: choux pastry, pastry cream, icing, assembly. Renumber steps sequentially from 1. Merge tips into one section starting at 1. Deduplicate ingredients by combining amounts for the same ingredient, formatted as 'Ingredient [i]: [quantity] [unit] [description]'. | split & merge, classification, numerical reasoning |
| 2 | **Blog Post Conversion** | Rewrite `recipe_eclair.txt` into a casual blog-post style. Add a personal intro (2–3 paragraphs) about how your grandma taught you this recipe and why éclairs are special to you. Sprinkle in 2–4 brief, high-level historical notes about pâte à choux and French pastry traditions, but keep them generic and paraphrased: do not include specific names, dates, book titles, citations, or quotes. Format the ingredients as a Markdown table with columns 'Ingredient' and 'Amount'. Write the preparation as flowing prose paragraphs, weaving in tips near the relevant parts. Keep all step and tip numbers referenced in the text, and keep the exact wording of all steps and tips. | Create a formal structured recipe from this blog post. Remove all personal stories, historical commentary, and casual prose. Convert the ingredient table to 'Ingredient [i]: [quantity] [unit] [description]' format. Extract steps from the prose as a numbered list. Collect tips into a separate section as a numbered list. Format as: '# CHOCOLATE ECLAIR RECIPE', ## INGREDIENTS, ## PREPARATION STEPS, ## CHEF'S TIPS. Keep exact wording of steps and tips. | context expansion, format knowledge |
| 3 | **Imperial Scaling** | In `recipe_eclair.txt`, scale the recipe from 12 éclairs to 30 éclairs and convert all ingredient measurements and any temperatures to imperial units. Update the title to say it's for 30 éclairs. Use only these conversions and rounding rules: 1 mL = 0.033814 fl oz; 1 L = 33.814 fl oz; 1 g = 0.035274 oz; 28.3495 g = 1 oz; 16 oz = 1 lb; °F = (°C × 9/5) + 32. Round weights to the nearest 0.1 oz (use lb + oz if over 16 oz), round volumes to the nearest 0.1 fl oz, and round temperatures to the nearest whole °F. Keep all steps and tips the same except for measurements that need converting; do not change wording otherwise. | Scale this recipe to 12 eclairs and convert all measurements to metric units. Update the title to reflect 12 eclairs. Format ingredients as 'Ingredient [i]: [quantity] [unit] [description]'. Keep all steps and tips the same except for measurements that need converting. | numerical reasoning |
| 4 | **Equipment Tracks** | Reorganize this recipe by equipment station into four files: `track_oven.txt`, `track_stovetop.txt`, `track_mixer.txt`, and `track_bench.txt`. Each file should have `# TRACK: [NAME]`, then `## INGREDIENTS` (only ingredients for that track, `Ingredient N:` format), `## STEPS`, and `## CHEF'S TIPS` (tips for relevant steps). Include shared ingredients in each track with appropriate portions. For unrelated tips, choose the most relevant track. Renumber ingredients, steps, and tips from 1, keeping wording exactly the same. Generate `timeline.csv` with columns `OrigStep,Track,TrackStep` mapping each original step to its track and new step number. | Merge the track files into `recipe_eclair.txt` titled `# CHOCOLATE ECLAIR RECIPE (for 12 eclairs)`. Use `timeline.csv` to order steps sequentially, renumbered from 1. Combine all ingredients into one `## INGREDIENTS` section, deduplicating by summing amounts and numbering from 1. Collect all tips into `## CHEF'S TIPS`, numbering from 1. Keep wording exactly the same. Delete timeline.csv. | split & merge, classification, format knowledge, numerical reasoning, sorting |
| 5 | **Measurement References** | Replace every numeric value or measurement in the steps and tips with reference tokens [M1], [M2], etc. Don't touch the ingredients section. Reuse tokens for repeated values. Keep all other wording the same. Add a `## MEASUREMENT MAP` section at the bottom listing each token and the text it replaced, like `M1 = 100g`. | Expand each [M__] token in the steps and tips using values from the MEASUREMENT MAP, then remove that section. | string manipulation, referencing, numerical reasoning, format knowledge |
