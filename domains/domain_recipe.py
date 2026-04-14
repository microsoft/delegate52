from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, ujson as json


UNIT_NORMALIZATION = {
    # Volume - base: L
    'l': ('L', 1.0), 'L': ('L', 1.0), 'liter': ('L', 1.0), 'liters': ('L', 1.0), 'litre': ('L', 1.0), 'litres': ('L', 1.0),
    'ml': ('L', 0.001), 'mL': ('L', 0.001), 'milliliter': ('L', 0.001), 'milliliters': ('L', 0.001),
    'cup': ('L', 0.237), 'cups': ('L', 0.237),
    # Mass - base: g
    'g': ('g', 1.0), 'gram': ('g', 1.0), 'grams': ('g', 1.0),
    'kg': ('g', 1000.0), 'kilogram': ('g', 1000.0), 'kilograms': ('g', 1000.0),
    'oz': ('g', 28.35), 'ounce': ('g', 28.35), 'ounces': ('g', 28.35),
    'lb': ('g', 453.6), 'pound': ('g', 453.6), 'pounds': ('g', 453.6),
    # Spoon measures - base: tbsp
    'tablespoon': ('tbsp', 1.0), 'tablespoons': ('tbsp', 1.0), 'tbsp': ('tbsp', 1.0),
    'teaspoon': ('tbsp', 0.333), 'teaspoons': ('tbsp', 0.333), 'tsp': ('tbsp', 0.333),
    # Other
    'pinch': ('pinch', 1.0),
}

KNOWN_UNITS = set(UNIT_NORMALIZATION.keys()) | {'whole', 'large', 'medium', 'small', 'fine'}


def normalize_unit(unit):
    if unit is None:
        return None, 1.0
    unit_clean = unit.lower().strip()
    if unit_clean in UNIT_NORMALIZATION:
        return UNIT_NORMALIZATION[unit_clean]
    return (unit_clean, 1.0)


def parse_ingredient(text):
    # Extract quantity, unit, and ingredient name from text like "200 g Type 55 flour"
    # Handle fractions like "1/4"
    frac_match = re.match(r'^(\d+)/(\d+)\s+(\S+)\s+(.*)$', text)
    if frac_match:
        qty = float(frac_match.group(1)) / float(frac_match.group(2))
        unit = frac_match.group(3)
        name = frac_match.group(4).strip()
        return qty, unit, name
    
    # Handle "quantity unit name" pattern
    full_match = re.match(r'^([\d.]+)\s+(\S+)\s+(.*)$', text)
    if full_match:
        qty = float(full_match.group(1))
        unit = full_match.group(2)
        name = full_match.group(3).strip()
        return qty, unit, name
    
    # Handle "quantity name" (no unit, e.g., "5 whole eggs")
    num_match = re.match(r'^([\d.]+)\s+(.*)$', text)
    if num_match:
        return float(num_match.group(1)), None, num_match.group(2).strip()
    
    # No quantity found
    return None, None, text


def parse_recipe(text):
    ingredients = []
    for m in re.finditer(r'Ingredient\s+(\d+):\s*(.+)', text):
        qty, unit, name = parse_ingredient(m.group(2).strip())
        ingredients.append({"number": int(m.group(1)), "description": m.group(2).strip(), "quantity": qty, "unit": unit, "ingredient_name": name})
    steps = [{"number": int(m.group(1)), "description": m.group(2).strip()} for m in re.finditer(r'Step\s+(\d+):\s*(.+)', text)]
    tips = [{"number": int(m.group(1)), "description": m.group(2).strip()} for m in re.finditer(r'Tip\s+(\d+):\s*(.+)', text)]
    return {"ingredients": ingredients, "steps": steps, "tips": tips}


def compute_quantity_similarity(q1, u1, q2, u2):
    # Normalize units and convert to base units, then compare quantities
    base_unit1, factor1 = normalize_unit(u1)
    base_unit2, factor2 = normalize_unit(u2)
    
    # Convert to base units
    base_q1 = q1 * factor1 if q1 is not None else None
    base_q2 = q2 * factor2 if q2 is not None else None
    
    # If units are incompatible (different base types), penalize
    if base_unit1 != base_unit2 and base_unit1 is not None and base_unit2 is not None:
        return 0.5
    
    # Compare quantities
    if base_q1 is None or base_q2 is None:
        return 1.0 if base_q1 == base_q2 else 0.5
    if base_q1 == 0 and base_q2 == 0:
        return 1.0
    if base_q1 == 0 or base_q2 == 0:
        return 0.0
    return min(base_q1, base_q2) / max(base_q1, base_q2)


