from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
from icalendar import Calendar
from datetime import date, timedelta
import os, math, re, ujson as json


def strip_unused_ics_components(content):
    # Remove VTIMEZONE, VALARM, VTODO, VJOURNAL, VFREEBUSY blocks - we only need VEVENT
    # These can contain invalid syntax that breaks parsing but aren't used for evaluation
    patterns = [
        r'BEGIN:VTIMEZONE.*?END:VTIMEZONE\r?\n?',
        r'BEGIN:VALARM.*?END:VALARM\r?\n?',
        r'BEGIN:VTODO.*?END:VTODO\r?\n?',
        r'BEGIN:VJOURNAL.*?END:VJOURNAL\r?\n?',
        r'BEGIN:VFREEBUSY.*?END:VFREEBUSY\r?\n?',
    ]
    for pattern in patterns:
        content = re.sub(pattern, '', content, flags=re.DOTALL | re.IGNORECASE)
    return content


def parse_ics_events(content):
    try:
        cal = Calendar.from_ical(content)
    except Exception as e:
        print(f"\033[91mICS parsing error: {e}\033[0m")
        return []
    
    events = []
    for component in cal.walk():
        if component.name == 'VEVENT':
            dtstart = component.get('DTSTART')
            dtend = component.get('DTEND')
            categories = component.get('CATEGORIES')
            # Extract individual category values (not a single opaque string)
            cat_values = []
            if categories:
                if hasattr(categories, 'cats'):
                    cat_values = [str(c).strip() for c in categories.cats if str(c).strip()]
                elif hasattr(categories, 'to_ical'):
                    cat_values = [s.strip() for s in str(categories.to_ical(), 'utf-8').split(',') if s.strip()]
                else:
                    v = str(categories).strip()
                    if v:
                        cat_values = [v]
            
            # Fallback: extract category from DESCRIPTION if it starts with "Track:"
            if not cat_values:
                description = str(component.get('DESCRIPTION', ''))
                if description.lower().startswith('track:'):
                    cat_values = [description[6:].strip()]
            
            dt_start = dtstart.dt if dtstart else None
            dt_end = dtend.dt if dtend else None

            # Infer DTEND for all-day events when missing (RFC 5545: duration = 1 day)
            if dt_end is None and dt_start is not None and isinstance(dt_start, date) and not hasattr(dt_start, 'hour'):
                dt_end = dt_start + timedelta(days=1)

            events.append({
                'uid': str(component.get('UID', '')),
                'summary': str(component.get('SUMMARY', '')),
                'dtstart': dt_start,
                'dtend': dt_end,
                'categories': cat_values,
                'location': str(component.get('LOCATION', '')),
            })
    return events


def parse_all_ics_events(context):
    all_events = []
    for filename, content in context.items():
        if filename.endswith('.ics'):
            events = parse_ics_events(content)
            all_events.extend(events)
    return all_events


def normalize_datetime_str(dt):
    if dt is None:
        return ''
    if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)  # Strip timezone to compare local time
    return dt.isoformat() if hasattr(dt, 'isoformat') else str(dt)


def event_fingerprint(event):
    uid = event['uid'].strip()
    # Strip @domain suffix — LLMs sometimes add/remove email-style domains on UIDs
    if '@' in uid:
        uid = uid.split('@')[0]
    return uid


def compute_event_coverage_score(ref_events, gen_events):
    if not ref_events and not gen_events:
        return 1.0
    if not ref_events or not gen_events:
        return 0.0
    
    ref_fps = {event_fingerprint(e) for e in ref_events}
    gen_fps = {event_fingerprint(e) for e in gen_events}
    
    intersection = len(ref_fps & gen_fps)
    union = len(ref_fps | gen_fps)
    return intersection / union if union > 0 else 1.0


