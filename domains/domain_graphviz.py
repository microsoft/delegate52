from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import pydot
import os, re, math, ujson as json


def preprocess_dot_content(content):
    # Fix common malformed DOT syntax that models generate

    # --- Fix 1: Subgraph inline attributes ---
    # Pattern: "subgraph X { attr1=v1, attr2=v2;" -> proper multiline format
    def fix_subgraph_inline_attrs(match):
        subgraph_decl = match.group(1)  # "subgraph cluster_X"
        attrs_str = match.group(2)  # everything after { until first newline or node/edge
        # Split by comma, but be careful with quoted values containing commas
        attrs = []
        current = ""
        in_quotes = False
        for char in attrs_str:
            if char == '"' and (not current or current[-1] != '\\'):
                in_quotes = not in_quotes
            if char == ',' and not in_quotes:
                if current.strip():
                    attrs.append(current.strip())
                current = ""
            else:
                current += char
        if current.strip():
            attrs.append(current.strip())
        # Rebuild with proper semicolon separation
        fixed_attrs = ";\n    ".join(a.rstrip(';') for a in attrs if a)
        return f"{subgraph_decl} {{\n    {fixed_attrs};\n"
    
    # Match: subgraph <name> { <attrs on same line with commas>
    # Use [^\S\n]* instead of \s* after { to avoid crossing newlines
    # (otherwise the regex captures node declarations on the next line)
    content = re.sub(
        r'(subgraph\s+\w+)\s*\{[^\S\n]*([^{}\n]+,[^{}\n]+);?[^\S\n]*\n',
        fix_subgraph_inline_attrs,
        content
    )

    # --- Fix 2: Unterminated hex color quotes ---
    # Models write e.g. color="#d9e7eeff]; instead of color="#d9e7eeff"];
    content = re.sub(
        r'="(#[0-9a-fA-F]{3,8})([\];\s,}])',
        r'="\1"\2',
        content
    )

    # --- Fix 3: name= attribute (pydot constructor conflict) ---
    # pydot's Node/Graph __init__ uses 'name' as a positional arg,
    # so name= as a DOT attribute crashes it. Rename to _dot_name.
    content = re.sub(r'\bname\s*=', '_dot_name=', content)

    # --- Fix 4: $ prefix on attribute names ---
    # Models sometimes write $row="func" instead of row="func"
    content = re.sub(r'\$(\w+)\s*=', r'\1=', content)

    # --- Fix 5: Empty attribute values ---
    # E.g. weight= , or color=] — remove the dangling attribute
    content = re.sub(r'\b\w+=\s*(?=[,\]\;])', '', content)
    # Clean up resulting double/trailing commas
    content = re.sub(r',\s*,', ',', content)
    content = re.sub(r',\s*\]', ']', content)
    content = re.sub(r'\[\s*,', '[', content)

    # --- Fix 6: Semicolons as attribute separators inside [ ] ---
    # Models write [attr1="x"; attr2=y] instead of [attr1="x", attr2=y]
    def fix_semicolons_in_attrs(line):
        result = []
        in_bracket = False
        in_quote = False
        for ch in line:
            if ch == '"':
                in_quote = not in_quote
            elif ch == '[' and not in_quote:
                in_bracket = True
            elif ch == ']' and not in_quote:
                in_bracket = False
            elif ch == ';' and in_bracket and not in_quote:
                ch = ','
            result.append(ch)
        return ''.join(result)

    lines = content.split('\n')
    fixed_lines = []
    for line in lines:
        if ';' in line and '[' in line:
            line = fix_semicolons_in_attrs(line)
        fixed_lines.append(line)
    content = '\n'.join(fixed_lines)

    # --- Fix 7: } instead of ] to close multi-line attribute lists ---
    lines = content.split('\n')
    fixed_lines = []
    in_attr_list = False
    for line in lines:
        stripped = line.strip()
        if not in_attr_list:
            if re.search(r'\[', stripped) and not re.search(r'\]', stripped) and not stripped.startswith('//'):
                in_attr_list = True
        else:
            if re.match(r'^[\t ]*\};?\s*$', stripped):
                line = line.replace('}', ']', 1)
                in_attr_list = False
            elif re.search(r'\]', stripped):
                in_attr_list = False
        fixed_lines.append(line)
    content = '\n'.join(fixed_lines)

    # --- Fix 8: ) instead of ] at end of attribute lists ---
    # E.g. [color="red" penwidth=2) — only when ) is outside quotes
    lines = content.split('\n')
    fixed_lines = []
    for line in lines:
        if re.search(r'\)[\s;]*$', line.rstrip()) and '[' in line:
            in_quote = False
            chars = list(line)
            for j, ch in enumerate(chars):
                if ch == '"':
                    in_quote = not in_quote
                elif ch == ')' and not in_quote:
                    rest = line[j + 1:].rstrip()
                    if rest == '' or rest == ';':
                        chars[j] = ']'
            line = ''.join(chars)
        fixed_lines.append(line)
    content = '\n'.join(fixed_lines)

    return content


