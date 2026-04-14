from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import subprocess
import tempfile
import os, re, math, ujson as json


def parse_makefile_with_make(content):
    """Use GNU make -p to parse and normalize Makefile content.
    Returns structured representation of targets, variables, and dependencies."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.mk', delete=False) as f:
        f.write(content)
        tmp_path = f.name
    
    result = {"targets": {}, "variables": {}, "phony_targets": set(), "pattern_rules": [], "parse_error": None}
    
    try:
        proc = subprocess.run(
            ['make', '-p', '-f', tmp_path, '-q'],
            capture_output=True, text=True, cwd='/tmp', timeout=15
        )
        output = proc.stdout + proc.stderr
        
        # Check for actual parse errors (not just "nothing to be done")
        if "*** " in proc.stderr and "Stop." in proc.stderr:
            error_match = re.search(r'\*\*\* (.+?)\.  Stop\.', proc.stderr)
            result["parse_error"] = error_match.group(1) if error_match else proc.stderr[:200]
            return result
        
        # Extract variables defined in the makefile (not defaults/environment)
        # Pattern: "# makefile (from 'path', line N)\nVARNAME = value"
        var_pattern = re.compile(r"# makefile \(from '[^']+', line \d+\)\n([A-Za-z_][A-Za-z0-9_]*)\s*[:?]?=\s*(.*)$", re.MULTILINE)
        # Internal variables that change between invocations and should be excluded
        _INTERNAL_VARS = {"MAKEFILE_LIST", "MAKEFLAGS", "CURDIR", ".DEFAULT_GOAL"}
        for match in var_pattern.finditer(output):
            var_name = match.group(1)
            if var_name in _INTERNAL_VARS:
                continue
            var_value = match.group(2).strip()
            result["variables"][var_name] = var_value
        
        # Extract targets with their dependencies and recipes
        # Pattern: "target: deps\n#  Phony target...\n#  recipe to execute...\n\tcommands"
        lines = output.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            # Match target definition (but not pattern rules with %)
            target_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_.-]*):\s*(.*)$', line)
            if target_match and '%' not in target_match.group(1):
                target_name = target_match.group(1)
                deps_str = target_match.group(2).strip()
                deps = [d for d in deps_str.split() if d] if deps_str else []
                
                is_phony = False
                recipe_lines = []
                j = i + 1
                
                # Parse metadata and recipe
                while j < len(lines):
                    meta_line = lines[j]
                    if meta_line.startswith('#  Phony target'):
                        is_phony = True
                    elif meta_line.startswith('#  recipe to execute'):
                        # Collect recipe lines (start with tab)
                        k = j + 1
                        while k < len(lines) and (lines[k].startswith('\t') or lines[k] == ''):
                            if lines[k].startswith('\t'):
                                recipe_lines.append(lines[k][1:])  # Remove leading tab
                            elif lines[k] == '' and recipe_lines:
                                break  # Empty line after recipe ends it
                            k += 1
                        j = k - 1
                        break
                    elif not meta_line.startswith('#') and meta_line.strip():
                        break  # Non-comment, non-empty line ends metadata
                    j += 1
                
                result["targets"][target_name] = {
                    "name": target_name,
                    "deps": deps,
                    "recipe": recipe_lines,
                    "phony": is_phony
                }
                if is_phony:
                    result["phony_targets"].add(target_name)
                
                i = j
            # Match pattern rules (contain %)
            elif line and '%' in line and ':' in line:
                pattern_match = re.match(r'^([^:]+):\s*(.*)$', line)
                if pattern_match:
                    pattern = pattern_match.group(1).strip()
                    deps_str = pattern_match.group(2).strip()
                    
                    recipe_lines = []
                    j = i + 1
                    while j < len(lines):
                        if lines[j].startswith('#  recipe to execute'):
                            k = j + 1
                            while k < len(lines) and (lines[k].startswith('\t') or lines[k] == ''):
                                if lines[k].startswith('\t'):
                                    recipe_lines.append(lines[k][1:])
                                elif lines[k] == '' and recipe_lines:
                                    break
                                k += 1
                            break
                        elif not lines[j].startswith('#') and lines[j].strip():
                            break
                        j += 1
                    
                    result["pattern_rules"].append({
                        "pattern": pattern,
                        "deps": deps_str,
                        "recipe": recipe_lines
                    })
            i += 1
        
    except subprocess.TimeoutExpired:
        result["parse_error"] = "make -p timed out"
    except Exception as e:
        result["parse_error"] = str(e)
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass
    
    return result


def fallback_regex_parse_makefile(content):
    """Regex-based fallback parser for when GNU make -p fails.
    Extracts targets, variables, .PHONY declarations, and pattern rules
    using line-by-line regex matching. Less accurate than make -p but
    resilient to syntax errors and sandbox limitations."""
    result = {"targets": {}, "variables": {}, "phony_targets": set(), "pattern_rules": [], "parse_error": None}
    _INTERNAL_VARS = {"MAKEFILE_LIST", "MAKEFLAGS", "CURDIR", ".DEFAULT_GOAL",
                      "SHELL", "MAKE", "MAKELEVEL", "MAKEOVERRIDES", "SUFFIXES"}

    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip blank / comment-only / directive lines
        stripped = line.strip()
        if (not stripped or stripped.startswith('#')
                or stripped.startswith('ifdef') or stripped.startswith('ifndef')
                or stripped.startswith('ifeq') or stripped.startswith('ifneq')
                or stripped.startswith('else') or stripped.startswith('endif')
                or stripped.startswith('-include') or stripped.startswith('include')
                or stripped.startswith('export') or stripped.startswith('unexport')
                or stripped.startswith('override') or stripped.startswith('define')
                or stripped.startswith('endef') or stripped.startswith('vpath')
                or stripped.startswith('.SUFFIXES') or stripped.startswith('.DEFAULT')):
            i += 1
            continue

        # Lines starting with tab/space are recipe continuations — skip
        if line and line[0] in ' \t':
            i += 1
            continue

        # .PHONY: targets
        phony_match = re.match(r'^\.PHONY:\s*(.*)', line)
        if phony_match:
            for t in phony_match.group(1).split():
                if not t.startswith('#'):
                    result["phony_targets"].add(t)
            i += 1
            continue

        # Variable assignment: VAR = value | VAR := | VAR ?= | VAR +=
        var_match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*[:?+]?=\s*(.*)', line)
        if var_match:
            var_name = var_match.group(1)
            if var_name not in _INTERNAL_VARS:
                result["variables"][var_name] = var_match.group(2).strip()
            i += 1
            continue

        # Target or pattern rule:  name: deps
        target_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_.%-]*)\s*:(?!=)\s*(.*)', line)
        if target_match:
            target_name = target_match.group(1)
            deps_str = re.sub(r'##.*$', '', re.sub(r'#(?!#).*$', '', target_match.group(2))).strip()
            deps = [d for d in deps_str.split() if d]

            # Collect recipe lines (tab- or space-indented)
            recipe_lines = []
            j = i + 1
            while j < len(lines):
                rline = lines[j]
                if rline.startswith('\t'):
                    recipe_lines.append(rline[1:])
                elif rline.startswith('    '):
                    recipe_lines.append(rline.lstrip(' '))
                elif rline == '':
                    if recipe_lines:
                        break
                else:
                    break
                j += 1

            is_phony = target_name in result["phony_targets"]
            if '%' in target_name:
                result["pattern_rules"].append({
                    "pattern": target_name,
                    "deps": deps_str,
                    "recipe": recipe_lines,
                })
            else:
                result["targets"][target_name] = {
                    "name": target_name,
                    "deps": deps,
                    "recipe": recipe_lines,
                    "phony": is_phony,
                }
                if is_phony:
                    result["phony_targets"].add(target_name)
            i = j
            continue

        i += 1

    return result


def parse_all_makefiles(context):
    """Parse all Makefile content from context and merge.
    Uses GNU make -p as primary parser, falls back to regex if make fails."""
    merged = {"targets": {}, "variables": {}, "phony_targets": set(),
              "pattern_rules": [], "parse_error": None, "used_fallback": False}

    for filename, content in context.items():
        if filename.lower().endswith(('.mk', '.makefile')) or 'makefile' in filename.lower():
            parsed = parse_makefile_with_make(content)
            if parsed["parse_error"]:
                # Primary parser failed — try regex fallback
                parsed = fallback_regex_parse_makefile(content)
                if not parsed["targets"] and not parsed["variables"]:
                    # Fallback also found nothing — genuine failure
                    merged["parse_error"] = "no content parsed"
                else:
                    merged["used_fallback"] = True
            merged["targets"].update(parsed["targets"])
            merged["variables"].update(parsed["variables"])
            merged["phony_targets"].update(parsed["phony_targets"])
            merged["pattern_rules"].extend(parsed["pattern_rules"])

    return merged


def normalize_recipe_line(line):
    """Normalize a recipe line for comparison."""
    line = line.strip()
    line = re.sub(r'\s+', ' ', line)  # Collapse whitespace
    line = line.lstrip('@-')  # Remove @ (silent) and - (ignore errors) prefixes
    return line.lower()


def compute_target_coverage(ref_targets, gen_targets):
    """Jaccard similarity on target names."""
    if not ref_targets and not gen_targets:
        return 1.0
    if not ref_targets or not gen_targets:
        return 0.0
    
    ref_names = set(ref_targets.keys())
    gen_names = set(gen_targets.keys())
    
    intersection = len(ref_names & gen_names)
    union = len(ref_names | gen_names)
    return intersection / union if union > 0 else 1.0


def compute_dependency_accuracy(ref_targets, gen_targets):
    """For matched targets, compare dependency lists."""
    if not ref_targets and not gen_targets:
        return 1.0
    if not ref_targets or not gen_targets:
        return 0.0
    
    matched = set(ref_targets.keys()) & set(gen_targets.keys())
    if not matched:
        return 0.0
    
    scores = []
    for target_name in matched:
        ref_deps = set(ref_targets[target_name]["deps"])
        gen_deps = set(gen_targets[target_name]["deps"])
        
        if not ref_deps and not gen_deps:
            scores.append(1.0)
        elif not ref_deps or not gen_deps:
            scores.append(0.0)
        else:
            intersection = len(ref_deps & gen_deps)
            union = len(ref_deps | gen_deps)
            scores.append(intersection / union if union > 0 else 1.0)
    
    return sum(scores) / len(scores)


def compute_recipe_accuracy(ref_targets, gen_targets):
    """For matched targets, compare recipe commands using sequence matching."""
    if not ref_targets and not gen_targets:
        return 1.0
    if not ref_targets or not gen_targets:
        return 0.0
    
    matched = set(ref_targets.keys()) & set(gen_targets.keys())
    if not matched:
        return 0.0
    
    scores = []
    for target_name in matched:
        ref_recipe = [normalize_recipe_line(l) for l in ref_targets[target_name]["recipe"] if l.strip()]
        gen_recipe = [normalize_recipe_line(l) for l in gen_targets[target_name]["recipe"] if l.strip()]
        
        if not ref_recipe and not gen_recipe:
            scores.append(1.0)
        elif not ref_recipe or not gen_recipe:
            scores.append(0.0)
        else:
            ref_str = '\n'.join(ref_recipe)
            gen_str = '\n'.join(gen_recipe)
            scores.append(SequenceMatcher(None, ref_str, gen_str).ratio())
    
    return sum(scores) / len(scores)


def compute_variable_score(ref_vars, gen_vars):
    """Compare variable definitions."""
    if not ref_vars and not gen_vars:
        return 1.0
    if not ref_vars or not gen_vars:
        return 0.0
    
    # Coverage
    ref_names = set(ref_vars.keys())
    gen_names = set(gen_vars.keys())
    coverage = len(ref_names & gen_names) / len(ref_names | gen_names) if (ref_names | gen_names) else 1.0
    
    # Value accuracy for matched variables
    matched = ref_names & gen_names
    if not matched:
        return coverage * 0.5
    
    value_scores = []
    for var_name in matched:
        ref_val = ref_vars[var_name].strip().lower()
        gen_val = gen_vars[var_name].strip().lower()
        if ref_val == gen_val:
            value_scores.append(1.0)
        else:
            value_scores.append(SequenceMatcher(None, ref_val, gen_val).ratio())
    
    value_accuracy = sum(value_scores) / len(value_scores)
    return coverage * 0.4 + value_accuracy * 0.6


def compute_phony_score(ref_phony, gen_phony):
    """Jaccard similarity on phony target declarations."""
    if not ref_phony and not gen_phony:
        return 1.0
    if not ref_phony or not gen_phony:
        return 0.0
    
    intersection = len(ref_phony & gen_phony)
    union = len(ref_phony | gen_phony)
    return intersection / union if union > 0 else 1.0


def compute_pattern_rule_score(ref_patterns, gen_patterns):
    """Compare pattern rules by their stem patterns."""
    if not ref_patterns and not gen_patterns:
        return 1.0
    if not ref_patterns or not gen_patterns:
        return 0.0
    
    ref_stems = {p["pattern"] for p in ref_patterns}
    gen_stems = {p["pattern"] for p in gen_patterns}
    
    intersection = len(ref_stems & gen_stems)
    union = len(ref_stems | gen_stems)
    return intersection / union if union > 0 else 1.0


class DomainMakefile(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "makefile"
        self.summary = "Build system files with targets, dependencies, and shell recipes"
        self.description = "GNU Makefile build systems"
        self.file_format = [".mk"]
        self.domain_parser = "custom"
        self.category = "code"
    
    def parse_context(self, context):
        return parse_all_makefiles(context)
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        targets = parsed.get('targets', {})
        variables = parsed.get('variables', {})
        total_deps = sum(len(t.get('dependencies', [])) for t in targets.values())
        total_recipe_lines = sum(len(t.get('recipe', [])) for t in targets.values())
        return {
            "Targets": len(targets),
            "Variables": len(variables),
            "Dependencies": total_deps,
            "Recipe Lines": total_recipe_lines,
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        
        if debug:
            print(f"Reference: {len(ref_parsed['targets'])} targets, {len(ref_parsed['variables'])} vars, {len(ref_parsed['pattern_rules'])} patterns")
            print(f"Generated: {len(gen_parsed['targets'])} targets, {len(gen_parsed['variables'])} vars, {len(gen_parsed['pattern_rules'])} patterns")
            if gen_parsed.get("used_fallback"):
                print("Generated context used regex fallback parser (make -p failed)")
        
        # Check for parse errors (only if both primary and fallback failed)
        if ref_parsed.get("parse_error"):
            return {"error": "ref_parse_error", "details": ref_parsed["parse_error"], "score": 0.0}
        if gen_parsed.get("parse_error"):
            return {"error": "gen_parse_error", "details": gen_parsed["parse_error"], "score": 0.0}
        
        target_coverage = compute_target_coverage(ref_parsed["targets"], gen_parsed["targets"])
        dep_accuracy = compute_dependency_accuracy(ref_parsed["targets"], gen_parsed["targets"])
        recipe_accuracy = compute_recipe_accuracy(ref_parsed["targets"], gen_parsed["targets"])
        variable_score = compute_variable_score(ref_parsed["variables"], gen_parsed["variables"])
        phony_score = compute_phony_score(ref_parsed["phony_targets"], gen_parsed["phony_targets"])
        pattern_score = compute_pattern_rule_score(ref_parsed["pattern_rules"], gen_parsed["pattern_rules"])
        
        # Coverage² gating: dep_accuracy and recipe_accuracy are computed only
        # over matched targets, so missing targets don't reduce them. Apply
        # coverage² to penalise omitted targets proportionally.
        n_ref = len(ref_parsed["targets"])
        n_matched = len(set(ref_parsed["targets"].keys()) & set(gen_parsed["targets"].keys()))
        coverage_ratio = n_matched / n_ref if n_ref > 0 else 1.0
        dep_accuracy_gated = coverage_ratio ** 2 * dep_accuracy
        recipe_accuracy_gated = coverage_ratio ** 2 * recipe_accuracy
        
        # Weighted score formula:
        # Target coverage is fundamental (25%)
        # Dependency accuracy is critical for correct builds (25%)
        # Recipe accuracy is the actual commands (30%)
        # Variables affect behavior (15%)
        # Phony correctness (5%)
        score = (
            0.25 * target_coverage +
            0.25 * dep_accuracy_gated +
            0.30 * recipe_accuracy_gated +
            0.15 * variable_score +
            0.05 * phony_score
        )
        
        # Bonus/penalty for pattern rules if present
        if ref_parsed["pattern_rules"] or gen_parsed["pattern_rules"]:
            score = score * 0.9 + pattern_score * 0.1

        # Penalty for using regex fallback (make -p failed = syntax issue)
        used_fallback = gen_parsed.get("used_fallback", False)
        if used_fallback:
            score *= 0.95

        eval_obj = {
            "score": score,
            "used_fallback": used_fallback,
            "target_coverage": target_coverage,
            "dep_accuracy": dep_accuracy,
            "recipe_accuracy": recipe_accuracy,
            "variable_score": variable_score,
            "phony_score": phony_score,
            "pattern_score": pattern_score,
            "ref_target_count": len(ref_parsed["targets"]),
            "gen_target_count": len(gen_parsed["targets"]),
            "ref_var_count": len(ref_parsed["variables"]),
            "gen_var_count": len(gen_parsed["variables"]),
        }
        
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


if __name__ == "__main__":
    # Test parsing with the sample Makefile
    test_content = open("data/makefiles/ai_gateway_Makefile.txt").read()
    parsed = parse_makefile_with_make(test_content)
    
    print("=" * 60)
    print("MAKEFILE PARSE TEST")
    print("=" * 60)
    
    if parsed["parse_error"]:
        print(f"PARSE ERROR: {parsed['parse_error']}")
    else:
        print(f"Targets: {len(parsed['targets'])}")
        print(f"Variables: {len(parsed['variables'])}")
        print(f"Phony targets: {len(parsed['phony_targets'])}")
        print(f"Pattern rules: {len(parsed['pattern_rules'])}")
        
        print("\n--- Sample Targets ---")
        for i, (name, target) in enumerate(list(parsed['targets'].items())[:10]):
            deps = ', '.join(target['deps'][:3]) + ('...' if len(target['deps']) > 3 else '')
            recipe_preview = target['recipe'][0][:50] + '...' if target['recipe'] else '-'
            phony = '(phony)' if target['phony'] else ''
            print(f"  {name:20} | deps: {deps:30} | {phony}")
        
        print("\n--- Sample Variables ---")
        for i, (name, value) in enumerate(list(parsed['variables'].items())[:10]):
            print(f"  {name:25} = {value[:50]}{'...' if len(value) > 50 else ''}")
        
        print("\n--- Pattern Rules ---")
        for rule in parsed['pattern_rules'][:5]:
            print(f"  {rule['pattern']:20} : {rule['deps'][:30]}")
