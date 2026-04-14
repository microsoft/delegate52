from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, ujson as json


def parse_plain_text_play(text):
    # Parse plain-text play format with # CHARACTERS:, # SCENE:, # DIALOGUE: sections
    characters = {}
    dialogues = []
    stage_directions = []
    
    # Parse sections based on # headers
    current_section = None
    dialogue_lines = []
    
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('# CHARACTERS'):
            current_section = 'characters'
            continue
        elif stripped.startswith('# SCENE'):
            current_section = 'scene'
            continue
        elif stripped.startswith('# DIALOGUE'):
            current_section = 'dialogue'
            continue
        
        if current_section == 'characters':
            # Parse character list: "- CHARACTER_NAME: description"
            char_pattern = r'^-\s*([A-Z][A-Z\s\']+?):\s*(.+)$'
            match = re.match(char_pattern, stripped)
            if match:
                char_name = match.group(1).strip()
                char_desc = match.group(2).strip()
                characters[char_name] = char_desc
        elif current_section == 'dialogue':
            dialogue_lines.append(stripped)
    
    # Parse dialogues from dialogue section
    dialogue_pattern = r'^([A-Z][A-Z\s\']+?)(?:\s*\([^)]*\))?\s*:\s*(.+)$'
    for stripped in dialogue_lines:
        match = re.match(dialogue_pattern, stripped)
        if match:
            char_name = match.group(1).strip()
            dialogue_text = match.group(2).strip()
            dialogue_clean = re.sub(r'\([^)]*\)\s*', '', dialogue_text).strip()
            dialogues.append({"character": char_name, "text": dialogue_clean})
        elif stripped.startswith('(') and stripped.endswith(')') and ':' not in stripped[:20]:
            stage_directions.append(stripped[1:-1].strip())
    
    return {"characters": characters, "dialogues": dialogues, "stage_directions": stage_directions}


def normalize_text(text):
    # Collapse whitespace, lowercase, strip punctuation for comparison
    text = re.sub(r'[^\w\s]', '', text.lower())
    return re.sub(r'\s+', ' ', text).strip()


def compute_dialogue_sequence_score(ref_dialogues, gen_dialogues):
    if not ref_dialogues and not gen_dialogues:
        return 1.0
    if not ref_dialogues or not gen_dialogues:
        return 0.0
    # Compare (character, normalized_text_prefix) tuples
    ref_seq = [(d["character"].upper(), normalize_text(d["text"])[:80]) for d in ref_dialogues]
    gen_seq = [(d["character"].upper(), normalize_text(d["text"])[:80]) for d in gen_dialogues]
    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


def compute_character_coverage(ref_chars, gen_chars):
    ref_set = set(c.upper() for c in ref_chars.keys())
    gen_set = set(c.upper() for c in gen_chars.keys())
    if not ref_set and not gen_set:
        return 1.0
    if not ref_set or not gen_set:
        return 0.0
    intersection = len(ref_set & gen_set)
    union = len(ref_set | gen_set)
    return intersection / union if union > 0 else 0.0


def compute_text_similarity(ref_text, gen_text):
    ref_norm = normalize_text(ref_text)
    gen_norm = normalize_text(gen_text)
    return SequenceMatcher(None, ref_norm, gen_norm, autojunk=False).ratio()


def compute_stage_direction_score(ref_directions, gen_directions):
    if not ref_directions and not gen_directions:
        return 1.0
    if not ref_directions or not gen_directions:
        return 0.0
    ref_text = ' '.join(normalize_text(d) for d in ref_directions)
    gen_text = ' '.join(normalize_text(d) for d in gen_directions)
    return SequenceMatcher(None, ref_text, gen_text, autojunk=False).ratio()


