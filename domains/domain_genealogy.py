from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
from gedcom.parser import Parser, GedcomFormatViolationError
from gedcom.element.individual import IndividualElement
from gedcom.element.family import FamilyElement
import os, tempfile, ujson as json


def preprocess_gedcom(content):
    """Normalize raw GEDCOM content before parsing.
    
    Fix 1: Remove premature TRLR (trailer) lines that appear before any
    INDI/FAM records. LLMs sometimes place the trailer right after the
    header, which prevents python-gedcom from reading sub-record data.
    """
    lines = content.split('\n')
    cleaned = []
    has_records = False
    for line in lines:
        stripped = line.strip()
        if stripped == '0 TRLR' and not has_records:
            continue  # skip premature trailer
        if stripped.startswith('0 @') and ('INDI' in stripped or 'FAM' in stripped):
            has_records = True
        cleaned.append(line)
    return '\n'.join(cleaned)


def normalize_gedcom_name(given, surname):
    """Deduplicate surname that LLMs embed in both given-name and surname fields.
    
    GEDCOM format: ``1 NAME Given /Surname/``.
    LLMs sometimes write: ``1 NAME Given Surname /Surname/``.
    python-gedcom returns ("Given Surname", "Surname"), and naive
    concatenation yields "Given Surname Surname".  If the surname words
    already appear as a contiguous subsequence inside the given-name words,
    we keep only the given-name string (which already contains the surname).
    """
    given = given.strip() if given else ""
    surname = surname.strip() if surname else ""
    if surname and given:
        given_words = given.lower().split()
        surname_words = surname.lower().split()
        for i in range(len(given_words) - len(surname_words) + 1):
            if given_words[i:i + len(surname_words)] == surname_words:
                return given  # surname already present — don't duplicate
    return f"{given} {surname}".strip()


def parse_gedcom_content(content):
    content = preprocess_gedcom(content)

    # python-gedcom requires a file path, so write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ged', delete=False) as f:
        f.write(content)
        temp_path = f.name
    
    try:
        parser = Parser()
        parser.parse_file(temp_path, strict=False)
        
        result = {'individuals': {}, 'families': {}, 'header': {}}
        
        for element in parser.get_root_child_elements():
            if isinstance(element, IndividualElement):
                pointer = element.get_pointer()
                name_parts = element.get_name()
                given = name_parts[0] if name_parts else ""
                surname = name_parts[1] if name_parts else ""
                name = normalize_gedcom_name(given, surname)
                birth = element.get_birth_data()
                death = element.get_death_data()
                
                new_data = {
                    'name': name,
                    'gender': element.get_gender(),
                    'birth_date': birth[0] if birth else "",
                    'birth_place': birth[1] if birth else "",
                    'death_date': death[0] if death else "",
                    'death_place': death[1] if death else "",
                }
                
                # Merge duplicate pointers: LLMs sometimes emit the same
                # individual twice (once with full data, once with only
                # FAMS links).  Keep the richer version of each field.
                if pointer in result['individuals']:
                    existing = result['individuals'][pointer]
                    for key, value in new_data.items():
                        if value and not existing.get(key):
                            existing[key] = value
                else:
                    result['individuals'][pointer] = new_data
            elif isinstance(element, FamilyElement):
                pointer = element.get_pointer()
                # Extract family members
                husb, wife, children = None, None, []
                for child in element.get_child_elements():
                    tag = child.get_tag()
                    if tag == "HUSB":
                        husb = child.get_value()
                    elif tag == "WIFE":
                        wife = child.get_value()
                    elif tag == "CHIL":
                        children.append(child.get_value())
                    elif tag == "MARR":
                        # Extract marriage date/place
                        marr_date, marr_place = "", ""
                        for marr_child in child.get_child_elements():
                            if marr_child.get_tag() == "DATE":
                                marr_date = marr_child.get_value()
                            elif marr_child.get_tag() == "PLAC":
                                marr_place = marr_child.get_value()
                        result['families'][pointer] = result['families'].get(pointer, {})
                        result['families'][pointer]['marriage_date'] = marr_date
                        result['families'][pointer]['marriage_place'] = marr_place
                
                if pointer not in result['families']:
                    result['families'][pointer] = {}
                result['families'][pointer].update({'husband': husb, 'wife': wife, 'children': children})
        
        return result
    finally:
        os.unlink(temp_path)


def merge_all_gedcom(context):
    merged = ""
    for filename, content in context.items():
        if filename.endswith('.ged'):
            merged += content.rstrip() + "\n"
    return merged


