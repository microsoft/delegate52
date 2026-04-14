from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, io, warnings, ujson as json

from Bio.PDB import PDBParser as BioPDBParser


# ---------------------------------------------------------------------------
# PDB Parsing via Biopython + lightweight annotation parsing
# ---------------------------------------------------------------------------

_biopdb_parser = BioPDBParser(QUIET=True)


def _parse_structure(content):
    """Use Biopython to parse ATOM/HETATM records into a Structure object."""
    handle = io.StringIO(content)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        structure = _biopdb_parser.get_structure("pdb", handle)
    return structure


def _atoms_from_structure(structure):
    """Extract atom dicts from a Biopython Structure (matching our eval schema)."""
    atoms = []
    for model in structure:
        for chain in model:
            for residue in chain:
                hetflag, resseq, icode = residue.get_id()
                resname = residue.get_resname().strip()
                chain_id = chain.get_id()
                for atom in residue:
                    atoms.append({
                        'record': 'HETATM' if hetflag.strip() else 'ATOM',
                        'serial': atom.get_serial_number(),
                        'name': atom.get_name(),
                        'resName': resname,
                        'chainID': chain_id,
                        'resSeq': resseq,
                        'iCode': icode.strip(),
                        'x': float(atom.get_vector()[0]),
                        'y': float(atom.get_vector()[1]),
                        'z': float(atom.get_vector()[2]),
                        'occupancy': float(atom.get_occupancy()),
                        'tempFactor': float(atom.get_bfactor()),
                        'element': atom.element.strip() if atom.element else '',
                    })
        break  # first model only
    return atoms


# --- Lightweight parsers for annotation records Biopython doesn't expose ---

def _parse_seqres(content):
    """Parse SEQRES records into {chain: [residue_names]}."""
    chains = {}
    for line in content.split('\n'):
        if line[:6].strip() == 'SEQRES':
            chain = line[11].strip()
            residues = line[19:].split()
            chains.setdefault(chain, []).extend(residues)
    return chains


def _parse_helix(content):
    """Parse HELIX records into list of (chain, start_res, end_res, helix_class)."""
    helices = []
    for line in content.split('\n'):
        if line[:6].strip() != 'HELIX':
            continue
        try:
            chain = line[19].strip()
            start = int(line[21:25])
            end = int(line[33:37])
            hclass = int(line[38:40]) if line[38:40].strip() else 1
            helices.append((chain, start, end, hclass))
        except (ValueError, IndexError):
            continue
    return helices


def _parse_sheet(content):
    """Parse SHEET records into list of (sheet_id, chain, start_res, end_res)."""
    sheets = []
    for line in content.split('\n'):
        if line[:6].strip() != 'SHEET':
            continue
        try:
            sheet_id = line[11:14].strip()
            chain = line[21].strip()
            start = int(line[22:26])
            end = int(line[33:37])
            sheets.append((sheet_id, chain, start, end))
        except (ValueError, IndexError):
            continue
    return sheets


def _parse_ssbond(content):
    """Parse SSBOND records into list of ((chain1, res1), (chain2, res2))."""
    bonds = []
    for line in content.split('\n'):
        if line[:6].strip() != 'SSBOND':
            continue
        try:
            chain1 = line[15].strip()
            res1 = int(line[17:21])
            chain2 = line[29].strip()
            res2 = int(line[31:35])
            bonds.append(((chain1, res1), (chain2, res2)))
        except (ValueError, IndexError):
            continue
    return bonds


def _parse_cryst1(content):
    """Parse CRYST1 record into unit cell parameters."""
    for line in content.split('\n'):
        if line[:6].strip() != 'CRYST1':
            continue
        try:
            return {
                'a': float(line[6:15]),
                'b': float(line[15:24]),
                'c': float(line[24:33]),
                'alpha': float(line[33:40]),
                'beta': float(line[40:47]),
                'gamma': float(line[47:54]),
                'spaceGroup': line[55:66].strip(),
            }
        except (ValueError, IndexError):
            continue
    return None


def _parse_resolution(content):
    """Extract resolution from REMARK 2 records."""
    for line in content.split('\n'):
        if line[:6].strip() == 'REMARK':
            rnum = line[7:10].strip()
            if rnum == '2' and 'RESOLUTION' in line.upper():
                match = re.search(r'(\d+\.?\d*)\s*ANGSTROM', line, re.IGNORECASE)
                if match:
                    return float(match.group(1))
    return None


