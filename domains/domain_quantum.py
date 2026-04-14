from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, ujson as json

try:
    import openqasm3
    from openqasm3 import parse as qasm_parse
except ImportError:
    raise ImportError("openqasm3 is required for quantum task: pip install openqasm3[parser]")


# ---------------------------------------------------------------------------
# AST extraction helpers
# ---------------------------------------------------------------------------

def _stmt_type(stmt):
    return type(stmt).__name__


def _dump_stmt(stmt):
    """Dump a single AST node to string via openqasm3."""
    try:
        return openqasm3.dumps(stmt).strip()
    except Exception:
        return ""


def _extract_gate_ops(stmts):
    """Recursively collect quantum gate operation signatures from a list of statements."""
    ops = []
    for s in stmts:
        st = _stmt_type(s)
        if st == "QuantumGate":
            gate_name = s.name.name if hasattr(s.name, "name") else str(s.name)
            # Collect qubit arguments
            qubits = []
            for q in (s.qubits or []):
                qubits.append(_dump_stmt(q))
            ops.append({"gate": gate_name, "qubits": qubits})
        elif st == "QuantumReset":
            ops.append({"gate": "reset", "qubits": [_dump_stmt(s.qubits) if hasattr(s, "qubits") else ""]})
        elif st == "QuantumMeasurement":
            ops.append({"gate": "measure", "qubits": []})
        elif st == "QuantumMeasurementStatement":
            ops.append({"gate": "measure", "qubits": []})

        # Recurse into control flow
        if hasattr(s, "body") and s.body:
            body = s.body if isinstance(s.body, list) else [s.body]
            ops.extend(_extract_gate_ops(body))
        if hasattr(s, "block") and s.block:
            block = s.block if isinstance(s.block, list) else [s.block]
            ops.extend(_extract_gate_ops(block))
        if hasattr(s, "if_body") and s.if_body:
            if_body = s.if_body if isinstance(s.if_body, list) else [s.if_body]
            ops.extend(_extract_gate_ops(if_body))
        if hasattr(s, "else_body") and s.else_body:
            else_body = s.else_body if isinstance(s.else_body, list) else [s.else_body]
            ops.extend(_extract_gate_ops(else_body))

    return ops


# ---------------------------------------------------------------------------
# Regex-based fallback parser (used when openqasm3 fails)
# ---------------------------------------------------------------------------

def _regex_parse_qasm(text):
    """Regex-based fallback parser for QASM 3.0.

    Extracts constants, qubit declarations, extern declarations, and
    subroutines using regex patterns.  Less precise than the AST parser
    but robust against syntax variants that openqasm3 v1.x rejects
    (e.g. ``bit[expr]`` return types, ``[start:end]`` range syntax).
    """
    result = {
        "version": "",
        "includes": [],
        "constants": {},
        "qubit_decls": [],
        "extern_decls": [],
        "gate_defs": [],
        "subroutines": {},
        "top_level_ops": [],
        "raw_text": text,
        "parse_error": None,
    }

    # Version
    m = re.search(r"OPENQASM\s+([\d.]+)", text)
    if m:
        result["version"] = m.group(1)

    # Includes
    for m in re.finditer(r'include\s+"([^"]+)"', text):
        result["includes"].append(m.group(1))

    # Strip full-line comments so they don't confuse later patterns
    code_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        # Remove trailing comments
        code_lines.append(re.sub(r'//.*', '', line))
    code = "\n".join(code_lines)

    # Constants: const <type> name = expr;
    for m in re.finditer(r'const\s+\w+\s+(\w+)\s*=\s*([^;]+);', code):
        result["constants"][m.group(1)] = m.group(2).strip()

    # Qubit declarations: qubit[size] name; or qubit name;
    for m in re.finditer(r'qubit\[([^\]]+)\]\s+(\w+)', code):
        result["qubit_decls"].append({"name": m.group(2), "size": m.group(1).strip()})
    for m in re.finditer(r'qubit\s+(\w+)\s*;', code):
        # Avoid matching 'qubit[...' which was already captured
        result["qubit_decls"].append({"name": m.group(1), "size": "1"})

    # Extern declarations: extern name(params) [-> ret];
    for m in re.finditer(r'extern\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*([^;]+))?\s*;', code):
        params = [p.strip() for p in m.group(2).split(',') if p.strip()]
        result["extern_decls"].append({
            "name": m.group(1),
            "params": params,
            "returns": m.group(3).strip() if m.group(3) else None,
        })

    # Subroutines: def name(args) [-> ret] { body }
    for m in re.finditer(r'def\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*([\w\[\]\s]+?))?\s*\{', code):
        name = m.group(1)
        args_str = m.group(2)
        ret_type = m.group(3).strip() if m.group(3) else None

        # Find matching closing brace
        start = m.end()
        depth = 1
        pos = start
        while pos < len(code) and depth > 0:
            if code[pos] == '{':
                depth += 1
            elif code[pos] == '}':
                depth -= 1
            pos += 1
        body_str = code[start:pos - 1].strip()

        # Parse args
        args = []
        for arg_m in re.finditer(r'(\w+(?:\[\w*\])?)\s+(\w+)', args_str):
            args.append({"name": arg_m.group(2), "type": arg_m.group(1)})

        # Extract gate ops from body (simple regex: gate-like calls)
        gate_ops = []
        for gm in re.finditer(r'\b(h|cx|cz|x|y|z|s|t|rx|ry|rz|reset|measure|cnot|swap)\b', body_str):
            gate_ops.append({"gate": gm.group(1), "qubits": []})

        result["subroutines"][name] = {
            "name": name,
            "args": args,
            "return_type": ret_type,
            "body_str": body_str,
            "gate_ops": gate_ops,
            "body_stmts_count": body_str.count('\n') + 1,
        }

    return result


