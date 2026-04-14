from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json


# ---------------------------------------------------------------------------
# Dockerfile Parser
# ---------------------------------------------------------------------------

DOCKERFILE_INSTRUCTIONS = {
    "FROM", "RUN", "CMD", "LABEL", "MAINTAINER", "EXPOSE", "ENV", "ADD",
    "COPY", "ENTRYPOINT", "VOLUME", "USER", "WORKDIR", "ARG", "ONBUILD",
    "STOPSIGNAL", "HEALTHCHECK", "SHELL",
}


def _join_continuations(text):
    """Join backslash-continued lines into single logical lines."""
    lines = text.split('\n')
    joined = []
    current = ""
    for line in lines:
        stripped = line.rstrip()
        if stripped.endswith('\\'):
            current += stripped[:-1] + " "
        else:
            current += stripped
            joined.append(current)
            current = ""
    if current:
        joined.append(current)
    return joined


def parse_dockerfile(content):
    """Parse a Dockerfile into a structured representation.

    Returns a list of stages, where each stage is:
    {
        "name": str or None,
        "base_image": str,
        "platform": str or None,
        "instructions": [
            {"instruction": str, "value": str, "comment_block": str}
        ]
    }
    Comments preceding an instruction are attached to that instruction as
    'comment_block'.
    """
    lines = _join_continuations(content)
    stages = []
    current_stage = None
    pending_comments = []

    for line in lines:
        stripped = line.strip()

        # Skip empty lines (but don't discard – they may separate comment blocks)
        if not stripped:
            if pending_comments and pending_comments[-1] != "":
                pending_comments.append("")
            continue

        # Comment line
        if stripped.startswith('#'):
            comment_text = stripped[1:].strip() if len(stripped) > 1 else ""
            pending_comments.append(comment_text)
            continue

        # Determine instruction keyword
        parts = stripped.split(None, 1)
        keyword = parts[0].upper()

        if keyword not in DOCKERFILE_INSTRUCTIONS:
            # Might be a raw continuation or unknown – attach to previous
            if current_stage and current_stage["instructions"]:
                prev = current_stage["instructions"][-1]
                prev["value"] += " " + stripped
            continue

        value = parts[1] if len(parts) > 1 else ""
        comment_block = "\n".join(pending_comments).strip()
        pending_comments = []

        if keyword == "FROM":
            # Parse FROM line: FROM [--platform=...] image[:tag] [AS name]
            platform = None
            name = None
            from_val = value

            platform_match = re.match(r'--platform=(\S+)\s+(.*)', from_val)
            if platform_match:
                platform = platform_match.group(1)
                from_val = platform_match.group(2)

            as_match = re.match(r'(.+?)\s+[Aa][Ss]\s+(\S+)', from_val)
            if as_match:
                base_image = as_match.group(1).strip()
                name = as_match.group(2).strip()
            else:
                base_image = from_val.strip()
                name = None

            current_stage = {
                "name": name,
                "base_image": base_image,
                "platform": platform,
                "instructions": [],
                "comment_block": comment_block,
            }
            stages.append(current_stage)
        else:
            if current_stage is None:
                # Instructions before any FROM – create implicit stage
                current_stage = {
                    "name": None,
                    "base_image": None,
                    "platform": None,
                    "instructions": [],
                    "comment_block": "",
                }
                stages.append(current_stage)

            current_stage["instructions"].append({
                "instruction": keyword,
                "value": value,
                "comment_block": comment_block,
            })

    return stages