def _parse_header_fields(content):
    """Extract header metadata from various PDB header records."""
    header = {}
    for line in content.split('\n'):
        rec = line[:6].strip() if len(line) >= 6 else ''
        if rec == 'HEADER':
            header['classification'] = line[10:50].strip()
            header['date'] = line[50:59].strip()
            header['idCode'] = line[62:66].strip()
        elif rec == 'TITLE':
            header.setdefault('title', '')
            header['title'] += ' ' + line[10:].strip()
        elif rec == 'KEYWDS':
            header.setdefault('keywords', '')
            header['keywords'] += ' ' + line[10:].strip()
        elif rec == 'EXPDTA':
            header.setdefault('expdata', '')
            header['expdata'] += ' ' + line[10:].strip()
        elif rec == 'SOURCE':
            header.setdefault('source', '')
            header['source'] += ' ' + line[10:].strip()
        elif rec == 'COMPND':
            header.setdefault('compound', '')
            header['compound'] += ' ' + line[10:].strip()
    for k in header:
        if isinstance(header[k], str):
            header[k] = ' '.join(header[k].split())
    return header


def _realign_pdb_atom_line(line):
    """Reformat an ATOM/HETATM line to strict PDB fixed-width columns.

    LLMs often produce coordinate fields with variable spacing or extra
    decimal precision, which breaks Biopython's strict column-position
    parser.  This function keeps columns 1-30 (record type, serial, atom
    name, residue info) as-is and re-emits the numeric fields (x, y, z,
    occupancy, B-factor) in canonical 8.3f / 6.2f format.
    """
    rec = line[:6].strip()
    if rec not in ('ATOM', 'HETATM'):
        return line
    prefix = line[:30]
    rest = line[30:]
    floats = re.findall(r'[+-]?\d+\.?\d*', rest)
    if len(floats) < 3:
        return line  # not enough coords — leave unchanged
    try:
        x, y, z = float(floats[0]), float(floats[1]), float(floats[2])
        occ = float(floats[3]) if len(floats) > 3 else 1.00
        bfac = float(floats[4]) if len(floats) > 4 else 0.00
    except (ValueError, IndexError):
        return line
    # Extract 1-2 letter element symbol from trailing text
    element = ''
    after_floats = re.sub(r'[+-]?\d+\.?\d*', '', rest).strip()
    if after_floats:
        parts = after_floats.split()
        if parts:
            candidate = parts[-1].strip()
            if re.match(r'^[A-Za-z]{1,2}$', candidate):
                element = candidate.upper()
    prefix = prefix.ljust(30)
    coord_str = f"{x:8.3f}{y:8.3f}{z:8.3f}{occ:6.2f}{bfac:6.2f}"
    element_str = f"{element:>2s}" if element else "  "
    return f"{prefix}{coord_str}          {element_str}  "


def _realign_pdb_content(content):
    """Realign all ATOM/HETATM lines in PDB content to strict fixed-width format."""
    lines = content.split('\n')
    return '\n'.join(
        _realign_pdb_atom_line(line) if line[:6].strip() in ('ATOM', 'HETATM') else line
        for line in lines
    )


def parse_pdb(content):
    """Parse PDB content into a structured representation.

    Uses Biopython for robust ATOM/HETATM parsing and lightweight custom
    parsers for annotation records (SEQRES, HELIX, SHEET, SSBOND, CRYST1).
    """
    # Biopython handles the heavy lifting for atom records
    try:
        structure = _parse_structure(content)
        atoms = _atoms_from_structure(structure)
    except Exception:
        atoms = []

    return {
        'atoms': atoms,
        'seqres': _parse_seqres(content),
        'helices': _parse_helix(content),
        'sheets': _parse_sheet(content),
        'ssbonds': _parse_ssbond(content),
        'cryst1': _parse_cryst1(content),
        'header': _parse_header_fields(content),
        'resolution': _parse_resolution(content),
    }


# ---------------------------------------------------------------------------
# Merge helper: concatenate all .pdb content in a context
# ---------------------------------------------------------------------------

def merge_all_pdb(context):
    merged = ""
    for filename, content in context.items():
        if filename.endswith('.pdb'):
            merged += content + "\n"
    return merged


