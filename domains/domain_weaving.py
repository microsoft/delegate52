from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, configparser, io
import ujson as json


def parse_wif(content):
    """Parse a WIF (Weaving Information File) into a structured dict.
    
    Returns a dict with keys:
        metadata: dict of WIF header fields (version, date, developer, source, etc.)
        text: dict with Title and comments
        weaving: dict with Shafts, Treadles, Rising Shed
        warp: dict with Threads, Units, Color, Spacing, Thickness
        weft: dict with Threads, Units, Color, Spacing, Thickness
        threading: dict mapping warp-thread-number (int) -> shaft (int)
        treadling: dict mapping weft-row-number (int) -> treadle (int) or list[int]
        tieup: dict mapping treadle (int) -> sorted list of shafts [int]
        color_table: dict mapping color-index (int) -> (r, g, b) tuple of ints
        color_palette: dict with Range and Entries
        warp_colors: dict mapping warp-thread-number (int) -> color-index (int)
        weft_colors: dict mapping weft-row-number (int) -> color-index (int)
        contents: dict of section-name -> bool (which sections are declared)
        section_order: list of section names in original order
    """
    result = {
        'metadata': {},
        'text': {},
        'weaving': {},
        'warp': {},
        'weft': {},
        'threading': {},
        'treadling': {},
        'tieup': {},
        'color_table': {},
        'color_palette': {},
        'warp_colors': {},
        'weft_colors': {},
        'contents': {},
        'section_order': [],
        'liftplan': {},
    }
    
    try:
        # Use configparser with case-sensitive keys
        config = configparser.ConfigParser(interpolation=None)
        config.optionxform = str  # preserve case
        config.read_string(content)
        
        # Track section order from raw content
        for line in content.splitlines():
            line_s = line.strip()
            if line_s.startswith('[') and ']' in line_s:
                sec_name = line_s[1:line_s.index(']')]
                if sec_name not in result['section_order']:
                    result['section_order'].append(sec_name)
        
        # [WIF] section
        if config.has_section('WIF'):
            for key in config.options('WIF'):
                result['metadata'][key] = config.get('WIF', key)
        
        # [CONTENTS] section
        if config.has_section('CONTENTS'):
            for key in config.options('CONTENTS'):
                result['contents'][key] = config.get('CONTENTS', key).lower() == 'true'
        
        # [TEXT] section - also capture comments
        if config.has_section('TEXT'):
            for key in config.options('TEXT'):
                result['text'][key] = config.get('TEXT', key)
        # Extract comments (lines starting with ;) from [TEXT] section
        in_text = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.upper() == '[TEXT]':
                in_text = True
                continue
            if stripped.startswith('[') and in_text:
                in_text = False
            if in_text and stripped.startswith(';'):
                result['text']['_comment'] = stripped
        
        # [WEAVING] section
        if config.has_section('WEAVING'):
            w = {}
            for key in config.options('WEAVING'):
                val = config.get('WEAVING', key)
                if key in ('Shafts', 'Treadles'):
                    w[key] = int(val)
                elif key == 'Rising Shed':
                    w[key] = val.lower() == 'true'
                else:
                    w[key] = val
            result['weaving'] = w
        
        # [WARP] section
        if config.has_section('WARP'):
            for key in config.options('WARP'):
                val = config.get('WARP', key)
                if key in ('Threads', 'Color'):
                    result['warp'][key] = int(val)
                elif key in ('Spacing', 'Thickness'):
                    result['warp'][key] = float(val)
                else:
                    result['warp'][key] = val
        
        # [WEFT] section
        if config.has_section('WEFT'):
            for key in config.options('WEFT'):
                val = config.get('WEFT', key)
                if key in ('Threads', 'Color'):
                    result['weft'][key] = int(val)
                elif key in ('Spacing', 'Thickness'):
                    result['weft'][key] = float(val)
                else:
                    result['weft'][key] = val
        
        # [THREADING] section: n=shaft
        if config.has_section('THREADING'):
            for key in config.options('THREADING'):
                try:
                    val = config.get('THREADING', key)
                    # Could be single shaft or comma-separated list
                    if ',' in val:
                        result['threading'][int(key)] = [int(x.strip()) for x in val.split(',')]
                    else:
                        result['threading'][int(key)] = int(val)
                except (ValueError, KeyError):
                    pass
        
        # [TREADLING] section: n=treadle (or comma-separated for multiple)
        if config.has_section('TREADLING'):
            for key in config.options('TREADLING'):
                try:
                    val = config.get('TREADLING', key)
                    if ',' in val:
                        result['treadling'][int(key)] = [int(x.strip()) for x in val.split(',')]
                    else:
                        result['treadling'][int(key)] = int(val)
                except (ValueError, KeyError):
                    pass
        
        # [TIEUP] section: treadle=shaft1,shaft2,...
        if config.has_section('TIEUP'):
            for key in config.options('TIEUP'):
                try:
                    val = config.get('TIEUP', key)
                    shafts = sorted([int(x.strip()) for x in val.split(',')])
                    result['tieup'][int(key)] = shafts
                except (ValueError, KeyError):
                    pass
        
        # [LIFTPLAN] section: row=shaft1,shaft2,...
        if config.has_section('LIFTPLAN'):
            for key in config.options('LIFTPLAN'):
                try:
                    val = config.get('LIFTPLAN', key)
                    shafts = sorted([int(x.strip()) for x in val.split(',')])
                    result['liftplan'][int(key)] = shafts
                except (ValueError, KeyError):
                    pass
        
        # [COLOR TABLE] section: n=r,g,b
        if config.has_section('COLOR TABLE'):
            for key in config.options('COLOR TABLE'):
                try:
                    val = config.get('COLOR TABLE', key)
                    parts = [int(x.strip()) for x in val.split(',')]
                    if len(parts) == 3:
                        result['color_table'][int(key)] = tuple(parts)
                except (ValueError, KeyError):
                    pass
        
        # [COLOR PALETTE] section
        if config.has_section('COLOR PALETTE'):
            for key in config.options('COLOR PALETTE'):
                val = config.get('COLOR PALETTE', key)
                if key == 'Entries':
                    result['color_palette'][key] = int(val)
                else:
                    result['color_palette'][key] = val
        
        # [WARP COLORS] section: n=color_index
        if config.has_section('WARP COLORS'):
            for key in config.options('WARP COLORS'):
                try:
                    result['warp_colors'][int(key)] = int(config.get('WARP COLORS', key))
                except (ValueError, KeyError):
                    pass
        
        # [WEFT COLORS] section: n=color_index
        if config.has_section('WEFT COLORS'):
            for key in config.options('WEFT COLORS'):
                try:
                    result['weft_colors'][int(key)] = int(config.get('WEFT COLORS', key))
                except (ValueError, KeyError):
                    pass
    
    except Exception as e:
        print(f"\033[91mWIF parsing error: {e}\033[0m")
    
    return result


