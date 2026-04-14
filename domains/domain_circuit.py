from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, tempfile, ujson as json
from spicelib import SpiceEditor


# ---------------------------------------------------------------------------
# Preprocessing helpers (SPICE is case-insensitive; spicelib needs uppercase
# component prefixes and no leading whitespace on element lines)
# ---------------------------------------------------------------------------

def preprocess_context(text):
    """Normalise a SPICE netlist so spicelib can parse it.

    * Convert C-style // line comments to SPICE * comments
    * Join continuation lines (lines starting with '+')
    * Strip leading whitespace from all lines
    * Uppercase the first character of element lines (R,C,M,X,V,…)
      because spicelib requires uppercase component prefixes
    * Ensure a title comment line exists as the first line
    * Ensure a .end statement exists at the end
    """
    # Convert C-style line comments to SPICE asterisk comments
    raw_lines = text.split('\n')
    converted = []
    for line in raw_lines:
        stripped = line.strip()
        if stripped.startswith('//'):
            converted.append('*' + stripped[2:])
        else:
            converted.append(line)

    # Join continuation lines
    joined = []
    for line in converted:
        if line.startswith('+') and joined:
            joined[-1] = joined[-1] + ' ' + line[1:].strip()
        else:
            joined.append(line)

    processed = []
    for line in joined:
        stripped = line.strip()
        if not stripped:
            processed.append('')
            continue
        if stripped.startswith('*') or stripped.startswith('.'):
            processed.append(stripped)
        else:
            # Element line — uppercase first char for spicelib
            processed.append(stripped[0].upper() + stripped[1:])

    # Ensure .end exists
    has_end = any(l.strip().lower() == '.end' for l in processed)
    if not has_end:
        processed.append('.end')

    # Ensure first line is a title comment (spicelib requires it)
    if processed and not processed[0].startswith('*'):
        processed.insert(0, '* netlist')

    return '\n'.join(processed)


# ---------------------------------------------------------------------------
# Structured parser using spicelib
# ---------------------------------------------------------------------------