def individual_fingerprint(ind):
    # Create fingerprint from name + birth year for matching across different ID schemes
    name = ind.get('name', '').lower().strip()
    birth_date = ind.get('birth_date', '')
    # Extract year from date if present
    year = ""
    if birth_date:
        parts = birth_date.split()
        for p in parts:
            if p.isdigit() and len(p) == 4:
                year = p
                break
    return f"{name}|{year}"


def compute_individual_score(ref_inds, gen_inds):
    if not ref_inds and not gen_inds:
        return 1.0, 1.0
    if not ref_inds or not gen_inds:
        return 0.0, 0.0
    
    # Create fingerprint sets for coverage
    ref_fps = {individual_fingerprint(ind) for ind in ref_inds.values()}
    gen_fps = {individual_fingerprint(ind) for ind in gen_inds.values()}
    
    # Jaccard similarity for coverage
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    coverage = intersection / union if union > 0 else 1.0
    
    # Field accuracy for matched individuals (by fingerprint)
    ref_by_fp = {individual_fingerprint(ind): ind for ind in ref_inds.values()}
    gen_by_fp = {individual_fingerprint(ind): ind for ind in gen_inds.values()}
    
    matched_fps = ref_fps & gen_fps
    if not matched_fps:
        return coverage, 0.0
    
    field_scores = []
    for fp in matched_fps:
        ref_ind = ref_by_fp[fp]
        gen_ind = gen_by_fp[fp]
        score = 0.0
        total = 0.0
        for field in ['gender', 'birth_date', 'birth_place', 'death_date', 'death_place']:
            ref_val = str(ref_ind.get(field, '')).lower().strip()
            gen_val = str(gen_ind.get(field, '')).lower().strip()
            if ref_val or gen_val:
                total += 1.0
                if ref_val == gen_val:
                    score += 1.0
                elif ref_val and gen_val:
                    score += SequenceMatcher(None, ref_val, gen_val).ratio() * 0.5
        field_scores.append(score / total if total > 0 else 1.0)
    
    return coverage, sum(field_scores) / len(field_scores)


def compute_relationship_score(ref_fams, gen_fams, ref_inds, gen_inds):
    if not ref_fams and not gen_fams:
        return 1.0
    if not ref_fams or not gen_fams:
        return 0.0
    
    # Build fingerprint mappings for individuals
    ref_ptr_to_fp = {ptr: individual_fingerprint(ind) for ptr, ind in ref_inds.items()}
    gen_ptr_to_fp = {ptr: individual_fingerprint(ind) for ptr, ind in gen_inds.items()}
    
    def family_fingerprint(fam, ptr_to_fp):
        husb_fp = ptr_to_fp.get(fam.get('husband'), '') if fam.get('husband') else ''
        wife_fp = ptr_to_fp.get(fam.get('wife'), '') if fam.get('wife') else ''
        return f"{husb_fp}+{wife_fp}"
    
    ref_fam_fps = {family_fingerprint(fam, ref_ptr_to_fp) for fam in ref_fams.values()}
    gen_fam_fps = {family_fingerprint(fam, gen_ptr_to_fp) for fam in gen_fams.values()}
    
    # Jaccard similarity for family coverage
    intersection = len(ref_fam_fps & gen_fam_fps)
    union = len(ref_fam_fps | gen_fam_fps)
    family_coverage = intersection / union if union > 0 else 1.0
    
    # Check children assignments for matched families
    ref_by_fp = {family_fingerprint(fam, ref_ptr_to_fp): fam for fam in ref_fams.values()}
    gen_by_fp = {family_fingerprint(fam, gen_ptr_to_fp): fam for fam in gen_fams.values()}
    
    matched_fps = ref_fam_fps & gen_fam_fps
    if not matched_fps:
        return family_coverage
    
    children_scores = []
    for fp in matched_fps:
        ref_fam = ref_by_fp[fp]
        gen_fam = gen_by_fp[fp]
        ref_children_fps = {ref_ptr_to_fp.get(c, c) for c in ref_fam.get('children', [])}
        gen_children_fps = {gen_ptr_to_fp.get(c, c) for c in gen_fam.get('children', [])}
        if ref_children_fps or gen_children_fps:
            inter = len(ref_children_fps & gen_children_fps)
            uni = len(ref_children_fps | gen_children_fps)
            children_scores.append(inter / uni if uni > 0 else 1.0)
        else:
            children_scores.append(1.0)
    
    children_accuracy = sum(children_scores) / len(children_scores) if children_scores else 1.0
    return 0.6 * family_coverage + 0.4 * children_accuracy