# ---------------------------------------------------------------------------
# QASM structured parser
# ---------------------------------------------------------------------------

def parse_qasm_program(text):
    """Parse an OpenQASM 3.0 program into a structured dict.

    Uses the openqasm3 AST parser.  Falls back to a regex-based parser
    when openqasm3 raises a QASM3ParsingError (common with model-generated
    code that uses syntax variants the library doesn't support).

    Returns
    -------
    dict with keys:
        version         : str (e.g. "3.0")
        includes        : list[str]
        constants       : dict[name -> expr_str]
        qubit_decls     : list[{name, size}]
        extern_decls    : list[{name, params, returns}]
        gate_defs       : list[{name, params, qubits, body_str}]
        subroutines     : dict[name -> {name, args, return_type, body_str, gate_ops, body_stmts_count}]
        top_level_ops   : list  (gate operations at top level, not in subroutines)
        raw_text        : str  (for fallback comparison)
        parse_error     : str or None
    """
    result = {
        "version": "",
        "includes": [],
        "constants": {},
        "qubit_decls": [],
        "extern_decls": [],
        "gate_defs": [],
        "subroutines": {},
        "top_level_ops": [],
        "raw_text": text,
        "parse_error": None,
    }

    try:
        program = qasm_parse(text)
    except Exception as e:
        # openqasm3 QASM3ParsingError often has an empty message;
        # ensure parse_error is always truthy so fallback logic triggers.
        result["parse_error"] = str(e) or type(e).__name__
        # Attempt regex-based fallback
        fb = _regex_parse_qasm(text)
        for key in ("version", "includes", "constants", "qubit_decls",
                    "extern_decls", "gate_defs", "subroutines", "top_level_ops"):
            result[key] = fb[key]
        return result

    # Extract version
    if hasattr(program, "version") and program.version:
        result["version"] = program.version
    else:
        # Try extracting from text
        m = re.search(r"OPENQASM\s+([\d.]+)", text)
        if m:
            result["version"] = m.group(1)

    for stmt in program.statements:
        st = _stmt_type(stmt)

        if st == "Include":
            result["includes"].append(stmt.filename)

        elif st == "ConstantDeclaration":
            name = stmt.identifier.name
            # Dump the initializer expression
            init_str = _dump_stmt(stmt.init_expression) if stmt.init_expression else ""
            result["constants"][name] = init_str

        elif st == "QubitDeclaration":
            name = stmt.qubit.name if hasattr(stmt.qubit, "name") else _dump_stmt(stmt.qubit)
            size_str = _dump_stmt(stmt.size) if stmt.size else "1"
            result["qubit_decls"].append({"name": name, "size": size_str})

        elif st == "ExternDeclaration":
            name = stmt.name.name
            params = []
            for arg in (stmt.arguments or []):
                params.append(_dump_stmt(arg))
            ret = _dump_stmt(stmt.return_type) if stmt.return_type else None
            result["extern_decls"].append({
                "name": name,
                "params": params,
                "returns": ret,
            })

        elif st == "GateDeclaration" or st == "QuantumGateDefinition":
            name = stmt.name.name if hasattr(stmt.name, "name") else str(stmt.name)
            params = [_dump_stmt(p) for p in (stmt.arguments or [])]
            qubits = [_dump_stmt(q) for q in (stmt.qubits or [])]
            body_str = ""
            if stmt.body:
                body_str = "\n".join(_dump_stmt(s) for s in stmt.body)
            result["gate_defs"].append({
                "name": name,
                "params": params,
                "qubits": qubits,
                "body_str": body_str,
            })

        elif st == "SubroutineDefinition":
            name = stmt.name.name
            args = []
            for arg in (stmt.arguments or []):
                args.append({
                    "name": arg.name.name,
                    "type": _dump_stmt(arg.type) if hasattr(arg, "type") and arg.type else "",
                })
            ret_type = _dump_stmt(stmt.return_type) if stmt.return_type else None
            body_str = "\n".join(_dump_stmt(s) for s in (stmt.body or []))
            gate_ops = _extract_gate_ops(stmt.body or [])
            result["subroutines"][name] = {
                "name": name,
                "args": args,
                "return_type": ret_type,
                "body_str": body_str,
                "gate_ops": gate_ops,
                "body_stmts_count": len(stmt.body) if stmt.body else 0,
            }

        else:
            # Top-level operations (gates, resets, measurements, etc.)
            gate_ops = _extract_gate_ops([stmt])
            result["top_level_ops"].extend(gate_ops)

    return result


