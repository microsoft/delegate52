from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, ujson as json


def parse_speaker_turns(text):
    # Parse earnings transcript into speaker turns: [(speaker, content), ...]
    # Format: "Speaker Name: content..." where content may span until next speaker
    turns = []
    # Match pattern: Name (possibly with title): followed by content
    # Speakers are at line start, name ends with colon
    lines = text.split('\n')
    current_speaker = None
    current_content = []
    
    for line in lines:
        # Check if line starts with a speaker (Name: or Name Name: pattern)
        speaker_match = re.match(r'^([A-Z][a-zA-Z\s\'\-]+?):\s*(.*)$', line)
        if speaker_match:
            # Save previous turn if exists
            if current_speaker is not None:
                turns.append((current_speaker, ' '.join(current_content).strip()))
            current_speaker = speaker_match.group(1).strip()
            current_content = [speaker_match.group(2).strip()] if speaker_match.group(2).strip() else []
        else:
            # Continue current speaker's content
            if current_speaker is not None and line.strip():
                current_content.append(line.strip())
    
    # Don't forget last turn
    if current_speaker is not None:
        turns.append((current_speaker, ' '.join(current_content).strip()))
    
    return turns


def extract_metrics(text):
    # Extract financial metrics: numbers with units/context
    metrics = []
    # Match patterns like: $1.48 billion, 8%, $0.98, 24.9%, etc.
    patterns = [
        r'\$[\d,]+\.?\d*\s*(?:billion|million)?\b',  # Dollar amounts
        r'\b\d+\.?\d*\s*(?:billion|million)\b',  # Amounts with billion/million
        r'\b\d+\.?\d*%',  # Percentages
        r'\b\d+\.?\d*\s*(?:basis points|bps)\b',  # Basis points
    ]
    combined_pattern = '|'.join(f'({p})' for p in patterns)
    for match in re.finditer(combined_pattern, text, re.IGNORECASE):
        metrics.append(match.group(0).strip())
    return metrics


def normalize_speaker_name(name):
    # Normalize speaker names for matching (handle slight variations)
    name = name.strip().lower()
    name = re.sub(r'\s+', ' ', name)
    return name


def compute_speaker_sequence_score(ref_turns, gen_turns):
    # Compare sequence of speakers (order matters)
    if not ref_turns:
        return 1.0 if not gen_turns else 0.0
    if not gen_turns:
        return 0.0
    
    ref_speakers = [normalize_speaker_name(t[0]) for t in ref_turns]
    gen_speakers = [normalize_speaker_name(t[0]) for t in gen_turns]
    return SequenceMatcher(None, ref_speakers, gen_speakers).ratio()


def compute_content_score(ref_turns, gen_turns):
    # Match turns by speaker and compare content
    if not ref_turns:
        return 1.0 if not gen_turns else 0.0
    if not gen_turns:
        return 0.0
    
    # Build speaker -> content map for generated (concatenate if multiple turns)
    gen_by_speaker = {}
    for speaker, content in gen_turns:
        norm_speaker = normalize_speaker_name(speaker)
        if norm_speaker not in gen_by_speaker:
            gen_by_speaker[norm_speaker] = []
        gen_by_speaker[norm_speaker].append(content)
    
    # Compare each reference turn's content
    scores = []
    for speaker, ref_content in ref_turns:
        norm_speaker = normalize_speaker_name(speaker)
        if norm_speaker in gen_by_speaker and gen_by_speaker[norm_speaker]:
            gen_content = gen_by_speaker[norm_speaker].pop(0)
            scores.append(SequenceMatcher(None, ref_content, gen_content).ratio())
        else:
            scores.append(0.0)
    
    return sum(scores) / len(scores) if scores else 0.0


def compute_metrics_score(ref_text, gen_text):
    # Compare financial metrics preservation
    ref_metrics = extract_metrics(ref_text)
    gen_metrics = extract_metrics(gen_text)
    
    if not ref_metrics:
        return 1.0 if not gen_metrics else 0.0
    if not gen_metrics:
        return 0.0
    
    # Check how many reference metrics appear in generated
    gen_metrics_set = set(m.lower().replace(' ', '') for m in gen_metrics)
    matches = sum(1 for m in ref_metrics if m.lower().replace(' ', '') in gen_metrics_set)
    
    # Penalize for missing or extra metrics
    precision = matches / len(gen_metrics) if gen_metrics else 0
    recall = matches / len(ref_metrics) if ref_metrics else 0
    
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)  # F1 score


class DomainEarncall(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "earncall"
        self.summary = "Earnings call transcripts with speaker turns and Q&A sections"
        self.description = "Earnings call transcripts"
        self.file_format = [".txt"]
        self.domain_parser = "custom"
        self.category = "everyday"
    
    def get_full_text(self, context):
        # Single file assumed for basic_state
        return list(context.values())[0] if context else ""
    
    def parse_context(self, context):
        text = self.get_full_text(context)
        turns = parse_speaker_turns(text)
        speakers = set(t[0] for t in turns if t[0])
        metrics = extract_metrics(text)
        return {
            "text": text,
            "turns": turns,
            "speakers": speakers,
            "metrics": metrics,
        }
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        return {
            "Speaker Turns": len(parsed["turns"]),
            "Speakers": len(parsed["speakers"]),
            "Financial Metrics": len(parsed["metrics"]),
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        
        # Compute component scores
        score_speaker_sequence = compute_speaker_sequence_score(ref_parsed["turns"], gen_parsed["turns"])
        score_content = compute_content_score(ref_parsed["turns"], gen_parsed["turns"])
        score_metrics = compute_metrics_score(ref_parsed["text"], gen_parsed["text"])
        
        # Weighted aggregate: content most important, then metrics, then speaker order
        score = 0.40 * score_content + 0.35 * score_metrics + 0.25 * score_speaker_sequence
        
        eval_obj = {
            "score": score,
            "score_speaker_sequence": score_speaker_sequence,
            "score_content": score_content,
            "score_metrics": score_metrics,
            "count_turns_reference": len(ref_parsed["turns"]),
            "count_turns_generated": len(gen_parsed["turns"]),
            "count_metrics_reference": len(ref_parsed["metrics"]),
            "count_metrics_generated": len(gen_parsed["metrics"]),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

