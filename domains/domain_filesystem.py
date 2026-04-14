from utils_context import build_context_from_folder
from .domain_base import DomainBase
import os, re, ujson as json


def parse_filesystem_entry(line):
    # Parse "MODE SIZE PATH" format, e.g. "100644    72935 CHANGES.rst" or "040000        - docs"
    match = re.match(r'^(\d{6})\s+(-|\d+)\s+(.+)$', line.strip())
    if not match:
        return None
    mode = match.group(1)
    size_str = match.group(2)
    size = None if size_str == '-' else int(size_str)
    path = match.group(3)
    return {"mode": mode, "size": size, "path": path}


def get_entry_type(mode):
    # 040xxx = directory, 100755 = executable, 100644 = regular file
    if mode.startswith("040"):
        return "directory"
    elif mode == "100755":
        return "executable"
    else:
        return "file"


def parse_filesystem(text):
    entries = {}
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        entry = parse_filesystem_entry(line)
        if entry:
            entries[entry["path"]] = entry
    return entries


def parse_all_filesystems(context):
    # Merge all filesystem entries from all files in context
    all_entries = {}
    for filename, content in context.items():
        if filename.endswith('.txt'):
            entries = parse_filesystem(content)
            all_entries.update(entries)
    return all_entries


def compute_path_coverage(ref_entries, gen_entries):
    # Jaccard similarity on paths
    ref_paths = set(ref_entries.keys())
    gen_paths = set(gen_entries.keys())
    if not ref_paths and not gen_paths:
        return 1.0
    if not ref_paths or not gen_paths:
        return 0.0
    intersection = len(ref_paths & gen_paths)
    union = len(ref_paths | gen_paths)
    return intersection / union


def compute_type_accuracy(ref_entries, gen_entries):
    # For matched paths, check if type (directory/file/executable) matches
    matched_paths = set(ref_entries.keys()) & set(gen_entries.keys())
    if not matched_paths:
        return 0.0
    correct = 0
    for path in matched_paths:
        ref_type = get_entry_type(ref_entries[path]["mode"])
        gen_type = get_entry_type(gen_entries[path]["mode"])
        if ref_type == gen_type:
            correct += 1
    return correct / len(matched_paths)


def compute_size_accuracy(ref_entries, gen_entries):
    # For matched files (not directories), compare sizes using min/max ratio
    matched_paths = set(ref_entries.keys()) & set(gen_entries.keys())
    file_paths = [p for p in matched_paths if ref_entries[p]["size"] is not None and gen_entries[p]["size"] is not None]
    if not file_paths:
        return 1.0
    ratios = []
    for path in file_paths:
        ref_size = ref_entries[path]["size"]
        gen_size = gen_entries[path]["size"]
        if ref_size == 0 and gen_size == 0:
            ratios.append(1.0)
        elif ref_size == 0 or gen_size == 0:
            ratios.append(0.0)
        else:
            ratios.append(min(ref_size, gen_size) / max(ref_size, gen_size))
    return sum(ratios) / len(ratios)


def compute_mode_accuracy(ref_entries, gen_entries):
    # For matched paths, check exact mode match
    matched_paths = set(ref_entries.keys()) & set(gen_entries.keys())
    if not matched_paths:
        return 0.0
    correct = 0
    for path in matched_paths:
        if ref_entries[path]["mode"] == gen_entries[path]["mode"]:
            correct += 1
    return correct / len(matched_paths)


class DomainFilesystem(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "filesystem"
        self.summary = "File tree listings with modes, sizes, timestamps, and directory paths"
        self.description = "File tree listings"
        self.file_format = [".txt"]
        self.domain_parser = "custom"
        self.category = "code"
    
    def parse_context(self, context):
        entries = parse_all_filesystems(context)
        return {"entries": entries}

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        entries = parsed["entries"]
        dirs = sum(1 for e in entries.values() if get_entry_type(e['mode']) == 'directory')
        files = sum(1 for e in entries.values() if get_entry_type(e['mode']) == 'file')
        executables = sum(1 for e in entries.values() if get_entry_type(e['mode']) == 'executable')
        total_size = sum(e['size'] for e in entries.values() if e['size'] is not None)
        return {
            "Entries": len(entries),
            "Directories": dirs,
            "Files": files,
            "Executables": executables,
            "Total Size": f"{total_size:,} B",
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
        
        ref_entries = self.parse_context(reference_context)["entries"]
        gen_entries = self.parse_context(generated_context)["entries"]
        
        if debug:
            print(f"  Reference entries: {len(ref_entries)}, Generated entries: {len(gen_entries)}")
            ref_paths = set(ref_entries.keys())
            gen_paths = set(gen_entries.keys())
            missing = ref_paths - gen_paths
            extra = gen_paths - ref_paths
            if missing:
                print(f"  Missing paths ({len(missing)}): {list(missing)[:5]}...")
            if extra:
                print(f"  Extra paths ({len(extra)}): {list(extra)[:5]}...")
        
        path_coverage = compute_path_coverage(ref_entries, gen_entries)
        type_accuracy = compute_type_accuracy(ref_entries, gen_entries)
        size_accuracy = compute_size_accuracy(ref_entries, gen_entries)
        mode_accuracy = compute_mode_accuracy(ref_entries, gen_entries)
        
        # Coverage gating: penalize missing entries proportionally
        n_matched = len(set(ref_entries.keys()) & set(gen_entries.keys()))
        n_ref = len(ref_entries)
        coverage_factor = n_matched / n_ref if n_ref > 0 else (1.0 if not gen_entries else 0.0)
        
        # Weighted linear combination with coverage gate
        score = coverage_factor * (0.30 * path_coverage + 0.25 * type_accuracy + 0.25 * size_accuracy + 0.20 * mode_accuracy)
        
        eval_obj = {
            "score": score,
            "path_coverage": path_coverage,
            "type_accuracy": type_accuracy,
            "size_accuracy": size_accuracy,
            "mode_accuracy": mode_accuracy,
            "ref_entry_count": len(ref_entries),
            "gen_entry_count": len(gen_entries),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
