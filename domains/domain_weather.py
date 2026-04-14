from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
from metar.Metar import Metar


# ---- METAR Parsing ----

def parse_metar_report(raw_line):
    """Parse a single METAR/SPECI report line into a structured dict.
    
    Uses the python-metar library for robust parsing, falling back to
    regex extraction for fields the library doesn't capture well.
    
    Returns dict with keys: report_type, station, time_str, raw,
    wind_dir, wind_speed, wind_gust, visibility, sky, weather,
    temp, dewpt, altimeter, remarks_raw, is_auto, is_cor, maintenance
    """
    entry = {
        'report_type': '', 'station': '', 'time_str': '', 'raw': raw_line.strip(),
        'wind_dir': '', 'wind_speed': '', 'wind_gust': '',
        'visibility': '', 'sky': [], 'weather': [],
        'temp': '', 'dewpt': '', 'altimeter': '',
        'remarks_raw': '', 'is_auto': False, 'is_cor': False,
        'maintenance': False,
    }
    
    line = raw_line.strip()
    if not line:
        return entry
    
    # Check for maintenance indicator ($)
    if line.endswith('$'):
        entry['maintenance'] = True
        line = line[:-1].strip()
    
    # Extract report type
    if line.startswith('SPECI '):
        entry['report_type'] = 'SPECI'
    elif line.startswith('METAR '):
        entry['report_type'] = 'METAR'
    else:
        return entry
    
    # Check for COR (corrected)
    if ' COR ' in line:
        entry['is_cor'] = True
    
    # Try parsing with metar library
    try:
        obs = Metar(line, strict=False)
        entry['station'] = obs.station_id or ''
        if obs.time:
            # Format back to DDHHMM format
            entry['time_str'] = f"{obs.time.day:02d}{obs.time.hour:02d}{obs.time.minute:02d}Z"
        
        # Wind
        if obs.wind_dir:
            entry['wind_dir'] = str(int(obs.wind_dir.value()))
        elif 'VRB' in line:
            entry['wind_dir'] = 'VRB'
        if obs.wind_speed:
            entry['wind_speed'] = str(int(obs.wind_speed.value('KT')))
        if obs.wind_gust:
            entry['wind_gust'] = str(int(obs.wind_gust.value('KT')))
        
        # Calm wind handling
        if '00000KT' in line:
            entry['wind_dir'] = '0'
            entry['wind_speed'] = '0'
        
        # Visibility
        if obs.vis:
            entry['visibility'] = str(obs.vis)
        
        # Sky conditions
        if obs.sky:
            for cover, height, cb in obs.sky:
                layer = {'cover': cover}
                if height:
                    layer['height'] = str(int(height.value('FT')))
                if cb:
                    layer['cb'] = cb
                entry['sky'].append(layer)
        
        # Weather phenomena
        if obs.weather:
            for wx_tuple in obs.weather:
                # wx is a tuple of (intensity, descriptor, precipitation, obscuration, other)
                wx_str = ''.join(str(x) for x in wx_tuple if x)
                if wx_str:
                    entry['weather'].append(wx_str)
        
        # Temperature and dewpoint
        if obs.temp:
            entry['temp'] = f"{obs.temp.value():.1f}"
        if obs.dewpt:
            entry['dewpt'] = f"{obs.dewpt.value():.1f}"
        
        # Altimeter
        if obs.press:
            entry['altimeter'] = f"{obs.press.value('IN'):.2f}"
        
        # Remarks - extract raw string
        rmk_match = re.search(r'\bRMK\b\s*(.*?)$', raw_line.rstrip(' $'))
        if rmk_match:
            entry['remarks_raw'] = rmk_match.group(1).strip()
        
        # AUTO
        if obs.station_id and 'AUTO' in line:
            entry['is_auto'] = True
            
    except Exception:
        # Fallback: extract station and time with regex
        m = re.match(r'(?:METAR|SPECI)\s+(?:COR\s+)?(\w{4})\s+(\d{6}Z)', line)
        if m:
            entry['station'] = m.group(1)
            entry['time_str'] = m.group(2)
    
    return entry