def parse_spice_netlist(text):
    """Parse a SPICE netlist into a structured dict using spicelib.

    Returns
    -------
    dict with keys:
        title            : str
        subcircuits      : dict[name] -> {ports, elements: [{name,prefix,nodes,value}]}
        top_instances    : list[{name, value, nodes}]   (X-instances)
        top_sources      : list[{name, value, nodes}]   (V/I sources)
        top_passives     : list[{name, value, nodes}]   (R/C/L/M/…)
        params           : dict[name] -> value
        control_text     : str  (raw .control block content)
        directives       : list[str]  (.tran, .include, .global, etc.)
    """
    preprocessed = preprocess_context(text)

    # spicelib reads from file
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.cir', delete=False, dir='/tmp'
    ) as f:
        f.write(preprocessed)
        tmp_path = f.name

    try:
        net = SpiceEditor(tmp_path)
    except Exception as e:
        # If parsing fails, return an empty structure
        os.unlink(tmp_path)
        return _empty_parse_result(str(e))

    result = {
        'title': '',
        'subcircuits': {},
        'top_instances': [],
        'top_sources': [],
        'top_passives': [],
        'params': {},
        'control_text': '',
        'directives': [],
        'parse_error': None,
    }

    # --- Title (first line) ---
    if net.netlist:
        first = str(net.netlist[0]).strip()
        if first.startswith('*'):
            result['title'] = first.lstrip('* ').strip()

    # --- Parameters ---
    for pname in net.get_all_parameter_names():
        result['params'][pname.lower()] = net.get_parameter(pname)

    # --- Subcircuit definitions ---
    for sname in net.get_subcircuit_names():
        sub = net.get_subcircuit_named(sname)
        elements = []
        for comp_name in sub.get_components():
            try:
                value = sub.get_component_value(comp_name)
                nodes = sub.get_component_nodes(comp_name)
            except Exception:
                value = ''
                nodes = []
            prefix = comp_name[0].upper()
            elements.append({
                'name': comp_name.lower(),
                'prefix': prefix,
                'value': str(value).lower(),
                'nodes': [n.lower() for n in nodes],
            })

        # Extract ports from the .subckt header line in the raw netlist
        ports = _extract_subckt_ports(preprocessed, sname)

        result['subcircuits'][sname.lower()] = {
            'name': sname.lower(),
            'ports': ports,
            'elements': elements,
        }

    # --- Top-level components ---
    all_top = net.get_components()
    for comp_name in all_top:
        try:
            value = net.get_component_value(comp_name)
            nodes = net.get_component_nodes(comp_name)
        except Exception:
            continue
        prefix = comp_name[0].upper()
        entry = {
            'name': comp_name.lower(),
            'value': str(value).lower(),
            'nodes': [n.lower() for n in nodes],
        }
        if prefix == 'X':
            result['top_instances'].append(entry)
        elif prefix in ('V', 'I'):
            result['top_sources'].append(entry)
        else:
            result['top_passives'].append(entry)

    # --- Control block ---
    try:
        controls = net.get_control_sections()
        if controls:
            # controls is a list of strings
            ctrl_text = '\n'.join(str(c) for c in controls)
            # Strip the .control / .endc wrapper if present
            ctrl_text = re.sub(r'(?i)^\.control\s*\n?', '', ctrl_text)
            ctrl_text = re.sub(r'(?i)\n?\.endc\s*$', '', ctrl_text)
            result['control_text'] = ctrl_text.strip()
    except Exception:
        pass

    # --- Directives (extract from raw preprocessed text) ---
    directive_prefixes = (
        '.tran', '.ac', '.dc', '.ic', '.op', '.option', '.options',
        '.temp', '.save', '.print', '.plot', '.meas', '.measure',
        '.noise', '.sens', '.tf', '.four', '.include', '.lib',
        '.global',
    )
    for line in preprocessed.split('\n'):
        sl = line.strip().lower()
        if any(sl.startswith(dp) for dp in directive_prefixes):
            result['directives'].append(line.strip())

    os.unlink(tmp_path)
    return result


def _extract_subckt_ports(text, subckt_name):
    """Extract port names from a .subckt header line."""
    pattern = re.compile(
        rf'\.subckt\s+{re.escape(subckt_name)}\s+(.*)',
        re.IGNORECASE,
    )
    for line in text.split('\n'):
        m = pattern.match(line.strip())
        if m:
            tokens = m.group(1).strip().split()
            # Exclude any key=value parameters
            return [t.lower() for t in tokens if '=' not in t]
    return []


def _empty_parse_result(error_msg=''):
    return {
        'title': '',
        'subcircuits': {},
        'top_instances': [],
        'top_sources': [],
        'top_passives': [],
        'params': {},
        'control_text': '',
        'directives': [],
        'parse_error': error_msg or 'empty',
    }


def parse_all_netlists(context):
    """Parse every file in context and merge into one structure."""
    merged = _empty_parse_result()
    merged['parse_error'] = None
    for fname, content in context.items():
        p = parse_spice_netlist(content)
        if p.get('parse_error'):
            if not merged['parse_error']:
                merged['parse_error'] = p['parse_error']
            continue
        if not merged['title']:
            merged['title'] = p['title']
        merged['subcircuits'].update(p['subcircuits'])
        merged['top_instances'].extend(p['top_instances'])
        merged['top_sources'].extend(p['top_sources'])
        merged['top_passives'].extend(p['top_passives'])
        merged['params'].update(p['params'])
        if p['control_text']:
            merged['control_text'] = (
                merged['control_text'] + '\n' + p['control_text']
            ).strip()
        merged['directives'].extend(p['directives'])
    return merged


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _f1(ref_set, gen_set):
    """F1 score between two sets.  Returns 0.0 when ref is empty and gen is not."""
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