def parse_all_wif(context):
    """Parse all .wif files in the context dict, return list of parsed WIF dicts."""
    parsed = []
    for filename, content in sorted(context.items()):
        if filename.endswith('.wif'):
            parsed.append(parse_wif(content))
    return parsed


def merge_wif_data(parsed_list):
    """Merge multiple parsed WIF dicts into combined data structures for comparison."""
    merged = {
        'threading': {},
        'treadling': {},
        'tieup': {},
        'color_table': {},
        'warp_colors': {},
        'weft_colors': {},
        'liftplan': {},
        'weaving': {},
        'warp': {},
        'weft': {},
        'metadata': {},
        'text': {},
        'color_palette': {},
    }
    for p in parsed_list:
        merged['threading'].update(p.get('threading', {}))
        merged['treadling'].update(p.get('treadling', {}))
        merged['tieup'].update(p.get('tieup', {}))
        merged['color_table'].update(p.get('color_table', {}))
        merged['warp_colors'].update(p.get('warp_colors', {}))
        merged['weft_colors'].update(p.get('weft_colors', {}))
        merged['liftplan'].update(p.get('liftplan', {}))
        if p.get('weaving'):
            merged['weaving'].update(p['weaving'])
        if p.get('warp'):
            merged['warp'].update(p['warp'])
        if p.get('weft'):
            merged['weft'].update(p['weft'])
        if p.get('metadata'):
            merged['metadata'].update(p['metadata'])
        if p.get('text'):
            merged['text'].update(p['text'])
        if p.get('color_palette'):
            merged['color_palette'].update(p['color_palette'])
    return merged


