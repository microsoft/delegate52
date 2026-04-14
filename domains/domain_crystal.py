from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json, tempfile
import CifFile


# ---------------------------------------------------------------------------
# CIF Parser — uses PyCifRW for robust Crystallographic Information File parsing
# ---------------------------------------------------------------------------

def _parse_numeric(val_str):
    """Parse a numeric CIF value, stripping uncertainty in parentheses.
    E.g. '5.2584(8)' -> 5.2584, '72.69(2)' -> 72.69
    Returns None if not numeric.
    """
    if val_str is None or val_str == '?' or val_str == '.':
        return None
    val_str = str(val_str).strip()
    # Strip uncertainty notation: 1.234(5) -> 1.234
    val_str = re.sub(r'\([^)]*\)', '', val_str)
    try:
        return float(val_str)
    except (ValueError, TypeError):
        return None


def _get(block, tag, default=None):
    """Safely get a value from a CifBlock, returning default if missing."""
    try:
        return block[tag]
    except KeyError:
        return default


def _get_scalar(block, tag, default=''):
    """Get a scalar string value from a CifBlock."""
    val = _get(block, tag)
    if val is None or val == '?' or val == '.':
        return default
    if isinstance(val, list):
        return val[0] if val else default
    return str(val)


def _get_loop_rows(block, tags):
    """Get loop data as a list of dicts keyed by tag names.
    
    PyCifRW returns loop columns as lists; this zips them into row dicts.
    """
    cols = {}
    for tag in tags:
        col = _get(block, tag)
        if col is not None and isinstance(col, list):
            cols[tag] = col
    if not cols:
        return []
    
    n_rows = min(len(v) for v in cols.values())
    rows = []
    for i in range(n_rows):
        row = {tag: cols[tag][i] for tag in cols}
        rows.append(row)
    return rows


