from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, ujson as json


ALLERGEN_CODES = {'Sh': 'Shellfish', 'F': 'Fish', 'G': 'Gluten', 'D': 'Dairy', 'E': 'Egg', 'N': 'Nuts', 'Se': 'Sesame', 'So': 'Soy'}
INDICATOR_CODES = {'A': 'alcoholic', 'V': 'vegetarian', 'VG': 'vegan'}


def split_name_description(text):
    # If text starts with ALL CAPS words followed by regular sentence, split them
    # Strategy: find consecutive ALL CAPS words (2+ letters), then check if remainder is a sentence
    words = text.split()
    if not words:
        return text.strip(), None
    
    # Find where ALL CAPS words end
    # A word is "all caps" only if it has 2+ letters and all are uppercase
    # Single letters like "A" could be the article starting a description
    caps_end = 0
    for i, word in enumerate(words):
        word_letters = re.sub(r'[^A-Za-z]', '', word)
        # Require 2+ letters for a word to count as ALL CAPS
        if len(word_letters) >= 2 and word_letters.isupper():
            caps_end = i + 1
        else:
            break
    
    # Need at least 2 ALL CAPS words and remaining text must start with sentence
    if caps_end >= 2 and caps_end < len(words):
        remaining = ' '.join(words[caps_end:])
        # Check if remaining looks like a sentence (has lowercase letters)
        if remaining and any(c.islower() for c in remaining[:30]):
            name = ' '.join(words[:caps_end])
            return name, remaining
    
    return text.strip(), None


def parse_menu_item(line, current_section):
    # Parse a single menu item line
    # Format: NAME [description] $PRICE [allergens] (indicators)
    line = line.strip()
    if not line or line.startswith('---') or line.startswith('===') or line.startswith('ALLERGEN') or line.startswith('OTHER'):
        return None
    
    # Extract price
    price_match = re.search(r'\$(\d+\.\d{2})', line)
    if not price_match:
        return None
    
    price = float(price_match.group(1))
    price_pos = price_match.start()
    
    # Text before price is name/description
    text_before = line[:price_pos].strip()
    # Text after price contains allergens and indicators
    text_after = line[price_match.end():].strip()
    
    # Extract allergens [XX]
    allergens = re.findall(r'\[([A-Za-z]+)\]', text_after)
    
    # Extract indicators (A), (V), (VG)
    indicators = re.findall(r'\(([AVG]+)\)', text_after)
    
    # Parse indicators into flags
    is_alcoholic = 'A' in indicators
    is_vegetarian = 'V' in indicators or 'VG' in indicators
    is_vegan = 'VG' in indicators
    
    # Split name and description
    name, description = split_name_description(text_before)
    
    return {
        'name': name,
        'description': description,
        'price': price,
        'section': current_section,
        'allergens': allergens,
        'is_alcoholic': is_alcoholic,
        'is_vegetarian': is_vegetarian,
        'is_vegan': is_vegan,
    }


def parse_menu_metadata(text):
    # Extract restaurant name, location, date from header
    metadata = {}
    name_match = re.search(r'^=+\s*\n\s*(.+?)\s*\n=+', text, re.MULTILINE)
    if name_match:
        metadata['restaurant_name'] = name_match.group(1).strip()
    
    loc_match = re.search(r'Location:\s*(.+)', text)
    if loc_match:
        metadata['location'] = loc_match.group(1).strip()
    
    date_match = re.search(r'Date:\s*(\d{4}-\d{2}-\d{2})', text)
    if date_match:
        metadata['date'] = date_match.group(1)
    
    return metadata


def parse_menu(text):
    metadata = parse_menu_metadata(text)
    items = []
    sections = []
    current_section = None
    
    for line in text.split('\n'):
        # Check for section header: --- SECTION NAME ---
        # Must have actual text (not just dashes) between the delimiters
        section_match = re.match(r'^---\s*([A-Za-z][A-Za-z\s]+?)\s*---$', line.strip())
        if section_match:
            current_section = section_match.group(1).strip()
            sections.append(current_section)
            continue
        
        # Skip non-item lines
        if not line.strip() or line.strip().startswith('='):
            continue
        # Skip pure-dash separator lines, but not lines with '-' as bullet prefix
        if re.match(r'^\s*-+\s*$', line):
            continue
        if any(line.strip().startswith(x) for x in ['Location:', 'Date:', 'ALLERGEN', 'OTHER', '[Sh]', '[F]', '[G]', '[E]', '[N]', '[Se]', '[So]', '(A)', '(V)']):
            continue
        
        item = parse_menu_item(line, current_section)
        if item:
            items.append(item)
    
    return {'metadata': metadata, 'sections': sections, 'items': items}