def _normalize_value(v):
    """Normalize a threading/treadling value for comparison (int or sorted list)."""
    if isinstance(v, list):
        return tuple(sorted(v))
    return v


def compute_threading_score(ref_threading, gen_threading):
    """Compare threading assignments: fraction of matching thread->shaft mappings."""
    if not ref_threading and not gen_threading:
        return 1.0
    if not ref_threading or not gen_threading:
        return 0.0
    
    all_keys = set(ref_threading.keys()) | set(gen_threading.keys())
    if not all_keys:
        return 1.0
    
    matches = 0
    for k in all_keys:
        ref_val = _normalize_value(ref_threading.get(k))
        gen_val = _normalize_value(gen_threading.get(k))
        if ref_val == gen_val:
            matches += 1
    
    return matches / len(all_keys)


def compute_treadling_score(ref_treadling, gen_treadling):
    """Compare treadling sequences: fraction of matching row->treadle mappings."""
    if not ref_treadling and not gen_treadling:
        return 1.0
    if not ref_treadling or not gen_treadling:
        return 0.0
    
    all_keys = set(ref_treadling.keys()) | set(gen_treadling.keys())
    if not all_keys:
        return 1.0
    
    matches = 0
    for k in all_keys:
        ref_val = _normalize_value(ref_treadling.get(k))
        gen_val = _normalize_value(gen_treadling.get(k))
        if ref_val == gen_val:
            matches += 1
    
    return matches / len(all_keys)


def compute_tieup_score(ref_tieup, gen_tieup):
    """Compare tieup configurations: fraction of treadles with matching shaft sets."""
    if not ref_tieup and not gen_tieup:
        return 1.0
    if not ref_tieup or not gen_tieup:
        return 0.0
    
    all_keys = set(ref_tieup.keys()) | set(gen_tieup.keys())
    if not all_keys:
        return 1.0
    
    matches = 0
    for k in all_keys:
        ref_shafts = tuple(sorted(ref_tieup.get(k, [])))
        gen_shafts = tuple(sorted(gen_tieup.get(k, [])))
        if ref_shafts == gen_shafts:
            matches += 1
    
    return matches / len(all_keys)


def compute_color_table_score(ref_colors, gen_colors):
    """Compare color tables: average color similarity across all entries."""
    if not ref_colors and not gen_colors:
        return 1.0
    if not ref_colors or not gen_colors:
        return 0.0
    
    all_keys = set(ref_colors.keys()) | set(gen_colors.keys())
    if not all_keys:
        return 1.0
    
    total_sim = 0.0
    for k in all_keys:
        ref_rgb = ref_colors.get(k)
        gen_rgb = gen_colors.get(k)
        if ref_rgb is None or gen_rgb is None:
            total_sim += 0.0
        elif ref_rgb == gen_rgb:
            total_sim += 1.0
        else:
            # Euclidean distance normalized by max possible distance
            max_val = 999  # WIF uses 0-999 range typically
            max_dist = (3 * max_val**2) ** 0.5
            dist = sum((a - b)**2 for a, b in zip(ref_rgb, gen_rgb)) ** 0.5
            total_sim += max(0.0, 1.0 - dist / max_dist)
    
    return total_sim / len(all_keys)