# --- Subcircuit scoring ---

def score_subcircuit_coverage(ref_sub, gen_sub):
    """F1 on subcircuit names."""
    return _f1(set(ref_sub.keys()), set(gen_sub.keys()))


def score_subcircuit_ports(ref_sub, gen_sub):
    """Average port-list similarity for matched subcircuits."""
    matched = set(ref_sub.keys()) & set(gen_sub.keys())
    if not matched:
        return 0.0
    scores = []
    for name in matched:
        rp = ref_sub[name]['ports']
        gp = gen_sub[name]['ports']
        if rp == gp:
            scores.append(1.0)
        elif not rp and not gp:
            scores.append(1.0)
        elif not rp or not gp:
            scores.append(0.0)
        else:
            # Ordered comparison
            scores.append(_seq_sim(' '.join(rp), ' '.join(gp)))
    return sum(scores) / len(scores)


def score_subcircuit_elements(ref_sub, gen_sub):
    """Per-subcircuit element accuracy, averaged over ref subcircuits.

    For each matched subcircuit: compare element names, their
    prefix (type), value (model), and node connections.
    """
    if not ref_sub:
        return 1.0
    scores = []
    for name, ref_sc in ref_sub.items():
        if name not in gen_sub:
            scores.append(0.0)
            continue
        gen_sc = gen_sub[name]
        ref_elems = {e['name']: e for e in ref_sc['elements']}
        gen_elems = {e['name']: e for e in gen_sc['elements']}
        if not ref_elems and not gen_elems:
            scores.append(1.0)
            continue
        if not ref_elems or not gen_elems:
            scores.append(0.0)
            continue

        # Name coverage
        name_f1 = _f1(set(ref_elems.keys()), set(gen_elems.keys()))

        # For matched elements: check value and nodes
        matched = set(ref_elems.keys()) & set(gen_elems.keys())
        if not matched:
            scores.append(name_f1 * 0.3)
            continue

        detail_scores = []
        for ename in matched:
            re_ = ref_elems[ename]
            ge_ = gen_elems[ename]
            # Prefix match (type)
            prefix_ok = 1.0 if re_['prefix'] == ge_['prefix'] else 0.0
            # Value/model match
            val_sim = 1.0 if re_['value'] == ge_['value'] else _seq_sim(re_['value'], ge_['value'])
            # Node match (ordered)
            if re_['nodes'] == ge_['nodes']:
                node_sim = 1.0
            else:
                node_sim = _f1(set(re_['nodes']), set(ge_['nodes']))
            detail_scores.append(0.2 * prefix_ok + 0.3 * val_sim + 0.5 * node_sim)

        detail_avg = sum(detail_scores) / len(detail_scores)
        scores.append(name_f1 * 0.4 + detail_avg * 0.6)

    return sum(scores) / len(scores)


# --- Top-level instance scoring ---

def score_top_instances(ref_inst, gen_inst):
    """Score top-level subcircuit instances (X-components).

    Compares name, subcircuit type, and node connections.
    """
    if not ref_inst and not gen_inst:
        return 1.0
    if not ref_inst or not gen_inst:
        return 0.0

    ref_map = {e['name']: e for e in ref_inst}
    gen_map = {e['name']: e for e in gen_inst}

    name_f1 = _f1(set(ref_map.keys()), set(gen_map.keys()))
    matched = set(ref_map.keys()) & set(gen_map.keys())
    if not matched:
        return name_f1 * 0.3

    detail_scores = []
    for n in matched:
        r, g = ref_map[n], gen_map[n]
        subckt_ok = 1.0 if r['value'] == g['value'] else 0.0
        node_sim = 1.0 if r['nodes'] == g['nodes'] else _f1(set(r['nodes']), set(g['nodes']))
        detail_scores.append(0.4 * subckt_ok + 0.6 * node_sim)

    detail_avg = sum(detail_scores) / len(detail_scores)
    return name_f1 * 0.4 + detail_avg * 0.6


