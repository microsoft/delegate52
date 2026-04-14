from utils_context import build_context_from_folder
from .domain_base import DomainBase
from difflib import SequenceMatcher
import os, re, ujson as json


def parse_lean_declaration(text):
    # Extract declarations (theorem, lemma, def, example, instance, etc.)
    declarations = []
    lines = text.split('\n')
    decl_buffer = []
    in_decl = False
    
    for line in lines:
        stripped = line.strip()
        decl_match = re.match(r'^(theorem|lemma|def|abbrev|instance|example)\s+(\S+)', stripped)
        if decl_match:
            in_decl = True
            decl_buffer = [stripped]
        elif in_decl:
            decl_buffer.append(stripped)
        
        if in_decl and ':=' in stripped:
            full_decl = ' '.join(decl_buffer)
            match = re.match(r'(theorem|lemma|def|abbrev|instance|example)\s+(\S+)\s*(.*?)\s*:=', full_decl, re.DOTALL)
            if match:
                decl_type = match.group(1)
                name = match.group(2)
                rest = match.group(3).strip()
                if ':' in rest:
                    last_colon = rest.rfind(':')
                    params = rest[:last_colon].strip()
                    signature = rest[last_colon+1:].strip()
                else:
                    params = rest
                    signature = ""
                declarations.append({"type": decl_type, "name": name, "params": params, "signature": signature})
            in_decl = False
            decl_buffer = []
    
    return declarations


def parse_lean_imports(text):
    imports = []
    for match in re.finditer(r'(?:public\s+)?import\s+(\S+)', text):
        imports.append(match.group(1))
    return imports


def parse_lean_sections(text):
    sections = []
    for match in re.finditer(r'(section|namespace)\s+(\S+)', text):
        sections.append({"type": match.group(1), "name": match.group(2)})
    return sections


def parse_lean_file(text):
    return {
        "imports": parse_lean_imports(text),
        "sections": parse_lean_sections(text),
        "declarations": parse_lean_declaration(text),
        "raw_text": text
    }


def parse_all_lean_files(context):
    parsed = []
    for filename, content in context.items():
        if filename.endswith('.lean'):
            parsed.append({"filename": filename, **parse_lean_file(content)})
    return parsed


def merge_lean_parsed(parsed_files):
    merged = {"imports": [], "sections": [], "declarations": [], "raw_text": ""}
    for pf in parsed_files:
        merged["imports"].extend(pf["imports"])
        merged["sections"].extend(pf["sections"])
        merged["declarations"].extend(pf["declarations"])
        merged["raw_text"] += pf["raw_text"] + "\n"
    return merged


def compute_declaration_match_score(ref_decls, gen_decls):
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    
    if not ref_decls and not gen_decls:
        return 1.0
    if not ref_decls or not gen_decls:
        return 0.0
    
    n_ref, n_gen = len(ref_decls), len(gen_decls)
    sim_matrix = np.zeros((n_ref, n_gen))
    
    for i, ref in enumerate(ref_decls):
        for j, gen in enumerate(gen_decls):
            name_sim = SequenceMatcher(None, ref["name"], gen["name"]).ratio()
            sig_sim = SequenceMatcher(None, ref["signature"], gen["signature"]).ratio()
            type_match = 1.0 if ref["type"] == gen["type"] else 0.8
            sim_matrix[i, j] = type_match * (0.5 * name_sim + 0.5 * sig_sim)
    
    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    matched_sim = sim_matrix[row_ind, col_ind].sum()
    return matched_sim / max(n_ref, n_gen)


def compute_import_coverage(ref_imports, gen_imports):
    ref_set = set(ref_imports)
    gen_set = set(gen_imports)
    if not ref_set and not gen_set:
        return 1.0
    if not ref_set:
        return 0.5
    intersection = len(ref_set & gen_set)
    return intersection / len(ref_set)


def compute_section_coverage(ref_sections, gen_sections):
    if not ref_sections and not gen_sections:
        return 1.0
    if not ref_sections:
        return 0.5
    ref_names = set(s["name"] for s in ref_sections)
    gen_names = set(s["name"] for s in gen_sections)
    intersection = len(ref_names & gen_names)
    return intersection / len(ref_names)


class DomainMathlean(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "mathlean"
        self.summary = "Lean 4 mathematical proofs with theorems, lemmas, and tactics"
        self.description = "Lean 4 formal proofs"
        self.file_format = [".lean"]
        self.domain_parser = "custom"
        self.category = "science"
    
    def parse_context(self, context):
        parsed_files = parse_all_lean_files(context)
        return merge_lean_parsed(parsed_files)

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        all_decls = parsed["declarations"]
        all_imports = parsed["imports"]
        theorems = sum(1 for d in all_decls if d.get('type') == 'theorem')
        lemmas = sum(1 for d in all_decls if d.get('type') == 'lemma')
        return {
            "Declarations": len(all_decls),
            "Theorems": theorems,
            "Lemmas": lemmas,
            "Imports": len(all_imports),
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
        
        import_coverage = compute_import_coverage(ref_parsed["imports"], gen_parsed["imports"])
        section_coverage = compute_section_coverage(ref_parsed["sections"], gen_parsed["sections"])
        declaration_score = compute_declaration_match_score(ref_parsed["declarations"], gen_parsed["declarations"])
        text_similarity = SequenceMatcher(None, ref_parsed["raw_text"], gen_parsed["raw_text"]).ratio()
        
        # Gate structural scores (imports, sections) by declaration coverage so they
        # can't inflate the total when most declarations are missing.
        n_ref = len(ref_parsed["declarations"])
        n_gen = len(gen_parsed["declarations"])
        decl_coverage = min(n_gen / max(n_ref, 1), 1.0)
        
        # Weighted combination: declarations most important, then imports, then sections, then text
        score = 0.40 * declaration_score + decl_coverage ** 2 * (0.25 * import_coverage + 0.15 * section_coverage) + 0.20 * text_similarity
        
        eval_obj = {
            "score": score,
            "declaration_score": declaration_score,
            "import_coverage": import_coverage,
            "section_coverage": section_coverage,
            "text_similarity": text_similarity,
            "ref_declaration_count": len(ref_parsed["declarations"]),
            "gen_declaration_count": len(gen_parsed["declarations"]),
            "ref_import_count": len(ref_parsed["imports"]),
            "gen_import_count": len(gen_parsed["imports"]),
        }
        
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