# ---------------------------------------------------------------------------
# Scoring Functions
# ---------------------------------------------------------------------------

def compute_atom_coverage_score(ref_atoms, gen_atoms):
    """Jaccard overlap of atom fingerprints (chain + resSeq + atom name)."""
    def fingerprint(atom):
        return (atom['chainID'], atom['resSeq'], atom['resName'], atom['name'])

    ref_fps = set(fingerprint(a) for a in ref_atoms)
    gen_fps = set(fingerprint(a) for a in gen_atoms)

    if not ref_fps and not gen_fps:
        return 1.0
    if not ref_fps or not gen_fps:
        return 0.0

    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union


def compute_coordinate_accuracy(ref_atoms, gen_atoms):
    """Average coordinate accuracy for matched atoms (tolerance-based)."""
    def key(atom):
        return (atom['chainID'], atom['resSeq'], atom['resName'], atom['name'])

    ref_map = {key(a): a for a in ref_atoms}
    gen_map = {key(a): a for a in gen_atoms}

    common_keys = set(ref_map) & set(gen_map)
    if not common_keys:
        return 1.0 if (not ref_atoms and not gen_atoms) else 0.0

    deviations = []
    for k in common_keys:
        r, g = ref_map[k], gen_map[k]
        dx = r['x'] - g['x']
        dy = r['y'] - g['y']
        dz = r['z'] - g['z']
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        deviations.append(dist)

    if not deviations:
        return 0.0

    # Score based on distance: perfect ≤ 0.01 Å, zero at ≥ 2.0 Å
    scores = [max(0, 1 - d / 2.0) for d in deviations]
    return sum(scores) / len(scores)


def compute_bfactor_accuracy(ref_atoms, gen_atoms):
    """Accuracy of B-factor (temperature factor) values for matched atoms."""
    def key(atom):
        return (atom['chainID'], atom['resSeq'], atom['resName'], atom['name'])

    ref_map = {key(a): a for a in ref_atoms}
    gen_map = {key(a): a for a in gen_atoms}

    common_keys = set(ref_map) & set(gen_map)
    if not common_keys:
        return 1.0 if (not ref_atoms and not gen_atoms) else 0.0

    scores = []
    for k in common_keys:
        r_bf = ref_map[k]['tempFactor']
        g_bf = gen_map[k]['tempFactor']
        diff = abs(r_bf - g_bf)
        # Perfect ≤ 0.01, zero at ≥ 20.0
        scores.append(max(0, 1 - diff / 20.0))

    return sum(scores) / len(scores) if scores else 0.0


def compute_seqres_score(ref_seqres, gen_seqres):
    """Sequence matching between SEQRES records."""
    if not ref_seqres and not gen_seqres:
        return 1.0
    if not ref_seqres or not gen_seqres:
        return 0.0

    all_chains = set(ref_seqres) | set(gen_seqres)
    chain_scores = []
    for chain in all_chains:
        ref_seq = ref_seqres.get(chain, [])
        gen_seq = gen_seqres.get(chain, [])
        if not ref_seq and not gen_seq:
            chain_scores.append(1.0)
        elif not ref_seq or not gen_seq:
            chain_scores.append(0.0)
        else:
            chain_scores.append(SequenceMatcher(None, ref_seq, gen_seq).ratio())

    return sum(chain_scores) / len(chain_scores) if chain_scores else 0.0


def compute_secondary_structure_score(ref_helices, ref_sheets, gen_helices, gen_sheets):
    """Compare secondary structure annotations."""
    def helix_set(helices):
        return set((h[0], h[1], h[2]) for h in helices)  # chain, start, end

    def sheet_set(sheets):
        return set((s[0], s[1], s[2], s[3]) for s in sheets)  # id, chain, start, end

    ref_h = helix_set(ref_helices)
    gen_h = helix_set(gen_helices)
    ref_s = sheet_set(ref_sheets)
    gen_s = sheet_set(gen_sheets)

    # Helix score (Jaccard)
    if not ref_h and not gen_h:
        h_score = 1.0
    elif not ref_h or not gen_h:
        h_score = 0.0
    else:
        h_score = len(ref_h & gen_h) / len(ref_h | gen_h)

    # Sheet score (Jaccard)
    if not ref_s and not gen_s:
        s_score = 1.0
    elif not ref_s or not gen_s:
        s_score = 0.0
    else:
        s_score = len(ref_s & gen_s) / len(ref_s | gen_s)

    # Weight by count (only include a component if at least one side has data)
    n_h = max(len(ref_h), len(gen_h))
    n_s = max(len(ref_s), len(gen_s))
    total = n_h + n_s
    if total == 0:
        return 1.0  # no secondary structure in either → trivially matched
    return (h_score * n_h + s_score * n_s) / total