# --- Source scoring ---

def score_sources(ref_src, gen_src):
    """Score voltage/current sources (V/I components)."""
    if not ref_src and not gen_src:
        return 1.0
    if not ref_src or not gen_src:
        return 0.0

    ref_map = {e['name']: e for e in ref_src}
    gen_map = {e['name']: e for e in gen_src}

    name_f1 = _f1(set(ref_map.keys()), set(gen_map.keys()))
    matched = set(ref_map.keys()) & set(gen_map.keys())
    if not matched:
        return name_f1 * 0.3

    detail_scores = []
    for n in matched:
        r, g = ref_map[n], gen_map[n]
        val_sim = _seq_sim(r['value'], g['value'])
        node_sim = 1.0 if r['nodes'] == g['nodes'] else _f1(set(r['nodes']), set(g['nodes']))
        detail_scores.append(0.5 * val_sim + 0.5 * node_sim)

    detail_avg = sum(detail_scores) / len(detail_scores)
    return name_f1 * 0.4 + detail_avg * 0.6


# --- Parameter scoring ---

def score_params(ref_p, gen_p):
    """Score .param definitions."""
    if not ref_p and not gen_p:
        return 1.0
    if not ref_p or not gen_p:
        return 0.0

    ref_keys = set(ref_p.keys())
    gen_keys = set(gen_p.keys())
    name_f1 = _f1(ref_keys, gen_keys)

    matched = ref_keys & gen_keys
    if not matched:
        return name_f1 * 0.3

    val_scores = []
    for k in matched:
        rv = str(ref_p[k]).strip().lower()
        gv = str(gen_p[k]).strip().lower()
        val_scores.append(1.0 if rv == gv else _seq_sim(rv, gv))

    val_avg = sum(val_scores) / len(val_scores)
    return name_f1 * 0.4 + val_avg * 0.6


# --- Control block scoring ---

def score_control_block(ref_ctrl, gen_ctrl):
    """Sequence similarity on the raw control block text."""
    if not ref_ctrl and not gen_ctrl:
        return 1.0
    if not ref_ctrl or not gen_ctrl:
        return 0.0
    # Normalise whitespace
    ref_norm = re.sub(r'\s+', ' ', ref_ctrl.strip().lower())
    gen_norm = re.sub(r'\s+', ' ', gen_ctrl.strip().lower())
    return _seq_sim(ref_norm, gen_norm)


# --- Directive scoring ---

def score_directives(ref_dirs, gen_dirs):
    """Compare directives by normalised text similarity."""
    if not ref_dirs and not gen_dirs:
        return 1.0
    if not ref_dirs or not gen_dirs:
        return 0.0

    def norm(d): return re.sub(r'\s+', ' ', d.strip().lower())
    ref_set = set(norm(d) for d in ref_dirs)
    gen_set = set(norm(d) for d in gen_dirs)
    f1 = _f1(ref_set, gen_set)

    # For matched directives, check exact text
    matched = ref_set & gen_set
    exact_ratio = len(matched) / len(ref_set) if ref_set else 1.0
    return f1 * 0.6 + exact_ratio * 0.4


# ---------------------------------------------------------------------------
# Task class
# ---------------------------------------------------------------------------

