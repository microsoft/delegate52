from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import ly.document
import ly.music.items as items
import os, ujson as json


NOTE_NAMES = ['c', 'd', 'e', 'f', 'g', 'a', 'b']


def pitch_to_semitone(note_idx, alter):
    # Convert ly pitch (note index 0-6, alter as Fraction) to semitone (0-11)
    semitones = [0, 2, 4, 5, 7, 9, 11]  # c, d, e, f, g, a, b
    base = semitones[note_idx % 7]
    # alter is a Fraction: 1/2 = sharp, -1/2 = flat, 1 = double sharp, etc.
    alter_semitones = int(float(alter) * 2) if alter else 0
    return (base + alter_semitones) % 12


def parse_lilypond(ly_content):
    doc = ly.document.Document(ly_content)
    tree = ly.music.document(doc)
    
    result = {'voices': {}, 'lyrics': {}, 'header': {}, 'key': None, 'time': None, 'all_notes': [], 'all_dynamics': []}
    
    for item in tree:
        if isinstance(item, items.Assignment):
            name = str(item.name())  # Convert token to string
            value = item.value()
            
            # Check if it's a voice/music assignment (contains notes)
            if value and hasattr(value, 'iter_depth'):
                notes = []
                dynamics = []
                is_voice = False
                
                for desc in value.iter_depth():
                    if isinstance(desc, items.Note):
                        is_voice = True
                        pitch = desc.pitch
                        semitone = pitch_to_semitone(pitch.note, pitch.alter)
                        duration = desc.length()  # returns Fraction
                        notes.append({'semitone': semitone, 'note': pitch.note, 'alter': float(pitch.alter) if pitch.alter else 0, 'octave': pitch.octave, 'duration': float(duration) if duration else 0.25})
                    elif isinstance(desc, items.Dynamic):
                        dynamics.append(str(desc.token))
                    elif isinstance(desc, items.LyricText):
                        # This is a lyrics variable
                        pass
                
                if is_voice and notes:
                    result['voices'][name] = {'notes': notes, 'dynamics': dynamics}
                    result['all_notes'].extend(notes)
                    result['all_dynamics'].extend(dynamics)
            
            # Check for lyrics
            if isinstance(value, items.LyricMode):
                words = []
                for desc in value.iter_depth():
                    if isinstance(desc, items.LyricText):
                        text = str(desc.token).strip()
                        if text:
                            words.append(text)
                if words:
                    result['lyrics'][name] = words
            
            # Check for global settings (key, time)
            if name == 'global' and value:
                for desc in value.iter_depth():
                    if isinstance(desc, items.KeySignature):
                        for child in desc:
                            if isinstance(child, items.Note):
                                key_pitch = child.pitch.note
                                key_alter = float(child.pitch.alter) if child.pitch.alter else 0
                            elif isinstance(child, items.Command):
                                key_mode = str(child.token).replace('\\', '')
                        result['key'] = (key_pitch, key_alter, key_mode if 'key_mode' in dir() else 'major')
                    elif isinstance(desc, items.TimeSignature):
                        result['time'] = (desc.numerator(), desc.fraction())
        
        # Extract header
        elif isinstance(item, items.Header):
            for desc in item.iter_depth():
                if isinstance(desc, items.Assignment):
                    field_name = str(desc.name())  # Convert token to string
                    field_value = desc.value()
                    if isinstance(field_value, items.String):
                        result['header'][field_name] = field_value.value()
    
    return result


def compute_note_sequence_score(ref_notes, gen_notes):
    if not ref_notes and not gen_notes:
        return 1.0
    if not ref_notes or not gen_notes:
        return 0.0
    ref_pitches = [n['semitone'] for n in ref_notes]
    gen_pitches = [n['semitone'] for n in gen_notes]
    return SequenceMatcher(None, ref_pitches, gen_pitches).ratio()