# ---- TAF Parsing ----

def parse_taf_report(raw_text):
    """Parse a TAF forecast into a structured dict.
    
    A TAF has:
    - Header: TAF [AMD] STATION DDHHMMZ VALID_FROM/VALID_TO
    - Initial forecast group (wind, vis, sky, weather)
    - Change groups: FM, TEMPO, BECMG, PROB30/PROB40
    
    Returns dict with keys: station, issue_time, valid_from, valid_to,
    is_amended, groups (list of forecast groups), raw
    """
    entry = {
        'station': '', 'issue_time': '', 'valid_from': '', 'valid_to': '',
        'is_amended': False, 'groups': [], 'raw': raw_text.strip(),
    }
    
    # Normalize to single line for parsing
    text = ' '.join(raw_text.strip().split())
    
    if not text.startswith('TAF'):
        return entry
    
    # Check for AMD (amended)
    if ' AMD ' in text:
        entry['is_amended'] = True
    
    # Parse header: TAF [AMD] STATION DDHHMMZ DDHH/DDHH
    header_match = re.match(
        r'TAF\s+(?:AMD\s+)?(\w{4})\s+(\d{6}Z)\s+(\d{4})/(\d{4})\s+(.*)',
        text
    )
    if not header_match:
        return entry
    
    entry['station'] = header_match.group(1)
    entry['issue_time'] = header_match.group(2)
    entry['valid_from'] = header_match.group(3)
    entry['valid_to'] = header_match.group(4)
    forecast_body = header_match.group(5)
    
    # Split into groups by FM/TEMPO/BECMG/PROB markers
    # First group is the initial forecast
    group_pattern = r'(?=\b(?:FM\d{6}|TEMPO\s|BECMG\s|PROB\d{2}\s))'
    parts = re.split(group_pattern, forecast_body)
    
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        
        group = parse_taf_group(part, is_initial=(i == 0))
        if group:
            entry['groups'].append(group)
    
    return entry


def parse_taf_group(text, is_initial=False):
    """Parse a single TAF forecast group (initial, FM, TEMPO, BECMG, PROB).
    
    Returns dict with: group_type, from_time, wind_dir, wind_speed, wind_gust,
    visibility, sky, weather
    """
    group = {
        'group_type': 'INITIAL' if is_initial else '',
        'from_time': '',
        'wind_dir': '', 'wind_speed': '', 'wind_gust': '',
        'visibility': '', 'sky': [], 'weather': [], 'raw': text,
    }
    
    tokens = text.split()
    if not tokens:
        return None
    
    idx = 0
    
    # Determine group type and time
    if not is_initial:
        first = tokens[0]
        if first.startswith('FM'):
            group['group_type'] = 'FM'
            group['from_time'] = first[2:]  # DDHHMM
            idx = 1
        elif first == 'TEMPO':
            group['group_type'] = 'TEMPO'
            idx = 1
            if idx < len(tokens) and re.match(r'\d{4}/\d{4}', tokens[idx]):
                group['from_time'] = tokens[idx]
                idx += 1
        elif first == 'BECMG':
            group['group_type'] = 'BECMG'
            idx = 1
            if idx < len(tokens) and re.match(r'\d{4}/\d{4}', tokens[idx]):
                group['from_time'] = tokens[idx]
                idx += 1
        elif first.startswith('PROB'):
            group['group_type'] = first  # e.g., PROB30, PROB40
            idx = 1
            if idx < len(tokens) and re.match(r'\d{4}/\d{4}', tokens[idx]):
                group['from_time'] = tokens[idx]
                idx += 1
    
    # Parse remaining tokens
    for t in tokens[idx:]:
        # Wind
        wind_match = re.match(r'(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?KT', t)
        if wind_match:
            group['wind_dir'] = wind_match.group(1)
            group['wind_speed'] = wind_match.group(2)
            if wind_match.group(3):
                group['wind_gust'] = wind_match.group(3)
            continue
        
        # Calm wind
        if t == '00000KT':
            group['wind_dir'] = '000'
            group['wind_speed'] = '00'
            continue
        
        # Visibility
        if re.match(r'P?\d+SM$', t):
            group['visibility'] = t
            continue
        if t in ('M1/4SM', '1/4SM', '1/2SM', '3/4SM', '1SM', '2SM', '3SM'):
            group['visibility'] = t
            continue
        
        # Sky conditions
        sky_match = re.match(r'(FEW|SCT|BKN|OVC|CLR|SKC|VV)(\d{3})?(?:(CB|TCU))?$', t)
        if sky_match:
            layer = {'cover': sky_match.group(1)}
            if sky_match.group(2):
                layer['height'] = sky_match.group(2)
            if sky_match.group(3):
                layer['cb'] = sky_match.group(3)
            group['sky'].append(layer)
            continue
        
        # Weather phenomena (starts with - + or nothing, followed by 2-char groups)
        if re.match(r'^[-+]?(?:MI|PR|BC|DR|BL|SH|TS|FZ|VC)?(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+$', t):
            group['weather'].append(t)
            continue
    
    return group


