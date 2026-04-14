from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
from rdkit import Chem
from rdkit.Chem import rdFMCS
import os, io, re
import ujson as json


# ── Parsing ──────────────────────────────────────────────────────────

def parse_sdf(sdf_text):
    """Parse SDF text into a list of (rdkit_mol, properties_dict) tuples.

    Uses RDKit's ForwardSDMolSupplier for molecular graph parsing and
    extracts all > <Key> data properties.  Returns (list, error|None).
    Each element is a dict with keys: 'rdmol', 'properties'.
    """
    supplier = Chem.ForwardSDMolSupplier(
        io.BytesIO(sdf_text.encode('utf-8')),
        sanitize=True, removeHs=True,
    )

    molecules = []
    for rdmol in supplier:
        if rdmol is None:
            continue
        props = {key: rdmol.GetProp(key) for key in rdmol.GetPropsAsDict()}
        molecules.append({"rdmol": rdmol, "properties": props})

    if not molecules:
        return [], "No valid molecule records found in SDF"
    return molecules, None


def merge_sdf_files(context):
    """Merge all .sdf files in a context dict into one SDF text."""
    merged = ""
    for filename, content in sorted(context.items()):
        if filename.endswith('.sdf'):
            merged += content
            if not content.rstrip().endswith('$$$$'):
                merged += '\n$$$$\n'
    return merged


# ── SDF header normalization ─────────────────────────────────────────

def normalize_sdf_headers(sdf_text):
    """Normalize each molecule record's header to exactly 3 lines before
    the V2000/V3000 counts line.

    LLMs commonly produce SDF files with wrong header line counts:
      - Extra annotation lines (e.g. "MW Rank 2/4 | entry #1")
      - Missing program/timestamp or comment lines
    RDKit's ForwardSDMolSupplier rejects these.  This function fixes
    the header while preserving all atom/bond/property data.
    """
    # Split into molecule records on $$$$
    parts = re.split(r'(\$\$\$\$[ \t]*\n?)', sdf_text)
    fixed_parts = []
    for part in parts:
        stripped = part.strip()
        if not stripped or stripped == '$$$$':
            fixed_parts.append(part)
            continue
        lines = part.split('\n')
        # Find the counts line (contains V2000 or V3000)
        counts_idx = None
        for j, line in enumerate(lines):
            if 'V2000' in line or 'V3000' in line:
                counts_idx = j
                break
        if counts_idx is None or counts_idx == 3:
            # No counts line found, or already correct (3 lines before it)
            fixed_parts.append(part)
            continue
        # Everything before counts_idx are header lines; we need exactly 3.
        # Keep the first non-empty line as molecule name, pad/trim to 3 lines.
        header_lines = lines[:counts_idx]
        # Find molecule name (first non-blank header line)
        name_line = ''
        for hl in header_lines:
            if hl.strip():
                name_line = hl
                break
        # Reconstruct: name, blank (program), blank (comment), then counts+rest
        fixed_header = [name_line, '', '']
        fixed_parts.append('\n'.join(fixed_header + lines[counts_idx:]))
    return ''.join(fixed_parts)


# ── Identifier / matching ────────────────────────────────────────────

_ID_KEYS = ['PUBCHEM_COMPOUND_CID', 'CID', 'ID', 'Compound_ID']
_SMILES_KEYS = ['PUBCHEM_SMILES', 'SMILES', 'PUBCHEM_OPENEYE_CAN_SMILES']


def get_mol_identifier(mol):
    """Get a stable identifier for a molecule (CID > SMILES > name)."""
    props = mol['properties']
    for key in _ID_KEYS:
        if key in props:
            return str(props[key]).strip()
    for key in _SMILES_KEYS:
        if key in props:
            return str(props[key]).strip()
    name = mol['rdmol'].GetProp('_Name') if mol['rdmol'].HasProp('_Name') else ''
    return name if name else None