def parse_dot_content(content):
    # Parse DOT file using pydot
    # Returns: {nodes: {id: {attrs}}, edges: [{src, tgt, attrs}], subgraphs: {name: {nodes, attrs}}, global_attrs: {}}
    result = {"nodes": {}, "edges": [], "subgraphs": {}, "global_attrs": {}, "graph_name": ""}
    
    try:
        graphs = pydot.graph_from_dot_data(content)
        if not graphs:
            return result
        graph = graphs[0]
    except Exception as e:
        print(f"\033[91mDOT parsing error: {e}\033[0m")
        return result
    
    result["graph_name"] = graph.get_name() or ""
    result["global_attrs"] = {k.lower(): v.strip('"') for k, v in graph.obj_dict.get("attributes", {}).items()}
    
    # Parse nodes from main graph
    for node in graph.get_nodes():
        node_id = node.get_name().strip('"')
        if node_id in ['node', 'edge', 'graph', '\\n', '']:
            continue
        attrs = {k.lower(): v.strip('"') if isinstance(v, str) else v for k, v in node.obj_dict.get("attributes", {}).items()}
        result["nodes"][node_id] = {"id": node_id, "attrs": attrs, "subgraph": None}
    
    # Parse edges from main graph
    for edge in graph.get_edges():
        src = str(edge.get_source()).strip('"')
        tgt = str(edge.get_destination()).strip('"')
        attrs = {k.lower(): v.strip('"') if isinstance(v, str) else v for k, v in edge.obj_dict.get("attributes", {}).items()}
        attrs["_directed"] = graph.get_type() == "digraph"
        result["edges"].append({"src": src, "tgt": tgt, "attrs": attrs, "subgraph": None})
    
    # Parse subgraphs recursively
    def process_subgraph(sg, parent_name=None):
        sg_name = sg.get_name().strip('"')
        if sg_name.startswith('cluster') or not sg_name.startswith('"'):
            sg_name_clean = sg_name
        else:
            sg_name_clean = sg_name
        
        result["subgraphs"][sg_name_clean] = {"nodes": set(), "node_defaults": {}, "edge_defaults": {}}
        
        # Get subgraph's node/edge defaults
        for attr_stmt in sg.obj_dict.get("attributes", {}).items():
            pass  # These are graph-level attrs for the subgraph
        
        # Parse nodes in subgraph
        for node in sg.get_nodes():
            node_id = node.get_name().strip('"')
            if node_id in ['node', 'edge', 'graph', '\\n', '']:
                continue
            attrs = {k.lower(): v.strip('"') if isinstance(v, str) else v for k, v in node.obj_dict.get("attributes", {}).items()}
            if node_id not in result["nodes"]:
                result["nodes"][node_id] = {"id": node_id, "attrs": attrs, "subgraph": sg_name_clean}
            else:
                result["nodes"][node_id]["attrs"].update(attrs)
                result["nodes"][node_id]["subgraph"] = sg_name_clean
            result["subgraphs"][sg_name_clean]["nodes"].add(node_id)
        
        # Parse edges in subgraph
        for edge in sg.get_edges():
            src = str(edge.get_source()).strip('"')
            tgt = str(edge.get_destination()).strip('"')
            attrs = {k.lower(): v.strip('"') if isinstance(v, str) else v for k, v in edge.obj_dict.get("attributes", {}).items()}
            attrs["_directed"] = graph.get_type() == "digraph"
            result["edges"].append({"src": src, "tgt": tgt, "attrs": attrs, "subgraph": sg_name_clean})
            # Track nodes mentioned in edges
            result["subgraphs"][sg_name_clean]["nodes"].add(src)
            result["subgraphs"][sg_name_clean]["nodes"].add(tgt)
        
        # Recurse into nested subgraphs
        for nested_sg in sg.get_subgraphs():
            process_subgraph(nested_sg, sg_name_clean)
    
    for sg in graph.get_subgraphs():
        process_subgraph(sg)
    
    return result