def compute_rhythm_score(ref_notes, gen_notes):
    if not ref_notes and not gen_notes:
        return 1.0
    if not ref_notes or not gen_notes:
        return 0.0
    ref_durations = [n['duration'] for n in ref_notes]
    gen_durations = [n['duration'] for n in gen_notes]
    return SequenceMatcher(None, ref_durations, gen_durations).ratio()


def _voice_matched_scores(ref_parsed, gen_parsed):
    """Compute note_sequence and rhythm scores with per-voice matching.

    LLMs may define voice variables in a different order or use different
    variable names (e.g. splitting one monolithic voice into per-section
    sub-voices).  The flat all_notes comparison is sensitive to the
    definition order and produces artificially low scores when voice
    ordering differs.

    This helper compares notes *per voice* with matching, then returns
    max(flat_score, per_voice_score) so the score never decreases.
    """
    ref_notes = ref_parsed['all_notes']
    gen_notes = gen_parsed['all_notes']
    ref_voices = ref_parsed['voices']
    gen_voices = gen_parsed['voices']

    # Flat scores (original behaviour)
    flat_note = compute_note_sequence_score(ref_notes, gen_notes)
    flat_rhythm = compute_rhythm_score(ref_notes, gen_notes)

    if not ref_voices or not gen_voices:
        return flat_note, flat_rhythm

    # Build per-voice pitch/duration lists
    ref_v_pitch = {n: [x['semitone'] for x in v['notes']] for n, v in ref_voices.items()}
    ref_v_dur   = {n: [x['duration'] for x in v['notes']] for n, v in ref_voices.items()}
    gen_v_pitch = {n: [x['semitone'] for x in v['notes']] for n, v in gen_voices.items()}
    gen_v_dur   = {n: [x['duration'] for x in v['notes']] for n, v in gen_voices.items()}

    if set(ref_v_pitch) == set(gen_v_pitch):
        # Same voice names – match by name
        tw, ws_note, ws_rhythm = 0, 0.0, 0.0
        for name in ref_v_pitch:
            w = max(len(ref_v_pitch[name]), len(gen_v_pitch[name]))
            if w:
                ws_note   += SequenceMatcher(None, ref_v_pitch[name], gen_v_pitch[name]).ratio() * w
                ws_rhythm += SequenceMatcher(None, ref_v_dur[name],   gen_v_dur[name]).ratio() * w
                tw += w
        pv_note   = ws_note   / tw if tw else 1.0
        pv_rhythm = ws_rhythm / tw if tw else 1.0
    else:
        # Different voice names – match by pitch similarity
        gen_to_ref = {}
        for gn, gp in gen_v_pitch.items():
            gen_to_ref[gn] = max(ref_v_pitch, key=lambda rn: SequenceMatcher(None, ref_v_pitch[rn], gp).ratio())

        ref_groups = {rn: [] for rn in ref_v_pitch}
        for gn in gen_v_pitch:           # preserves dict insertion order
            ref_groups[gen_to_ref[gn]].append(gn)

        tw, ws_note, ws_rhythm = 0, 0.0, 0.0
        for rn in ref_v_pitch:
            rp, rd = ref_v_pitch[rn], ref_v_dur[rn]
            gp, gd = [], []
            for gn in ref_groups[rn]:
                gp.extend(gen_v_pitch[gn])
                gd.extend(gen_v_dur[gn])
            w = max(len(rp), len(gp)) if (rp or gp) else 0
            if w:
                ws_note   += SequenceMatcher(None, rp, gp).ratio() * w
                ws_rhythm += SequenceMatcher(None, rd, gd).ratio() * w
                tw += w
        pv_note   = ws_note   / tw if tw else 1.0
        pv_rhythm = ws_rhythm / tw if tw else 1.0

    return max(flat_note, pv_note), max(flat_rhythm, pv_rhythm)


def compute_dynamics_score(ref_dynamics, gen_dynamics):
    if not ref_dynamics and not gen_dynamics:
        return 1.0
    if not ref_dynamics or not gen_dynamics:
        return 0.0
    return SequenceMatcher(None, ref_dynamics, gen_dynamics).ratio()


