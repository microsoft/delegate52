from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, ujson as json
import numpy as np
from scipy.optimize import linear_sum_assignment


def parse_slide_position(text):
    # Extract [@(x,y)] or [@(x,y) | Npt]
    match = re.search(r'\[@\((\d+),(\d+)\)(?:\s*\|\s*(\d+)pt)?\]', text)
    if match:
        return {'x': int(match.group(1)), 'y': int(match.group(2)),
                'fontsize': int(match.group(3)) if match.group(3) else None}
    return None


def parse_presentation(content):
    metadata = {}
    
    # Parse YAML frontmatter
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split('\n'):
                if ':' in line:
                    key, val = line.split(':', 1)
                    metadata[key.strip()] = val.strip().strip('"')
            content = parts[2]
    
    slides = []
    elements = []
    
    # Split by slide headers
    slide_chunks = re.split(r'^## ', content, flags=re.MULTILINE)
    
    for i, chunk in enumerate(slide_chunks[1:], 1):  # skip first empty chunk
        lines = chunk.strip().split('\n')
        if not lines:
            continue
        
        # Parse slide title
        title_line = lines[0]
        pos_info = parse_slide_position(title_line)
        title_text = re.sub(r'\s*\[@\([^)]+\)(?:\s*\|[^\]]+)?\]', '', title_line).strip()
        
        slides.append({'index': i, 'title': title_text, 'position': pos_info})
        elements.append({'slide': i, 'type': 'title', 'text': title_text,
                        'position': pos_info, 'level': 0})
        
        # Parse content lines - track notes blocks and table context
        in_notes = False
        notes_text = []
        current_table_rows = []
        
        for line in lines[1:]:
            stripped = line.strip()
            
            # Handle speaker notes blocks
            if stripped == '::: {.notes}':
                in_notes = True
                notes_text = []
                continue
            elif stripped == ':::' and in_notes:
                # End of notes block - save accumulated notes
                if notes_text:
                    elements.append({'slide': i, 'type': 'notes', 'text': ' '.join(notes_text),
                                   'position': None, 'level': 0})
                in_notes = False
                continue
            elif in_notes:
                # Accumulate notes content
                if stripped:
                    notes_text.append(stripped)
                continue
            
            if not stripped:
                continue
            
            pos_info = parse_slide_position(stripped)
            
            if stripped.startswith('- '):
                # Bullet - count indentation from original line
                indent = len(line) - len(line.lstrip())
                level = indent // 2
                text = re.sub(r'\s*\[@\([^)]+\)(?:\s*\|[^\]]+)?\]', '', stripped[2:]).strip()
                elements.append({'slide': i, 'type': 'bullet', 'text': text,
                               'position': pos_info, 'level': level})
            
            elif stripped.startswith('[IMAGE:'):
                # Image - extract filename and position from [IMAGE: name @(x,y)]
                match = re.match(r'\[IMAGE:\s*([^@\]]+?)(?:\s*@\((\d+),(\d+)\))?\]', stripped)
                if match:
                    filename = match.group(1).strip()
                    if match.group(2) and match.group(3):
                        pos_info = {'x': int(match.group(2)), 'y': int(match.group(3)), 'fontsize': None}
                    else:
                        pos_info = None
                else:
                    filename = ''
                    pos_info = None
                elements.append({'slide': i, 'type': 'image', 'text': filename,
                               'position': pos_info, 'level': 0})
            
            elif stripped.startswith('[CHART:'):
                # Chart - extract name and position from [CHART: name @(x,y)]
                match = re.match(r'\[CHART:\s*([^@\]]+?)(?:\s*@\((\d+),(\d+)\))?\]', stripped)
                if match:
                    chart_name = match.group(1).strip()
                    if match.group(2) and match.group(3):
                        pos_info = {'x': int(match.group(2)), 'y': int(match.group(3)), 'fontsize': None}
                    else:
                        pos_info = None
                else:
                    chart_name = ''
                    pos_info = None
                elements.append({'slide': i, 'type': 'chart', 'text': chart_name,
                               'position': pos_info, 'level': 0})
            
            elif stripped.startswith('[TABLE'):
                # Table marker - start collecting rows
                current_table_rows = []
                elements.append({'slide': i, 'type': 'table_marker', 'text': '',
                               'position': pos_info, 'level': 0})
            
            elif stripped.startswith('*') and '*' in stripped[1:]:
                # Subtitle (italic text)
                text = re.sub(r'\s*\[@\([^)]+\)(?:\s*\|[^\]]+)?\]', '', stripped).strip('* ')
                elements.append({'slide': i, 'type': 'subtitle', 'text': text,
                               'position': pos_info, 'level': 0})
            
            elif stripped.startswith('|') and '|' in stripped[1:]:
                # Table row - extract cell contents
                # Skip separator rows (|---|---|)
                if re.match(r'^\|[-:\s|]+\|$', stripped):
                    continue
                # Extract cell text
                cells = [c.strip() for c in stripped.split('|')[1:-1]]  # Remove empty first/last
                cell_text = ' | '.join(c for c in cells if c)  # Join non-empty cells
                if cell_text:
                    elements.append({'slide': i, 'type': 'table_row', 'text': cell_text,
                                   'position': None, 'level': 0})
    
    return {'metadata': metadata, 'slides': slides, 'elements': elements}


