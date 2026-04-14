from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
from xml.etree import ElementTree as ET


# VOTable namespace
VOT_NS = "http://www.ivoa.net/xml/VOTable/v1.3"
# Also handle 1.1 and 1.2 namespaces
VOT_NAMESPACES = [
    "http://www.ivoa.net/xml/VOTable/v1.3",
    "http://www.ivoa.net/xml/VOTable/v1.2",
    "http://www.ivoa.net/xml/VOTable/v1.1",
    "",  # no namespace
]


def _ns_tag(tag, ns):
    """Build a namespaced tag."""
    if ns:
        return f"{{{ns}}}{tag}"
    return tag


def _strip_ns(tag):
    """Strip namespace from an element tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_votable_xml(content):
    """Parse VOTable XML content into a structured representation.
    
    Returns a dict with:
      - votable_attrs: dict of VOTABLE element attributes
      - resources: list of resource dicts, each containing:
          - attrs: resource attributes (ID, name, type)
          - description: text
          - info: list of INFO name/value pairs
          - coosys: list of COOSYS dicts
          - tables: list of table dicts, each containing:
              - attrs: table attributes (ID, name)
              - description: text
              - fields: list of field dicts (name, ucd, datatype, unit, etc.)
              - rows: list of row dicts mapping field_name -> value
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        return None, f"XML parse error: {e}"
    
    # Detect namespace
    ns = ""
    root_tag = root.tag
    for candidate_ns in VOT_NAMESPACES:
        if root_tag == _ns_tag("VOTABLE", candidate_ns):
            ns = candidate_ns
            break
    
    result = {
        "votable_attrs": {},
        "resources": [],
    }
    
    # Extract VOTABLE attributes (version, etc.)
    for attr_name in ["version"]:
        val = root.get(attr_name)
        if val:
            result["votable_attrs"][attr_name] = val
    
    # Find all RESOURCE elements
    for resource_elem in root.iter(_ns_tag("RESOURCE", ns)):
        resource = {
            "attrs": dict(resource_elem.attrib),
            "description": "",
            "info": [],
            "coosys": [],
            "tables": [],
        }
        
        # Resource DESCRIPTION
        desc_elem = resource_elem.find(_ns_tag("DESCRIPTION", ns))
        if desc_elem is not None and desc_elem.text:
            resource["description"] = desc_elem.text.strip()
        
        # INFO elements
        for info_elem in resource_elem.findall(_ns_tag("INFO", ns)):
            info = {
                "name": info_elem.get("name", ""),
                "value": info_elem.get("value", ""),
            }
            if info_elem.text and info_elem.text.strip():
                info["text"] = info_elem.text.strip()
            resource["info"].append(info)
        
        # COOSYS elements
        for coosys_elem in resource_elem.findall(_ns_tag("COOSYS", ns)):
            resource["coosys"].append(dict(coosys_elem.attrib))
        
        # Also check for COOSYS directly under RESOURCE's parent
        # (COOSYS can be at RESOURCE level in some VOTable versions)
        
        # TABLE elements
        for table_elem in resource_elem.iter(_ns_tag("TABLE", ns)):
            table = {
                "attrs": dict(table_elem.attrib),
                "description": "",
                "fields": [],
                "rows": [],
            }
            
            # Table DESCRIPTION
            tdesc = table_elem.find(_ns_tag("DESCRIPTION", ns))
            if tdesc is not None and tdesc.text:
                table["description"] = tdesc.text.strip()
            
            # FIELD definitions
            for field_elem in table_elem.findall(_ns_tag("FIELD", ns)):
                field = {}
                for attr_name in ["name", "ucd", "datatype", "unit", "width",
                                  "precision", "arraysize", "ref", "ID"]:
                    val = field_elem.get(attr_name)
                    if val is not None:
                        field[attr_name] = val
                # Field DESCRIPTION
                fdesc = field_elem.find(_ns_tag("DESCRIPTION", ns))
                if fdesc is not None and fdesc.text:
                    field["description"] = fdesc.text.strip()
                # VALUES element (null value)
                values_elem = field_elem.find(_ns_tag("VALUES", ns))
                if values_elem is not None:
                    null_val = values_elem.get("null")
                    if null_val:
                        field["null_value"] = null_val
                table["fields"].append(field)
            
            # DATA/TABLEDATA rows
            field_names = [f.get("name", f"col{i}") for i, f in enumerate(table["fields"])]
            data_elem = table_elem.find(_ns_tag("DATA", ns))
            if data_elem is not None:
                tabledata_elem = data_elem.find(_ns_tag("TABLEDATA", ns))
                if tabledata_elem is not None:
                    for tr_elem in tabledata_elem.findall(_ns_tag("TR", ns)):
                        td_elems = tr_elem.findall(_ns_tag("TD", ns))
                        row = {}
                        for i, td in enumerate(td_elems):
                            if i < len(field_names):
                                row[field_names[i]] = (td.text or "").strip()
                        table["rows"].append(row)
            
            resource["tables"].append(table)
        
        result["resources"].append(resource)
    
    # Also pick up COOSYS at the RESOURCE level (outside TABLE)
    for resource_elem in root.iter(_ns_tag("RESOURCE", ns)):
        for coosys_elem in resource_elem.findall(_ns_tag("COOSYS", ns)):
            coosys_dict = dict(coosys_elem.attrib)
            # Add to first resource if not already there
            if result["resources"]:
                existing_ids = {c.get("ID") for c in result["resources"][0]["coosys"]}
                if coosys_dict.get("ID") not in existing_ids:
                    result["resources"][0]["coosys"].append(coosys_dict)
    
    return result, None