def compute_ssbond_score(ref_bonds, gen_bonds):
    """Compare disulfide bond annotations."""
    def bond_set(bonds):
        # Normalize: order the two cysteines consistently
        s = set()
        for b in bonds:
            pair = tuple(sorted([b[0], b[1]]))
            s.add(pair)
        return s

    ref_s = bond_set(ref_bonds)
    gen_s = bond_set(gen_bonds)

    if not ref_s and not gen_s:
        return 1.0
    if not ref_s or not gen_s:
        return 0.0
    return len(ref_s & gen_s) / len(ref_s | gen_s)


def compute_metadata_score(ref_parsed, gen_parsed):
    """Compare crystallographic and header metadata."""
    scores = []

    # CRYST1 comparison
    rc = ref_parsed['cryst1']
    gc = gen_parsed['cryst1']
    if rc and gc:
        # Compare unit cell parameters
        params_match = 0
        params_total = 0
        for k in ['a', 'b', 'c', 'alpha', 'beta', 'gamma']:
            if k in rc and k in gc:
                params_total += 1
                if abs(rc[k] - gc[k]) < 0.1:
                    params_match += 1
        cell_score = params_match / params_total if params_total > 0 else 0.0
        # Space group
        sg_score = 1.0 if rc.get('spaceGroup', '') == gc.get('spaceGroup', '') else 0.0
        scores.append(0.7 * cell_score + 0.3 * sg_score)
    elif not rc and not gc:
        scores.append(1.0)
    else:
        scores.append(0.0)

    # Resolution comparison
    rr = ref_parsed['resolution']
    gr = gen_parsed['resolution']
    if rr is not None and gr is not None:
        scores.append(1.0 if abs(rr - gr) < 0.05 else 0.5 if abs(rr - gr) < 0.2 else 0.0)
    elif rr is None and gr is None:
        scores.append(1.0)
    else:
        scores.append(0.0)

    # Header fields comparison
    ref_h = ref_parsed['header']
    gen_h = gen_parsed['header']
    important_fields = ['classification', 'idCode', 'title']
    h_match = 0
    h_total = 0
    for field in important_fields:
        rv = ref_h.get(field, '')
        gv = gen_h.get(field, '')
        if rv or gv:
            h_total += 1
            if rv.strip().lower() == gv.strip().lower():
                h_match += 1
    if h_total > 0:
        scores.append(h_match / h_total)
    else:
        scores.append(1.0)

    return sum(scores) / len(scores) if scores else 1.0


# ---------------------------------------------------------------------------
# Task Class
# ---------------------------------------------------------------------------