def parse_all_dockerfiles(context):
    """Parse all Dockerfile-like files in a context dict, returning merged list of stages."""
    all_stages = []
    for filename, content in sorted(context.items()):
        lname = filename.lower()
        if 'dockerfile' in lname or lname.endswith('.dockerfile'):
            stages = parse_dockerfile(content)
            all_stages.extend(stages)
    return all_stages


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def extract_envs(stages):
    """Extract all ENV key=value pairs across all stages, keyed by (stage_name, key)."""
    envs = {}
    for stage in stages:
        sname = stage["name"] or "_unnamed_"
        for instr in stage["instructions"]:
            if instr["instruction"] == "ENV":
                val = instr["value"]
                # ENV KEY=VALUE or ENV KEY VALUE
                eq_match = re.match(r'(\S+?)=(.+)', val)
                if eq_match:
                    envs[(sname, eq_match.group(1))] = eq_match.group(2).strip()
                else:
                    parts = val.split(None, 1)
                    if len(parts) == 2:
                        envs[(sname, parts[0])] = parts[1].strip()
                    elif len(parts) == 1:
                        envs[(sname, parts[0])] = ""
    return envs


def extract_args(stages):
    """Extract all ARG definitions."""
    args = {}
    for stage in stages:
        sname = stage["name"] or "_unnamed_"
        for instr in stage["instructions"]:
            if instr["instruction"] == "ARG":
                val = instr["value"]
                eq_match = re.match(r'(\S+?)=(.+)', val)
                if eq_match:
                    args[(sname, eq_match.group(1))] = eq_match.group(2).strip()
                else:
                    args[(sname, val.strip())] = None
    return args


def extract_exposes(stages):
    """Extract all EXPOSE ports per stage."""
    exposes = {}
    for stage in stages:
        sname = stage["name"] or "_unnamed_"
        ports = set()
        for instr in stage["instructions"]:
            if instr["instruction"] == "EXPOSE":
                for p in instr["value"].split():
                    ports.add(p.strip())
        if ports:
            exposes[sname] = ports
    return exposes


def extract_healthchecks(stages):
    """Extract HEALTHCHECK commands per stage."""
    hcs = {}
    for stage in stages:
        sname = stage["name"] or "_unnamed_"
        for instr in stage["instructions"]:
            if instr["instruction"] == "HEALTHCHECK":
                hcs[sname] = instr["value"]
    return hcs


def extract_entrypoints(stages):
    """Extract ENTRYPOINT/CMD per stage."""
    eps = {}
    for stage in stages:
        sname = stage["name"] or "_unnamed_"
        for instr in stage["instructions"]:
            if instr["instruction"] in ("ENTRYPOINT", "CMD"):
                eps[sname] = (instr["instruction"], instr["value"])
    return eps


def extract_copies(stages):
    """Extract COPY instructions per stage (important for multi-stage builds)."""
    copies = {}
    for stage in stages:
        sname = stage["name"] or "_unnamed_"
        stage_copies = []
        for instr in stage["instructions"]:
            if instr["instruction"] in ("COPY", "ADD"):
                stage_copies.append(instr["value"])
        if stage_copies:
            copies[sname] = stage_copies
    return copies


def extract_runs(stages):
    """Extract RUN commands per stage."""
    runs = {}
    for stage in stages:
        sname = stage["name"] or "_unnamed_"
        stage_runs = []
        for instr in stage["instructions"]:
            if instr["instruction"] == "RUN":
                stage_runs.append(instr["value"])
        if stage_runs:
            runs[sname] = stage_runs
    return runs


def extract_comments(stages):
    """Extract all comment text."""
    comments = []
    for stage in stages:
        if stage.get("comment_block"):
            comments.append(stage["comment_block"])
        for instr in stage["instructions"]:
            if instr.get("comment_block"):
                comments.append(instr["comment_block"])
    return comments


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def normalize_whitespace(s):
    """Collapse whitespace for comparison."""
    return re.sub(r'\s+', ' ', s).strip().lower()