def parse_all_dot_files(context):
    # Parse all DOT files and merge the results
    merged = {"nodes": {}, "edges": [], "subgraphs": {}, "global_attrs": {}}
    
    for filename, content in context.items():
        if filename.endswith('.dot') or filename.endswith('.gv'):
            parsed = parse_dot_content(content)
            merged["nodes"].update(parsed["nodes"])
            merged["edges"].extend(parsed["edges"])
            merged["subgraphs"].update(parsed["subgraphs"])
            merged["global_attrs"].update(parsed["global_attrs"])
    
    return merged


def build_node_id_mapping(ref_nodes, gen_nodes):
    """Build a mapping from generated node IDs to reference node IDs.
    
    Handles the case where the model uses different IDs than the reference
    (e.g. team names like 'FloridaState' instead of short codes like 't1')
    but preserves the semantic identity through labels, tooltips, or id attributes.
    
    Returns a dict mapping gen_node_id -> ref_node_id for any mismatched IDs.
    """
    ref_ids = set(ref_nodes.keys())
    gen_ids = set(gen_nodes.keys())
    
    # If IDs already overlap well, no mapping needed
    overlap = len(ref_ids & gen_ids)
    if overlap >= len(ref_ids) * 0.5:
        return {}
    
    mapping = {}
    
    # Strategy 1: gen node's "id" attribute matches a ref node ID
    # e.g., gen: FloridaState [id="t1"] -> ref: t1 [label="FloridaState"]
    for gen_id, gen_node in gen_nodes.items():
        gen_id_attr = gen_node.get("attrs", {}).get("id", "").strip('"').lower()
        if gen_id_attr:
            for ref_id in ref_ids:
                if ref_id.lower() == gen_id_attr and ref_id not in mapping.values():
                    mapping[gen_id] = ref_id
                    break
    
    if len(mapping) >= len(gen_ids) * 0.5:
        return mapping
    
    # Strategy 2: gen node ID matches a ref node's label or tooltip
    # e.g., gen: FloridaState [...] -> ref: t1 [label="FloridaState"]
    ref_label_to_id = {}
    for ref_id, ref_node in ref_nodes.items():
        attrs = ref_node.get("attrs", {})
        for attr_key in ["label", "tooltip"]:
            val = attrs.get(attr_key, "")
            if val:
                ref_label_to_id[val.lower().strip()] = ref_id
    
    for gen_id, gen_node in gen_nodes.items():
        if gen_id in mapping:
            continue
        gen_id_lower = gen_id.lower().strip()
        if gen_id_lower in ref_label_to_id:
            ref_id = ref_label_to_id[gen_id_lower]
            if ref_id not in mapping.values():
                mapping[gen_id] = ref_id
    
    # Strategy 3: gen node's label matches ref node's label
    if len(mapping) < len(gen_ids) * 0.5:
        gen_label_to_id = {}
        for gen_id, gen_node in gen_nodes.items():
            if gen_id in mapping:
                continue
            attrs = gen_node.get("attrs", {})
            for attr_key in ["label", "tooltip"]:
                val = attrs.get(attr_key, "")
                if val:
                    gen_label_to_id[val.lower().strip()] = gen_id
        
        for label, gen_id in gen_label_to_id.items():
            if label in ref_label_to_id and gen_id not in mapping:
                ref_id = ref_label_to_id[label]
                if ref_id not in mapping.values():
                    mapping[gen_id] = ref_id
    
    return mapping


def apply_node_id_mapping(parsed, mapping):
    """Apply a node ID mapping to a parsed DOT result, renaming node IDs
    and updating edge endpoints and subgraph membership accordingly."""
    if not mapping:
        return parsed
    
    # Remap nodes
    new_nodes = {}
    for node_id, node_data in parsed["nodes"].items():
        new_id = mapping.get(node_id, node_id)
        new_node = dict(node_data)
        new_node["id"] = new_id
        new_nodes[new_id] = new_node
    
    # Remap edges
    new_edges = []
    for edge in parsed["edges"]:
        new_edge = dict(edge)
        new_edge["src"] = mapping.get(edge["src"], edge["src"])
        new_edge["tgt"] = mapping.get(edge["tgt"], edge["tgt"])
        new_edges.append(new_edge)
    
    # Remap subgraph node sets
    new_subgraphs = {}
    for sg_name, sg_data in parsed["subgraphs"].items():
        new_sg = dict(sg_data)
        new_sg["nodes"] = {mapping.get(n, n) for n in sg_data.get("nodes", set())}
        new_subgraphs[sg_name] = new_sg
    
    return {
        "nodes": new_nodes,
        "edges": new_edges,
        "subgraphs": new_subgraphs,
        "global_attrs": parsed["global_attrs"],
    }