def compute_element_similarity(ref_el, gen_el):
    # Text similarity (primary)
    if not ref_el['text'] and not gen_el['text']:
        text_sim = 1.0
    elif not ref_el['text'] or not gen_el['text']:
        text_sim = 0.0
    else:
        text_sim = SequenceMatcher(None, ref_el['text'].lower(), gen_el['text'].lower()).ratio()
    
    # Type match
    type_match = 1.0 if ref_el['type'] == gen_el['type'] else 0.5
    
    # Position similarity (if both have positions)
    pos_sim = 1.0
    if ref_el['position'] and gen_el['position']:
        dx = abs(ref_el['position']['x'] - gen_el['position']['x'])
        dy = abs(ref_el['position']['y'] - gen_el['position']['y'])
        pos_sim = max(0, 1 - (dx + dy) / 20)  # 20 units tolerance
    
    # Level match (for bullets)
    level_sim = 1.0 if ref_el['level'] == gen_el['level'] else 0.7
    
    return text_sim * 0.55 + type_match * 0.2 + pos_sim * 0.15 + level_sim * 0.1


def compute_content_matching_score(ref_elements, gen_elements):
    # Filter to text elements (including table rows and speaker notes)
    text_types = {'title', 'bullet', 'subtitle', 'table_row', 'notes'}
    ref_text = [e for e in ref_elements if e['type'] in text_types]
    gen_text = [e for e in gen_elements if e['type'] in text_types]
    
    if not ref_text:
        return 1.0 if not gen_text else 0.0
    if not gen_text:
        return 0.0
    
    # Hungarian matching
    n_ref, n_gen = len(ref_text), len(gen_text)
    sim_matrix = np.zeros((n_ref, n_gen))
    for i, ref in enumerate(ref_text):
        for j, gen in enumerate(gen_text):
            sim_matrix[i, j] = compute_element_similarity(ref, gen)
    
    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    matched_sim = sim_matrix[row_ind, col_ind].sum()
    
    count_penalty = min(n_ref, n_gen) / max(n_ref, n_gen)
    return (matched_sim / n_ref) * (0.5 + 0.5 * count_penalty)


def compute_slide_coverage_score(ref_slides, gen_slides):
    # Normalize slide titles for comparison
    def normalize_title(t):
        t = t.lower().strip()
        t = re.sub(r'^slide\s*\d+$', '', t)  # Remove "Slide N" placeholder titles
        return t
    
    ref_titles = {normalize_title(s['title']) for s in ref_slides if normalize_title(s['title'])}
    gen_titles = {normalize_title(s['title']) for s in gen_slides if normalize_title(s['title'])}
    
    if not ref_titles and not gen_titles:
        return 1.0
    if not ref_titles or not gen_titles:
        # Fall back to count comparison
        return min(len(ref_slides), len(gen_slides)) / max(len(ref_slides), len(gen_slides))
    
    intersection = len(ref_titles & gen_titles)
    union = len(ref_titles | gen_titles)
    return intersection / union


def compute_slide_order_score(ref_slides, gen_slides):
    # Compare sequence of slide titles
    def normalize_title(t):
        return t.lower().strip()
    
    ref_seq = [normalize_title(s['title']) for s in ref_slides]
    gen_seq = [normalize_title(s['title']) for s in gen_slides]
    
    if not ref_seq and not gen_seq:
        return 1.0
    if not ref_seq or not gen_seq:
        return 0.0
    
    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


def compute_image_score(ref_elements, gen_elements):
    ref_images = {e['text'] for e in ref_elements if e['type'] == 'image' and e['text']}
    gen_images = {e['text'] for e in gen_elements if e['type'] == 'image' and e['text']}
    
    if not ref_images and not gen_images:
        return 1.0
    if not ref_images or not gen_images:
        return 0.0
    
    return len(ref_images & gen_images) / len(ref_images | gen_images)


def compute_image_order_score(ref_elements, gen_elements):
    # Extract ordered sequence of image filenames (preserving order across slides)
    ref_seq = [e['text'] for e in ref_elements if e['type'] == 'image' and e['text']]
    gen_seq = [e['text'] for e in gen_elements if e['type'] == 'image' and e['text']]
    
    if not ref_seq and not gen_seq:
        return 1.0
    if not ref_seq or not gen_seq:
        return 0.0
    
    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