def get_all_rows(parsed):
    """Extract all data rows from all tables in the parsed VOTable."""
    rows = []
    if parsed is None:
        return rows
    for resource in parsed.get("resources", []):
        for table in resource.get("tables", []):
            rows.extend(table.get("rows", []))
    return rows


def get_all_fields(parsed):
    """Extract all field definitions from all tables."""
    fields = []
    if parsed is None:
        return fields
    for resource in parsed.get("resources", []):
        for table in resource.get("tables", []):
            fields.extend(table.get("fields", []))
    return fields


def get_id_field(fields):
    """Find the primary identifier field (ucd contains meta.id or meta.main)."""
    for f in fields:
        ucd = f.get("ucd", "")
        if "meta.id" in ucd and "meta.main" in ucd:
            return f.get("name")
    # Fallback: first field
    if fields:
        return fields[0].get("name")
    return None


def normalize_value(val):
    """Normalize a cell value for comparison."""
    if val is None:
        return ""
    val = str(val).strip()
    # Normalize whitespace in coordinate strings
    val = re.sub(r'\s+', ' ', val)
    return val


def values_match(ref_val, gen_val, datatype=None):
    """Compare two cell values. Returns similarity 0-1."""
    ref_norm = normalize_value(ref_val)
    gen_norm = normalize_value(gen_val)
    
    if ref_norm == gen_norm:
        return 1.0
    
    if not ref_norm and not gen_norm:
        return 1.0
    if not ref_norm or not gen_norm:
        return 0.0
    
    # Try numeric comparison for float/double/int types
    if datatype in ("float", "double", "int", "short", "long"):
        try:
            ref_num = float(ref_norm)
            gen_num = float(gen_norm)
            if ref_num == gen_num:
                return 1.0
            if ref_num == 0:
                return 0.0
            rel_err = abs(ref_num - gen_num) / max(abs(ref_num), 1e-10)
            if rel_err < 0.001:
                return 0.98
            elif rel_err < 0.01:
                return 0.9
            elif rel_err < 0.1:
                return 0.7
            else:
                return 0.0
        except (ValueError, ZeroDivisionError):
            pass
    
    # String fuzzy match
    return SequenceMatcher(None, ref_norm, gen_norm).ratio()