def compute_parameters_score(ref_data, gen_data):
    """Compare loom parameters (weaving, warp, weft sections)."""
    params_to_check = []
    
    # Weaving section
    for key in ('Shafts', 'Treadles', 'Rising Shed'):
        ref_val = ref_data.get('weaving', {}).get(key)
        gen_val = gen_data.get('weaving', {}).get(key)
        if ref_val is not None or gen_val is not None:
            params_to_check.append((ref_val, gen_val))
    
    # Warp section
    for key in ('Threads', 'Units', 'Color', 'Spacing', 'Thickness'):
        ref_val = ref_data.get('warp', {}).get(key)
        gen_val = gen_data.get('warp', {}).get(key)
        if ref_val is not None or gen_val is not None:
            params_to_check.append((ref_val, gen_val))
    
    # Weft section
    for key in ('Threads', 'Units', 'Color', 'Spacing', 'Thickness'):
        ref_val = ref_data.get('weft', {}).get(key)
        gen_val = gen_data.get('weft', {}).get(key)
        if ref_val is not None or gen_val is not None:
            params_to_check.append((ref_val, gen_val))
    
    if not params_to_check:
        return 1.0
    
    matches = sum(1 for r, g in params_to_check if r == g)
    base_score = matches / len(params_to_check)
    
    # Data consistency gating: parameters like "Threads: 188" are only
    # meaningful when the actual threading/treadling data is present.
    # Gate by coverage² so the score drops when data entries are missing.
    coverage_factors = []
    for section in ('threading', 'treadling'):
        ref_count = len(ref_data.get(section, {}))
        gen_count = len(gen_data.get(section, {}))
        if ref_count > 0:
            coverage_factors.append(min(gen_count / ref_count, 1.0))
    
    if coverage_factors:
        data_coverage = sum(coverage_factors) / len(coverage_factors)
        return base_score * (data_coverage ** 2)
    
    return base_score