def parse_all_qasm(context):
    """Parse all files in a context dict, merge into one structure."""
    merged = {
        "version": "",
        "includes": [],
        "constants": {},
        "qubit_decls": [],
        "extern_decls": [],
        "gate_defs": [],
        "subroutines": {},
        "top_level_ops": [],
        "raw_text": "",
        "parse_error": None,
    }
    for fname, content in context.items():
        p = parse_qasm_program(content)
        if p["parse_error"] and not merged["parse_error"]:
            merged["parse_error"] = p["parse_error"]
        # Always merge extracted elements (regex fallback populates them
        # even when the AST parser fails).
        if not merged["version"]:
            merged["version"] = p["version"]
        merged["includes"].extend(p["includes"])
        merged["constants"].update(p["constants"])
        merged["qubit_decls"].extend(p["qubit_decls"])
        merged["extern_decls"].extend(p["extern_decls"])
        merged["gate_defs"].extend(p["gate_defs"])
        merged["subroutines"].update(p["subroutines"])
        merged["top_level_ops"].extend(p["top_level_ops"])
        merged["raw_text"] += "\n" + p["raw_text"]
    return merged


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _f1(ref_set, gen_set):
    """F1 score between two sets."""
    if not ref_set and not gen_set:
        return 1.0
    if not ref_set or not gen_set:
        return 0.0
    tp = len(ref_set & gen_set)
    precision = tp / len(gen_set)
    recall = tp / len(ref_set)
    if precision + recall == 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _seq_sim(a, b):
    """SequenceMatcher ratio between two strings."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# --- Constant scoring ---

def score_constants(ref_consts, gen_consts):
    """Score constant declarations by name coverage and value accuracy."""
    if not ref_consts and not gen_consts:
        return 1.0
    if not ref_consts or not gen_consts:
        return 0.0

    ref_keys = set(ref_consts.keys())
    gen_keys = set(gen_consts.keys())
    name_f1 = _f1(ref_keys, gen_keys)

    matched = ref_keys & gen_keys
    if not matched:
        return name_f1 * 0.3

    val_scores = []
    for k in matched:
        rv = ref_consts[k].strip()
        gv = gen_consts[k].strip()
        val_scores.append(1.0 if rv == gv else _seq_sim(rv, gv))

    val_avg = sum(val_scores) / len(val_scores)
    return name_f1 * 0.4 + val_avg * 0.6


# --- Qubit declaration scoring ---

def score_qubit_decls(ref_decls, gen_decls):
    """Score qubit declarations by name and size matching."""
    if not ref_decls and not gen_decls:
        return 1.0
    if not ref_decls or not gen_decls:
        return 0.0

    ref_map = {d["name"]: d["size"] for d in ref_decls}
    gen_map = {d["name"]: d["size"] for d in gen_decls}

    name_f1 = _f1(set(ref_map.keys()), set(gen_map.keys()))
    matched = set(ref_map.keys()) & set(gen_map.keys())
    if not matched:
        return name_f1 * 0.3

    size_scores = []
    for n in matched:
        size_scores.append(1.0 if ref_map[n] == gen_map[n] else _seq_sim(ref_map[n], gen_map[n]))

    size_avg = sum(size_scores) / len(size_scores)
    return name_f1 * 0.4 + size_avg * 0.6


# --- Extern declaration scoring ---

def score_extern_decls(ref_externs, gen_externs):
    """Score extern declarations by name, parameter, and return type matching."""
    if not ref_externs and not gen_externs:
        return 1.0
    if not ref_externs or not gen_externs:
        return 0.0

    ref_map = {e["name"]: e for e in ref_externs}
    gen_map = {e["name"]: e for e in gen_externs}

    name_f1 = _f1(set(ref_map.keys()), set(gen_map.keys()))
    matched = set(ref_map.keys()) & set(gen_map.keys())
    if not matched:
        return name_f1 * 0.3

    detail_scores = []
    for n in matched:
        r, g = ref_map[n], gen_map[n]
        # Parameter signature comparison
        r_params = ", ".join(r["params"])
        g_params = ", ".join(g["params"])
        param_sim = 1.0 if r_params == g_params else _seq_sim(r_params, g_params)
        # Return type comparison
        r_ret = r["returns"] or ""
        g_ret = g["returns"] or ""
        ret_sim = 1.0 if r_ret == g_ret else _seq_sim(r_ret, g_ret)
        detail_scores.append(0.6 * param_sim + 0.4 * ret_sim)

    detail_avg = sum(detail_scores) / len(detail_scores)
    return name_f1 * 0.4 + detail_avg * 0.6


# --- Gate definition scoring ---

def score_gate_defs(ref_gates, gen_gates):
    """Score custom gate definitions."""
    if not ref_gates and not gen_gates:
        return 1.0
    if not ref_gates or not gen_gates:
        return 0.0

    ref_map = {g["name"]: g for g in ref_gates}
    gen_map = {g["name"]: g for g in gen_gates}

    name_f1 = _f1(set(ref_map.keys()), set(gen_map.keys()))
    matched = set(ref_map.keys()) & set(gen_map.keys())
    if not matched:
        return name_f1 * 0.3

    detail_scores = []
    for n in matched:
        r, g = ref_map[n], gen_map[n]
        body_sim = _seq_sim(r["body_str"], g["body_str"])
        qubit_sim = 1.0 if r["qubits"] == g["qubits"] else _seq_sim(str(r["qubits"]), str(g["qubits"]))
        detail_scores.append(0.7 * body_sim + 0.3 * qubit_sim)

    detail_avg = sum(detail_scores) / len(detail_scores)
    return name_f1 * 0.4 + detail_avg * 0.6


# --- Subroutine scoring ---

def score_subroutines(ref_subs, gen_subs):
    """Score subroutines comprehensively.

    Computes a per-subroutine score averaged over ALL reference subroutines
    (missing subroutines score 0), plus a penalty for extra subroutines in gen.

    Returns a single combined score.
    """
    if not ref_subs and not gen_subs:
        return 1.0
    if not ref_subs:
        return 0.5  # Extra subs only, no ref subs
    if not gen_subs:
        return 0.0

    per_sub_scores = []
    for name, r in ref_subs.items():
        if name not in gen_subs:
            per_sub_scores.append(0.0)
            continue

        g = gen_subs[name]

        # 1. Signature similarity (25%)
        r_args = [(a["name"], a.get("type", "")) for a in r["args"]]
        g_args = [(a["name"], a.get("type", "")) for a in g["args"]]
        if r_args == g_args:
            sig_sim = 1.0
        else:
            r_str = ", ".join(f"{n}:{t}" for n, t in r_args)
            g_str = ", ".join(f"{n}:{t}" for n, t in g_args)
            sig_sim = _seq_sim(r_str, g_str)
        r_ret = r["return_type"] or ""
        g_ret = g["return_type"] or ""
        ret_sim = 1.0 if r_ret == g_ret else _seq_sim(r_ret, g_ret)
        sig_score = 0.6 * sig_sim + 0.4 * ret_sim

        # 2. Body content similarity (50%)
        body_sim = _seq_sim(r["body_str"], g["body_str"])

        # 3. Gate operations similarity (25%)
        r_ops = r["gate_ops"]
        g_ops = g["gate_ops"]
        if not r_ops and not g_ops:
            gate_sim = 1.0
        elif not r_ops or not g_ops:
            gate_sim = 0.0
        else:
            r_seq = " ".join(op["gate"] for op in r_ops)
            g_seq = " ".join(op["gate"] for op in g_ops)
            gate_sim = _seq_sim(r_seq, g_seq)

        sub_score = 0.25 * sig_score + 0.50 * body_sim + 0.25 * gate_sim
        per_sub_scores.append(sub_score)

    # Average over all reference subroutines (missing ones are 0)
    avg_score = sum(per_sub_scores) / len(per_sub_scores)

    # Penalty for extra subroutines not in reference
    extra = set(gen_subs.keys()) - set(ref_subs.keys())
    if extra:
        extra_penalty = min(len(extra) / len(ref_subs), 0.2)
        avg_score *= (1.0 - extra_penalty)

    return avg_score


# --- Raw text fallback scoring ---

def score_raw_text(ref_text, gen_text):
    """Fallback: compare normalized raw text."""
    def normalize(t):
        # Strip comments, normalize whitespace
        lines = []
        for line in t.split("\n"):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            lines.append(stripped)
        return "\n".join(lines).strip()

    ref_norm = normalize(ref_text)
    gen_norm = normalize(gen_text)
    return _seq_sim(ref_norm, gen_norm)


# ---------------------------------------------------------------------------
# Task class
# ---------------------------------------------------------------------------

class DomainQuantum(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "quantum"
        self.summary = "OpenQASM 3.0 quantum circuits with subroutines, constants, qubit registers, and gate operations"
        self.description = "OpenQASM quantum circuits"
        self.file_format = [".qasm"]
        self.domain_parser = "openqasm3"
        self.category = "science"

    def parse_context(self, context):
        return parse_all_qasm(context)

    def parse_programs(self, context):
        return self.parse_context(context)

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        total_gate_ops = sum(
            len(sub["gate_ops"]) for sub in parsed["subroutines"].values()
        ) + len(parsed["top_level_ops"])
        return {
            "Constants": len(parsed["constants"]),
            "Qubit Registers": len(parsed["qubit_decls"]),
            "Extern Decls": len(parsed["extern_decls"]),
            "Gate Defs": len(parsed["gate_defs"]),
            "Subroutines": len(parsed["subroutines"]),
            "Total Gate Ops": total_gate_ops,
        }

    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {"score": None}

        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)

        start_state_id = sample["start_state"]
        start_state = [
            s for s in sample["states"] if s["state_id"] == start_state_id
        ][0]
        reference_context = build_context_from_folder(
            os.path.join(sample_folder, start_state["solution_folder"])
        )

        ref = self.parse_context(reference_context)
        gen = self.parse_context(generated_context)

        # If generated fails to parse at all (AST + regex both empty),
        # fall back to raw text comparison
        gen_has_elements = (gen["subroutines"] or gen["constants"]
                           or gen["qubit_decls"] or gen["extern_decls"])
        if gen["parse_error"] and not gen_has_elements:
            raw_score = score_raw_text(ref["raw_text"], gen["raw_text"])
            eval_obj = {
                "score": round(raw_score * 0.5, 6),  # Max 0.5 for unparseable
                "parse_error": gen["parse_error"],
                "raw_text_similarity": round(raw_score, 4),
            }
            print(f"\033[94m{eval_obj}\033[0m")
            return eval_obj

        if debug:
            print(f"Ref: {len(ref['constants'])} consts, {len(ref['qubit_decls'])} qubits, "
                  f"{len(ref['subroutines'])} subs, {len(ref['extern_decls'])} externs")
            print(f"Gen: {len(gen['constants'])} consts, {len(gen['qubit_decls'])} qubits, "
                  f"{len(gen['subroutines'])} subs, {len(gen['extern_decls'])} externs")

        # --- Component scores ---
        s_const = score_constants(ref["constants"], gen["constants"])
        s_qubit = score_qubit_decls(ref["qubit_decls"], gen["qubit_decls"])
        s_extern = score_extern_decls(ref["extern_decls"], gen["extern_decls"])
        s_gate_def = score_gate_defs(ref["gate_defs"], gen["gate_defs"])
        s_subs = score_subroutines(ref["subroutines"], gen["subroutines"])

        # --- Weighted score ---
        # Subroutines are the heart of a QASM program (65%):
        #   unified score covering coverage, signatures, body, gate ops
        # Constants 10%
        # Qubit declarations 10%
        # Extern declarations 10%
        # Gate definitions 5%
        raw_score = (
            0.10 * s_const
            + 0.10 * s_qubit
            + 0.10 * s_extern
            + 0.05 * s_gate_def
            + 0.65 * s_subs
        )

        # Multiplicative penalty: if major sections are completely missing
        multiplier = 1.0
        if ref["subroutines"] and not gen["subroutines"]:
            multiplier *= 0.2
        if ref["constants"] and not gen["constants"]:
            multiplier *= 0.6
        if ref["qubit_decls"] and not gen["qubit_decls"]:
            multiplier *= 0.7

        score = raw_score * multiplier

        eval_obj = {
            "score": round(score, 6),
            "constant_accuracy": round(s_const, 4),
            "qubit_decl_accuracy": round(s_qubit, 4),
            "extern_decl_accuracy": round(s_extern, 4),
            "gate_def_accuracy": round(s_gate_def, 4),
            "subroutine_accuracy": round(s_subs, 4),
            "multiplier": round(multiplier, 4),
            "ref_subroutine_count": len(ref["subroutines"]),
            "gen_subroutine_count": len(gen["subroutines"]),
            "ref_constant_count": len(ref["constants"]),
            "gen_constant_count": len(gen["constants"]),
        }

        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

    def render_context_visual(self, context, outfile):
        """Render OpenQASM 3.0 quantum circuits as PNG images.

        Strategy:
        1. Try ``qiskit.qasm3.loads()`` → ``QuantumCircuit.draw('mpl')``
           (works for simple / flat circuits).
        2. Fall back to a matplotlib structural diagram built from the
           parsed AST (subroutines, qubit registers, gate operations).
        """
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        context = self.preprocess_context(context)

        qasm_files = {f: c for f, c in context.items() if f.endswith('.qasm')}
        if not qasm_files:
            return None

        out_path = outfile + '.png'
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)

        # --- Strategy 1: qiskit direct load ----------------------------------
        if len(qasm_files) == 1:
            try:
                from qiskit.qasm3 import loads as qasm3_loads
                qc = qasm3_loads(next(iter(qasm_files.values())))
                fig = qc.draw('mpl')
                fig.savefig(out_path, dpi=150, bbox_inches='tight')
                plt.close(fig)
                return out_path
            except Exception:
                pass

        # --- Strategy 2: structural diagram from parsed data -----------------
        parsed = self.parse_context(context)
        fig = self._render_structural_diagram(parsed, qasm_files)
        if fig is not None:
            fig.savefig(out_path, dpi=150, bbox_inches='tight')
            plt.close(fig)
            return out_path

        return None

    # ------------------------------------------------------------------
    # Structural diagram renderer (fallback)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_qubit_size(size_str, constants):
        """Try to evaluate a qubit size expression using known constants."""
        try:
            return int(size_str)
        except (ValueError, TypeError):
            pass
        # Substitute known constants and try eval
        expr = size_str
        for name, val in constants.items():
            expr = re.sub(r'\b' + re.escape(name) + r'\b', str(val), expr)
        try:
            return int(eval(expr, {"__builtins__": {}}))
        except Exception:
            return 4  # sensible default

    def _render_structural_diagram(self, parsed, qasm_files):
        """Build a matplotlib figure showing the circuit structure.

        Draws horizontal qubit-register wires with labelled subroutine
        blocks and top-level gate operations.
        """
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        constants = parsed.get('constants', {})
        qubit_decls = parsed.get('qubit_decls', [])
        subroutines = parsed.get('subroutines', {})
        top_ops = parsed.get('top_level_ops', [])
        gate_defs = parsed.get('gate_defs', [])

        # --- Resolve qubit registers ----------------------------------------
        registers = []
        total_qubits = 0
        for decl in qubit_decls:
            sz = self._resolve_qubit_size(decl['size'], constants)
            sz = min(sz, 32)  # cap for rendering
            registers.append((decl['name'], sz))
            total_qubits += sz
        if total_qubits == 0:
            total_qubits = 1
            registers = [('q', 1)]

        # --- Layout parameters -----------------------------------------------
        n_subs = len(subroutines)
        has_top_ops = len(top_ops) > 0
        n_columns = n_subs + (1 if has_top_ops else 0)
        if n_columns == 0:
            # Nothing to draw – render raw text summary
            return self._render_text_card(parsed, qasm_files)

        col_width = 2.2
        wire_spacing = 0.45
        left_margin = 2.5
        right_margin = 0.8
        top_margin = 1.0
        bottom_margin = 0.6

        fig_w = left_margin + n_columns * col_width + right_margin
        fig_h = top_margin + total_qubits * wire_spacing + bottom_margin
        fig_w = max(fig_w, 5)
        fig_h = max(fig_h, 3)
        # Cap figure size for very large circuits
        fig_h = min(fig_h, 18)

        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        ax.set_xlim(-0.5, left_margin + n_columns * col_width + 0.3)
        ax.set_ylim(-0.5, total_qubits * wire_spacing + 0.5)
        ax.set_aspect('auto')
        ax.axis('off')

        # Title
        title_parts = list(qasm_files.keys())
        version = parsed.get('version', '')
        title = f"OpenQASM {version}" if version else "OpenQASM"
        if title_parts:
            title += f"  —  {', '.join(title_parts)}"
        ax.set_title(title, fontsize=11, fontweight='bold', pad=10)

        # --- Draw qubit wires ------------------------------------------------
        wire_y = {}  # register_name -> list of y positions
        y = (total_qubits - 1) * wire_spacing
        wire_end_x = left_margin + n_columns * col_width
        for reg_name, reg_size in registers:
            ys = []
            for i in range(min(reg_size, 32)):
                ax.plot([left_margin - 0.3, wire_end_x],
                        [y, y], color='#444444', linewidth=0.7, zorder=1)
                label = f"{reg_name}[{i}]" if reg_size > 1 else reg_name
                ax.text(left_margin - 0.4, y, label,
                        ha='right', va='center', fontsize=7,
                        fontfamily='monospace', color='#333333')
                ys.append(y)
                y -= wire_spacing
            wire_y[reg_name] = ys

        # --- Colour palette for subroutine blocks ----------------------------
        cmap = plt.cm.get_cmap('tab10')
        colours = [cmap(i % 10) for i in range(max(n_columns, 1))]

        # --- Draw subroutine blocks ------------------------------------------
        col = 0
        for sub_name, sub_data in subroutines.items():
            x_center = left_margin + col * col_width + col_width / 2
            colour = colours[col % len(colours)]

            # Block spanning all wires
            block_h = (total_qubits - 1) * wire_spacing + 0.4
            block_y = -0.2
            rect = mpatches.FancyBboxPatch(
                (x_center - col_width * 0.4, block_y),
                col_width * 0.8, block_h,
                boxstyle='round,pad=0.08',
                facecolor=(*colour[:3], 0.15),
                edgecolor=(*colour[:3], 0.7),
                linewidth=1.5, zorder=2,
            )
            ax.add_patch(rect)

            # Subroutine name
            gate_ops = sub_data.get('gate_ops', [])
            n_gates = len(gate_ops)
            label = f"{sub_name}\n({n_gates} gates)"
            label_y = block_y + block_h / 2
            ax.text(x_center, label_y, label,
                    ha='center', va='center', fontsize=8,
                    fontweight='bold', color=(*colour[:3], 0.9),
                    zorder=3)

            # Show representative gate names inside block
            unique_gates = []
            seen = set()
            for op in gate_ops:
                g = op['gate']
                if g not in seen:
                    unique_gates.append(g)
                    seen.add(g)
            gate_summary = ', '.join(unique_gates[:6])
            if len(unique_gates) > 6:
                gate_summary += ', …'
            ax.text(x_center, label_y - 0.35, gate_summary,
                    ha='center', va='center', fontsize=6,
                    fontfamily='monospace', color='#555555', zorder=3)

            col += 1

        # --- Draw top-level ops column ---------------------------------------
        if has_top_ops:
            x_center = left_margin + col * col_width + col_width / 2
            colour = colours[col % len(colours)]
            block_h = (total_qubits - 1) * wire_spacing + 0.4
            block_y = -0.2
            rect = mpatches.FancyBboxPatch(
                (x_center - col_width * 0.4, block_y),
                col_width * 0.8, block_h,
                boxstyle='round,pad=0.08',
                facecolor=(*colour[:3], 0.12),
                edgecolor=(*colour[:3], 0.6),
                linewidth=1.2, linestyle='--', zorder=2,
            )
            ax.add_patch(rect)
            n_top = len(top_ops)
            unique_top = list({op['gate'] for op in top_ops})
            ax.text(x_center, block_y + block_h / 2,
                    f"top-level\n({n_top} ops)",
                    ha='center', va='center', fontsize=8,
                    fontweight='bold', color=(*colour[:3], 0.85), zorder=3)
            top_summary = ', '.join(unique_top[:6])
            ax.text(x_center, block_y + block_h / 2 - 0.35, top_summary,
                    ha='center', va='center', fontsize=6,
                    fontfamily='monospace', color='#555555', zorder=3)

        # --- Stats footer ----------------------------------------------------
        stats_parts = []
        if constants:
            stats_parts.append(f"{len(constants)} consts")
        if gate_defs:
            stats_parts.append(f"{len(gate_defs)} gate defs")
        stats_parts.append(f"{n_subs} subroutines")
        stats_parts.append(f"{total_qubits} qubits")
        stats_line = '  |  '.join(stats_parts)
        ax.text((left_margin + wire_end_x) / 2, -0.4, stats_line,
                ha='center', va='top', fontsize=7, color='#888888')

        fig.tight_layout()
        return fig

    @staticmethod
    def _render_text_card(parsed, qasm_files):
        """Last-resort renderer: display raw QASM source as a text card."""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        # Combine all file contents
        text = '\n'.join(qasm_files.values()).strip()
        # Truncate for rendering
        lines = text.split('\n')[:60]
        display_text = '\n'.join(lines)
        if len(text.split('\n')) > 60:
            display_text += '\n  …'

        fig, ax = plt.subplots(figsize=(10, max(3, len(lines) * 0.22)))
        ax.axis('off')
        ax.text(0.02, 0.98, display_text,
                transform=ax.transAxes, fontsize=7,
                fontfamily='monospace', verticalalignment='top',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='#f8f8f8',
                          edgecolor='#cccccc'))
        title_parts = list(qasm_files.keys())
        ax.set_title(', '.join(title_parts), fontsize=10, fontweight='bold')
        fig.tight_layout()
        return fig


if __name__ == "__main__":
    task = TaskQuantum()
    context = build_context_from_folder("samples/quantum1/basic_state")

    print("=" * 60)
    print("QUANTUM SELF-EVALUATION TEST (openqasm3)")
    print("=" * 60)

    kpis = task.compute_domain_statistics(context)
    print(f"KPIs: {kpis}")

    target_state = {"state_id": "basic_state"}
    result = task.evaluate_context("quantum1", context, target_state, debug=True)
    print(f"\nSelf-evaluation score: {result['score']}")
    assert result["score"] == 1.0, f"Self-evaluation failed: {result['score']}"
    print("PASS: Self-evaluation = 1.0")