def compute_field_schema_score(ref_fields, gen_fields):
    """Compare field definitions (schema) between reference and generated.
    
    Scores:
      - field_coverage: Jaccard on field names
      - field_attr_accuracy: For matched fields, how many attributes match
    """
    if not ref_fields and not gen_fields:
        return 1.0, 1.0
    if not ref_fields or not gen_fields:
        return 0.0, 0.0
    
    ref_names = {f.get("name", "") for f in ref_fields}
    gen_names = {f.get("name", "") for f in gen_fields}
    
    intersection = ref_names & gen_names
    union = ref_names | gen_names
    field_coverage = len(intersection) / len(union) if union else 1.0
    
    # For matched fields, compare attributes
    ref_by_name = {f.get("name"): f for f in ref_fields}
    gen_by_name = {f.get("name"): f for f in gen_fields}
    
    attr_scores = []
    for name in intersection:
        ref_f = ref_by_name[name]
        gen_f = gen_by_name[name]
        # Compare key attributes
        attrs_to_check = ["datatype", "ucd", "unit", "arraysize"]
        matched = 0
        total = 0
        for attr in attrs_to_check:
            ref_val = ref_f.get(attr, "")
            gen_val = gen_f.get(attr, "")
            if ref_val or gen_val:
                total += 1
                if normalize_value(ref_val) == normalize_value(gen_val):
                    matched += 1
        attr_scores.append(matched / total if total > 0 else 1.0)
    
    field_attr_accuracy = sum(attr_scores) / len(attr_scores) if attr_scores else 0.0
    
    return field_coverage, field_attr_accuracy


def compute_row_coverage_score(ref_rows, gen_rows, id_field):
    """Compute coverage of rows using the ID field as key.
    
    Returns Jaccard similarity on row IDs.
    """
    if not ref_rows and not gen_rows:
        return 1.0
    if not ref_rows or not gen_rows:
        return 0.0
    
    ref_ids = {normalize_value(r.get(id_field, "")) for r in ref_rows}
    gen_ids = {normalize_value(r.get(id_field, "")) for r in gen_rows}
    
    # Remove empty IDs
    ref_ids.discard("")
    gen_ids.discard("")
    
    if not ref_ids and not gen_ids:
        # No IDs; fall back to row count ratio
        return min(len(ref_rows), len(gen_rows)) / max(len(ref_rows), len(gen_rows))
    
    intersection = ref_ids & gen_ids
    union = ref_ids | gen_ids
    return len(intersection) / len(union) if union else 1.0


def compute_row_accuracy_score(ref_rows, gen_rows, id_field, fields):
    """For rows matched by ID, compute average cell-level accuracy."""
    if not ref_rows and not gen_rows:
        return 1.0
    if not ref_rows or not gen_rows:
        return 0.0
    
    ref_by_id = {}
    for r in ref_rows:
        rid = normalize_value(r.get(id_field, ""))
        if rid:
            ref_by_id[rid] = r
    
    gen_by_id = {}
    for r in gen_rows:
        gid = normalize_value(r.get(id_field, ""))
        if gid:
            gen_by_id[gid] = r
    
    matched_ids = set(ref_by_id.keys()) & set(gen_by_id.keys())
    if not matched_ids:
        return 0.0
    
    # Build datatype lookup
    dtype_map = {f.get("name", ""): f.get("datatype", "char") for f in fields}
    
    # Compare each matched row field by field
    row_scores = []
    for rid in matched_ids:
        ref_row = ref_by_id[rid]
        gen_row = gen_by_id[rid]
        
        all_keys = set(ref_row.keys()) | set(gen_row.keys())
        # Skip the ID field itself
        compare_keys = all_keys - {id_field}
        
        if not compare_keys:
            row_scores.append(1.0)
            continue
        
        cell_scores = []
        for key in compare_keys:
            ref_val = ref_row.get(key, "")
            gen_val = gen_row.get(key, "")
            dtype = dtype_map.get(key, "char")
            cell_scores.append(values_match(ref_val, gen_val, dtype))
        
        row_scores.append(sum(cell_scores) / len(cell_scores))
    
    return sum(row_scores) / len(row_scores)