def node_fingerprint(node):
    node_id = node.get("id", "")
    return node_id.lower().strip()


def edge_fingerprint(edge):
    s, t = edge['src'].lower(), edge['tgt'].lower()
    # For undirected graphs, canonicalize edge direction so a--b == b--a
    if not edge.get('attrs', {}).get('_directed', True):
        s, t = min(s, t), max(s, t)
    return f"{s}|{t}"


def compute_node_coverage(ref_nodes, gen_nodes):
    if not ref_nodes and not gen_nodes:
        return 1.0
    if not ref_nodes or not gen_nodes:
        return 0.0
    
    ref_fps = {node_fingerprint(n) for n in ref_nodes.values()}
    gen_fps = {node_fingerprint(n) for n in gen_nodes.values()}
    
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def normalize_color(color):
    if not color:
        return ""
    color = str(color).lower().strip().strip('"\'')
    return color


def normalize_attr_value(value):
    if value is None:
        return ""
    value = str(value).lower().strip().strip('"\'')
    value = re.sub(r'\s+', ' ', value)
    return value


def compute_node_attribute_accuracy(ref_nodes, gen_nodes):
    if not ref_nodes and not gen_nodes:
        return 1.0
    if not ref_nodes or not gen_nodes:
        return 0.0
    
    ref_by_fp = {node_fingerprint(n): n for n in ref_nodes.values()}
    gen_by_fp = {node_fingerprint(n): n for n in gen_nodes.values()}
    
    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0
    
    attr_weights = {
        "label": 2.0, "shape": 1.5, "fillcolor": 1.0, "color": 1.0,
        "fontcolor": 0.5, "fontsize": 0.5, "style": 0.5, "url": 1.0,
        "tooltip": 0.5, "width": 0.3, "height": 0.3, "fixedsize": 0.3, "row": 0.5,
    }
    
    node_scores = []
    for fp in matched_fps:
        ref_attrs = ref_by_fp[fp].get("attrs", {})
        gen_attrs = gen_by_fp[fp].get("attrs", {})
        
        score = 0.0
        total_weight = 0.0
        
        for attr, weight in attr_weights.items():
            ref_val = normalize_attr_value(ref_attrs.get(attr, ""))
            gen_val = normalize_attr_value(gen_attrs.get(attr, ""))
            
            if ref_val or gen_val:
                total_weight += weight
                if ref_val == gen_val:
                    score += weight
                elif ref_val and gen_val:
                    if attr in ["fillcolor", "color", "fontcolor"]:
                        if normalize_color(ref_val) == normalize_color(gen_val):
                            score += weight
                    else:
                        score += weight * SequenceMatcher(None, ref_val, gen_val).ratio() * 0.7
        
        node_scores.append(score / total_weight if total_weight > 0 else 1.0)
    
    return sum(node_scores) / len(node_scores) if node_scores else 0.0


def compute_edge_coverage(ref_edges, gen_edges):
    if not ref_edges and not gen_edges:
        return 1.0
    if not ref_edges or not gen_edges:
        return 0.0
    
    ref_fps = {edge_fingerprint(e) for e in ref_edges}
    gen_fps = {edge_fingerprint(e) for e in gen_edges}
    
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def compute_edge_attribute_accuracy(ref_edges, gen_edges):
    if not ref_edges and not gen_edges:
        return 1.0
    if not ref_edges or not gen_edges:
        return 0.0
    
    ref_by_fp = {edge_fingerprint(e): e for e in ref_edges}
    gen_by_fp = {edge_fingerprint(e): e for e in gen_edges}
    
    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0
    
    attr_weights = {
        "arrowhead": 1.0, "arrowsize": 0.5, "color": 1.0,
        "style": 0.5, "weight": 0.5, "label": 1.0, "_directed": 1.5,
    }
    
    edge_scores = []
    for fp in matched_fps:
        ref_attrs = ref_by_fp[fp].get("attrs", {})
        gen_attrs = gen_by_fp[fp].get("attrs", {})
        
        score = 0.0
        total_weight = 0.0
        
        for attr, weight in attr_weights.items():
            ref_val = normalize_attr_value(ref_attrs.get(attr, ""))
            gen_val = normalize_attr_value(gen_attrs.get(attr, ""))
            
            if ref_val or gen_val:
                total_weight += weight
                if ref_val == gen_val:
                    score += weight
                elif ref_val and gen_val:
                    if attr == "color":
                        if normalize_color(ref_val) == normalize_color(gen_val):
                            score += weight
                    else:
                        score += weight * SequenceMatcher(None, str(ref_val), str(gen_val)).ratio() * 0.7
        
        edge_scores.append(score / total_weight if total_weight > 0 else 1.0)
    
    return sum(edge_scores) / len(edge_scores) if edge_scores else 0.0