# ---- Bulletin Parsing ----

def parse_bulletin(content):
    """Parse a weather bulletin file into structured components.
    
    Returns dict with:
    - header: dict of header fields (dtg, region, stations)
    - metar_reports: list of parsed METAR/SPECI entries
    - taf_reports: list of parsed TAF entries
    """
    result = {
        'header': {},
        'metar_reports': [],
        'taf_reports': [],
    }
    
    lines = content.strip().split('\n')
    
    # Parse header
    for line in lines:
        line = line.strip()
        if line.startswith('DTG:'):
            result['header']['dtg'] = line[4:].strip()
        elif line.startswith('REGION:'):
            result['header']['region'] = line[7:].strip()
        elif line.startswith('STATIONS:'):
            result['header']['stations'] = line[9:].strip()
        elif line.startswith('AVIATION WEATHER BULLETIN'):
            result['header']['title'] = line
    
    # Find METAR section and TAF section
    in_metar_section = False
    in_taf_section = False
    current_taf_lines = []
    
    for line in lines:
        stripped = line.strip()
        
        if 'METAR' in stripped and 'OBSERVATION' in stripped.upper():
            in_metar_section = True
            in_taf_section = False
            continue
        if 'TERMINAL AERODROME FORECAST' in stripped.upper() or ('TAF' in stripped and 'FORECAST' in stripped.upper()):
            in_metar_section = False
            in_taf_section = True
            # Flush any pending TAF
            if current_taf_lines:
                taf_text = '\n'.join(current_taf_lines)
                result['taf_reports'].append(parse_taf_report(taf_text))
                current_taf_lines = []
            continue
        
        if stripped.startswith('===') or stripped == 'END OF BULLETIN':
            continue
        
        # Parse METAR/SPECI lines
        if in_metar_section and (stripped.startswith('METAR ') or stripped.startswith('SPECI ')):
            result['metar_reports'].append(parse_metar_report(stripped))
        
        # Parse TAF blocks (multi-line)
        if in_taf_section:
            if stripped.startswith('TAF '):
                # Flush previous TAF if any
                if current_taf_lines:
                    taf_text = '\n'.join(current_taf_lines)
                    result['taf_reports'].append(parse_taf_report(taf_text))
                current_taf_lines = [stripped]
            elif stripped and current_taf_lines:
                current_taf_lines.append(line.rstrip())  # preserve indentation
            # blank line = end of TAF block
            elif not stripped and current_taf_lines:
                taf_text = '\n'.join(current_taf_lines)
                result['taf_reports'].append(parse_taf_report(taf_text))
                current_taf_lines = []
    
    # Flush final TAF
    if current_taf_lines:
        taf_text = '\n'.join(current_taf_lines)
        result['taf_reports'].append(parse_taf_report(taf_text))

    # Fallback: if no section headers were found, scan all lines for METAR/TAF
    if not result['metar_reports'] and not result['taf_reports']:
        current_taf_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('METAR ') or stripped.startswith('SPECI '):
                result['metar_reports'].append(parse_metar_report(stripped))
            elif stripped.startswith('TAF '):
                if current_taf_lines:
                    taf_text = '\n'.join(current_taf_lines)
                    result['taf_reports'].append(parse_taf_report(taf_text))
                current_taf_lines = [stripped]
            elif stripped and current_taf_lines:
                current_taf_lines.append(line.rstrip())
            elif not stripped and current_taf_lines:
                taf_text = '\n'.join(current_taf_lines)
                result['taf_reports'].append(parse_taf_report(taf_text))
                current_taf_lines = []
        if current_taf_lines:
            taf_text = '\n'.join(current_taf_lines)
            result['taf_reports'].append(parse_taf_report(taf_text))

    return result