def compute_position_accuracy_score(ref_elements, gen_elements):
    # For elements that match by text, compare positions
    ref_by_text = {}
    for e in ref_elements:
        if e['text'] and e['position']:
            key = (e['type'], e['text'].lower()[:50])
            ref_by_text[key] = e['position']
    
    gen_by_text = {}
    for e in gen_elements:
        if e['text'] and e['position']:
            key = (e['type'], e['text'].lower()[:50])
            gen_by_text[key] = e['position']
    
    if not ref_by_text:
        return 1.0  # No positions to compare in reference
    
    # Score over ALL reference positioned elements — unmatched get 0
    pos_scores = []
    for key in ref_by_text:
        if key in gen_by_text:
            ref_pos = ref_by_text[key]
            gen_pos = gen_by_text[key]
            dx = abs(ref_pos['x'] - gen_pos['x'])
            dy = abs(ref_pos['y'] - gen_pos['y'])
            score = max(0, 1 - (dx + dy) / 10)  # Stricter tolerance
            pos_scores.append(score)
        else:
            pos_scores.append(0.0)
    
    return sum(pos_scores) / len(pos_scores)


class DomainSlides(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "slides"
        self.summary = "Markdown presentations with slides, bullet points, and speaker notes"
        self.description = "Presentation slides"
        self.file_format = [".md"]
        self.domain_parser = "custom"
        self.category = "creative"
    
    def parse_all_presentations(self, context):
        presentations = []
        for filename, content in context.items():
            if filename.endswith('.md'):
                presentations.append(parse_presentation(content))
        return presentations

    def parse_context(self, context):
        presentations = self.parse_all_presentations(context)
        return self.merge_presentations(presentations)
    
    def compute_domain_statistics(self, context):
        merged = self.parse_context(context)
        slides = merged.get('slides', [])
        elements = merged.get('elements', [])
        bullets = sum(1 for e in elements if e.get('type') == 'bullet')
        images = sum(1 for e in elements if e.get('type') == 'image')
        notes = sum(1 for e in elements if e.get('type') == 'notes')
        return {
            "Slides": len(slides),
            "Elements": len(elements),
            "Bullets": bullets,
            "Images": images,
            "Notes": notes,
        }
    
    def merge_presentations(self, presentations):
        merged = {'metadata': {}, 'slides': [], 'elements': []}
        for pres in presentations:
            merged['metadata'].update(pres['metadata'])
            merged['slides'].extend(pres['slides'])
            merged['elements'].extend(pres['elements'])
        return merged
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(
            os.path.join(sample_folder, start_state["solution_folder"]))
        
        # Parse all presentations
        ref_pres = self.parse_context(reference_context)
        gen_pres = self.parse_context(generated_context)
        
        # Compute component scores
        slide_coverage = compute_slide_coverage_score(ref_pres['slides'], gen_pres['slides'])
        slide_order = compute_slide_order_score(ref_pres['slides'], gen_pres['slides'])
        content_score = compute_content_matching_score(ref_pres['elements'], gen_pres['elements'])
        image_score = compute_image_score(ref_pres['elements'], gen_pres['elements'])
        image_order_score = compute_image_order_score(ref_pres['elements'], gen_pres['elements'])
        position_score = compute_position_accuracy_score(ref_pres['elements'], gen_pres['elements'])
        
        # Weighted final score
        # Content is most important, then coverage, then position/order/images
        score = (0.20 * slide_coverage + 
                 0.10 * slide_order + 
                 0.40 * content_score + 
                 0.075 * image_score + 
                 0.075 * image_order_score +
                 0.15 * position_score)
        
        eval_obj = {
            "score": score,
            "slide_coverage": slide_coverage,
            "slide_order": slide_order,
            "content_score": content_score,
            "image_score": image_score,
            "image_order_score": image_order_score,
            "position_score": position_score,
            "ref_slides": len(ref_pres['slides']),
            "gen_slides": len(gen_pres['slides']),
            "ref_elements": len(ref_pres['elements']),
            "gen_elements": len(gen_pres['elements']),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


if __name__ == "__main__":
    # Test the parser
    with open("samples/slides/basic_state/presentation.md", "r") as f:
        content = f.read()
    
    pres = parse_presentation(content)
    
    print("=" * 60)
    print("METADATA")
    print("=" * 60)
    for k, v in pres['metadata'].items():
        print(f"  {k}: {v}")
    
    print("\n" + "=" * 60)
    print(f"SLIDES ({len(pres['slides'])})")
    print("=" * 60)
    for slide in pres['slides'][:10]:
        pos_str = f"@({slide['position']['x']},{slide['position']['y']})" if slide['position'] else ""
        print(f"  {slide['index']:2d}. {slide['title'][:50]:<50} {pos_str}")
    if len(pres['slides']) > 10:
        print(f"  ... and {len(pres['slides']) - 10} more slides")
    
    print("\n" + "=" * 60)
    print(f"ELEMENTS ({len(pres['elements'])})")
    print("=" * 60)
    
    # Group by type
    by_type = {}
    for el in pres['elements']:
        by_type.setdefault(el['type'], []).append(el)
    
    for el_type, elements in by_type.items():
        print(f"\n  {el_type.upper()} ({len(elements)})")
        for el in elements[:3]:
            pos_str = f"@({el['position']['x']},{el['position']['y']})" if el['position'] else ""
            text_preview = el['text'][:40] + '...' if len(el['text']) > 40 else el['text']
            print(f"    S{el['slide']:02d} L{el['level']} | {text_preview:<45} {pos_str}")
        if len(elements) > 3:
            print(f"    ... and {len(elements) - 3} more")