def normalize_subgraph_name(name):
    # Remove cluster_ prefix (Graphviz convention for visual grouping)
    name = name.lower().strip()
    if name.startswith("cluster_"):
        return name[8:]
    return name


def compute_subgraph_score(ref_parsed, gen_parsed):
    ref_subgraphs = ref_parsed.get("subgraphs", {})
    gen_subgraphs = gen_parsed.get("subgraphs", {})
    
    if not ref_subgraphs and not gen_subgraphs:
        return 1.0
    
    ref_node_sg = {}
    gen_node_sg = {}
    
    for sg_name, sg_data in ref_subgraphs.items():
        for node_id in sg_data.get("nodes", set()):
            ref_node_sg[node_id.lower()] = normalize_subgraph_name(sg_name)
    
    for sg_name, sg_data in gen_subgraphs.items():
        for node_id in sg_data.get("nodes", set()):
            gen_node_sg[node_id.lower()] = normalize_subgraph_name(sg_name)
    
    if not ref_node_sg and not gen_node_sg:
        return 1.0
    
    common_nodes = set(ref_node_sg.keys()) & set(gen_node_sg.keys())
    if not common_nodes:
        return 0.0
    
    matches = sum(1 for n in common_nodes if ref_node_sg[n] == gen_node_sg[n])
    return matches / len(common_nodes)


def compute_global_settings_score(ref_parsed, gen_parsed):
    ref_attrs = ref_parsed.get("global_attrs", {})
    gen_attrs = gen_parsed.get("global_attrs", {})
    
    if not ref_attrs and not gen_attrs:
        return 1.0
    
    all_keys = set(ref_attrs.keys()) | set(gen_attrs.keys())
    if not all_keys:
        return 1.0
    
    matches = 0
    for key in all_keys:
        ref_val = normalize_attr_value(ref_attrs.get(key, ""))
        gen_val = normalize_attr_value(gen_attrs.get(key, ""))
        if ref_val == gen_val:
            matches += 1
        elif ref_val and gen_val:
            matches += SequenceMatcher(None, ref_val, gen_val).ratio() * 0.5
    
    return matches / len(all_keys)