def compute_molecule_coverage(ref_mols, gen_mols):
    """Fraction of reference molecules found in generated output.
    Returns (coverage_score, matched_index_pairs)."""
    if not ref_mols:
        return (1.0, []) if not gen_mols else (0.0, [])

    ref_ids = {get_mol_identifier(m): i for i, m in enumerate(ref_mols)
               if get_mol_identifier(m) is not None}
    gen_ids = {get_mol_identifier(m): i for i, m in enumerate(gen_mols)
               if get_mol_identifier(m) is not None}

    matched = [(ri, gen_ids[mid]) for mid, ri in ref_ids.items() if mid in gen_ids]
    coverage = len(matched) / len(ref_mols)
    return coverage, matched


# ── Structure score (RDKit graph comparison) ─────────────────────────

def compute_structure_score(ref_mol, gen_mol):
    """Semantic comparison of two molecular structures.

    Identical canonical SMILES → 1.0.
    Otherwise uses Maximum Common Substructure for partial credit.
    """
    ref_rd = ref_mol['rdmol']
    gen_rd = gen_mol['rdmol']

    if ref_rd is None and gen_rd is None:
        return 1.0
    if ref_rd is None or gen_rd is None:
        return 0.0

    if Chem.MolToSmiles(ref_rd) == Chem.MolToSmiles(gen_rd):
        return 1.0

    try:
        mcs = rdFMCS.FindMCS(
            [ref_rd, gen_rd],
            timeout=5,
            bondCompare=rdFMCS.BondCompare.CompareOrderExact,
            atomCompare=rdFMCS.AtomCompare.CompareElements,
        )
        if mcs.numAtoms > 0:
            max_atoms = max(ref_rd.GetNumAtoms(), gen_rd.GetNumAtoms())
            return mcs.numAtoms / max_atoms if max_atoms else 0.0
    except Exception:
        pass
    return 0.0


# ── Property score ───────────────────────────────────────────────────

def compute_property_score(ref_mol, gen_mol):
    """Compare SDF data properties between two molecules.
    Checks property presence and value accuracy."""
    ref_props = ref_mol['properties']
    gen_props = gen_mol['properties']

    if not ref_props:
        return 1.0 if not gen_props else 0.5

    ref_keys = set(ref_props.keys())
    gen_keys = set(gen_props.keys())

    key_coverage = len(ref_keys & gen_keys) / len(ref_keys) if ref_keys else 1.0

    value_scores = []
    for key in ref_keys & gen_keys:
        ref_val = str(ref_props[key]).strip()
        gen_val = str(gen_props[key]).strip()
        if ref_val == gen_val:
            value_scores.append(1.0)
        else:
            try:
                ref_num, gen_num = float(ref_val), float(gen_val)
                if ref_num == 0 and gen_num == 0:
                    value_scores.append(1.0)
                elif ref_num == 0:
                    value_scores.append(0.0)
                else:
                    rel_err = abs(ref_num - gen_num) / abs(ref_num)
                    value_scores.append(
                        1.0 if rel_err < 0.001 else
                        0.9 if rel_err < 0.01 else
                        0.5 if rel_err < 0.1 else 0.0
                    )
            except ValueError:
                value_scores.append(SequenceMatcher(None, ref_val, gen_val).ratio())

    value_accuracy = sum(value_scores) / len(value_scores) if value_scores else 0.0
    return 0.4 * key_coverage + 0.6 * value_accuracy


# ── Order score ──────────────────────────────────────────────────────

def compute_molecule_order_score(ref_mols, gen_mols):
    """Check if the molecules appear in the same order."""
    ref_ids = [x for x in (get_mol_identifier(m) for m in ref_mols) if x]
    gen_ids = [x for x in (get_mol_identifier(m) for m in gen_mols) if x]
    if not ref_ids:
        return 1.0
    return SequenceMatcher(None, ref_ids, gen_ids).ratio()


# ── Task class ───────────────────────────────────────────────────────