def compute_lyrics_score(ref_lyrics, gen_lyrics):
    if not ref_lyrics and not gen_lyrics:
        return 1.0
    if not ref_lyrics or not gen_lyrics:
        return 0.0
    # Flatten all lyrics
    ref_all = []
    gen_all = []
    for words in ref_lyrics.values():
        ref_all.extend(words)
    for words in gen_lyrics.values():
        gen_all.extend(words)
    return SequenceMatcher(None, ref_all, gen_all).ratio()


def compute_structural_score(ref_parsed, gen_parsed):
    score = 0.0
    total = 0.0
    
    # Key signature match
    if ref_parsed['key'] is not None or gen_parsed['key'] is not None:
        total += 1.0
        if ref_parsed['key'] == gen_parsed['key']:
            score += 1.0
    
    # Time signature match
    if ref_parsed['time'] is not None or gen_parsed['time'] is not None:
        total += 1.0
        if ref_parsed['time'] == gen_parsed['time']:
            score += 1.0
    
    # Header fields match
    important_fields = ['title', 'composer', 'arranger']
    for field in important_fields:
        ref_val = ref_parsed['header'].get(field, '')
        gen_val = gen_parsed['header'].get(field, '')
        if ref_val or gen_val:
            total += 1.0
            if ref_val.lower().strip() == gen_val.lower().strip():
                score += 1.0
    
    # Voice count similarity
    ref_voices = len(ref_parsed['voices'])
    gen_voices = len(gen_parsed['voices'])
    if ref_voices > 0 or gen_voices > 0:
        total += 1.0
        score += min(ref_voices, gen_voices) / max(ref_voices, gen_voices)
    
    return score / total if total > 0 else 1.0


def merge_all_content(context):
    merged = ""
    for filename, content in context.items():
        if filename.endswith('.ly'):
            merged += content + "\n"
    return merged


class DomainMusicSheet(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "musicsheet"
        self.summary = "LilyPond music notation with notes, rhythms, and score layout"
        self.description = "LilyPond music notation"
        self.file_format = [".ly"]
        self.domain_parser = "ly"
        self.category = "creative"

    def parse_context(self, context):
        merged = merge_all_content(context)
        parsed = parse_lilypond(merged)
        return parsed

    def compute_domain_statistics(self, context):
        try:
            parsed = self.parse_context(context)
            num_notes = len(parsed.get('all_notes', []))
            num_voices = len(parsed.get('voices', {}))
            num_dynamics = len(parsed.get('all_dynamics', []))
            lyrics_words = sum(len(w) for w in parsed.get('lyrics', {}).values())
            header = parsed.get('header', {})
            return {
                "Notes": num_notes,
                "Voices": num_voices,
                "Dynamics": num_dynamics,
                "Lyric Words": lyrics_words,
                "Title": header.get('title', ''),
            }
        except Exception:
            return {}
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        # Merge all .ly files and parse
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        
        # Compute component scores (per-voice matching for robustness)
        note_score, rhythm_score = _voice_matched_scores(ref_parsed, gen_parsed)
        dynamics_score = compute_dynamics_score(ref_parsed['all_dynamics'], gen_parsed['all_dynamics'])
        lyrics_score = compute_lyrics_score(ref_parsed['lyrics'], gen_parsed['lyrics'])
        structural_score = compute_structural_score(ref_parsed, gen_parsed)
        
        # Weighted aggregate
        score = 0.35 * note_score + 0.25 * rhythm_score + 0.15 * dynamics_score + 0.15 * lyrics_score + 0.10 * structural_score
        
        eval_obj = {
            "score": score,
            "note_sequence_score": note_score,
            "rhythm_score": rhythm_score,
            "dynamics_score": dynamics_score,
            "lyrics_score": lyrics_score,
            "structural_score": structural_score,
            "ref_note_count": len(ref_parsed['all_notes']),
            "gen_note_count": len(gen_parsed['all_notes']),
            "ref_voice_count": len(ref_parsed['voices']),
            "gen_voice_count": len(gen_parsed['voices']),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