class DomainGraphviz(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "graphviz"
        self.summary = "DOT graph diagrams with nodes, edges, subgraphs, and styling"
        self.description = "DOT graph descriptions"
        self.file_format = [".dot"]
        self.domain_parser = "pydot"
        self.category = "code"
    
    def preprocess_context(self, context):
        """Preprocess all DOT files in the context dict."""
        cleaned = {}
        for filename, content in context.items():
            if filename.endswith(('.dot', '.gv')):
                cleaned[filename] = preprocess_dot_content(content)
            else:
                cleaned[filename] = content
        return cleaned

    def parse_context(self, context):
        context = self.preprocess_context(context)
        return parse_all_dot_files(context)
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        num_nodes = len(parsed.get('nodes', {}))
        num_edges = len(parsed.get('edges', []))
        num_subgraphs = len(parsed.get('subgraphs', {}))
        return {
            "Nodes": num_nodes,
            "Edges": num_edges,
            "Subgraphs": num_subgraphs,
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
        
        # Normalize generated node IDs to match reference when the model used
        # different IDs (e.g. team names vs short codes) but preserved identity
        # through labels, tooltips, or id attributes
        node_mapping = build_node_id_mapping(ref_parsed["nodes"], gen_parsed["nodes"])
        if node_mapping:
            gen_parsed = apply_node_id_mapping(gen_parsed, node_mapping)
            if debug:
                print(f"Applied node ID mapping ({len(node_mapping)} nodes remapped)")
        
        if debug:
            print(f"Reference: {len(ref_parsed['nodes'])} nodes, {len(ref_parsed['edges'])} edges, {len(ref_parsed['subgraphs'])} subgraphs")
            print(f"Generated: {len(gen_parsed['nodes'])} nodes, {len(gen_parsed['edges'])} edges, {len(gen_parsed['subgraphs'])} subgraphs")
        
        node_coverage = compute_node_coverage(ref_parsed["nodes"], gen_parsed["nodes"])
        node_accuracy = compute_node_attribute_accuracy(ref_parsed["nodes"], gen_parsed["nodes"])
        edge_coverage = compute_edge_coverage(ref_parsed["edges"], gen_parsed["edges"])
        edge_accuracy = compute_edge_attribute_accuracy(ref_parsed["edges"], gen_parsed["edges"])
        subgraph_score = compute_subgraph_score(ref_parsed, gen_parsed)
        global_score = compute_global_settings_score(ref_parsed, gen_parsed)
        
        # edge_coverage directly multiplies score (edges are fundamental to graphs)
        # edge_accuracy and subgraph_score are secondary (under sqrt)
        secondary_avg = (edge_accuracy + subgraph_score) / 2.0
        score = (node_coverage ** 2) * node_accuracy * edge_coverage * math.sqrt(secondary_avg) if secondary_avg > 0 else 0.0
        
        if global_score < 0.5:
            score *= (0.8 + 0.2 * global_score)
        
        eval_obj = {
            "score": score,
            "node_coverage": node_coverage,
            "node_accuracy": node_accuracy,
            "edge_coverage": edge_coverage,
            "edge_accuracy": edge_accuracy,
            "subgraph_score": subgraph_score,
            "global_score": global_score,
            "ref_node_count": len(ref_parsed["nodes"]),
            "gen_node_count": len(gen_parsed["nodes"]),
            "ref_edge_count": len(ref_parsed["edges"]),
            "gen_edge_count": len(gen_parsed["edges"]),
        }

        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

    def render_context_visual(self, context, outfile):
        """Render DOT context to a PNG image using pydot (graphviz)."""
        # Find the (first) DOT file in the context
        dot_content = None
        for fname, content in context.items():
            if fname.endswith(('.dot', '.gv')):
                dot_content = content
                break
        if dot_content is None:
            return None

        dot_content = preprocess_dot_content(dot_content)
        try:
            graphs = pydot.graph_from_dot_data(dot_content)
            if not graphs:
                return None
            graph = graphs[0]
        except Exception:
            return None

        out_path = outfile + '.png'
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        graph.write_png(out_path)
        return out_path


if __name__ == "__main__":
    with open("samples/graphviz1/basic_state/linux_kernel.dot", "r") as f:
        content = f.read()
    
    parsed = parse_dot_content(content)
    
    print("=" * 60)
    print(f"GRAPH: {parsed['graph_name']}")
    print("=" * 60)
    print(f"Nodes: {len(parsed['nodes'])}")
    print(f"Edges: {len(parsed['edges'])}")
    print(f"Subgraphs: {len(parsed['subgraphs'])}")
    print(f"Global attrs: {list(parsed['global_attrs'].keys())}")
    
    print("\n--- Sample Nodes ---")
    for i, (node_id, node) in enumerate(list(parsed['nodes'].items())[:10]):
        label = node['attrs'].get('label', node_id)
        shape = node['attrs'].get('shape', '-')
        color = node['attrs'].get('fillcolor', '-')
        sg = node.get('subgraph', '-')
        print(f"  {node_id:20} | {str(label)[:20]:20} | {str(shape):10} | {str(color)[:15]:15} | sg:{sg}")
    
    print("\n--- Sample Edges ---")
    for i, edge in enumerate(parsed['edges'][:10]):
        arrow = edge['attrs'].get('arrowhead', '-')
        color = edge['attrs'].get('color', '-')
        directed = "→" if edge['attrs'].get('_directed', True) else "—"
        print(f"  {edge['src']:15} {directed} {edge['tgt']:15} | arrow:{str(arrow):10} | color:{color}")
    
    print("\n--- Subgraphs ---")
    for sg_name, sg_data in list(parsed['subgraphs'].items())[:15]:
        node_count = len(sg_data.get('nodes', set()))
        print(f"  {sg_name:20} | {node_count} nodes")