class DomainWeaving(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "weaving"
        self.summary = "WIF (Weaving Information File) draft patterns with threading, tieup, treadling, and color data"
        self.description = "WIF weaving drafts"
        self.file_format = [".wif"]
        self.domain_parser = "custom"
        self.category = "creative"
    
    def parse_all_entries(self, context):
        return parse_all_wif(context)

    def parse_context(self, context):
        patterns = self.parse_all_entries(context)
        return {"patterns": patterns}
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        parsed_list = parsed["patterns"]
        if not parsed_list:
            return {}
        merged = merge_wif_data(parsed_list)
        shafts = merged.get('weaving', {}).get('Shafts', 0)
        treadles = merged.get('weaving', {}).get('Treadles', 0)
        warp_threads = len(merged.get('threading', {}))
        weft_rows = len(merged.get('treadling', {}))
        colors = len(merged.get('color_table', {}))
        return {
            "Shafts": shafts,
            "Treadles": treadles,
            "Warp Threads": warp_threads,
            "Weft Rows": weft_rows,
            "Colors": colors,
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
        
        ref_parsed = self.parse_context(reference_context)["patterns"]
        gen_parsed = self.parse_context(generated_context)["patterns"]
        
        ref_data = merge_wif_data(ref_parsed)
        gen_data = merge_wif_data(gen_parsed)
        
        if debug:
            print(f"Ref threading: {len(ref_data['threading'])}, Gen threading: {len(gen_data['threading'])}")
            print(f"Ref treadling: {len(ref_data['treadling'])}, Gen treadling: {len(gen_data['treadling'])}")
            print(f"Ref tieup: {len(ref_data['tieup'])}, Gen tieup: {len(gen_data['tieup'])}")
        
        # Compute component scores
        threading_score = compute_threading_score(ref_data['threading'], gen_data['threading'])
        treadling_score = compute_treadling_score(ref_data['treadling'], gen_data['treadling'])
        tieup_score = compute_tieup_score(ref_data['tieup'], gen_data['tieup'])
        color_score = compute_color_table_score(ref_data['color_table'], gen_data['color_table'])
        params_score = compute_parameters_score(ref_data, gen_data)
        
        # Weighted aggregate:
        # Threading and treadling are the core pattern data (30% each)
        # Tieup defines the weave structure (20%)
        # Colors matter for visual accuracy (10%)
        # Parameters ensure correct loom setup (10%)
        score = (0.30 * threading_score +
                 0.30 * treadling_score +
                 0.20 * tieup_score +
                 0.10 * color_score +
                 0.10 * params_score)
        
        eval_obj = {
            "score": score,
            "threading_score": threading_score,
            "treadling_score": treadling_score,
            "tieup_score": tieup_score,
            "color_table_score": color_score,
            "parameters_score": params_score,
            "ref_threading_count": len(ref_data['threading']),
            "gen_threading_count": len(gen_data['threading']),
            "ref_treadling_count": len(ref_data['treadling']),
            "gen_treadling_count": len(gen_data['treadling']),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

    def render_context_visual(self, context, outfile):
        """Render WIF weaving draft to a PNG drawdown image using matplotlib."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        parsed = self.parse_context(context)["patterns"]
        if not parsed:
            return None
        data = merge_wif_data(parsed)

        threading = data.get("threading", {})
        treadling = data.get("treadling", {})
        tieup = data.get("tieup", {})
        liftplan = data.get("liftplan", {})
        color_table = data.get("color_table", {})
        warp_colors = data.get("warp_colors", {})
        weft_colors = data.get("weft_colors", {})
        warp_info = data.get("warp", {})
        weft_info = data.get("weft", {})
        rising_shed = str(data.get("weaving", {}).get("Rising Shed", "1")) == "1"

        if not threading or (not treadling and not liftplan):
            return None

        n_warp = max(threading.keys()) if threading else 0
        n_weft = max((treadling or liftplan).keys()) if (treadling or liftplan) else 0
        if n_warp == 0 or n_weft == 0:
            return None

        def resolve_color(color_idx, fallback):
            if color_idx in color_table:
                r, g, b = color_table[color_idx]
                return (r / 999.0, g / 999.0, b / 999.0)
            return fallback

        default_warp_color_idx = int(warp_info.get("Color", 1))
        default_weft_color_idx = int(weft_info.get("Color", 2))
        default_warp_rgb = resolve_color(default_warp_color_idx, (0.0, 0.0, 0.0))
        default_weft_rgb = resolve_color(default_weft_color_idx, (1.0, 1.0, 1.0))

        # Build drawdown grid
        grid = np.zeros((n_weft, n_warp, 3), dtype=np.float64)
        for row in range(1, n_weft + 1):
            # Determine active shafts for this row
            if liftplan:
                active = set(liftplan.get(row, []) if isinstance(liftplan.get(row), list) else [liftplan.get(row)] if liftplan.get(row) else [])
            else:
                treadle_val = treadling.get(row, [])
                treadles = treadle_val if isinstance(treadle_val, list) else [treadle_val]
                active = set()
                for t in treadles:
                    if t and t in tieup:
                        active.update(tieup[t])

            weft_cidx = weft_colors.get(row, default_weft_color_idx)
            weft_rgb = resolve_color(weft_cidx, default_weft_rgb)

            for col in range(1, n_warp + 1):
                shaft = threading.get(col)
                shafts = shaft if isinstance(shaft, list) else [shaft] if shaft else []
                warp_raised = any(s in active for s in shafts)

                warp_cidx = warp_colors.get(col, default_warp_color_idx)
                warp_rgb = resolve_color(warp_cidx, default_warp_rgb)

                if rising_shed:
                    grid[row - 1, col - 1] = warp_rgb if warp_raised else weft_rgb
                else:
                    grid[row - 1, col - 1] = weft_rgb if warp_raised else warp_rgb

        grid = np.clip(grid, 0.0, 1.0)

        # Render
        aspect = n_warp / n_weft
        fig_w = max(4, min(12, n_warp / 30))
        fig_h = fig_w / aspect if aspect > 0 else fig_w
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=150)
        ax.imshow(grid, aspect="equal", interpolation="nearest", origin="upper")
        ax.set_axis_off()

        out_path = outfile + ".png"
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, bbox_inches="tight", pad_inches=0.02)
        plt.close(fig)
        return out_path