def _jaccard(set_a, set_b):
    """Jaccard similarity."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 1.0


def score_stage_structure(ref_stages, gen_stages):
    """Compare stage names and base images.

    Returns a score [0, 1] reflecting how well the generated Dockerfile
    preserves the multi-stage build structure.
    """
    ref_info = [(s["name"], s["base_image"]) for s in ref_stages]
    gen_info = [(s["name"], s["base_image"]) for s in gen_stages]

    if not ref_info and not gen_info:
        return 1.0
    if not ref_info or not gen_info:
        return 0.0

    # Stage count match
    count_ratio = min(len(ref_info), len(gen_info)) / max(len(ref_info), len(gen_info))

    # Name matching
    ref_names = {s[0] for s in ref_info if s[0]}
    gen_names = {s[0] for s in gen_info if s[0]}
    name_score = _jaccard(ref_names, gen_names) if ref_names else 1.0

    # Base image matching (by stage name when possible, else by position)
    ref_by_name = {s[0]: s[1] for s in ref_info if s[0]}
    gen_by_name = {s[0]: s[1] for s in gen_info if s[0]}
    matched_names = ref_names & gen_names
    if matched_names:
        base_scores = []
        for name in matched_names:
            ref_base = normalize_whitespace(ref_by_name.get(name, ""))
            gen_base = normalize_whitespace(gen_by_name.get(name, ""))
            base_scores.append(1.0 if ref_base == gen_base else
                               SequenceMatcher(None, ref_base, gen_base).ratio())
        base_score = sum(base_scores) / len(base_scores)
    else:
        # Positional comparison
        base_scores = []
        for r, g in zip(ref_info, gen_info):
            rb = normalize_whitespace(r[1] or "")
            gb = normalize_whitespace(g[1] or "")
            base_scores.append(1.0 if rb == gb else
                               SequenceMatcher(None, rb, gb).ratio())
        base_score = sum(base_scores) / len(base_scores) if base_scores else 0.0

    # Per-stage instruction completeness: penalizes stages that are missing
    # instructions even when stage names/base images are correct.
    pairs = _match_stages(ref_stages, gen_stages)
    completeness_scores = []
    for ref_stage, gen_stage in pairs:
        ref_n = len(ref_stage["instructions"])
        if gen_stage is None:
            completeness_scores.append(0.0)
        else:
            gen_n = len(gen_stage["instructions"])
            if ref_n == 0 and gen_n == 0:
                completeness_scores.append(1.0)
            elif max(ref_n, gen_n) == 0:
                completeness_scores.append(0.0)
            else:
                completeness_scores.append(min(ref_n, gen_n) / max(ref_n, gen_n))
    completeness_score = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 1.0

    return 0.20 * count_ratio + 0.25 * name_score + 0.25 * base_score + 0.30 * completeness_score


def _match_stages(ref_stages, gen_stages):
    """Match reference stages to generated stages by name, then by position.

    Returns a list of (ref_stage, gen_stage_or_None) for every reference stage.
    Unmatched reference stages get None as the second element.
    """
    def stage_key(s, idx):
        return s["name"] or f"_pos_{idx}"

    gen_map = {stage_key(s, i): s for i, s in enumerate(gen_stages)}
    used = set()
    pairs = []

    for i, ref in enumerate(ref_stages):
        key = stage_key(ref, i)
        if key in gen_map and key not in used:
            pairs.append((ref, gen_map[key]))
            used.add(key)
        else:
            pairs.append((ref, None))

    return pairs


def score_instruction_sequence(ref_stages, gen_stages):
    """Compare instruction sequences within matched stages using SequenceMatcher.

    Averages over ALL reference stages — unmatched stages contribute 0.
    Each stage score is coverage × accuracy so that missing instructions
    are penalised, not just reordered ones.
    """
    if not ref_stages and not gen_stages:
        return 1.0
    if not ref_stages:
        return 0.0

    pairs = _match_stages(ref_stages, gen_stages)
    scores = []
    for ref_stage, gen_stage in pairs:
        ref_seq = [i["instruction"] for i in ref_stage["instructions"]]
        if gen_stage is None:
            scores.append(0.0)
            continue
        gen_seq = [i["instruction"] for i in gen_stage["instructions"]]
        if not ref_seq and not gen_seq:
            scores.append(1.0)
        elif not ref_seq or not gen_seq:
            scores.append(0.0)
        else:
            accuracy = SequenceMatcher(None, ref_seq, gen_seq).ratio()
            coverage = min(len(gen_seq), len(ref_seq)) / max(len(gen_seq), len(ref_seq))
            scores.append(coverage * accuracy)

    return sum(scores) / len(scores)


def score_run_commands(ref_stages, gen_stages):
    """Compare RUN command content in matched stages.

    Averages over ALL reference stages that have RUN commands.
    Missing stages contribute 0.  Each stage score is
    coverage × accuracy so missing RUN commands are penalised.
    """
    ref_runs = extract_runs(ref_stages)
    gen_runs = extract_runs(gen_stages)

    if not ref_runs and not gen_runs:
        return 1.0
    if not ref_runs:
        return 0.0  # nothing to compare

    scores = []
    for key in ref_runs:
        if key not in gen_runs:
            scores.append(0.0)
            continue
        ref_cmds = [normalize_whitespace(r) for r in ref_runs[key]]
        gen_cmds = [normalize_whitespace(r) for r in gen_runs[key]]
        ref_str = "\n".join(ref_cmds)
        gen_str = "\n".join(gen_cmds)
        accuracy = SequenceMatcher(None, ref_str, gen_str).ratio()
        coverage = min(len(gen_cmds), len(ref_cmds)) / max(len(gen_cmds), len(ref_cmds))
        scores.append(coverage * accuracy)

    return sum(scores) / len(scores)


def score_configuration(ref_stages, gen_stages):
    """Compare ENV, ARG, EXPOSE, HEALTHCHECK, ENTRYPOINT/CMD configurations."""
    sub_scores = []

    # ENVs
    ref_envs = extract_envs(ref_stages)
    gen_envs = extract_envs(gen_stages)
    if ref_envs or gen_envs:
        ref_keys = set(ref_envs.keys())
        gen_keys = set(gen_envs.keys())
        coverage = _jaccard(ref_keys, gen_keys)
        matched = ref_keys & gen_keys
        if matched:
            val_scores = []
            for k in matched:
                rv = normalize_whitespace(ref_envs[k])
                gv = normalize_whitespace(gen_envs[k])
                val_scores.append(1.0 if rv == gv else SequenceMatcher(None, rv, gv).ratio())
            val_acc = sum(val_scores) / len(val_scores)
        else:
            val_acc = 0.0
        sub_scores.append(0.4 * coverage + 0.6 * val_acc)
    else:
        sub_scores.append(1.0)

    # ARGs
    ref_args = extract_args(ref_stages)
    gen_args = extract_args(gen_stages)
    if ref_args or gen_args:
        ref_keys = set(ref_args.keys())
        gen_keys = set(gen_args.keys())
        coverage = _jaccard(ref_keys, gen_keys)
        matched = ref_keys & gen_keys
        if matched:
            val_scores = []
            for k in matched:
                rv = normalize_whitespace(str(ref_args[k] or ""))
                gv = normalize_whitespace(str(gen_args[k] or ""))
                val_scores.append(1.0 if rv == gv else SequenceMatcher(None, rv, gv).ratio())
            val_acc = sum(val_scores) / len(val_scores)
        else:
            val_acc = 0.0
        sub_scores.append(0.4 * coverage + 0.6 * val_acc)
    else:
        sub_scores.append(1.0)

    # EXPOSE
    ref_exp = extract_exposes(ref_stages)
    gen_exp = extract_exposes(gen_stages)
    if ref_exp or gen_exp:
        ref_all = set()
        for v in ref_exp.values():
            ref_all |= v
        gen_all = set()
        for v in gen_exp.values():
            gen_all |= v
        sub_scores.append(_jaccard(ref_all, gen_all))
    else:
        sub_scores.append(1.0)

    # HEALTHCHECK
    ref_hc = extract_healthchecks(ref_stages)
    gen_hc = extract_healthchecks(gen_stages)
    if ref_hc or gen_hc:
        matched = set(ref_hc.keys()) & set(gen_hc.keys())
        if matched:
            hc_scores = []
            for k in matched:
                rv = normalize_whitespace(ref_hc[k])
                gv = normalize_whitespace(gen_hc[k])
                hc_scores.append(1.0 if rv == gv else SequenceMatcher(None, rv, gv).ratio())
            sub_scores.append(sum(hc_scores) / len(hc_scores))
        else:
            sub_scores.append(0.0)
    else:
        sub_scores.append(1.0)

    # ENTRYPOINT/CMD
    ref_ep = extract_entrypoints(ref_stages)
    gen_ep = extract_entrypoints(gen_stages)
    if ref_ep or gen_ep:
        matched = set(ref_ep.keys()) & set(gen_ep.keys())
        if matched:
            ep_scores = []
            for k in matched:
                r_type, r_val = ref_ep[k]
                g_type, g_val = gen_ep[k]
                type_match = 1.0 if r_type == g_type else 0.5
                val_match = 1.0 if normalize_whitespace(r_val) == normalize_whitespace(g_val) else \
                    SequenceMatcher(None, normalize_whitespace(r_val), normalize_whitespace(g_val)).ratio()
                ep_scores.append(0.3 * type_match + 0.7 * val_match)
            sub_scores.append(sum(ep_scores) / len(ep_scores))
        else:
            sub_scores.append(0.0)
    else:
        sub_scores.append(1.0)

    return sum(sub_scores) / len(sub_scores) if sub_scores else 1.0


def score_copy_instructions(ref_stages, gen_stages):
    """Compare COPY/ADD instructions in matched stages.

    Averages over ALL reference stages that have COPY/ADD commands.
    Missing stages contribute 0.  Each stage score is
    coverage × accuracy so missing COPY/ADD instructions are penalised.
    """
    ref_copies = extract_copies(ref_stages)
    gen_copies = extract_copies(gen_stages)

    if not ref_copies and not gen_copies:
        return 1.0
    if not ref_copies:
        return 0.0

    scores = []
    for key in ref_copies:
        if key not in gen_copies:
            scores.append(0.0)
            continue
        ref_c = [normalize_whitespace(c) for c in ref_copies[key]]
        gen_c = [normalize_whitespace(c) for c in gen_copies[key]]
        accuracy = SequenceMatcher(None, "\n".join(ref_c), "\n".join(gen_c)).ratio()
        coverage = min(len(gen_c), len(ref_c)) / max(len(gen_c), len(ref_c))
        scores.append(coverage * accuracy)

    return sum(scores) / len(scores)


def score_comments(ref_stages, gen_stages):
    """Compare comment content preservation."""
    ref_comments = extract_comments(ref_stages)
    gen_comments = extract_comments(gen_stages)

    if not ref_comments and not gen_comments:
        return 1.0
    if not ref_comments or not gen_comments:
        return 0.0

    ref_text = normalize_whitespace(" ".join(ref_comments))
    gen_text = normalize_whitespace(" ".join(gen_comments))

    return SequenceMatcher(None, ref_text, gen_text).ratio()


# ---------------------------------------------------------------------------
# Task class
# ---------------------------------------------------------------------------

class DomainDocker(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "docker"
        self.summary = "Dockerfiles with multi-stage builds, services, and deployment configuration"
        self.description = "Dockerfile container builds"
        self.file_format = ["Dockerfile"]
        self.domain_parser = "custom"
        self.category = "code"

    def parse_dockerfiles(self, context):
        """Parse all Dockerfiles in the context into structured stage representation."""
        return parse_all_dockerfiles(context)

    def parse_context(self, context):
        """Parse all Dockerfiles in the context into a structured dict.

        Returns:
            dict with key 'stages' containing the list of parsed stage dicts.
        """
        stages = self.parse_dockerfiles(context)
        return {"stages": stages}

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        stages = parsed["stages"]
        total_instructions = sum(len(s["instructions"]) for s in stages)
        total_runs = sum(1 for s in stages for i in s["instructions"] if i["instruction"] == "RUN")
        total_copies = sum(1 for s in stages for i in s["instructions"] if i["instruction"] in ("COPY", "ADD"))
        envs = extract_envs(stages)
        args = extract_args(stages)
        return {
            "Stages": len(stages),
            "Instructions": total_instructions,
            "RUN commands": total_runs,
            "COPY/ADD": total_copies,
            "ENV vars": len(envs),
            "ARG vars": len(args),
        }

    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}

        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)

        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(
            os.path.join(sample_folder, start_state["solution_folder"])
        )

        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        ref_stages = ref_parsed["stages"]
        gen_stages = gen_parsed["stages"]

        if debug:
            print(f"Reference: {len(ref_stages)} stages, "
                  f"{sum(len(s['instructions']) for s in ref_stages)} instructions")
            print(f"Generated: {len(gen_stages)} stages, "
                  f"{sum(len(s['instructions']) for s in gen_stages)} instructions")

        # Component scores
        stage_score = score_stage_structure(ref_stages, gen_stages)
        instr_score = score_instruction_sequence(ref_stages, gen_stages)
        run_score = score_run_commands(ref_stages, gen_stages)
        config_score = score_configuration(ref_stages, gen_stages)
        copy_score = score_copy_instructions(ref_stages, gen_stages)
        comment_score = score_comments(ref_stages, gen_stages)

        # Hybrid scoring: weighted geometric mean for core structural
        # components, with comments as an additive modifier.
        #
        # Core components (geometric mean, weights sum to 1.0):
        #   Stage structure (25%): stage names, base images, count
        #   Instruction sequence (15%): order of instructions per stage
        #   RUN commands (25%): actual shell commands
        #   Configuration (20%): ENV, ARG, EXPOSE, HEALTHCHECK, ENTRYPOINT
        #   COPY instructions (15%): build artifact transfers
        #
        # Comments (additive): scale core score between 90%–100%.
        core_weights = [0.25, 0.15, 0.25, 0.20, 0.15]
        core_components = [stage_score, instr_score, run_score, config_score, copy_score]
        eps = 1e-9
        log_sum = sum(w * math.log(max(c, eps)) for w, c in zip(core_weights, core_components))
        core_score = math.exp(log_sum)
        # Comments modulate between 90% and 100% of core score
        score = core_score * (0.90 + 0.10 * comment_score)

        eval_obj = {
            "score": score,
            "stage_structure": stage_score,
            "instruction_sequence": instr_score,
            "run_commands": run_score,
            "configuration": config_score,
            "copy_instructions": copy_score,
            "comments": comment_score,
            "ref_stage_count": len(ref_stages),
            "gen_stage_count": len(gen_stages),
            "ref_instruction_count": sum(len(s["instructions"]) for s in ref_stages),
            "gen_instruction_count": sum(len(s["instructions"]) for s in gen_stages),
        }

        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


if __name__ == "__main__":
    # Self-evaluation test
    from utils_context import build_context_from_folder

    context = build_context_from_folder("samples/docker1/basic_state")
    task = TaskDocker()

    print("=" * 60)
    print("SELF-EVALUATION TEST")
    print("=" * 60)

    # Parse and display structure
    stages = task.parse_dockerfiles(context)
    print(f"\nParsed {len(stages)} stages:")
    for s in stages:
        n_instr = len(s["instructions"])
        print(f"  {s['name'] or '(unnamed)':20} | base: {s['base_image'][:40]:40} | {n_instr} instructions")

    print(f"\nKPIs: {task.compute_domain_statistics(context)}")

    # Self-eval: compare context against itself
    sample_json_path = "samples/docker1/sample.json"
    if os.path.exists(sample_json_path):
        with open(sample_json_path) as f:
            sample = json.load(f)
        basic_state = [s for s in sample["states"] if s["state_id"] == "basic_state"][0]
        result = task.evaluate_context("docker1", context, basic_state, debug=True)
        print(f"\nSelf-eval score: {result.get('score', 'N/A')}")
    else:
        print("\nNo sample.json yet – skipping evaluation test")