def parse_all_reports(context):
    """Parse all weather files in a context dict."""
    all_metar = []
    all_taf = []
    header = {}
    
    for filename, content in context.items():
        parsed = parse_bulletin(content)
        all_metar.extend(parsed['metar_reports'])
        all_taf.extend(parsed['taf_reports'])
        if parsed['header']:
            header.update(parsed['header'])
    
    return {'header': header, 'metar_reports': all_metar, 'taf_reports': all_taf}


# ---- Fingerprinting & Matching ----

def metar_fingerprint(entry):
    """Create a fingerprint for matching METARs: STATION + TIME."""
    station = entry.get('station', '').upper().strip()
    time_str = entry.get('time_str', '').upper().strip()
    report_type = entry.get('report_type', '').upper().strip()
    return f"{report_type}_{station}_{time_str}"


def taf_fingerprint(entry):
    """Fingerprint for TAF: STATION + ISSUE_TIME."""
    station = entry.get('station', '').upper().strip()
    issue_time = entry.get('issue_time', '').upper().strip()
    return f"TAF_{station}_{issue_time}"


# ---- Comparison Functions ----

def field_similarity(ref_val, gen_val):
    """Compare two field values. Returns [0, 1]."""
    if not ref_val and not gen_val:
        return 1.0
    if not ref_val or not gen_val:
        return 0.0
    ref_norm = ' '.join(str(ref_val).upper().split())
    gen_norm = ' '.join(str(gen_val).upper().split())
    if ref_norm == gen_norm:
        return 1.0
    return SequenceMatcher(None, ref_norm, gen_norm).ratio()


def compute_metar_coverage(ref_reports, gen_reports):
    """Compute Jaccard coverage on METAR fingerprints."""
    if not ref_reports and not gen_reports:
        return 1.0
    if not ref_reports or not gen_reports:
        return 0.0
    
    ref_fps = {metar_fingerprint(e) for e in ref_reports}
    gen_fps = {metar_fingerprint(e) for e in gen_reports}
    
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def sky_similarity(ref_sky, gen_sky):
    """Compare sky condition lists."""
    if not ref_sky and not gen_sky:
        return 1.0
    if not ref_sky or not gen_sky:
        return 0.0
    
    # Convert to string representation for comparison
    def sky_str(layers):
        parts = []
        for layer in layers:
            s = layer.get('cover', '')
            if 'height' in layer:
                s += layer['height']
            if 'cb' in layer:
                s += layer['cb']
            parts.append(s)
        return ' '.join(parts)
    
    return field_similarity(sky_str(ref_sky), sky_str(gen_sky))