class DomainProtein(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "protein"
        self.summary = "PDB protein structure files with atomic coordinates, sequence, and annotations"
        self.description = "PDB protein structures"
        self.file_format = [".pdb"]
        self.domain_parser = "biopython"
        self.category = "science"

    def preprocess_context(self, context):
        """Realign ATOM/HETATM lines to strict PDB fixed-width columns.

        LLMs frequently produce coordinate fields with variable spacing or
        extra decimal precision, which breaks Biopython's column-position
        parser.  This normalises each ATOM/HETATM line to canonical format
        while leaving all other records untouched.
        """
        cleaned = {}
        for filename, content in context.items():
            if filename.endswith('.pdb'):
                cleaned[filename] = _realign_pdb_content(content)
            else:
                cleaned[filename] = content
        return cleaned

    def parse_context(self, context):
        """Parse all PDB files in context into a structured dict.

        Returns dict with keys: atoms, seqres, helices, sheets, ssbonds,
        cryst1, header, resolution.
        """
        context = self.preprocess_context(context)
        pdb = merge_all_pdb(context)
        return parse_pdb(pdb)

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        n_residues = sum(len(seq) for seq in parsed['seqres'].values())
        return {
            "Atoms": len(parsed['atoms']),
            "Residues": n_residues,
            "Chains": len(parsed['seqres']),
            "Helices": len(parsed['helices']),
            "Sheets": len(parsed['sheets']),
            "Disulfides": len(parsed['ssbonds']),
            "Resolution": f"{parsed['resolution']} Å" if parsed['resolution'] else "N/A",
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

        ref = self.parse_context(reference_context)
        gen = self.parse_context(generated_context)

        # Component scores
        atom_coverage = compute_atom_coverage_score(ref['atoms'], gen['atoms'])
        coord_accuracy = compute_coordinate_accuracy(ref['atoms'], gen['atoms'])
        bfactor_accuracy = compute_bfactor_accuracy(ref['atoms'], gen['atoms'])
        seqres_score = compute_seqres_score(ref['seqres'], gen['seqres'])
        ss_score = compute_secondary_structure_score(
            ref['helices'], ref['sheets'], gen['helices'], gen['sheets']
        )
        ssbond_score = compute_ssbond_score(ref['ssbonds'], gen['ssbonds'])
        metadata_score = compute_metadata_score(ref, gen)

        # Weighted aggregate
        # atom_coverage gates overall score so missing atoms are heavily penalised
        # Quality: how accurate is the content that IS present
        quality = (
            0.34 * coord_accuracy +
            0.13 * bfactor_accuracy +
            0.20 * seqres_score +
            0.13 * ss_score +
            0.07 * ssbond_score +
            0.13 * metadata_score
        )
        score = atom_coverage * quality

        eval_obj = {
            "score": score,
            "atom_coverage_score": round(atom_coverage, 4),
            "coordinate_accuracy_score": round(coord_accuracy, 4),
            "bfactor_accuracy_score": round(bfactor_accuracy, 4),
            "seqres_score": round(seqres_score, 4),
            "secondary_structure_score": round(ss_score, 4),
            "ssbond_score": round(ssbond_score, 4),
            "metadata_score": round(metadata_score, 4),
            "ref_atom_count": len(ref['atoms']),
            "gen_atom_count": len(gen['atoms']),
            "ref_residues": sum(len(s) for s in ref['seqres'].values()),
            "gen_residues": sum(len(s) for s in gen['seqres'].values()),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

    def render_context_visual(self, context, outfile):
        """Render PDB protein structure as a ball-and-stick model using biotite."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import tempfile

        try:
            import biotite.structure as bst
            import biotite.structure.io.pdb as bpdb
            import biotite.structure.graphics as gfx
        except ImportError:
            return None

        # Get raw PDB text
        all_text = "\n".join(context.values()) if isinstance(context, dict) else str(context)

        # Write to temp file for biotite's PDB reader
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".pdb", delete=False) as tmp:
                tmp.write(all_text)
                tmp_path = tmp.name
            pdb_file = bpdb.PDBFile.read(tmp_path)
            structure = bpdb.get_structure(pdb_file, model=1)
        except Exception:
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        if len(structure) == 0:
            return None

        # Infer bonds from standard residue templates
        try:
            structure.bonds = bst.connect_via_residue_names(structure)
        except Exception:
            return None

        if structure.bonds is None or structure.bonds.get_bond_count() == 0:
            return None

        # CPK element colours (RGB arrays for biotite)
        CPK = {
            "C": [0.50, 0.50, 0.50], "N": [0.19, 0.31, 0.97],
            "O": [1.00, 0.05, 0.05], "S": [1.00, 1.00, 0.19],
            "H": [0.90, 0.90, 0.90], "P": [1.00, 0.50, 0.00],
            "FE": [0.88, 0.40, 0.20], "ZN": [0.49, 0.50, 0.69],
            "MG": [0.13, 0.55, 0.13], "CA": [0.24, 1.00, 0.00],
            "CU": [0.78, 0.50, 0.20],
        }
        DEFAULT = [1.00, 0.08, 0.58]
        colors = np.array([CPK.get(e.upper(), DEFAULT) for e in structure.element])

        fig = plt.figure(figsize=(7, 7))
        ax = fig.add_subplot(111, projection="3d")
        try:
            gfx.plot_ball_and_stick_model(
                ax, structure, colors, ball_size=80, line_width=0.8
            )
        except Exception:
            plt.close(fig)
            return None

        fig.tight_layout()
        out_path = outfile + ".png"
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return out_path