def compute_item_similarity(ref_item, cand_item):
    # Multiplicative penalty approach: each error dimension multiplies down the score
    # Formula: penalty_factor = 1 - severity * (1 - similarity)
    # This gives direct control: if severity=0.8 and sim=0.5, factor=0.6 (40% loss)
    
    # Name similarity (base score, most important)
    name_sim = SequenceMatcher(None, ref_item['name'].lower(), cand_item['name'].lower()).ratio()
    
    # Description similarity
    if ref_item['description'] and cand_item['description']:
        desc_sim = SequenceMatcher(None, ref_item['description'].lower(), cand_item['description'].lower()).ratio()
    elif ref_item['description'] or cand_item['description']:
        desc_sim = 0.5  # partial penalty if one has description and other doesn't
    else:
        desc_sim = 1.0
    
    # Price similarity (ratio-based)
    if ref_item['price'] == cand_item['price']:
        price_sim = 1.0
    elif ref_item['price'] == 0 or cand_item['price'] == 0:
        price_sim = 0.0
    else:
        price_sim = min(ref_item['price'], cand_item['price']) / max(ref_item['price'], cand_item['price'])
    
    # Section match (binary)
    section_sim = 1.0 if ref_item['section'] == cand_item['section'] else 0.0
    
    # Allergen similarity (Jaccard, but with penalty for any difference)
    ref_allergens = set(ref_item['allergens'])
    cand_allergens = set(cand_item['allergens'])
    if len(ref_allergens) == 0 and len(cand_allergens) == 0:
        allergen_sim = 1.0
    elif len(ref_allergens | cand_allergens) == 0:
        allergen_sim = 1.0
    else:
        allergen_sim = len(ref_allergens & cand_allergens) / len(ref_allergens | cand_allergens)
    
    # Flags similarity (per-flag check)
    flags_correct = 0
    flags_total = 3
    if ref_item['is_alcoholic'] == cand_item['is_alcoholic']: flags_correct += 1
    if ref_item['is_vegetarian'] == cand_item['is_vegetarian']: flags_correct += 1
    if ref_item['is_vegan'] == cand_item['is_vegan']: flags_correct += 1
    flags_sim = flags_correct / flags_total
    
    # Severity weights: how much does an error in this dimension hurt?
    # severity=0.8 means a 50% similarity → 60% of score (40% loss)
    SEVERITY_PRICE = 0.8       # doubled price → 40% loss
    SEVERITY_SECTION = 0.6     # wrong section → 30% loss (since section_sim=0 when wrong)
    SEVERITY_ALLERGEN = 0.7    # missing all allergens → 35% loss
    SEVERITY_FLAGS = 0.6       # all flags wrong → 20% loss (since flags_sim=0 when all wrong)
    SEVERITY_DESC = 0.3        # missing description → 15% loss
    
    # Compute penalty factors
    price_factor = 1 - SEVERITY_PRICE * (1 - price_sim)
    section_factor = 1 - SEVERITY_SECTION * (1 - section_sim)
    allergen_factor = 1 - SEVERITY_ALLERGEN * (1 - allergen_sim)
    flags_factor = 1 - SEVERITY_FLAGS * (1 - flags_sim)
    desc_factor = 1 - SEVERITY_DESC * (1 - desc_sim)
    
    # Final score: name_sim as base, multiplied by all penalty factors
    return name_sim * price_factor * section_factor * allergen_factor * flags_factor * desc_factor