def compute_metar_field_accuracy(ref_reports, gen_reports):
    """Compare METAR fields for matched reports.
    
    Fields compared with weights:
    - wind (direction, speed, gust): 0.20
    - visibility: 0.15
    - sky conditions: 0.15
    - weather phenomena: 0.10
    - temperature/dewpoint: 0.15
    - altimeter: 0.10
    - remarks: 0.15
    """
    ref_by_fp = {metar_fingerprint(e): e for e in ref_reports}
    gen_by_fp = {metar_fingerprint(e): e for e in gen_reports}
    
    matched = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched:
        return 0.0
    
    scores = []
    for fp in matched:
        ref = ref_by_fp[fp]
        gen = gen_by_fp[fp]
        
        # Wind
        wind_score = (
            field_similarity(ref.get('wind_dir', ''), gen.get('wind_dir', '')) * 0.4 +
            field_similarity(ref.get('wind_speed', ''), gen.get('wind_speed', '')) * 0.4 +
            field_similarity(ref.get('wind_gust', ''), gen.get('wind_gust', '')) * 0.2
        )
        
        # Visibility
        vis_score = field_similarity(ref.get('visibility', ''), gen.get('visibility', ''))
        
        # Sky conditions
        sky_score = sky_similarity(ref.get('sky', []), gen.get('sky', []))
        
        # Weather phenomena
        ref_wx = ' '.join(sorted(ref.get('weather', [])))
        gen_wx = ' '.join(sorted(gen.get('weather', [])))
        wx_score = field_similarity(ref_wx, gen_wx)
        
        # Temperature and dewpoint
        temp_score = (
            field_similarity(ref.get('temp', ''), gen.get('temp', '')) * 0.5 +
            field_similarity(ref.get('dewpt', ''), gen.get('dewpt', '')) * 0.5
        )
        
        # Altimeter
        alt_score = field_similarity(ref.get('altimeter', ''), gen.get('altimeter', ''))
        
        # Remarks
        rmk_score = field_similarity(ref.get('remarks_raw', ''), gen.get('remarks_raw', ''))
        
        entry_score = (
            0.20 * wind_score +
            0.15 * vis_score +
            0.15 * sky_score +
            0.10 * wx_score +
            0.15 * temp_score +
            0.10 * alt_score +
            0.15 * rmk_score
        )
        scores.append(entry_score)
    
    return sum(scores) / len(scores)


def compute_taf_coverage(ref_tafs, gen_tafs):
    """Compute Jaccard coverage on TAF fingerprints."""
    if not ref_tafs and not gen_tafs:
        return 1.0
    if not ref_tafs or not gen_tafs:
        return 0.0
    
    ref_fps = {taf_fingerprint(e) for e in ref_tafs}
    gen_fps = {taf_fingerprint(e) for e in gen_tafs}
    
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def taf_group_similarity(ref_group, gen_group):
    """Compare two TAF forecast groups."""
    if not ref_group and not gen_group:
        return 1.0
    if not ref_group or not gen_group:
        return 0.0
    
    type_score = 1.0 if ref_group.get('group_type') == gen_group.get('group_type') else 0.0
    time_score = field_similarity(ref_group.get('from_time', ''), gen_group.get('from_time', ''))
    wind_score = (
        field_similarity(ref_group.get('wind_dir', ''), gen_group.get('wind_dir', '')) * 0.5 +
        field_similarity(ref_group.get('wind_speed', ''), gen_group.get('wind_speed', '')) * 0.5
    )
    vis_score = field_similarity(ref_group.get('visibility', ''), gen_group.get('visibility', ''))
    sky_score = sky_similarity(ref_group.get('sky', []), gen_group.get('sky', []))
    wx_score = field_similarity(
        ' '.join(sorted(ref_group.get('weather', []))),
        ' '.join(sorted(gen_group.get('weather', [])))
    )
    
    return 0.15 * type_score + 0.15 * time_score + 0.25 * wind_score + 0.15 * vis_score + 0.20 * sky_score + 0.10 * wx_score