class DomainMolecule(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "molecule"
        self.summary = "MDL SDF molecule files with V2000 connection tables and data properties"
        self.description = "SDF molecular structures"
        self.file_format = [".sdf"]
        self.domain_parser = "rdkit"
        self.category = "science"

    def preprocess_context(self, context):
        """Normalize SDF headers in generated contexts.

        LLMs frequently produce SDF files with non-standard header line
        counts (extra annotation lines or missing program/comment lines).
        This normalizes each molecule record to the 3-line header that
        RDKit expects before the V2000 counts line.
        """
        fixed = {}
        for filename, content in context.items():
            if filename.endswith('.sdf'):
                fixed[filename] = normalize_sdf_headers(content)
            else:
                fixed[filename] = content
        return fixed

    def parse_context(self, context):
        """Parse all .sdf files in context into molecule records.

        Returns a dict with keys:
            sdf_text  – merged raw SDF text
            molecules – list of {rdmol, properties} dicts
            error     – str or None
        """
        sdf_text = merge_sdf_files(context)
        molecules, error = parse_sdf(sdf_text)
        return {
            "sdf_text": sdf_text,
            "molecules": molecules,
            "error": error,
        }

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        if parsed["error"]:
            return {"error": parsed["error"]}
        mols = parsed["molecules"]

        all_props = set()
        total_atoms = 0
        total_bonds = 0
        for mol in mols:
            all_props.update(mol['properties'].keys())
            total_atoms += mol['rdmol'].GetNumAtoms()
            total_bonds += mol['rdmol'].GetNumBonds()

        return {
            "Molecules": len(mols),
            "Total Atoms": total_atoms,
            "Total Bonds": total_bonds,
            "Properties": len(all_props),
        }

    def evaluate_context(self, sample_id, generated_context, target_state):
        if target_state["state_id"] != "basic_state":
            return {}

        # Load reference context
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)

        start_state = [s for s in sample["states"]
                       if s["state_id"] == sample["start_state"]][0]
        reference_context = build_context_from_folder(
            os.path.join(sample_folder, start_state["solution_folder"])
        )

        ref_parsed = self.parse_context(reference_context)
        if ref_parsed["error"]:
            return {"error": "ref_parse_error", "details": ref_parsed["error"], "score": 0.0}
        ref_mols = ref_parsed["molecules"]

        # Preprocess generated context (normalize SDF headers)
        generated_context = self.preprocess_context(generated_context)

        gen_parsed = self.parse_context(generated_context)
        if gen_parsed["error"]:
            return {"error": "gen_parse_error", "details": gen_parsed["error"], "score": 0.0}
        gen_mols = gen_parsed["molecules"]

        coverage, matched_pairs = compute_molecule_coverage(ref_mols, gen_mols)

        structure_scores = []
        prop_scores = []
        for ref_idx, gen_idx in matched_pairs:
            structure_scores.append(compute_structure_score(ref_mols[ref_idx], gen_mols[gen_idx]))
            prop_scores.append(compute_property_score(ref_mols[ref_idx], gen_mols[gen_idx]))

        avg_structure = sum(structure_scores) / len(structure_scores) if structure_scores else 0.0
        avg_prop = sum(prop_scores) / len(prop_scores) if prop_scores else 0.0
        order_score = compute_molecule_order_score(ref_mols, gen_mols)

        quality = 0.50 * avg_structure + 0.35 * avg_prop + 0.15 * order_score
        score = coverage * quality

        eval_obj = {
            "score": round(score, 4),
            "molecule_coverage": round(coverage, 4),
            "structure_score": round(avg_structure, 4),
            "property_score": round(avg_prop, 4),
            "order_score": round(order_score, 4),
            "ref_molecule_count": len(ref_mols),
            "gen_molecule_count": len(gen_mols),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

    def render_context_visual(self, context, outfile):
        """Render SDF molecules to a PNG grid image using RDKit."""
        from rdkit.Chem import Draw

        context = self.preprocess_context(context)
        parsed = self.parse_context(context)
        if parsed["error"] or not parsed["molecules"]:
            return None

        rdmols = [m["rdmol"] for m in parsed["molecules"] if m["rdmol"] is not None]
        if not rdmols:
            return None

        legends = []
        for m in parsed["molecules"]:
            if m["rdmol"] is None:
                continue
            ident = get_mol_identifier(m) or ""
            legends.append(ident)

        if len(rdmols) == 1:
            img = Draw.MolToImage(rdmols[0], size=(400, 400))
        else:
            img = Draw.MolsToGridImage(
                rdmols,
                molsPerRow=min(4, len(rdmols)),
                subImgSize=(300, 300),
                legends=legends,
            )

        out_path = outfile + ".png"
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        img.save(out_path)
        return out_path