def parse_cif(text):
    """Parse CIF text using PyCifRW, returning (block_name, CifBlock) or (None, None) on failure."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cif', delete=False) as tmp:
        tmp.write(text)
        tmp_path = tmp.name
    try:
        cf = CifFile.ReadCif(tmp_path)
    except Exception as e:
        return None, None, str(e)
    finally:
        os.unlink(tmp_path)
    
    if cf is None or not cf.keys():
        return None, None, "No data blocks found"
    
    block_name = list(cf.keys())[0]
    return block_name, cf[block_name], None


# ---------------------------------------------------------------------------
# Extractors: pull structured domain objects from CifBlock
# ---------------------------------------------------------------------------

def extract_cell_params(block):
    """Extract unit cell parameters. Returns dict or None."""
    params = {}
    for key in ['_cell_length_a', '_cell_length_b', '_cell_length_c',
                '_cell_angle_alpha', '_cell_angle_beta', '_cell_angle_gamma',
                '_cell_volume', '_cell_formula_units_z',
                '_cell_measurement_temperature']:
        val = _parse_numeric(_get_scalar(block, key))
        if val is not None:
            params[key] = val
    return params if params else None


def extract_symmetry(block):
    """Extract symmetry information."""
    result = {
        'space_group': _get_scalar(block, '_symmetry_space_group_name_h-m'),
        'hall_symbol': _get_scalar(block, '_symmetry_space_group_name_hall'),
        'it_number': _parse_numeric(_get_scalar(block, '_space_group_it_number')),
        'cell_setting': _get_scalar(block, '_symmetry_cell_setting'),
    }
    
    # Symmetry operations from loop
    ops_col = _get(block, '_symmetry_equiv_pos_as_xyz')
    if ops_col and isinstance(ops_col, list):
        result['operations'] = sorted(
            op.lower().replace(' ', '') for op in ops_col if op
        )
    
    return result


def extract_atom_sites(block):
    """Extract atom site data. Returns list of dicts."""
    tags = ['_atom_site_label', '_atom_site_type_symbol',
            '_atom_site_fract_x', '_atom_site_fract_y', '_atom_site_fract_z',
            '_atom_site_u_iso_or_equiv', '_atom_site_adp_type', '_atom_site_occupancy']
    rows = _get_loop_rows(block, tags)
    
    sites = []
    for row in rows:
        site = {
            'label': row.get('_atom_site_label', ''),
            'type_symbol': row.get('_atom_site_type_symbol', ''),
            'fract_x': _parse_numeric(row.get('_atom_site_fract_x')),
            'fract_y': _parse_numeric(row.get('_atom_site_fract_y')),
            'fract_z': _parse_numeric(row.get('_atom_site_fract_z')),
            'u_iso': _parse_numeric(row.get('_atom_site_u_iso_or_equiv')),
            'adp_type': row.get('_atom_site_adp_type', ''),
            'occupancy': _parse_numeric(row.get('_atom_site_occupancy')),
        }
        sites.append(site)
    return sites


def extract_aniso_params(block):
    """Extract anisotropic displacement parameters. Returns dict keyed by atom label."""
    tags = ['_atom_site_aniso_label',
            '_atom_site_aniso_u_11', '_atom_site_aniso_u_22', '_atom_site_aniso_u_33',
            '_atom_site_aniso_u_23', '_atom_site_aniso_u_13', '_atom_site_aniso_u_12']
    rows = _get_loop_rows(block, tags)
    
    aniso = {}
    for row in rows:
        label = row.get('_atom_site_aniso_label', '')
        params = {}
        for key in ['_atom_site_aniso_u_11', '_atom_site_aniso_u_22', '_atom_site_aniso_u_33',
                    '_atom_site_aniso_u_23', '_atom_site_aniso_u_13', '_atom_site_aniso_u_12']:
            val = _parse_numeric(row.get(key))
            if val is not None:
                params[key.split('_')[-1]] = val
        aniso[label] = params
    return aniso


def extract_bonds(block):
    """Extract bond geometry. Returns list of dicts."""
    tags = ['_geom_bond_atom_site_label_1', '_geom_bond_atom_site_label_2',
            '_geom_bond_distance', '_geom_bond_site_symmetry_2']
    rows = _get_loop_rows(block, tags)
    
    bonds = []
    for row in rows:
        bond = {
            'atom1': row.get('_geom_bond_atom_site_label_1', ''),
            'atom2': row.get('_geom_bond_atom_site_label_2', ''),
            'distance': _parse_numeric(row.get('_geom_bond_distance')),
            'symmetry': row.get('_geom_bond_site_symmetry_2', '.'),
        }
        bonds.append(bond)
    return bonds


def extract_angles(block):
    """Extract bond angles. Returns list of dicts."""
    tags = ['_geom_angle_atom_site_label_1', '_geom_angle_atom_site_label_2',
            '_geom_angle_atom_site_label_3', '_geom_angle',
            '_geom_angle_site_symmetry_1', '_geom_angle_site_symmetry_3']
    rows = _get_loop_rows(block, tags)
    
    angles = []
    for row in rows:
        angle = {
            'atom1': row.get('_geom_angle_atom_site_label_1', ''),
            'atom2': row.get('_geom_angle_atom_site_label_2', ''),
            'atom3': row.get('_geom_angle_atom_site_label_3', ''),
            'angle': _parse_numeric(row.get('_geom_angle')),
            'symmetry_1': row.get('_geom_angle_site_symmetry_1', '.'),
            'symmetry_3': row.get('_geom_angle_site_symmetry_3', '.'),
        }
        angles.append(angle)
    return angles


def extract_hbonds(block):
    """Extract hydrogen bonds. Returns list of dicts."""
    tags = ['_geom_hbond_atom_site_label_d', '_geom_hbond_atom_site_label_h',
            '_geom_hbond_atom_site_label_a', '_geom_hbond_distance_dh',
            '_geom_hbond_distance_ha', '_geom_hbond_distance_da',
            '_geom_hbond_angle_dha', '_geom_hbond_site_symmetry_a']
    rows = _get_loop_rows(block, tags)
    
    hbonds = []
    for row in rows:
        hb = {
            'donor': row.get('_geom_hbond_atom_site_label_d', ''),
            'hydrogen': row.get('_geom_hbond_atom_site_label_h', ''),
            'acceptor': row.get('_geom_hbond_atom_site_label_a', ''),
            'dh_dist': _parse_numeric(row.get('_geom_hbond_distance_dh')),
            'ha_dist': _parse_numeric(row.get('_geom_hbond_distance_ha')),
            'da_dist': _parse_numeric(row.get('_geom_hbond_distance_da')),
            'angle': _parse_numeric(row.get('_geom_hbond_angle_dha')),
            'symmetry_a': row.get('_geom_hbond_site_symmetry_a', '.'),
        }
        hbonds.append(hb)
    return hbonds


def extract_metadata(block):
    """Extract publication and experimental metadata."""
    meta = {}
    
    for key in ['_chemical_formula_sum', '_chemical_formula_weight',
                '_journal_name_full', '_journal_year', '_journal_volume',
                '_journal_page_first', '_journal_page_last',
                '_exptl_crystal_colour', '_exptl_crystal_density_diffrn',
                '_diffrn_radiation_type', '_diffrn_radiation_wavelength',
                '_refine_ls_r_factor_gt', '_refine_ls_wr_factor_ref',
                '_refine_ls_goodness_of_fit_ref']:
        val = _get_scalar(block, key)
        if val:
            meta[key] = val
    
    # Authors from loop
    authors = _get(block, '_publ_author_name')
    if authors and isinstance(authors, list):
        meta['authors'] = list(authors)
    
    # Title
    title = _get_scalar(block, '_publ_section_title')
    if title:
        meta['title'] = title.strip()
    
    return meta


def extract_scattering_factors(block):
    """Extract atomic scattering factors from _atom_type loop."""
    tags = ['_atom_type_symbol', '_atom_type_scat_dispersion_real',
            '_atom_type_scat_dispersion_imag']
    rows = _get_loop_rows(block, tags)
    
    factors = {}
    for row in rows:
        symbol = row.get('_atom_type_symbol', '')
        f_real = _parse_numeric(row.get('_atom_type_scat_dispersion_real'))
        f_imag = _parse_numeric(row.get('_atom_type_scat_dispersion_imag'))
        factors[symbol] = {'f_real': f_real, 'f_imag': f_imag}
    return factors


# ---------------------------------------------------------------------------
# Structured representation: combine all extracted data
# ---------------------------------------------------------------------------

def build_crystal_structure(text):
    """Parse CIF text into a complete crystal structure representation."""
    block_name, block, error = parse_cif(text)
    
    if error:
        return {'parse_error': error}
    
    return {
        'data_block': block_name,
        'cell_params': extract_cell_params(block),
        'symmetry': extract_symmetry(block),
        'atom_sites': extract_atom_sites(block),
        'aniso_params': extract_aniso_params(block),
        'bonds': extract_bonds(block),
        'angles': extract_angles(block),
        'hbonds': extract_hbonds(block),
        'metadata': extract_metadata(block),
        'scattering_factors': extract_scattering_factors(block),
        'parse_error': None,
    }


# ---------------------------------------------------------------------------
# Comparison / scoring helpers
# ---------------------------------------------------------------------------

def compare_cell_params(ref_cell, gen_cell):
    """Compare cell parameters. Returns score 0-1."""
    if not ref_cell and not gen_cell:
        return 1.0
    if not ref_cell or not gen_cell:
        return 0.0
    
    scores = []
    for key in ['_cell_length_a', '_cell_length_b', '_cell_length_c',
                '_cell_angle_alpha', '_cell_angle_beta', '_cell_angle_gamma']:
        ref_val = ref_cell.get(key)
        gen_val = gen_cell.get(key)
        if ref_val is not None and gen_val is not None:
            if ref_val == 0:
                scores.append(1.0 if gen_val == 0 else 0.0)
            else:
                rel_err = abs(ref_val - gen_val) / abs(ref_val)
                if rel_err < 0.001:
                    scores.append(1.0)
                elif rel_err < 0.01:
                    scores.append(0.9)
                elif rel_err < 0.05:
                    scores.append(0.5)
                else:
                    scores.append(0.0)
        elif ref_val is not None:
            scores.append(0.0)
    
    return sum(scores) / len(scores) if scores else 1.0


def compare_symmetry(ref_sym, gen_sym):
    """Compare symmetry information. Returns score 0-1."""
    scores = []
    
    # Space group name (critical)
    ref_sg = ref_sym.get('space_group', '').strip().lower().replace(' ', '')
    gen_sg = gen_sym.get('space_group', '').strip().lower().replace(' ', '')
    if ref_sg and gen_sg:
        scores.append(1.0 if ref_sg == gen_sg else 0.0)
    elif ref_sg:
        scores.append(0.0)
    
    # Symmetry operations
    ref_ops = ref_sym.get('operations', [])
    gen_ops = gen_sym.get('operations', [])
    if ref_ops:
        ref_set = set(ref_ops)
        gen_set = set(gen_ops)
        if ref_set or gen_set:
            jaccard = len(ref_set & gen_set) / len(ref_set | gen_set)
            scores.append(jaccard)
    
    return sum(scores) / len(scores) if scores else 1.0


def compare_atom_sites(ref_sites, gen_sites):
    """Compare atom sites using recall-based per-atom scoring.
    
    For each reference atom, checks whether it exists in the generated output
    and scores coordinate/property accuracy. Missing atoms score 0.
    Returns (atom_score, atom_recall).
    """
    if not ref_sites and not gen_sites:
        return 1.0, 1.0
    if not ref_sites:
        return 0.5, 1.0   # nothing to verify against
    if not gen_sites:
        return 0.0, 0.0
    
    ref_by_label = {s['label']: s for s in ref_sites}
    gen_by_label = {s['label']: s for s in gen_sites}
    
    per_atom_scores = []
    matched = 0
    
    for label, ref in ref_by_label.items():
        gen = gen_by_label.get(label)
        if gen is None:
            per_atom_scores.append(0.0)
            continue
        
        matched += 1
        
        # Coordinate accuracy
        coord_scores = []
        for key in ['fract_x', 'fract_y', 'fract_z']:
            rv = ref.get(key)
            gv = gen.get(key)
            if rv is not None and gv is not None:
                diff = abs(rv - gv)
                if diff < 0.001:
                    coord_scores.append(1.0)
                elif diff < 0.005:
                    coord_scores.append(0.9)
                elif diff < 0.01:
                    coord_scores.append(0.7)
                elif diff < 0.03:
                    coord_scores.append(0.3)
                elif diff < 0.05:
                    coord_scores.append(0.1)
                else:
                    coord_scores.append(0.0)
            elif rv is not None:
                coord_scores.append(0.0)
        coord_acc = sum(coord_scores) / len(coord_scores) if coord_scores else 1.0
        
        # Property accuracy (type_symbol, occupancy)
        prop_scores = []
        ref_ts = (ref.get('type_symbol') or '').strip()
        gen_ts = (gen.get('type_symbol') or '').strip()
        if ref_ts:
            prop_scores.append(1.0 if ref_ts == gen_ts else 0.0)
        ref_occ = ref.get('occupancy')
        gen_occ = gen.get('occupancy')
        if ref_occ is not None and gen_occ is not None:
            prop_scores.append(1.0 if abs(ref_occ - gen_occ) < 0.01 else 0.0)
        prop_acc = sum(prop_scores) / len(prop_scores) if prop_scores else 1.0
        
        per_atom_scores.append(coord_acc * 0.7 + prop_acc * 0.3)
    
    atom_score = sum(per_atom_scores) / len(per_atom_scores) if per_atom_scores else 0.0
    atom_recall = matched / len(ref_by_label) if ref_by_label else 1.0
    
    # Penalty for spurious extra atoms
    n_extra = len(set(gen_by_label.keys()) - set(ref_by_label.keys()))
    if n_extra > 0:
        extra_penalty = max(0.0, 1.0 - n_extra / (len(ref_by_label) * 2))
        atom_score *= extra_penalty
    
    return atom_score, atom_recall


def compare_aniso(ref_aniso, gen_aniso):
    """Compare anisotropic displacement parameters. Recall-based scoring.
    
    Each reference atom's aniso params are scored; missing atoms get 0.
    """
    if not ref_aniso and not gen_aniso:
        return 1.0
    if not ref_aniso:
        return 0.5
    if not gen_aniso:
        return 0.0
    
    per_atom_scores = []
    for label, ref_p in ref_aniso.items():
        gen_p = gen_aniso.get(label)
        if gen_p is None:
            per_atom_scores.append(0.0)
            continue
        
        pscores = []
        for key in ['11', '22', '33', '23', '13', '12']:
            rv = ref_p.get(key)
            gv = gen_p.get(key)
            if rv is not None and gv is not None:
                diff = abs(rv - gv)
                if diff < 0.0005:
                    pscores.append(1.0)
                elif diff < 0.005:
                    pscores.append(0.8)
                else:
                    pscores.append(0.0)
        per_atom_scores.append(sum(pscores) / len(pscores) if pscores else 0.0)
    
    return sum(per_atom_scores) / len(per_atom_scores) if per_atom_scores else 0.0


def compare_bonds(ref_bonds, gen_bonds):
    """Compare bond geometry. Recall-based: each ref bond scored, missing = 0."""
    if not ref_bonds and not gen_bonds:
        return 1.0
    if not ref_bonds:
        return 0.5
    if not gen_bonds:
        return 0.0
    
    def bond_key(b):
        a1 = b.get('atom1', '')
        a2 = b.get('atom2', '')
        sym = b.get('symmetry', '.')
        return (min(a1, a2), max(a1, a2), sym)
    
    gen_by_key = {}
    for b in gen_bonds:
        gen_by_key[bond_key(b)] = b
    
    per_bond_scores = []
    for rb in ref_bonds:
        gb = gen_by_key.get(bond_key(rb))
        if gb is None:
            per_bond_scores.append(0.0)
            continue
        
        rd = rb.get('distance')
        gd = gb.get('distance')
        if rd is not None and gd is not None:
            diff = abs(rd - gd)
            if diff < 0.005:
                per_bond_scores.append(1.0)
            elif diff < 0.02:
                per_bond_scores.append(0.8)
            elif diff < 0.1:
                per_bond_scores.append(0.5)
            else:
                per_bond_scores.append(0.1)
        else:
            per_bond_scores.append(0.5)  # found but no distance to compare
    
    return sum(per_bond_scores) / len(per_bond_scores) if per_bond_scores else 0.0


def compare_angles(ref_angles, gen_angles):
    """Compare angle geometry. Recall-based: each ref angle scored, missing = 0."""
    if not ref_angles and not gen_angles:
        return 1.0
    if not ref_angles:
        return 0.5
    if not gen_angles:
        return 0.0
    
    def angle_key(a):
        return (a.get('atom1', ''), a.get('atom2', ''), a.get('atom3', ''),
                a.get('symmetry_1', '.'), a.get('symmetry_3', '.'))
    
    gen_by_key = {angle_key(a): a for a in gen_angles}
    
    per_angle_scores = []
    for ra in ref_angles:
        ga = gen_by_key.get(angle_key(ra))
        if ga is None:
            per_angle_scores.append(0.0)
            continue
        
        rv = ra.get('angle')
        gv = ga.get('angle')
        if rv is not None and gv is not None:
            diff = abs(rv - gv)
            if diff < 0.1:
                per_angle_scores.append(1.0)
            elif diff < 1.0:
                per_angle_scores.append(0.8)
            elif diff < 5.0:
                per_angle_scores.append(0.3)
            else:
                per_angle_scores.append(0.0)
        else:
            per_angle_scores.append(0.5)
    
    return sum(per_angle_scores) / len(per_angle_scores) if per_angle_scores else 0.0


def compare_hbonds(ref_hb, gen_hb):
    """Compare hydrogen bonds. Recall-based with value checking."""
    if not ref_hb and not gen_hb:
        return 1.0
    if not ref_hb:
        return 0.5
    if not gen_hb:
        return 0.0
    
    def hb_key(h):
        return (h.get('donor', ''), h.get('hydrogen', ''), h.get('acceptor', ''),
                h.get('symmetry_a', '.'))
    
    gen_by_key = {hb_key(h): h for h in gen_hb}
    
    per_hb_scores = []
    for rh in ref_hb:
        gh = gen_by_key.get(hb_key(rh))
        if gh is None:
            per_hb_scores.append(0.0)
            continue
        
        sub_scores = []
        for field in ['dh_dist', 'ha_dist', 'da_dist']:
            rv = rh.get(field)
            gv = gh.get(field)
            if rv is not None and gv is not None:
                diff = abs(rv - gv)
                sub_scores.append(1.0 if diff < 0.01 else (0.5 if diff < 0.05 else 0.0))
        
        rv = rh.get('angle')
        gv = gh.get('angle')
        if rv is not None and gv is not None:
            diff = abs(rv - gv)
            sub_scores.append(1.0 if diff < 1.0 else (0.5 if diff < 5.0 else 0.0))
        
        per_hb_scores.append(sum(sub_scores) / len(sub_scores) if sub_scores else 1.0)
    
    return sum(per_hb_scores) / len(per_hb_scores) if per_hb_scores else 0.0


def compare_metadata(ref_meta, gen_meta):
    """Compare publication/experimental metadata. Returns score 0-1."""
    if not ref_meta and not gen_meta:
        return 1.0
    if not ref_meta or not gen_meta:
        return 0.0
    
    scores = []
    
    # Chemical formula (important)
    ref_formula = ref_meta.get('_chemical_formula_sum', '').strip().lower().replace(' ', '')
    gen_formula = gen_meta.get('_chemical_formula_sum', '').strip().lower().replace(' ', '')
    if ref_formula:
        scores.append(1.0 if ref_formula == gen_formula else 
                      SequenceMatcher(None, ref_formula, gen_formula).ratio())
    
    # Authors
    ref_authors = ref_meta.get('authors', [])
    gen_authors = gen_meta.get('authors', [])
    if ref_authors:
        ref_names = set(a.lower().strip() for a in ref_authors)
        gen_names = set(a.lower().strip() for a in gen_authors)
        if ref_names or gen_names:
            scores.append(len(ref_names & gen_names) / len(ref_names | gen_names))
    
    # Other scalar metadata (journal, year, etc.)
    for key in ['_journal_name_full', '_journal_year', '_journal_volume',
                '_diffrn_radiation_type', '_exptl_crystal_colour']:
        ref_val = ref_meta.get(key, '').strip().lower()
        gen_val = gen_meta.get(key, '').strip().lower()
        if ref_val:
            scores.append(1.0 if ref_val == gen_val else
                          SequenceMatcher(None, ref_val, gen_val).ratio())
    
    return sum(scores) / len(scores) if scores else 1.0


# ---------------------------------------------------------------------------
# Task class
# ---------------------------------------------------------------------------

class DomainCrystal(DomainBase):
    supports_visual = True

    def __init__(self, prompt_file="prompts/domain_documents.txt"):
        super().__init__(prompt_file)
        self.sample_type = "crystal"
        self.summary = "CIF crystallographic data with cell parameters, symmetry, atoms, and geometry"
        self.description = "CIF crystallographic structures"
        self.file_format = [".cif"]
        self.domain_parser = "PyCifRW"
        self.category = "science"

    def preprocess_context(self, context: str) -> str:
        """Normalize raw CIF context string before parsing.

        Fixes common CIF syntax issues produced by LLMs that would cause
        PyCifRW to reject otherwise-correct crystallographic data:

        1. Strip markdown code fences (```cif ... ```)
        2. Convert multi-line single-quoted values to semicolon text fields
        3. Quote unquoted multi-word scalar values on the same line as a tag
        4. Remove empty loop_ blocks (header tags with no data rows)
        5. Deduplicate loop_ blocks (same tag set appearing twice)
        6. Split inline semicolon text fields onto separate lines
        """
        text = context

        # --- 1. Strip markdown code fences ---
        text = re.sub(r'^```[^\n]*\n', '', text)
        text = re.sub(r'\n```\s*$', '', text)

        # --- 2. Multi-line single-quoted values → semicolon text fields ---
        # CIF requires multi-line values to use ; delimiters, not quotes.
        # LLMs sometimes produce:  _tag\n'\nlong text\nmore text\n'
        # Fix: detect a line that is just a bare single quote, accumulate
        # lines until a closing quote at end-of-line, wrap in ; ... ;
        lines = text.split('\n')
        result = []
        i = 0
        in_multiline_quote = False
        ml_content: list[str] = []
        while i < len(lines):
            line = lines[i]
            if in_multiline_quote:
                if line.rstrip().endswith("'") and not line.rstrip().endswith("\\'"):
                    ml_content.append(line.rstrip()[:-1])  # drop closing quote
                    result.append(';')
                    result.extend(ml_content)
                    result.append(';')
                    in_multiline_quote = False
                else:
                    ml_content.append(line)
                i += 1
                continue
            if line.strip() == "'":
                in_multiline_quote = True
                ml_content = []
                i += 1
                continue
            result.append(line)
            i += 1
        if in_multiline_quote:          # unclosed — emit as semicolon field
            result.append(';')
            result.extend(ml_content)
            result.append(';')
        text = '\n'.join(result)

        # --- 3. Quote unquoted multi-word scalar values ---
        # e.g. _chemical_formula_sum  C6 H14 Cu1 N4 O12  →  '...'
        lines = text.split('\n')
        result = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('_') and not stripped.startswith('loop_'):
                parts = stripped.split(None, 1)
                if len(parts) == 2:
                    tag, value = parts
                    value = value.strip()
                    if (' ' in value
                            and not (value.startswith("'") and value.endswith("'"))
                            and not (value.startswith('"') and value.endswith('"'))):
                        line = f"{tag} '{value}'"
            result.append(line)
        text = '\n'.join(result)

        # --- 4. Remove empty loop_ blocks ---
        # A loop_ followed only by tag names (no data rows) is invalid CIF.
        lines = text.split('\n')
        result = []
        i = 0
        while i < len(lines):
            if lines[i].strip() == 'loop_':
                j = i + 1
                while j < len(lines) and lines[j].strip().startswith('_'):
                    j += 1
                # Skip blank lines to find first data line
                k = j
                while k < len(lines) and lines[k].strip() == '':
                    k += 1
                has_data = (k < len(lines)
                            and not lines[k].strip().startswith(('loop_', 'data_', '_'))
                            and lines[k].strip() != '')
                if has_data:
                    for idx in range(i, j):
                        result.append(lines[idx])
                    i = j       # continue from first data line
                else:
                    i = j       # skip entire empty loop header
            else:
                result.append(lines[i])
                i += 1
        text = '\n'.join(result)

        # --- 5. Deduplicate loop_ blocks (same tag set twice) ---
        lines = text.split('\n')
        loop_blocks: list[tuple[int, int, frozenset]] = []
        i = 0
        while i < len(lines):
            if lines[i].strip() == 'loop_':
                start = i
                j = i + 1
                while j < len(lines) and lines[j].strip().startswith('_'):
                    j += 1
                tags = frozenset(
                    lines[k].strip().split()[0]
                    for k in range(i + 1, j)
                    if lines[k].strip().startswith('_')
                )
                # Scan past data rows to find end of this loop block
                k = j
                while (k < len(lines) and lines[k].strip()
                       and not lines[k].strip().startswith(('loop_', 'data_'))):
                    k += 1
                loop_blocks.append((start, k, tags))
                i = k
            else:
                i += 1
        seen_tags: set[frozenset] = set()
        remove_ranges: list[tuple[int, int]] = []
        for start, end, tags in loop_blocks:
            if tags in seen_tags:
                remove_ranges.append((start, end))
            else:
                seen_tags.add(tags)
        for start, end in reversed(remove_ranges):
            lines = lines[:start] + lines[end:]
        text = '\n'.join(lines)

        # --- 6. Split inline semicolon text fields ---
        # CIF semicolon-delimited text blocks require the opening and closing
        # ';' each at column 1 of their own line.  LLMs sometimes produce a
        # single line like:  ;Some long text value;
        # Fix: split into three lines:  ;\nSome long text value\n;
        lines = text.split('\n')
        result = []
        for line in lines:
            stripped = line.strip()
            if (stripped.startswith(';') and stripped.endswith(';')
                    and len(stripped) > 2):
                # Opening ; on its own line, text, closing ; on its own line
                result.append(';')
                result.append(stripped[1:-1])
                result.append(';')
            else:
                result.append(line)
        text = '\n'.join(result)

        return text

    def parse_context(self, context):
        """Parse crystal context (dict of filename->content) into a structured dict."""
        all_text = '\n'.join(context.values()) if isinstance(context, dict) else str(context)
        all_text = self.preprocess_context(all_text)
        return build_crystal_structure(all_text)

    def compute_domain_statistics(self, context):
        """Compute domain-specific KPIs from the crystal context."""
        struct = self.parse_context(context)
        
        kpis = {}
        if struct.get('atom_sites'):
            kpis['Atom Sites'] = len(struct['atom_sites'])
        if struct.get('aniso_params'):
            kpis['Aniso Parameters'] = len(struct['aniso_params'])
        if struct.get('bonds'):
            kpis['Bonds'] = len(struct['bonds'])
        if struct.get('angles'):
            kpis['Angles'] = len(struct['angles'])
        if struct.get('hbonds'):
            kpis['H-Bonds'] = len(struct['hbonds'])
        
        sym = struct.get('symmetry', {})
        if sym.get('space_group'):
            kpis['Space Group'] = sym['space_group']
        if sym.get('operations'):
            kpis['Symm Ops'] = len(sym['operations'])
        
        meta = struct.get('metadata', {})
        formula = meta.get('_chemical_formula_sum')
        if formula:
            kpis['Formula'] = formula
        
        return kpis
    
    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        """Evaluate the round-trip reconstruction of a CIF crystal structure.
        
        Flat component weights with atom_recall cascading:
          - Cell parameters (5%)
          - Symmetry (5%)
          - Atom sites (30%) — recall-based per-atom scoring
          - Aniso params (10%) — scaled by atom_recall
          - Bonds (20%) — scaled by atom_recall
          - Angles (10%) — scaled by atom_recall
          - H-bonds (10%) — scaled by atom_recall
          - Metadata (10%)
        
        atom_recall scales dependent structural scores because missing
        atoms cascade: bonds/angles/aniso referencing absent atoms
        become meaningless.
        """
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        # Parse both structures
        ref_struct = self.parse_context(reference_context)
        gen_struct = self.parse_context(generated_context)
        
        if ref_struct.get('parse_error'):
            return {"score": None, "error": f"Reference parse error: {ref_struct['parse_error']}"}
        if gen_struct.get('parse_error'):
            return {"score": 0.0, "error": f"Generated parse error: {gen_struct['parse_error']}"}
        
        # Compute component scores
        cell_score = compare_cell_params(ref_struct['cell_params'], gen_struct['cell_params'])
        sym_score = compare_symmetry(ref_struct['symmetry'], gen_struct['symmetry'])
        
        atom_score, atom_recall = compare_atom_sites(
            ref_struct['atom_sites'], gen_struct['atom_sites']
        )
        
        aniso_score = compare_aniso(ref_struct['aniso_params'], gen_struct['aniso_params'])
        bond_score = compare_bonds(ref_struct['bonds'], gen_struct['bonds'])
        angle_score = compare_angles(ref_struct['angles'], gen_struct['angles'])
        hbond_score = compare_hbonds(ref_struct['hbonds'], gen_struct['hbonds'])
        meta_score = compare_metadata(ref_struct['metadata'], gen_struct['metadata'])
        
        # Atom recall scales dependent structural scores —
        # if atoms are missing, related geometry/aniso data is less meaningful
        eff_aniso = aniso_score * atom_recall
        eff_bonds = bond_score * atom_recall
        eff_angles = angle_score * atom_recall
        eff_hbonds = hbond_score * atom_recall
        
        # Weighted final score (flat, no intermediate composites)
        score = (
            cell_score  * 0.05 +
            sym_score   * 0.05 +
            atom_score  * 0.30 +
            eff_aniso   * 0.10 +
            eff_bonds   * 0.20 +
            eff_angles  * 0.10 +
            eff_hbonds  * 0.10 +
            meta_score  * 0.10
        )
        
        eval_obj = {
            "score": score,
            "cell_params_score": cell_score,
            "symmetry_score": sym_score,
            "atom_sites_score": atom_score,
            "atom_recall": atom_recall,
            "aniso_params_score": aniso_score,
            "bond_score": bond_score,
            "angle_score": angle_score,
            "hbond_score": hbond_score,
            "metadata_score": meta_score,
            "eff_aniso": eff_aniso,
            "eff_bonds": eff_bonds,
            "eff_angles": eff_angles,
            "eff_hbonds": eff_hbonds,
            "ref_atom_count": len(ref_struct.get('atom_sites', [])),
            "gen_atom_count": len(gen_struct.get('atom_sites', [])),
            "ref_bond_count": len(ref_struct.get('bonds', [])),
            "gen_bond_count": len(gen_struct.get('bonds', [])),
        }
        
        if debug:
            print(f"Cell: {cell_score:.3f}, Sym: {sym_score:.3f}, Atoms: {atom_score:.3f} (recall={atom_recall:.3f}), "
                  f"Aniso: {aniso_score:.3f}, Bonds: {bond_score:.3f}, Angles: {angle_score:.3f}, "
                  f"HBonds: {hbond_score:.3f}, Meta: {meta_score:.3f}")
        
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

    def render_context_visual(self, context, outfile):
        """Render CIF crystal structure using pymatgen + ASE plot_atoms.

        Parses CIF with pymatgen (proper symmetry expansion), converts to ASE
        Atoms, and renders with ASE's plot_atoms which draws proper spheres
        with Jmol CPK colours and depth-sorted occlusion.
        """
        import warnings
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        try:
            from pymatgen.core.structure import Structure
            from pymatgen.io.ase import AseAtomsAdaptor
            from ase.visualize.plot import plot_atoms
        except ImportError:
            return None

        # ---- get raw CIF text ----
        all_text = '\n'.join(context.values()) if isinstance(context, dict) else str(context)
        all_text = self.preprocess_context(all_text)

        # ---- parse with pymatgen, convert to ASE ----
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                structure = Structure.from_str(all_text, fmt='cif')
        except Exception:
            return None

        if len(structure) == 0:
            return None

        try:
            atoms = AseAtomsAdaptor.get_atoms(structure)
        except Exception:
            return None

        # ---- plot with ASE's plot_atoms ----
        fig, ax = plt.subplots(1, 1, figsize=(7, 7))
        try:
            plot_atoms(atoms, ax, radii=0.8, rotation='10x,20y,3z')
        except Exception:
            plt.close(fig)
            return None

        # Title: formula + space group
        formula = structure.composition.reduced_formula
        sg_symbol = ''
        try:
            from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                sga = SpacegroupAnalyzer(structure, symprec=0.1)
                sg_symbol = sga.get_space_group_symbol()
        except Exception:
            pass

        title_parts = [p for p in [formula, sg_symbol] if p]
        if title_parts:
            ax.set_title(' | '.join(title_parts), fontsize=11)

        fig.tight_layout()

        out_path = outfile + '.png'
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        return out_path