def compute_taf_field_accuracy(ref_tafs, gen_tafs):
    """Compare TAF fields for matched forecasts."""
    ref_by_fp = {taf_fingerprint(e): e for e in ref_tafs}
    gen_by_fp = {taf_fingerprint(e): e for e in gen_tafs}
    
    matched = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched:
        return 0.0
    
    scores = []
    for fp in matched:
        ref = ref_by_fp[fp]
        gen = gen_by_fp[fp]
        
        # Compare header fields
        header_score = (
            field_similarity(ref.get('valid_from', ''), gen.get('valid_from', '')) * 0.5 +
            field_similarity(ref.get('valid_to', ''), gen.get('valid_to', '')) * 0.5
        )
        
        # Compare forecast groups using sequence matching
        ref_groups = ref.get('groups', [])
        gen_groups = gen.get('groups', [])
        
        if not ref_groups and not gen_groups:
            group_score = 1.0
        elif not ref_groups or not gen_groups:
            group_score = 0.0
        else:
            # Match groups by position (they should be in order)
            group_scores = []
            max_len = max(len(ref_groups), len(gen_groups))
            for i in range(max_len):
                if i < len(ref_groups) and i < len(gen_groups):
                    group_scores.append(taf_group_similarity(ref_groups[i], gen_groups[i]))
                else:
                    group_scores.append(0.0)  # Missing group penalty
            group_score = sum(group_scores) / max_len if max_len > 0 else 1.0
        
        taf_score = 0.30 * header_score + 0.70 * group_score
        scores.append(taf_score)
    
    return sum(scores) / len(scores)


def compute_sequence_score(ref_reports, gen_reports):
    """Compare ordering of reports by fingerprint sequence."""
    if not ref_reports and not gen_reports:
        return 1.0
    if not ref_reports or not gen_reports:
        return 0.0
    
    ref_seq = [metar_fingerprint(e) for e in ref_reports]
    gen_seq = [metar_fingerprint(e) for e in gen_reports]
    
    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


def compute_header_similarity(ref_header, gen_header):
    """Compare bulletin header fields."""
    if not ref_header and not gen_header:
        return 1.0
    if not ref_header or not gen_header:
        return 0.0
    
    scores = []
    for key in ('dtg', 'region', 'stations', 'title'):
        scores.append(field_similarity(
            ref_header.get(key, ''),
            gen_header.get(key, '')
        ))
    
    return sum(scores) / len(scores) if scores else 1.0