def compute_event_accuracy_score(ref_events, gen_events):
    if not ref_events and not gen_events:
        return 1.0
    if not ref_events or not gen_events:
        return 0.0
    
    ref_by_fp = {event_fingerprint(e): e for e in ref_events}
    gen_by_fp = {event_fingerprint(e): e for e in gen_events}
    
    matched_fps = set(ref_by_fp.keys()) & set(gen_by_fp.keys())
    if not matched_fps:
        return 0.0
    
    field_scores = []
    for fp in matched_fps:
        ref_event = ref_by_fp[fp]
        gen_event = gen_by_fp[fp]
        
        score = 0.0
        total = 0.0
        
        # Compare DTEND
        ref_dtend = ref_event['dtend']
        gen_dtend = gen_event['dtend']
        if ref_dtend or gen_dtend:
            total += 1.0
            if ref_dtend and gen_dtend:
                ref_str = normalize_datetime_str(ref_dtend)
                gen_str = normalize_datetime_str(gen_dtend)
                if ref_str == gen_str:
                    score += 1.0
                else:
                    score += SequenceMatcher(None, ref_str, gen_str).ratio() * 0.5
        
        # Compare LOCATION (stricter - reduced partial credit)
        ref_loc = ref_event['location'].lower().strip()
        gen_loc = gen_event['location'].lower().strip()
        if ref_loc or gen_loc:
            total += 1.0
            if ref_loc == gen_loc:
                score += 1.0
            elif ref_loc and gen_loc:
                ratio = SequenceMatcher(None, ref_loc, gen_loc).ratio()
                score += ratio * 0.5  # only 50% partial credit for fuzzy match
        
        # Compare CATEGORIES — only penalize when ref has categories
        ref_cat_set = {c.lower().strip() for c in ref_event['categories']} if ref_event['categories'] else set()
        gen_cat_set = {c.lower().strip() for c in gen_event['categories']} if gen_event['categories'] else set()
        if ref_cat_set:  # only score when reference has categories
            total += 1.0
            if ref_cat_set == gen_cat_set:
                score += 1.0
            elif gen_cat_set:
                # Jaccard similarity on individual category values
                intersection = len(ref_cat_set & gen_cat_set)
                union = len(ref_cat_set | gen_cat_set)
                score += intersection / union if union > 0 else 0.0
        
        field_scores.append(score / total if total > 0 else 1.0)
    
    return sum(field_scores) / len(field_scores) if field_scores else 0.0


def compute_time_ordering_score(ref_events, gen_events):
    if not ref_events and not gen_events:
        return 1.0
    if not ref_events or not gen_events:
        return 0.0
    
    # Sort by dtstart, then by UID to break ties deterministically
    # This ensures events at the same time don't penalize for arbitrary file order
    def sort_key(e):
        return (normalize_datetime_str(e['dtstart']), event_fingerprint(e))
    
    ref_sorted = sorted(ref_events, key=sort_key)
    gen_sorted = sorted(gen_events, key=sort_key)
    
    ref_seq = [event_fingerprint(e) for e in ref_sorted]
    gen_seq = [event_fingerprint(e) for e in gen_sorted]
    
    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


def compute_category_score(ref_events, gen_events):
    if not ref_events and not gen_events:
        return 1.0
    if not ref_events or not gen_events:
        return 0.0
    
    ref_cats = set()
    gen_cats = set()
    for e in ref_events:
        for c in (e['categories'] or []):
            ref_cats.add(c.lower().strip())
    for e in gen_events:
        for c in (e['categories'] or []):
            gen_cats.add(c.lower().strip())
    
    if not ref_cats and not gen_cats:
        return 1.0
    if not ref_cats:
        return 1.0  # Don't penalize extra categories when reference has none
    if not gen_cats:
        return 0.0
    
    intersection = len(ref_cats & gen_cats)
    union = len(ref_cats | gen_cats)
    return intersection / union if union > 0 else 1.0


class DomainCalendar(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "calendar"
        self.summary = "iCalendar (.ics) files with events, schedules, and conference sessions"
        self.description = "iCalendar events"
        self.file_format = [".ics"]
        self.domain_parser = "icalendar"
        self.category = "records"
    
    def preprocess_context(self, context):
        """Strip non-VEVENT components from .ics files that can break parsing."""
        result = {}
        for filename, content in context.items():
            if filename.endswith('.ics'):
                content = strip_unused_ics_components(content)
            result[filename] = content
        return result

    def parse_all_events(self, context):
        return parse_all_ics_events(context)
    
    def parse_context(self, context):
        context = self.preprocess_context(context)
        events = self.parse_all_events(context)
        return {"events": events}
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        events = parsed["events"]
        categories = set()
        with_location = 0
        for e in events:
            if e.get('categories'):
                categories.update(e['categories'] if isinstance(e['categories'], list) else [e['categories']])
            if e.get('location'):
                with_location += 1
        return {
            "Events": len(events),
            "Categories": len(categories),
            "With Location": with_location,
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
        
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        ref_events = ref_parsed["events"]
        gen_events = gen_parsed["events"]
        
        if debug:
            print(f"Reference events: {len(ref_events)}, Generated events: {len(gen_events)}")
        
        # Compute component scores
        coverage_score = compute_event_coverage_score(ref_events, gen_events)
        accuracy_score = compute_event_accuracy_score(ref_events, gen_events)
        ordering_score = compute_time_ordering_score(ref_events, gen_events)
        category_score = compute_category_score(ref_events, gen_events)
        
        # Multiplicative scoring: coverage^2 gates everything, accuracy multiplies, ordering/category averaged
        # This harshly penalizes missing events and field errors
        secondary_avg = (ordering_score + category_score) / 2.0
        score = (coverage_score ** 2) * accuracy_score * math.sqrt(secondary_avg) if secondary_avg > 0 else 0.0
        
        eval_obj = {
            "score": score,
            "event_coverage_score": coverage_score,
            "event_accuracy_score": accuracy_score,
            "time_ordering_score": ordering_score,
            "category_score": category_score,
            "ref_event_count": len(ref_events),
            "gen_event_count": len(gen_events),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