def compute_metadata_score(ref_parsed, gen_parsed):
    """Compare VOTable metadata: resource descriptions, INFO, COOSYS."""
    scores = []
    
    ref_resources = ref_parsed.get("resources", [])
    gen_resources = gen_parsed.get("resources", [])
    
    if not ref_resources and not gen_resources:
        return 1.0
    if not ref_resources or not gen_resources:
        return 0.0
    
    # Compare first resource
    ref_res = ref_resources[0]
    gen_res = gen_resources[0]
    
    # Resource description
    ref_desc = normalize_value(ref_res.get("description", ""))
    gen_desc = normalize_value(gen_res.get("description", ""))
    if ref_desc or gen_desc:
        if ref_desc == gen_desc:
            scores.append(1.0)
        elif ref_desc and gen_desc:
            scores.append(SequenceMatcher(None, ref_desc, gen_desc).ratio())
        else:
            scores.append(0.0)
    
    # COOSYS
    ref_coosys = ref_res.get("coosys", [])
    gen_coosys = gen_res.get("coosys", [])
    if ref_coosys or gen_coosys:
        if not ref_coosys or not gen_coosys:
            scores.append(0.0)
        else:
            # Compare first COOSYS attributes
            ref_c = ref_coosys[0]
            gen_c = gen_coosys[0]
            coosys_attrs = ["system", "epoch", "ID"]
            matched = sum(1 for a in coosys_attrs
                         if ref_c.get(a, "") == gen_c.get(a, ""))
            scores.append(matched / len(coosys_attrs))
    
    # Table description
    ref_tables = ref_res.get("tables", [])
    gen_tables = gen_res.get("tables", [])
    if ref_tables and gen_tables:
        ref_tdesc = normalize_value(ref_tables[0].get("description", ""))
        gen_tdesc = normalize_value(gen_tables[0].get("description", ""))
        if ref_tdesc or gen_tdesc:
            if ref_tdesc == gen_tdesc:
                scores.append(1.0)
            elif ref_tdesc and gen_tdesc:
                scores.append(SequenceMatcher(None, ref_tdesc, gen_tdesc).ratio())
            else:
                scores.append(0.0)
    
    return sum(scores) / len(scores) if scores else 1.0


def compute_row_order_score(ref_rows, gen_rows, id_field):
    """Score how well the row ordering is preserved."""
    if not ref_rows or not gen_rows:
        return 1.0 if (not ref_rows and not gen_rows) else 0.0
    
    ref_order = [normalize_value(r.get(id_field, "")) for r in ref_rows]
    gen_order = [normalize_value(r.get(id_field, "")) for r in gen_rows]
    
    # Filter to common IDs
    common = set(ref_order) & set(gen_order)
    ref_filtered = [x for x in ref_order if x in common]
    gen_filtered = [x for x in gen_order if x in common]
    
    if not ref_filtered:
        return 1.0
    
    return SequenceMatcher(None, ref_filtered, gen_filtered).ratio()