class DomainWeather(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "weather"
        self.summary = "ICAO METAR/TAF aviation weather bulletin with observations and terminal forecasts"
        self.description = "METAR/TAF weather reports"
        self.file_format = [".txt"]
        self.domain_parser = "metar"
        self.category = "science"

    def preprocess_context(self, context):
        """Normalize section headers in generated weather bulletins.

        LLMs frequently produce valid METAR/TAF content but with non-standard
        section headers.  The bulletin parser relies on section headers to
        determine which lines are METAR vs TAF, so we normalize any
        recognizable header to the canonical form.

        Handled variants (all case-insensitive):
        - Single-line delimited: ``==== METAR / SPECI ====``
        - Multi-line: ``====`` / ``TAFs`` / ``====`` on separate lines
        - Dash-delimited: ``--- TAFS ---``
        - Bare label lines: ``TAFs`` or ``METARs`` on a line by themselves
          (only when not a TAF report line like ``TAF KBOS …``)
        """
        _METAR_CANONICAL = [
            '============================================================',
            'METAR / SPECI OBSERVATIONS',
            '============================================================',
        ]
        _TAF_CANONICAL = [
            '============================================================',
            'TERMINAL AERODROME FORECASTS (TAF)',
            '============================================================',
        ]

        def _is_separator(s):
            """True for pure delimiter lines (====…, ----…, ***…)."""
            return bool(s) and all(c in '=-*~' for c in s)

        def _is_metar_label(upper):
            """True if the text is a METAR/SPECI section label (not a report)."""
            if 'TAF' in upper:
                return False
            if not ('METAR' in upper or 'SPECI' in upper or 'OBSERVATION' in upper):
                return False
            # Reject actual METAR/SPECI report lines: "METAR KXXX …" / "SPECI KXXX …"
            words = upper.split()
            if len(words) >= 2 and words[0] in ('METAR', 'SPECI'):
                if re.match(r'^[A-Z]{4}$', words[1]):
                    return False
            return True

        def _is_taf_label(upper):
            """True if the text is a TAF section label (not a report line)."""
            if 'METAR' in upper or 'SPECI' in upper or 'OBSERVATION' in upper:
                return False
            # Must contain TAF or FORECAST but NOT be a real TAF report
            # (reports look like "TAF KXXX …" with a 4-letter station)
            if 'TAF' not in upper and 'FORECAST' not in upper:
                return False
            # Reject actual TAF report lines: "TAF [AMD] STATION …"
            words = upper.split()
            if len(words) >= 2 and words[0] == 'TAF':
                candidate = words[1] if words[1] != 'AMD' else (words[2] if len(words) > 2 else '')
                if re.match(r'^[A-Z]{4}$', candidate):
                    return False
            return True

        def _classify_line(stripped):
            """Return 'sep', 'metar', 'taf', or None."""
            upper = stripped.upper()
            # Strip surrounding delimiter chars to get the label
            label = stripped.strip('=-*~').strip()
            label_upper = label.upper()
            if _is_separator(stripped):
                return 'sep'
            # Single-line delimited header (e.g. "==== TAF ====")
            if ('====' in stripped or '----' in stripped):
                if _is_metar_label(label_upper):
                    return 'metar'
                if _is_taf_label(label_upper):
                    return 'taf'
            # Bare / dash-delimited label (e.g. "TAFs", "--- TAFS ---")
            if label_upper and _is_metar_label(label_upper) and len(label) < 60:
                return 'metar'
            if label_upper and _is_taf_label(label_upper) and len(label) < 60:
                return 'taf'
            return None

        fixed = {}
        for filename, content in context.items():
            lines = content.split('\n')
            out_lines = []
            i = 0
            while i < len(lines):
                stripped = lines[i].strip()
                cls = _classify_line(stripped)

                if cls in ('metar', 'taf'):
                    canonical = _METAR_CANONICAL if cls == 'metar' else _TAF_CANONICAL
                    # Consume any adjacent separator lines (before was already
                    # emitted; check the line after)
                    # Check if the previous output line is a separator we
                    # already appended — if so, remove it (we'll replace)
                    if out_lines and _is_separator(out_lines[-1].strip()):
                        out_lines.pop()
                    out_lines.extend(canonical)
                    # Skip following separator line if present
                    if i + 1 < len(lines) and _is_separator(lines[i + 1].strip()):
                        i += 1
                    i += 1
                    continue

                if cls == 'sep':
                    # Look ahead: sep + label + sep?
                    if i + 1 < len(lines):
                        next_cls = _classify_line(lines[i + 1].strip())
                        if next_cls in ('metar', 'taf'):
                            # The label line will handle emitting the full
                            # canonical header (and consume trailing sep).
                            # Skip this leading separator.
                            i += 1
                            continue
                    out_lines.append(lines[i])
                    i += 1
                    continue

                out_lines.append(lines[i])
                i += 1
            fixed[filename] = '\n'.join(out_lines)
        return fixed

    def parse_context(self, context):
        """Parse context dict into structured data: header, METAR reports, and TAF reports."""
        parsed = parse_all_reports(context)
        return {
            'header': parsed['header'],
            'metar_reports': parsed['metar_reports'],
            'taf_reports': parsed['taf_reports'],
        }

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        metars = parsed['metar_reports']
        tafs = parsed['taf_reports']
        
        if not metars and not tafs:
            return {"parse_error": "No METAR or TAF reports parsed"}
        
        stations = set()
        report_types = {}
        has_weather = 0
        has_remarks = 0
        
        for m in metars:
            stations.add(m['station'])
            rt = m['report_type']
            report_types[rt] = report_types.get(rt, 0) + 1
            if m['weather']:
                has_weather += 1
            if m['remarks_raw']:
                has_remarks += 1
        
        taf_stations = set()
        total_taf_groups = 0
        for t in tafs:
            taf_stations.add(t['station'])
            total_taf_groups += len(t['groups'])
        
        return {
            "METAR/SPECI Count": len(metars),
            "TAF Count": len(tafs),
            "Stations (METAR)": len(stations),
            "Stations (TAF)": len(taf_stations),
            "Report Types": report_types,
            "With Weather": has_weather,
            "With Remarks": has_remarks,
            "TAF Groups Total": total_taf_groups,
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

        # Preprocess generated context (normalize section headers)
        generated_context = self.preprocess_context(generated_context)

        # Parse both contexts
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        
        ref_metars = ref_parsed['metar_reports']
        gen_metars = gen_parsed['metar_reports']
        ref_tafs = ref_parsed['taf_reports']
        gen_tafs = gen_parsed['taf_reports']
        
        if not ref_metars and not ref_tafs:
            return {"score": 0.0, "error": "Reference has no parseable reports"}
        if not gen_metars and not gen_tafs:
            return {"score": 0.0, "error": "Generated context has no parseable reports"}

        if debug:
            print(f"Ref METARs: {len(ref_metars)}, Gen METARs: {len(gen_metars)}")
            print(f"Ref TAFs: {len(ref_tafs)}, Gen TAFs: {len(gen_tafs)}")

        # Compute component scores
        metar_coverage = compute_metar_coverage(ref_metars, gen_metars)
        metar_fields = compute_metar_field_accuracy(ref_metars, gen_metars)
        taf_coverage = compute_taf_coverage(ref_tafs, gen_tafs)
        taf_fields = compute_taf_field_accuracy(ref_tafs, gen_tafs)
        sequence = compute_sequence_score(ref_metars, gen_metars)
        header_sim = compute_header_similarity(ref_parsed['header'], gen_parsed['header'])
        
        # Weight METAR and TAF based on how many we have
        total_ref = len(ref_metars) + len(ref_tafs)
        metar_weight = len(ref_metars) / total_ref if total_ref > 0 else 0.5
        taf_weight = len(ref_tafs) / total_ref if total_ref > 0 else 0.5
        
        # Normalize weights to sum to their allocated portion
        # Coverage (30%) → gates the score via squaring
        # Field accuracy (45%)
        # Sequence + header (25%)
        
        coverage = metar_weight * metar_coverage + taf_weight * taf_coverage
        field_accuracy = metar_weight * metar_fields + taf_weight * taf_fields
        auxiliary = 0.60 * sequence + 0.40 * header_sim
        
        # Score: coverage^2 (gate) × field_accuracy × sqrt(auxiliary)
        score = (coverage ** 2) * field_accuracy * math.sqrt(max(auxiliary, 0.0))

        eval_obj = {
            "score": score,
            "metar_coverage": metar_coverage,
            "metar_field_accuracy": metar_fields,
            "taf_coverage": taf_coverage,
            "taf_field_accuracy": taf_fields,
            "sequence_score": sequence,
            "header_similarity": header_sim,
            "ref_metar_count": len(ref_metars),
            "gen_metar_count": len(gen_metars),
            "ref_taf_count": len(ref_tafs),
            "gen_taf_count": len(gen_tafs),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
