# <img src="../assets/domain_icons/foodmenu.svg" width="28" height="28" style="vertical-align: middle;"> Food Menu

**Category:** Everyday
**File format:** `.txt`
**Summary:** Restaurant menus with items, prices, descriptions, and allergen info
**Work environments released:** 6 / 6

Plain-text restaurant menu files list dishes organized by section (drinks, appetizers, entrées, etc.), each with a name, optional description, price, allergen markers (e.g., `[Sh]` for shellfish, `[G]` for gluten), and dietary indicators (`(A)` alcoholic, `(V)` vegetarian, `(VG)` vegan). This domain tests an LLM's ability to manipulate structured culinary data — adjusting prices with arithmetic, splitting and merging sections, inferring allergens from dish descriptions, and reformatting items across different layouts.

**Domain implementation:** [`domain_foodmenu.py`](../domains/domain_foodmenu.py)

---

## Evaluation

The food menu domain evaluator parses menu items for name, description, price, allergens, and dietary indicators, then scores reconstruction quality across two dimensions:

- **Item matching (85%)** — Uses Hungarian algorithm for optimal alignment of items, with multiplicative penalty factors for mismatches in name (base score via sequence similarity), price (ratio-based, severity 0.8), section placement (binary, severity 0.6), allergen codes (Jaccard, severity 0.7), dietary flags (per-flag check, severity 0.6), and description text (sequence similarity, severity 0.3)
- **Section similarity (15%)** — Jaccard similarity over section names to verify structural preservation

**Score formula:** `0.85 × item_matching + 0.15 × section_jaccard`

---

## Example Work Environment: `foodmenu1`