class DomainStarcatalog(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "starcatalog"
        self.summary = "VOTable astronomical catalog data with XML schema and tabular records"
        self.description = "VOTable star catalogs"
        self.file_format = [".xml"]
        self.domain_parser = "xml.etree"
        self.category = "science"

    def parse_context(self, context):
        """Parse the VOTable XML file from a context dict.

        Returns a dict with:
          - filename: the matched .xml/.vot filename
          - content: raw file content
          - parsed: structured VOTable dict from parse_votable_xml
          - fields: list of field definitions across all tables
          - rows: list of data rows across all tables
          - id_field: name of the primary identifier field (or None)
          - resources: list of resource dicts
          - error: parse error string if parsing failed, else None
        """
        # Find the .xml/.vot file
        filename = None
        content = None
        for fn, c in context.items():
            if fn.endswith(('.xml', '.vot')):
                filename = fn
                content = c
                break
        # Fallback: first file
        if filename is None:
            filename = list(context.keys())[0]
            content = context[filename]

        parsed, err = parse_votable_xml(content)
        if err:
            return {
                "filename": filename,
                "content": content,
                "parsed": None,
                "fields": [],
                "rows": [],
                "id_field": None,
                "resources": [],
                "error": err,
            }

        fields = get_all_fields(parsed)
        rows = get_all_rows(parsed)
        id_field = get_id_field(fields)

        return {
            "filename": filename,
            "content": content,
            "parsed": parsed,
            "fields": fields,
            "rows": rows,
            "id_field": id_field,
            "resources": parsed.get("resources", []),
            "error": None,
        }

    def compute_domain_statistics(self, context):
        pc = self.parse_context(context)
        if pc["parsed"] is None:
            return {}
        return {
            "Fields": len(pc["fields"]),
            "Rows": len(pc["rows"]),
            "Resources": len(pc["resources"]),
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}
        
        # Load reference context
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(
            os.path.join(sample_folder, start_state["solution_folder"])
        )
        
        # Parse both contexts
        ref_pc = self.parse_context(reference_context)
        if ref_pc["error"]:
            return {"error": "ref_parse_error", "details": ref_pc["error"], "score": 0.0}
        
        gen_pc = self.parse_context(generated_context)
        if gen_pc["error"]:
            return {"error": "gen_parse_error", "details": gen_pc["error"], "score": 0.0}
        
        ref_parsed = ref_pc["parsed"]
        gen_parsed = gen_pc["parsed"]
        ref_fields = ref_pc["fields"]
        gen_fields = gen_pc["fields"]
        ref_rows = ref_pc["rows"]
        gen_rows = gen_pc["rows"]
        id_field = ref_pc["id_field"] or (ref_fields[0].get("name") if ref_fields else None)
        
        # Compute sub-scores
        field_coverage, field_attr_accuracy = compute_field_schema_score(ref_fields, gen_fields)
        row_coverage = compute_row_coverage_score(ref_rows, gen_rows, id_field) if id_field else 0.0
        row_accuracy = compute_row_accuracy_score(ref_rows, gen_rows, id_field, ref_fields) if id_field else 0.0
        metadata_score = compute_metadata_score(ref_parsed, gen_parsed)
        row_order = compute_row_order_score(ref_rows, gen_rows, id_field) if id_field else 1.0
        
        # Combined score: coverage-gated multiplicative formula
        # content_accuracy: quality of matched content (row data + schema)
        # auxiliary: structural/metadata factors
        # row_coverage^1.2 gates everything so missing rows degrade score proportionally
        content_accuracy = 0.70 * row_accuracy + 0.20 * field_attr_accuracy + 0.10 * field_coverage
        auxiliary = (metadata_score + row_order) / 2.0
        score = (row_coverage ** 1.2) * content_accuracy * math.sqrt(max(auxiliary, 0.0))
        
        eval_obj = {
            "score": score,
            "field_coverage": round(field_coverage, 4),
            "field_attr_accuracy": round(field_attr_accuracy, 4),
            "row_coverage": round(row_coverage, 4),
            "row_accuracy": round(row_accuracy, 4),
            "metadata_score": round(metadata_score, 4),
            "row_order": round(row_order, 4),
            "ref_fields": len(ref_fields),
            "gen_fields": len(gen_fields),
            "ref_rows": len(ref_rows),
            "gen_rows": len(gen_rows),
        }
        
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

    # ------------------------------------------------------------------ #
    #  Visual rendering
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_ra_hms(ra_str):
        """Convert RA string 'HH MM SS.ss' to decimal degrees."""
        parts = ra_str.strip().split()
        if len(parts) < 3:
            return None
        try:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return (h + m / 60.0 + s / 3600.0) * 15.0  # 1 h = 15 deg
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _parse_dec_dms(dec_str):
        """Convert Dec string '[+-]DD MM SS.s' to decimal degrees."""
        s = dec_str.strip()
        if not s:
            return None
        sign = -1 if s.startswith('-') else 1
        s = s.lstrip('+-')
        parts = s.split()
        if len(parts) < 3:
            return None
        try:
            d, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
            return sign * (d + m / 60.0 + sec / 3600.0)
        except (ValueError, IndexError):
            return None

    def render_context_visual(self, context, outfile):
        """Render a VOTable star catalog as a PNG star-chart plot.

        Stars are plotted as a scatter in (RA, Dec) with point sizes
        proportional to brightness (inverse magnitude) on a dark
        background following astronomical convention (RA increasing
        right-to-left, Dec on y-axis).
        """
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np

        pc = self.parse_context(context)
        if pc["error"] or not pc["rows"]:
            return None

        fields = pc["fields"]
        rows = pc["rows"]

        # --- Identify RA / Dec / magnitude field names by UCD ---------- #
        ra_field = dec_field = mag_field = sptype_field = None
        for f in fields:
            ucd = f.get("ucd", "")
            name = f.get("name", "")
            if "pos.eq.ra" in ucd:
                ra_field = name
            elif "pos.eq.dec" in ucd:
                dec_field = name
            elif "phot.mag" in ucd and mag_field is None:
                mag_field = name
            elif "src.spType" in ucd:
                sptype_field = name

        if ra_field is None or dec_field is None:
            return None

        # --- Determine if RA/Dec are sexagesimal strings or numeric ---- #
        ra_dtype = next((f.get("datatype", "char") for f in fields if f.get("name") == ra_field), "char")
        dec_dtype = next((f.get("datatype", "char") for f in fields if f.get("name") == dec_field), "char")

        ras, decs, mags, colors = [], [], [], []
        for row in rows:
            # Parse RA
            ra_raw = row.get(ra_field, "")
            if ra_dtype in ("float", "double"):
                try:
                    ra_val = float(ra_raw)
                except ValueError:
                    continue
            else:
                ra_val = self._parse_ra_hms(ra_raw)
            if ra_val is None:
                continue

            # Parse Dec
            dec_raw = row.get(dec_field, "")
            if dec_dtype in ("float", "double"):
                try:
                    dec_val = float(dec_raw)
                except ValueError:
                    continue
            else:
                dec_val = self._parse_dec_dms(dec_raw)
            if dec_val is None:
                continue

            # Magnitude (optional)
            mag_val = None
            if mag_field:
                try:
                    mag_val = float(row.get(mag_field, ""))
                except ValueError:
                    mag_val = None

            # Spectral-type colour heuristic
            sp = row.get(sptype_field or "", "").strip()
            color = self._spectral_color(sp)

            ras.append(ra_val)
            decs.append(dec_val)
            mags.append(mag_val)
            colors.append(color)

        if not ras:
            return None

        ras = np.array(ras)
        decs = np.array(decs)

        # --- Point sizes: brighter (lower mag) -> larger dot ----------- #
        if any(m is not None for m in mags):
            mag_arr = np.array([m if m is not None else 10.0 for m in mags])
            # Normalise to a sensible range (mag ≈ 0 large, mag ≈ 12 small)
            sizes = 10 + 200 * np.clip((12.0 - mag_arr) / 12.0, 0.05, 1.0) ** 2
        else:
            sizes = np.full(len(ras), 30.0)

        # --- Plot ------------------------------------------------------ #
        fig, ax = plt.subplots(figsize=(10, 6), facecolor='#0a0a2a')
        ax.set_facecolor('#0a0a2a')

        ax.scatter(ras, decs, s=sizes, c=colors, alpha=0.85,
                   edgecolors='none', zorder=2)

        # Astronomical convention: RA increases right-to-left
        ax.invert_xaxis()

        ax.set_xlabel('Right Ascension (deg)', color='white', fontsize=11)
        ax.set_ylabel('Declination (deg)', color='white', fontsize=11)
        ax.set_title('Star Chart', color='white', fontsize=13, pad=10)
        ax.tick_params(colors='white', labelsize=9)
        for spine in ax.spines.values():
            spine.set_color('#444466')
        ax.grid(True, color='#222244', linewidth=0.5, alpha=0.6)

        out_path = outfile + '.png'
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        return out_path

    @staticmethod
    def _spectral_color(sptype):
        """Map a spectral-type string to an approximate display colour."""
        if not sptype:
            return '#ffffff'
        letter = sptype[0].upper()
        cmap = {
            'O': '#9bb0ff',
            'B': '#aabfff',
            'A': '#cad7ff',
            'F': '#f8f7ff',
            'G': '#fff4e8',
            'K': '#ffddb4',
            'M': '#ffbd6f',
            'L': '#f7a058',
            'T': '#d47c3a',
        }
        return cmap.get(letter, '#ffffff')


if __name__ == "__main__":
    print("=" * 60)
    print("STARCATALOG EVALUATOR TESTS")
    print("=" * 60)
    
    # Test parsing
    test_xml = """<?xml version="1.0" encoding="UTF-8"?>
<VOTABLE version="1.4" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
<RESOURCE ID="test" name="TestCat" type="results">
  <DESCRIPTION>Test Catalog</DESCRIPTION>
  <COOSYS ID="J2000" system="ICRS" epoch="2000.0"/>
  <TABLE ID="main" name="main_table">
    <DESCRIPTION>Main Table</DESCRIPTION>
    <FIELD name="ID" ucd="meta.id;meta.main" datatype="int"/>
    <FIELD name="RA" ucd="pos.eq.ra" datatype="float" unit="deg"/>
    <FIELD name="Dec" ucd="pos.eq.dec" datatype="float" unit="deg"/>
    <FIELD name="Vmag" ucd="phot.mag" datatype="float" unit="mag"/>
    <DATA><TABLEDATA>
      <TR><TD>1</TD><TD>10.5</TD><TD>-20.3</TD><TD>5.4</TD></TR>
      <TR><TD>2</TD><TD>11.2</TD><TD>+15.7</TD><TD>8.1</TD></TR>
      <TR><TD>3</TD><TD>12.8</TD><TD>-45.9</TD><TD>6.7</TD></TR>
    </TABLEDATA></DATA>
  </TABLE>
</RESOURCE>
</VOTABLE>"""
    
    parsed, err = parse_votable_xml(test_xml)
    assert err is None, f"Parse error: {err}"
    assert len(get_all_fields(parsed)) == 4
    assert len(get_all_rows(parsed)) == 3
    print("Parse test: PASS")
    
    # Test self-evaluation
    task = TaskStarcatalog()
    
    # Test with actual sample if it exists
    sample_dir = "samples/starcatalog1/basic_state"
    if os.path.exists(sample_dir):
        ref_ctx = build_context_from_folder(sample_dir)
        target_state = {"state_id": "basic_state"}
        result = task.evaluate_context("starcatalog1", ref_ctx, target_state)
        print(f"Self-eval score: {result.get('score')}")
        assert result.get("score") == 1.0, f"Self-eval not 1.0: {result}"
        print("Self-evaluation test: PASS")
    else:
        print("Sample not yet created; skipping self-eval test")
    
    # Test value matching
    assert values_match("5.20", "5.20", "float") == 1.0
    assert values_match("5.20", "5.2", "float") >= 0.98
    assert values_match("K2", "K2", "char") == 1.0
    assert values_match("K2", "K3", "char") < 1.0
    assert values_match("", "", "float") == 1.0
    print("Value matching tests: PASS")
    
    print("\nAll tests passed!")