def compute_event_score(ref_fams, gen_fams, ref_inds, gen_inds):
    # Compare marriage events
    ref_ptr_to_fp = {ptr: individual_fingerprint(ind) for ptr, ind in ref_inds.items()}
    gen_ptr_to_fp = {ptr: individual_fingerprint(ind) for ptr, ind in gen_inds.items()}
    
    def family_fingerprint(fam, ptr_to_fp):
        husb_fp = ptr_to_fp.get(fam.get('husband'), '') if fam.get('husband') else ''
        wife_fp = ptr_to_fp.get(fam.get('wife'), '') if fam.get('wife') else ''
        return f"{husb_fp}+{wife_fp}"
    
    ref_by_fp = {family_fingerprint(fam, ref_ptr_to_fp): fam for fam in ref_fams.values()}
    gen_by_fp = {family_fingerprint(fam, gen_ptr_to_fp): fam for fam in gen_fams.values()}
    
    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 1.0 if not ref_fams and not gen_fams else 0.0
    
    event_scores = []
    for fp in matched_fps:
        ref_fam = ref_by_fp[fp]
        gen_fam = gen_by_fp[fp]
        
        ref_date = str(ref_fam.get('marriage_date', '')).lower().strip()
        gen_date = str(gen_fam.get('marriage_date', '')).lower().strip()
        ref_place = str(ref_fam.get('marriage_place', '')).lower().strip()
        gen_place = str(gen_fam.get('marriage_place', '')).lower().strip()
        
        score = 0.0
        total = 0.0
        if ref_date or gen_date:
            total += 1.0
            if ref_date == gen_date:
                score += 1.0
            elif ref_date and gen_date:
                score += SequenceMatcher(None, ref_date, gen_date).ratio() * 0.5
        if ref_place or gen_place:
            total += 1.0
            if ref_place == gen_place:
                score += 1.0
            elif ref_place and gen_place:
                score += SequenceMatcher(None, ref_place, gen_place).ratio() * 0.5
        
        event_scores.append(score / total if total > 0 else 1.0)
    
    return sum(event_scores) / len(event_scores) if event_scores else 1.0


class DomainGenealogy(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "genealogy"
        self.summary = "GEDCOM family tree data with individuals, relationships, and events"
        self.description = "GEDCOM family trees"
        self.file_format = [".ged"]
        self.domain_parser = "python-gedcom"
        self.category = "records"
    
    def parse_context(self, context):
        merged = merge_all_gedcom(context)
        return parse_gedcom_content(merged)

    def compute_domain_statistics(self, context):
        try:
            parsed = self.parse_context(context)
            individuals = parsed.get('individuals', {})
            families = parsed.get('families', {})
            with_birth = sum(1 for i in individuals.values() if i.get('birth_date'))
            total_children = sum(len(f.get('children', [])) for f in families.values())
            return {
                "Individuals": len(individuals),
                "Families": len(families),
                "With Birth Date": with_birth,
                "Children": total_children,
            }
        except Exception:
            return {"Individuals": 0}
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        # Parse GEDCOM files
        try:
            ref_parsed = self.parse_context(reference_context)
            gen_parsed = self.parse_context(generated_context)
        except (GedcomFormatViolationError, Exception) as e:
            print(f"\033[91mGEDCOM parsing error: {e}\033[0m")
            return {"score": 0.0, "individual_coverage": 0.0, "individual_accuracy": 0.0, "relationship_score": 0.0, "event_score": 0.0, "ref_individual_count": 0, "gen_individual_count": 0, "ref_family_count": 0, "gen_family_count": 0, "parse_error": str(e)}
        
        # Compute component scores
        ind_coverage, ind_accuracy = compute_individual_score(ref_parsed['individuals'], gen_parsed['individuals'])
        rel_score = compute_relationship_score(ref_parsed['families'], gen_parsed['families'], ref_parsed['individuals'], gen_parsed['individuals'])
        event_score = compute_event_score(ref_parsed['families'], gen_parsed['families'], ref_parsed['individuals'], gen_parsed['individuals'])
        
        # Weighted aggregate: individuals 30%, relationships 35%, events 20%, metadata 15% (simplified to individuals for now)
        # coverage² gating: missing individuals are penalized quadratically so
        # that accuracy computed only over matched items cannot inflate the score.
        individual_score = ind_coverage ** 2 * ind_accuracy
        score = 0.30 * individual_score + 0.35 * rel_score + 0.20 * event_score + 0.15 * individual_score
        
        eval_obj = {
            "score": score,
            "individual_coverage": ind_coverage,
            "individual_accuracy": ind_accuracy,
            "relationship_score": rel_score,
            "event_score": event_score,
            "ref_individual_count": len(ref_parsed['individuals']),
            "gen_individual_count": len(gen_parsed['individuals']),
            "ref_family_count": len(ref_parsed['families']),
            "gen_family_count": len(gen_parsed['families']),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