class DomainScreenplay(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "screenplay"
        self.summary = "Play and screenplay scripts with dialogue, stage directions, and scenes"
        self.description = "Screenplay scripts"
        self.file_format = [".txt"]
        self.domain_parser = "custom"
        self.category = "creative"
    
    def get_content(self, context):
        content = ""
        for filename, file_content in context.items():
            content += file_content + "\n"
        return content.strip()
    
    def preprocess_context(self, context):
        """Normalize alternate stage direction formats in the dialogue section.
        
        LLMs sometimes output stage directions in non-standard formats:
          1. SD\\d+: (text)           → (text)     — labeled prefix
          2. (SD\\d+: (text))         → (text)     — double-wrapped with label
          3. (stage direction: text)  → (text)     — lowercase label
          4. [text]                   → (text)     — brackets instead of parens
        """
        processed = {}
        for filename, content in context.items():
            lines = content.split('\n')
            out = []
            in_dialogue = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('# DIALOGUE'):
                    in_dialogue = True
                    out.append(line)
                    continue
                if stripped.startswith('#') and not stripped.startswith('# DIALOGUE'):
                    if in_dialogue and re.match(r'^#\s+[A-Z]', stripped):
                        in_dialogue = False
                
                if not in_dialogue:
                    out.append(line)
                    continue
                
                # Skip dialogue lines (CHARACTER: text)
                if re.match(r'^[A-Z][A-Z\s\']+(?:\s*\([^)]*\))?\s*:', stripped):
                    out.append(line)
                    continue
                
                # Pattern 2: (SD\d+: (text)) → (text)
                m = re.match(r'^\(SD\d+:\s*\((.+)\)\)$', stripped)
                if m:
                    out.append('(' + m.group(1) + ')')
                    continue
                
                # Pattern 1: SD\d+: (text) → (text)
                m = re.match(r'^SD\d+:\s*(\(.+\))$', stripped)
                if m:
                    out.append(m.group(1))
                    continue
                
                # Pattern 3: (stage direction: text) → (text)
                m = re.match(r'^\(stage direction:\s*(.+)\)$', stripped, re.IGNORECASE)
                if m:
                    out.append('(' + m.group(1) + ')')
                    continue
                
                # Pattern 4: [text] → (text) — standalone bracketed lines
                m = re.match(r'^\[(.+)\]$', stripped)
                if m:
                    out.append('(' + m.group(1) + ')')
                    continue
                
                out.append(line)
            
            processed[filename] = '\n'.join(out)
        return processed
    
    def parse_context(self, context):
        context = self.preprocess_context(context)
        content = self.get_content(context)
        return parse_plain_text_play(content)
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        return {
            "Characters": len(parsed.get('characters', {})),
            "Dialogues": len(parsed.get('dialogues', [])),
            "Stage Dirs": len(parsed.get('stage_directions', [])),
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        
        if debug:
            print(f"ref characters: {list(ref_parsed['characters'].keys())}")
            print(f"gen characters: {list(gen_parsed['characters'].keys())}")
            print(f"ref dialogues: {len(ref_parsed['dialogues'])}, gen dialogues: {len(gen_parsed['dialogues'])}")
        
        # Compute component scores
        dialogue_score = compute_dialogue_sequence_score(ref_parsed["dialogues"], gen_parsed["dialogues"])
        character_score = compute_character_coverage(ref_parsed["characters"], gen_parsed["characters"])
        direction_score = compute_stage_direction_score(ref_parsed["stage_directions"], gen_parsed["stage_directions"])
        
        # Also compute raw text similarity
        ref_text = self.get_content(reference_context)
        gen_text = self.get_content(generated_context)
        text_score = compute_text_similarity(ref_text, gen_text)
        
        # Weighted aggregate - dialogue is most important for lossless conversion
        score = 0.45 * dialogue_score + 0.20 * character_score + 0.20 * direction_score + 0.15 * text_score
        
        eval_obj = {
            "score": score,
            "dialogue_sequence_score": dialogue_score,
            "character_coverage_score": character_score,
            "stage_direction_score": direction_score,
            "text_similarity_score": text_score,
            "ref_dialogue_count": len(ref_parsed["dialogues"]),
            "gen_dialogue_count": len(gen_parsed["dialogues"]),
            "ref_character_count": len(ref_parsed["characters"]),
            "gen_character_count": len(gen_parsed["characters"]),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