class DomainCircuit(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "circuit"
        self.summary = "SPICE circuit netlists with subcircuits, elements, models, and simulation directives"
        self.description = "SPICE circuit netlists"
        self.file_format = [".cir"]
        self.domain_parser = "spicelib"
        self.category = "science"

    def parse_context(self, context):
        return parse_all_netlists(context)

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        total_subckt_elements = sum(
            len(sc['elements']) for sc in parsed['subcircuits'].values()
        )
        return {
            "Subcircuits": len(parsed['subcircuits']),
            "Subckt Elements": total_subckt_elements,
            "Top Instances": len(parsed['top_instances']),
            "Sources": len(parsed['top_sources']),
            "Parameters": len(parsed['params']),
            "Directives": len(parsed['directives']),
        }

    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}

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

        if debug:
            print(f"Ref: {len(ref['subcircuits'])} subckts, "
                  f"{len(ref['top_instances'])} instances, "
                  f"{len(ref['top_sources'])} sources, "
                  f"{len(ref['params'])} params")
            print(f"Gen: {len(gen['subcircuits'])} subckts, "
                  f"{len(gen['top_instances'])} instances, "
                  f"{len(gen['top_sources'])} sources, "
                  f"{len(gen['params'])} params")

        # --- Component scores ---
        s_cov = score_subcircuit_coverage(ref['subcircuits'], gen['subcircuits'])
        s_port = score_subcircuit_ports(ref['subcircuits'], gen['subcircuits'])
        s_elem = score_subcircuit_elements(ref['subcircuits'], gen['subcircuits'])
        t_inst = score_top_instances(ref['top_instances'], gen['top_instances'])
        t_src = score_sources(ref['top_sources'], gen['top_sources'])
        p_param = score_params(ref['params'], gen['params'])
        c_ctrl = score_control_block(ref['control_text'], gen['control_text'])
        d_dir = score_directives(ref['directives'], gen['directives'])

        # --- Weighted score ---
        # Subcircuit structure is critical (50%):
        #   coverage 10%, ports 10%, internal elements 30%
        # Top-level instances 20%
        # Source definitions 10%
        # Parameters 5%
        # Control block 3%
        # Directives 2%
        raw = (
            0.10 * s_cov
            + 0.10 * s_port
            + 0.30 * s_elem
            + 0.20 * t_inst
            + 0.10 * t_src
            + 0.10 * p_param
            + 0.05 * c_ctrl
            + 0.05 * d_dir
        )

        # Multiplicative penalty: if major sections are completely missing,
        # apply a harsh multiplier so partial matches don't inflate the score
        multiplier = 1.0
        if ref['subcircuits'] and not gen['subcircuits']:
            multiplier *= 0.3
        if ref['top_instances'] and not gen['top_instances']:
            multiplier *= 0.4
        if ref['top_sources'] and not gen['top_sources']:
            multiplier *= 0.7

        score = raw * multiplier

        eval_obj = {
            "score": round(score, 6),
            "subckt_coverage": round(s_cov, 4),
            "subckt_port_accuracy": round(s_port, 4),
            "subckt_element_accuracy": round(s_elem, 4),
            "top_instance_accuracy": round(t_inst, 4),
            "source_accuracy": round(t_src, 4),
            "param_accuracy": round(p_param, 4),
            "control_block_accuracy": round(c_ctrl, 4),
            "directive_accuracy": round(d_dir, 4),
            "multiplier": round(multiplier, 4),
            "ref_subckt_count": len(ref['subcircuits']),
            "gen_subckt_count": len(gen['subcircuits']),
            "ref_instance_count": len(ref['top_instances']),
            "gen_instance_count": len(gen['top_instances']),
            "ref_source_count": len(ref['top_sources']),
            "gen_source_count": len(gen['top_sources']),
        }

        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


if __name__ == "__main__":
    task = TaskCircuit()
    context = build_context_from_folder("samples/circuit1/basic_state")

    print("=" * 60)
    print("CIRCUIT SELF-EVALUATION TEST (spicelib)")
    print("=" * 60)

    kpis = task.compute_domain_statistics(context)
    print(f"KPIs: {kpis}")

    target_state = {"state_id": "basic_state"}
    result = task.evaluate_context("circuit1", context, target_state, debug=True)
    print(f"\nSelf-evaluation score: {result['score']}")
    assert result['score'] == 1.0, f"Self-evaluation failed: {result['score']}"
    print("PASS: Self-evaluation = 1.0")