def compute_menu_matching_score(ref_items, cand_items):
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    
    if len(ref_items) == 0:
        return 1.0 if len(cand_items) == 0 else 0.0
    if len(cand_items) == 0:
        return 0.0
    
    n_ref, n_cand = len(ref_items), len(cand_items)
    sim_matrix = np.zeros((n_ref, n_cand))
    for i, ref in enumerate(ref_items):
        for j, cand in enumerate(cand_items):
            sim_matrix[i, j] = compute_item_similarity(ref, cand)
    
    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    matched_similarity = sim_matrix[row_ind, col_ind].sum()
    
    # Penalize for count mismatch
    count_penalty = min(n_ref, n_cand) / max(n_ref, n_cand)
    return (matched_similarity / n_ref) * (0.5 + 0.5 * count_penalty)


class DomainFoodMenu(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "foodmenu"
        self.summary = "Restaurant menus with items, prices, descriptions, and allergen info"
        self.description = "Restaurant menus"
        self.file_format = [".txt"]
        self.domain_parser = "custom"
        self.category = "everyday"
    
    def preprocess_context(self, context: str) -> str:
        """Normalize raw menu text before parsing.
        
        Fixes common LLM formatting variations:
        1. Bullet prefixes (-, •, *) on item lines
        2. Price-first layout ($X.XX Item Name) → rewritten to (Item Name $X.XX)
        3. Dotted/dashed filler between name and price
        4. Numbered list prefixes (1. Item $5.00)
        5. Em/en dash separators before prices (Item — $5.00)
        6. Bare all-caps section headers (MENU → --- MENU ---)
        """
        lines = context.split('\n')
        result = []
        # Only treat as having a header block if the file starts with ====...
        first_nonempty = next((l.strip() for l in lines if l.strip()), '')
        in_header_block = first_nonempty.startswith('=')
        for line in lines:
            stripped = line.strip()
            
            # Don't touch existing section headers, metadata, or empty lines
            if not stripped or re.match(r'^---\s*[A-Za-z]', stripped) or stripped.startswith('='):
                result.append(line)
                # A dashed separator (----...) after the header block marks end
                if re.match(r'^-{4,}$', stripped):
                    in_header_block = False
                continue
            
            # Convert bare all-caps section headers to --- NAME --- format.
            # Only after the header/metadata block to avoid matching restaurant
            # names in the title block (e.g., "SAN CARLOS COFFEE SHOP" between
            # ==== lines).  Also skip metadata prefixes.
            if (not in_header_block
                    and len(stripped) <= 40
                    and '$' not in stripped
                    and re.match(r'^[A-Z][A-Z &/\'-]+$', stripped)
                    and not any(stripped.startswith(x) for x in
                                ['ALLERGEN', 'OTHER', 'LOCATION', 'DATE'])):
                result.append(f'--- {stripped} ---')
                continue
            
            # Once we see a non-empty, non-metadata content line, we're past the
            # header block.
            if in_header_block and not any(stripped.startswith(x) for x in
                                            ['Location:', 'Date:']):
                in_header_block = False
            
            # Strip bullet prefixes: "- Item $5.00" or "• Item $5.00" or "* Item $5.00"
            bullet_match = re.match(r'^\s*[-•\*]\s+', line)
            if bullet_match:
                line = line[bullet_match.end():]
                stripped = line.strip()
            
            # Strip numbered list prefixes: "1. Item $5.00", "103. Item $5.00"
            num_match = re.match(r'^\s*\d+[\.\)]\s+', line)
            if num_match:
                line = line[num_match.end():]
                stripped = line.strip()
            
            # Remove dotted/dashed filler between name and price
            # e.g. "Cook's Imperial ........................................ $1.25"
            line = re.sub(r'\s*[\.]{3,}\s*', '  ', line)
            line = re.sub(r'\s*[-]{3,}\s*(?=\$)', '  ', line)
            
            # Remove em/en dash separators before prices:
            # "Blue Point Fricassee — $0.50" → "Blue Point Fricassee  $0.50"
            line = re.sub(r'\s*[—–]\s*(?=\$)', '  ', line)
            stripped = line.strip()
            
            # Fix price-first layout: "$0.40  Bluefish, Broiled  [F]" → "Bluefish, Broiled  $0.40  [F]"
            price_first_match = re.match(r'^\s*\$(\d+\.\d{2})\s+(.+)$', stripped)
            if price_first_match:
                price = price_first_match.group(1)
                rest = price_first_match.group(2)
                # Extract allergens and indicators from end of rest
                suffix_parts = []
                # Pull trailing [XX] and (XX) tags
                while True:
                    tag_match = re.search(r'\s*(\[[A-Za-z]+\]|\([AVG]+\))\s*$', rest)
                    if tag_match:
                        suffix_parts.insert(0, tag_match.group(1))
                        rest = rest[:tag_match.start()]
                    else:
                        break
                suffix = '  '.join(suffix_parts)
                line = f"  {rest.strip()}  ${price}" + (f"  {suffix}" if suffix else "")
                stripped = line.strip()
            
            result.append(line)
        return '\n'.join(result)
    
    def parse_all_menus(self, context):
        all_menus = []
        for filename, content in context.items():
            content = self.preprocess_context(content)
            all_menus.append(parse_menu(content))
        return all_menus
    
    def parse_context(self, context):
        menus = self.parse_all_menus(context)
        return self.merge_menus(menus)
    
    def compute_domain_statistics(self, context):
        merged = self.parse_context(context)
        items = merged.get('items', [])
        sections = set(i.get('section', '') for i in items if i.get('section'))
        vegetarian = sum(1 for i in items if i.get('is_vegetarian'))
        with_allergens = sum(1 for i in items if i.get('allergens'))
        return {
            "Menu Items": len(items),
            "Sections": len(sections),
            "Vegetarian": vegetarian,
            "With Allergens": with_allergens,
        }
    
    def merge_menus(self, menus):
        merged = {'metadata': {}, 'sections': [], 'items': []}
        for menu in menus:
            merged['metadata'].update(menu['metadata'])
            merged['sections'].extend(menu['sections'])
            merged['items'].extend(menu['items'])
        merged['sections'] = list(dict.fromkeys(merged['sections']))  # dedupe preserving order
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
        
        gen_menu = self.parse_context(generated_context)
        ref_menu = self.parse_context(reference_context)
        
        score_items = compute_menu_matching_score(ref_menu['items'], gen_menu['items'])
        
        # Section similarity
        ref_sections = set(ref_menu['sections'])
        gen_sections = set(gen_menu['sections'])
        if len(ref_sections | gen_sections) > 0:
            score_sections = len(ref_sections & gen_sections) / len(ref_sections | gen_sections)
        else:
            score_sections = 1.0
        
        score = 0.85 * score_items + 0.15 * score_sections
        
        eval_obj = {
            "score": score,
            "score_items": score_items,
            "score_sections": score_sections,
            "count_items": len(gen_menu['items']),
            "count_sections": len(gen_menu['sections']),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


if __name__ == "__main__":
    # Test the parser
    with open("samples/foodmenu/basic_state/menu.txt", "r") as f:
        text = f.read()
    
    menu = parse_menu(text)
    
    print("=" * 60)
    print("METADATA")
    print("=" * 60)
    for k, v in menu['metadata'].items():
        print(f"  {k}: {v}")
    
    print("\n" + "=" * 60)
    print(f"SECTIONS ({len(menu['sections'])})")
    print("=" * 60)
    for section in menu['sections']:
        print(f"  - {section}")
    
    print("\n" + "=" * 60)
    print(f"ITEMS ({len(menu['items'])})")
    print("=" * 60)
    
    current_section = None
    for item in menu['items']:
        if item['section'] != current_section:
            current_section = item['section']
            print(f"\n--- {current_section} ---")
        
        allergens_str = ','.join(item['allergens']) if item['allergens'] else '-'
        flags = []
        if item['is_alcoholic']: flags.append('A')
        if item['is_vegetarian']: flags.append('V')
        if item['is_vegan']: flags.append('VG')
        flags_str = ','.join(flags) if flags else '-'
        
        desc_preview = (item['description'][:40] + '...') if item['description'] and len(item['description']) > 40 else (item['description'] or '-')
        
        print(f"  ${item['price']:.2f} | {item['name'][:30]:<30} | {desc_preview:<45} | [{allergens_str}] ({flags_str})")