**Document:** House of Chan Restaurant Menu
**Source:** [NYPL Menu Collection #28877](http://menus.nypl.org/menus/28877) (CC0 1.0 Universal — Public Domain)
**Size:** 158 lines · 3,244 tokens

### Seed Document Excerpt (`house_of_chan_menu.txt`)

```text
============================================================
  HOUSE OF CHAN
============================================================

Location: House Of Chan
Date: 1962-01-01

------------------------------------------------------------

--- DRINKS ---

  GENTLE DRAGON COCKTAIL                            $1.50  (A)
  LOTUS BLOSSOM COCKTAIL                            $1.25  (A)
  Bloody Mary                                       $0.90  (A)
  Daiquiri                                          $0.80  (A)
  Old Fashioned                                     $0.85  (A)
  Manhattan                                         $0.80  (A)
  Champagne                                         $1.10  (A)
  Martini                                           $0.80  (A)
  Brandy Alexander                                  $1.00  (A) [E]
  Stinger                                           $0.80  (A)
  Rye Sour                                          $0.85  (A) [E]
  Rum Sour                                          $0.85  (A) [E]
  Scotch Sour                                       $1.05  (A) [E]
  Bourbon Sour                                      $1.05  (A) [E]
  Standard Brands BONDED BOURBON                    $0.90  (A)
  Standard Brands BLENDED RYE                       $0.70  (A)
  Standard Brands SCOTCH WHISKIES                   $0.90  (A)
  Premium Brands BLENDED RYE                        $0.80  (A)
  Premium Brands BONDED BOURBON                     $0.95  (A)
  Premium Brands SCOTCH WHISKIES                    $0.95  (A)
  Piper Heidsieck                                   $3.50  (A)
  Great Western                                     $3.00  (A)
  Ballantine Ale                                    $0.60  (A) [G]
  Collins                                           $0.80  (A)
  Budweiser Beer                                    $0.60  (A) [G]
  Planter's Punch                                   $1.05  (A)
  Heineken Beer                                     $0.75  (A) [G]
  Singapore Sling                                   $0.95  (A)
```
<sup>Showing 44 of 158 lines. The full menu contains ~80 items across 6 sections (Drinks, Appetizers, Entrees, Chow Mein, Fried Rice, Sides), with an allergen legend and dietary indicator key at the bottom.</sup>

---

### Edit Tasks (8 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Price Increase** | Meat prices have gone up and we need to adjust the menu. Increase price of any dish with chicken by 20%, fish or seafood by 30%, and beef dishes by 40%. Round to nearest $0.05. | Meat prices have come down. We had raised chicken dishes by 20%, seafood dishes by 30%, and beef dishes by 40% — decrease them back by those same percentages. Round to $0.05. | numerical reasoning |
| 2 | **Entree Split** | Customers say the entrees section is too long and hard to navigate. Split ENTREES into subsections based on main protein: SEAFOOD ENTREES, BEEF ENTREES, CHICKEN & DUCK ENTREES, PORK ENTREES. Keep items in same order within each new section. Use same `---` format for section headers. | The separate protein sections are confusing customers who want variety. Merge SEAFOOD ENTREES, BEEF ENTREES, CHICKEN & DUCK ENTREES, and PORK ENTREES back into a single ENTREES section. Keep items in order: seafood first, then beef, then chicken/duck, then pork. | split & merge, classification |
| 3 | **Allergen Removal** | The allergen markers are cluttering the menu and customers find them overwhelming. Remove all the allergen brackets `[Sh]`, `[G]`, etc. from each item, and also remove the ALLERGEN LEGEND section at the bottom. Keep the `(A)`, `(V)`, `(VG)` markers though. | We've been getting requests from customers with food allergies. Add allergen markers after the price on each line using brackets: `[Sh]`=shellfish, `[F]`=fish, `[G]`=gluten, `[D]`=dairy, `[E]`=egg, `[N]`=nuts, `[Se]`=sesame, `[So]`=soy. Also add an ALLERGEN LEGEND section at the bottom. Figure out allergens from the dish names and descriptions. | domain knowledge |
| 4 | **Full Descriptions** | We want to upsell more by making every item sound appetizing. Add a short enticing description (10–20 words) to every item that doesn't already have one. Format same as entrees. Be creative but keep it classy — this is an upscale 1960s restaurant. | The menu is too wordy now and takes forever to read. Remove descriptions from everything except ENTREES. Non-entree item names should revert to not all caps. | context expansion |
| 5 | **Numbered Items** | Customers have trouble pronouncing Chinese dish names when ordering. Add sequential item numbers per section, using a letter code for the section followed by a number (e.g., `D1. Bloody Mary`). | The item numbers make the menu look like a takeout joint. Remove all item number prefixes. | string manipulation |
| 6 | **First-Timer Guide** | Add pronunciation guide in parentheses after Chinese dish names like `MOO GOO GAI PAN (moo-goo-guy-pan)`. Mark beginner-friendly dishes with ★ and adventurous dishes with ♦. Reorganize each section so ★ items come first, unmarked middle, ♦ last. Create `first_visit.txt` with top 10 recommendations for newcomers and why. | Remove the pronunciation guides in parentheses from dish names. Remove all ★ and ♦ markers. Delete `first_visit.txt`. | context expansion, classification, sorting |
| 7 | **Banquet Course Split** | Split the menu into separate files by section (`house_of_chan_drinks.txt`, `house_of_chan_appetizers.txt`, etc.). Move the allergen legend into `house_of_chan_allergen_legend.txt`. Within each course file, sort items by price from highest to lowest. Create `banquet_order.json` mapping each section to an array of item names in their original sequence. | Merge the course files back into a single `house_of_chan_menu.txt`. Use `banquet_order.json` to restore the original item order within each section. Fold allergen legend content back into the bottom of the menu. Delete all split files and `banquet_order.json`. | split & merge, sorting, referencing |
| 8 | **Entree Block Format** | Reformat each entree so the ALL CAPS dish name sits alone on the first line, and the description text plus price and markers go on the next line indented 4 spaces. Leave a blank line between each entree block. Add a FORMAT NOTE line after the ENTREES header. Non-entree sections stay as-is. | Collapse each two-line entree block back to a single line joined by a space. Remove the blank lines between entree items. Remove the FORMAT NOTE line after the ENTREES header. | string manipulation |