def compute_ingredient_matching_score(reference_items, candidate_items):
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    # Match on ingredient_name, then score with name_similarity * quantity_similarity
    if len(reference_items) == 0:
        return 1.0 if len(candidate_items) == 0 else 0.0
    if len(candidate_items) == 0:
        return 0.0
    
    n_ref, n_cand = len(reference_items), len(candidate_items)
    # Build similarity matrix based on ingredient_name only (for matching)
    name_sim_matrix = np.zeros((n_ref, n_cand))
    for i, ref in enumerate(reference_items):
        for j, cand in enumerate(candidate_items):
            name_sim_matrix[i, j] = SequenceMatcher(None, ref["ingredient_name"], cand["ingredient_name"]).ratio()
    
    # Hungarian algorithm to find optimal matching based on names
    row_ind, col_ind = linear_sum_assignment(1 - name_sim_matrix)
    
    # Compute pair scores: name_similarity * quantity_similarity
    pair_scores = []
    for i, j in zip(row_ind, col_ind):
        name_sim = name_sim_matrix[i, j]
        qty_sim = compute_quantity_similarity(reference_items[i]["quantity"], reference_items[i].get("unit"), candidate_items[j]["quantity"], candidate_items[j].get("unit"))
        pair_scores.append(name_sim * qty_sim)
    
    # Mean over all reference items (unmatched refs contribute 0)
    return sum(pair_scores) / n_ref


def compute_bipartite_matching_score(reference_items, candidate_items):
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    # Score based on optimal 1-to-1 matching using Hungarian algorithm
    if len(reference_items) == 0:
        return 1.0 if len(candidate_items) == 0 else 0.0
    if len(candidate_items) == 0:
        return 0.0
    
    # Build similarity matrix (reference x candidate)
    n_ref, n_cand = len(reference_items), len(candidate_items)
    sim_matrix = np.zeros((n_ref, n_cand))
    for i, ref in enumerate(reference_items):
        for j, cand in enumerate(candidate_items):
            sim_matrix[i, j] = SequenceMatcher(None, ref["description"], cand["description"]).ratio()
    
    # Hungarian algorithm minimizes cost, so we use (1 - similarity) as cost
    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    matched_similarity = sim_matrix[row_ind, col_ind].sum()
    return matched_similarity / n_ref


def compute_steps_score(reference_steps, candidate_steps):
    # Concatenate steps in order and compute Levenshtein ratio, weighted by coverage
    if len(reference_steps) == 0:
        return 1.0 if len(candidate_steps) == 0 else 0.0
    if len(candidate_steps) == 0:
        return 0.0
    
    coverage = min(len(candidate_steps), len(reference_steps)) / len(reference_steps)
    ref_sorted = sorted(reference_steps, key=lambda x: x["number"])
    cand_sorted = sorted(candidate_steps, key=lambda x: x["number"])
    ref_text = "\n".join([s["description"] for s in ref_sorted])
    cand_text = "\n".join([s["description"] for s in cand_sorted])
    text_similarity = SequenceMatcher(None, ref_text, cand_text).ratio()
    return coverage * text_similarity


class DomainRecipe(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "recipe"
        self.summary = "Cooking recipes with ingredients, quantities, steps, and timings"
        self.description = "Cooking recipes"
        self.file_format = [".txt"]
        self.domain_parser = "custom"
        self.category = "everyday"
    
    def parse_all_recipes(self, context):
        all_recipes = []
        for filename, content in context.items():
            all_recipes.append(parse_recipe(content))
        return all_recipes
    
    def parse_context(self, context):
        recipes = self.parse_all_recipes(context)
        return self.merge_recipes(recipes)
    
    def compute_domain_statistics(self, context):
        merged = self.parse_context(context)
        return {
            "Ingredients": len(merged.get('ingredients', [])),
            "Steps": len(merged.get('steps', [])),
            "Tips": len(merged.get('tips', [])),
        }
    
    def merge_recipes(self, recipes):
        # Merge multiple recipe dicts into one (in case context has multiple files)
        merged = {"ingredients": [], "steps": [], "tips": []}
        for recipe in recipes:
            merged["ingredients"].extend(recipe["ingredients"])
            merged["steps"].extend(recipe["steps"])
            merged["tips"].extend(recipe["tips"])
        return merged
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        # Parse and merge recipes from all files
        gen_recipe = self.parse_context(generated_context)
        ref_recipe = self.parse_context(reference_context)
        
        # Compute component scores
        score_ingredients = compute_ingredient_matching_score(ref_recipe["ingredients"], gen_recipe["ingredients"])
        score_steps = compute_steps_score(ref_recipe["steps"], gen_recipe["steps"])
        score_tips = compute_bipartite_matching_score(ref_recipe["tips"], gen_recipe["tips"])
        
        # Weighted aggregate
        score = 0.4 * score_ingredients + 0.4 * score_steps + 0.2 * score_tips
        
        eval_obj = {
            "score": score,
            "score_ingredients": score_ingredients,
            "score_steps": score_steps,
            "score_tips": score_tips,
            "count_ingredients": len(gen_recipe["ingredients"]),
            "count_steps": len(gen_recipe["steps"]),
            "count_tips":len(gen_recipe["tips"]),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
