from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, ujson as json
import numpy as np
from scipy.optimize import linear_sum_assignment


def parse_salary(salary_str):
    # Parse salary string like "$165,000/year" or "$51/hour"
    if not salary_str:
        return None, None
    match = re.search(r'\$?([\d,]+(?:\.\d+)?)\s*/\s*(year|hour)', salary_str, re.IGNORECASE)
    if not match:
        return None, None
    amount = float(match.group(1).replace(',', ''))
    period = match.group(2).lower()
    return amount, period


def normalize_salary_to_annual(amount, period):
    if amount is None:
        return None
    if period == 'hour':
        return amount * 2080  # standard work hours/year
    return amount


def parse_compact_job_line(line):
    """Parse a compact single-line job entry like:
    [JOB-XXXX] Title — Company (Location) — $Amount/period — Skills: skill1, skill2
    Also handles pipe-delimited format:
    JOB-XXXX | Title | Company | Location | $Amount/period | Skills: skill1, skill2
    Returns a job dict or None if the line doesn't match compact format.
    """
    job_match = re.match(r'\[?(JOB-\d+)\]?\s*(.+)', line)
    if not job_match:
        return None

    job = {'job_id': job_match.group(1)}
    rest = job_match.group(2).strip()

    # Detect delimiter: pipe-delimited vs em/en-dash-delimited
    # Pipe-delimited: rest starts with '|' or contains ' | '
    if rest.startswith('|') or ' | ' in rest:
        # Strip leading pipe if present
        if rest.startswith('|'):
            rest = rest[1:].strip()
        parts = [p.strip() for p in rest.split('|')]
    else:
        # Split by em dash (—) or en dash (–) only; avoid splitting on hyphens which
        # appear in company names like "Get It Recruit - Information Technology"
        parts = re.split(r'\s*[—–]\s*', rest)

    if not parts:
        return None

    job['title'] = parts[0].strip()
    job['company'] = ''
    job['location'] = ''
    job['type'] = ''
    job['salary_amount'] = None
    job['salary_period'] = None
    job['salary_raw'] = ''
    job['skills'] = []
    job['posted'] = ''

    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue

        # Check if it's a salary (contains $XX/year or $XX/hour)
        if re.search(r'\$[\d,]+(?:\.\d+)?\s*/\s*(?:year|hour)', part, re.IGNORECASE):
            amount, period = parse_salary(part)
            job['salary_amount'] = amount
            job['salary_period'] = period
            job['salary_raw'] = part
            continue

        # Check if it's a skills line
        if part.lower().startswith('skills:'):
            skills_str = part[7:].strip()
            job['skills'] = [s.strip().lower() for s in skills_str.split(',') if s.strip()]
            continue

        # Check if it's a labeled field (e.g., "Title: ...", "Tech: ...")
        labeled_match = re.match(r'(Title|Tech|Type|Posted|Location|Company):\s*(.*)', part, re.IGNORECASE)
        if labeled_match:
            label = labeled_match.group(1).lower()
            value = labeled_match.group(2).strip()
            if label == 'title':
                job['title'] = value
            elif label in ('tech', 'skills'):
                job['skills'] = [s.strip().lower() for s in value.split(',') if s.strip()]
            elif label == 'type':
                job['type'] = value
            elif label == 'posted':
                job['posted'] = value
            elif label == 'location':
                job['location'] = value
            elif label == 'company':
                job['company'] = value
            continue

        # Check if it's a posted date
        if re.match(r'\d{4}-\d{2}-\d{2}', part):
            job['posted'] = part
            continue

        # Check if it contains a location in parentheses: "Company (Location)"
        loc_match = re.match(r'(.+?)\s*\((.+?)\)\s*$', part)
        if loc_match:
            if not job['company']:
                job['company'] = loc_match.group(1).strip()
            job['location'] = loc_match.group(2).strip()
            continue

        # Otherwise treat as company name (first unrecognized part)
        if not job['company']:
            job['company'] = part
        elif not job['location']:
            job['location'] = part

    return job


def parse_job_block(block):
    # Parse a single job block into structured dict
    lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
    if not lines:
        return None
    
    job = {}
    
    # First line: [JOB-XXXX] Title
    first_line = lines[0]
    job_match = re.match(r'\[?(JOB-\d+)\]?\s*(.+)', first_line)
    if not job_match:
        return None
    job['job_id'] = job_match.group(1)
    job['title'] = job_match.group(2).strip()
    
    # Parse remaining labeled fields (only lines that belong to THIS job block,
    # stop at the next [JOB-XXXX] marker)
    for line in lines[1:]:
        if re.match(r'\[?(JOB-\d+)\]?', line):
            break  # next job starts here
        if line.startswith('Company:'):
            job['company'] = line.replace('Company:', '').strip()
        elif line.startswith('Location:'):
            job['location'] = line.replace('Location:', '').strip()
        elif line.startswith('Type:'):
            job['type'] = line.replace('Type:', '').strip()
        elif line.startswith('Salary:') or line.startswith('Adjusted Salary:'):
            salary_str = re.sub(r'^(Adjusted )?Salary:\s*', '', line)
            amount, period = parse_salary(salary_str)
            job['salary_amount'] = amount
            job['salary_period'] = period
            job['salary_raw'] = salary_str.strip()
        elif line.startswith('Skills:'):
            skills_str = line.replace('Skills:', '').strip()
            job['skills'] = [s.strip().lower() for s in skills_str.split(',') if s.strip()]
        elif line.startswith('Posted:'):
            job['posted'] = line.replace('Posted:', '').strip()
    
    # Set defaults for missing fields
    job.setdefault('company', '')
    job.setdefault('location', '')
    job.setdefault('type', '')
    job.setdefault('salary_amount', None)
    job.setdefault('salary_period', None)
    job.setdefault('salary_raw', '')
    job.setdefault('skills', [])
    job.setdefault('posted', '')

    # Fallback: if key fields are empty and the first line looks like compact format
    # (contains em dashes, en dashes, or pipe delimiters), try compact parsing
    has_labeled_fields = bool(job['company'] or job['salary_raw'] or job['skills'])
    has_compact_delimiters = bool(re.search(r'[—–]', first_line) or ' | ' in first_line or first_line.rstrip().endswith('|'))
    if not has_labeled_fields and has_compact_delimiters:
        compact_job = parse_compact_job_line(first_line)
        if compact_job:
            return compact_job
    
    return job


def parse_job_board(text):
    # Split into job blocks by "---" separator, ignoring header and footer
    jobs = []
    
    # Split on "---" lines
    blocks = re.split(r'\n\s*---\s*\n', text)
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        
        # Find all JOB-XXXX occurrences in block, with or without brackets
        job_matches = list(re.finditer(r'\[?JOB-\d+\]?', block))
        if not job_matches:
            continue
        
        # If multiple jobs in block (shouldn't happen normally), or job not at start,
        # extract just the job portion starting from JOB-XXXX
        for match in job_matches:
            job_start = match.start()
            # Find the end of this job (next job marker or end of block)
            remaining = block[job_start:]
            job = parse_job_block(remaining)
            if job:
                jobs.append(job)
    
    return jobs


def compute_text_similarity(ref, cand):
    if not ref and not cand:
        return 1.0
    if not ref or not cand:
        return 0.0
    return SequenceMatcher(None, ref.lower().strip(), cand.lower().strip()).ratio()


def compute_salary_similarity(ref_job, cand_job):
    ref_annual = normalize_salary_to_annual(ref_job['salary_amount'], ref_job['salary_period'])
    cand_annual = normalize_salary_to_annual(cand_job['salary_amount'], cand_job['salary_period'])
    
    if ref_annual is None and cand_annual is None:
        return 1.0
    if ref_annual is None or cand_annual is None:
        return 0.0
    if ref_annual == 0 or cand_annual == 0:
        return 0.0
    
    return min(ref_annual, cand_annual) / max(ref_annual, cand_annual)


def compute_skills_similarity(ref_skills, cand_skills):
    ref_set = set(s.lower() for s in ref_skills)
    cand_set = set(s.lower() for s in cand_skills)
    
    if not ref_set and not cand_set:
        return 1.0
    if not ref_set or not cand_set:
        return 0.0
    
    intersection = len(ref_set & cand_set)
    union = len(ref_set | cand_set)
    return intersection / union if union > 0 else 1.0


def compute_job_similarity(ref_job, cand_job):
    # Weighted field similarity
    scores = []
    weights = []
    
    # Title (15%)
    scores.append(compute_text_similarity(ref_job['title'], cand_job['title']))
    weights.append(0.15)
    
    # Company (15%)
    scores.append(compute_text_similarity(ref_job['company'], cand_job['company']))
    weights.append(0.15)
    
    # Location (15%)
    scores.append(compute_text_similarity(ref_job['location'], cand_job['location']))
    weights.append(0.15)
    
    # Type (10%)
    type_sim = 1.0 if ref_job['type'].lower() == cand_job['type'].lower() else compute_text_similarity(ref_job['type'], cand_job['type'])
    scores.append(type_sim)
    weights.append(0.10)
    
    # Salary (25%)
    scores.append(compute_salary_similarity(ref_job, cand_job))
    weights.append(0.25)
    
    # Skills (15%)
    scores.append(compute_skills_similarity(ref_job['skills'], cand_job['skills']))
    weights.append(0.15)
    
    # Posted date (5%)
    posted_sim = 1.0 if ref_job['posted'] == cand_job['posted'] else 0.0
    scores.append(posted_sim)
    weights.append(0.05)
    
    return sum(s * w for s, w in zip(scores, weights))


def compute_job_coverage_score(ref_jobs, gen_jobs):
    if not ref_jobs and not gen_jobs:
        return 1.0
    if not ref_jobs or not gen_jobs:
        return 0.0
    
    ref_ids = {j['job_id'] for j in ref_jobs}
    gen_ids = {j['job_id'] for j in gen_jobs}
    
    intersection = len(ref_ids & gen_ids)
    union = len(ref_ids | gen_ids)
    return intersection / union if union > 0 else 1.0


def compute_matched_accuracy(ref_jobs, gen_jobs):
    if not ref_jobs and not gen_jobs:
        return 1.0, []
    if not ref_jobs or not gen_jobs:
        return 0.0, []
    
    n_ref, n_gen = len(ref_jobs), len(gen_jobs)
    
    # Build similarity matrix
    sim_matrix = np.zeros((n_ref, n_gen))
    for i, ref in enumerate(ref_jobs):
        for j, gen in enumerate(gen_jobs):
            sim_matrix[i, j] = compute_job_similarity(ref, gen)
    
    # Hungarian algorithm for optimal matching
    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    matched_pairs = list(zip(row_ind, col_ind))
    
    # Compute average accuracy for matched pairs
    matched_scores = [sim_matrix[i, j] for i, j in matched_pairs]
    avg_accuracy = sum(matched_scores) / n_ref if matched_scores else 0.0
    
    return avg_accuracy, matched_pairs


def compute_sequence_score(ref_jobs, gen_jobs, matched_pairs):
    if not matched_pairs:
        return 1.0 if (not ref_jobs and not gen_jobs) else 0.0
    
    # Get job_id ordering in reference and generated
    ref_order = {j['job_id']: i for i, j in enumerate(ref_jobs)}
    gen_order = {j['job_id']: i for i, j in enumerate(gen_jobs)}
    
    # Build sequences of ranks for matched jobs
    ref_seq = []
    gen_seq = []
    for ref_idx, gen_idx in matched_pairs:
        ref_job_id = ref_jobs[ref_idx]['job_id']
        gen_job_id = gen_jobs[gen_idx]['job_id']
        ref_seq.append(ref_order.get(ref_job_id, -1))
        gen_seq.append(gen_order.get(gen_job_id, -1))
    
    return SequenceMatcher(None, ref_seq, gen_seq).ratio()


def parse_all_jobs(context):
    all_jobs = []
    for filename, content in context.items():
        if filename.endswith('.txt'):
            jobs = parse_job_board(content)
            all_jobs.extend(jobs)
    return all_jobs


class DomainJobboard(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "jobboard"
        self.summary = "Job board listings with titles, requirements, salaries, and descriptions"
        self.description = "Job listings"
        self.file_format = [".txt"]
        self.domain_parser = "custom"
        self.category = "everyday"
    
    def parse_all_jobs(self, context):
        return parse_all_jobs(context)

    def parse_context(self, context):
        return {"jobs": self.parse_all_jobs(context)}
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        jobs = parsed["jobs"]
        companies = set(j.get('company', '') for j in jobs if j.get('company'))
        with_salary = sum(1 for j in jobs if j.get('salary_amount'))
        all_skills = set()
        for j in jobs:
            all_skills.update(j.get('skills', []))
        return {
            "Jobs": len(jobs),
            "Companies": len(companies),
            "With Salary": with_salary,
            "Unique Skills": len(all_skills),
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
        
        ref_jobs = self.parse_context(reference_context)["jobs"]
        gen_jobs = self.parse_context(generated_context)["jobs"]
        
        if debug:
            print(f"Reference jobs: {len(ref_jobs)}, Generated jobs: {len(gen_jobs)}")
        
        # Compute component scores
        coverage_score = compute_job_coverage_score(ref_jobs, gen_jobs)
        accuracy_score, matched_pairs = compute_matched_accuracy(ref_jobs, gen_jobs)
        sequence_score = compute_sequence_score(ref_jobs, gen_jobs, matched_pairs)
        
        # Count factor
        n_ref, n_gen = len(ref_jobs), len(gen_jobs)
        count_factor = min(n_ref, n_gen) / max(n_ref, n_gen) if max(n_ref, n_gen) > 0 else 1.0
        
        # Final score: coverage² × accuracy × sqrt((sequence + count) / 2)
        score = (coverage_score ** 2) * accuracy_score * np.sqrt((sequence_score + count_factor) / 2)
        
        eval_obj = {
            "score": score,
            "coverage_score": coverage_score,
            "accuracy_score": accuracy_score,
            "sequence_score": sequence_score,
            "count_factor": count_factor,
            "ref_job_count": n_ref,
            "gen_job_count": n_gen,
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj


def run_ablation_test():
    import copy
    
    with open("samples/jobboard1/basic_state/jobboard.txt", "r") as f:
        text = f.read()
    
    ref_jobs = parse_job_board(text)
    print(f"Reference: {len(ref_jobs)} jobs\n")
    print("=" * 70)
    print("ABLATION TESTS")
    print("=" * 70)
    
    def compute_score(gen_jobs):
        coverage = compute_job_coverage_score(ref_jobs, gen_jobs)
        accuracy, pairs = compute_matched_accuracy(ref_jobs, gen_jobs)
        sequence = compute_sequence_score(ref_jobs, gen_jobs, pairs)
        n_ref, n_gen = len(ref_jobs), len(gen_jobs)
        count = min(n_ref, n_gen) / max(n_ref, n_gen) if max(n_ref, n_gen) > 0 else 1.0
        score = (coverage ** 2) * accuracy * np.sqrt((sequence + count) / 2)
        return {"score": score, "coverage": coverage, "accuracy": accuracy, "sequence": sequence, "count": count}
    
    def print_result(name, result):
        print(f"{name:<40} | score={result['score']:.4f} | cov={result['coverage']:.3f} acc={result['accuracy']:.3f} seq={result['sequence']:.3f}")
    
    # 1. Perfect match (baseline)
    result = compute_score(ref_jobs)
    print_result("1. Perfect match (baseline)", result)
    
    # 2. Remove 1 job
    gen = ref_jobs[1:]  # Remove JOB-0001
    result = compute_score(gen)
    print_result("2. Remove 1 job (JOB-0001)", result)
    
    # 3. Remove 5 jobs
    gen = ref_jobs[5:]
    result = compute_score(gen)
    print_result("3. Remove 5 jobs", result)
    
    # 4. Change 1 salary (double it)
    gen = copy.deepcopy(ref_jobs)
    gen[0]['salary_amount'] = gen[0]['salary_amount'] * 2
    result = compute_score(gen)
    print_result("4. Double salary of JOB-0001", result)
    
    # 5. Change 1 company name
    gen = copy.deepcopy(ref_jobs)
    gen[0]['company'] = "Wrong Company Name"
    result = compute_score(gen)
    print_result("5. Wrong company for JOB-0001", result)
    
    # 6. Remove all skills from 1 job
    gen = copy.deepcopy(ref_jobs)
    gen[0]['skills'] = []
    result = compute_score(gen)
    print_result("6. Remove skills from JOB-0001", result)
    
    # 7. Shuffle job order (random)
    import random
    gen = copy.deepcopy(ref_jobs)
    random.seed(42)
    random.shuffle(gen)
    result = compute_score(gen)
    print_result("7. Shuffle all jobs (random order)", result)
    
    # 8. Reverse job order
    gen = copy.deepcopy(ref_jobs)[::-1]
    result = compute_score(gen)
    print_result("8. Reverse job order", result)
    
    # 9. Change hourly to wrong annual (bad conversion)
    gen = copy.deepcopy(ref_jobs)
    # Find an hourly job and set wrong annual
    for j in gen:
        if j['salary_period'] == 'hour':
            j['salary_amount'] = j['salary_amount'] * 2000  # wrong multiplier
            j['salary_period'] = 'year'
            break
    result = compute_score(gen)
    print_result("9. Bad hourly->annual conversion", result)
    
    # 10. All salaries wrong by 10%
    gen = copy.deepcopy(ref_jobs)
    for j in gen:
        if j['salary_amount']:
            j['salary_amount'] *= 1.1
    result = compute_score(gen)
    print_result("10. All salaries +10%", result)
    
    # 11. Remove 10 jobs + shuffle rest
    gen = copy.deepcopy(ref_jobs[10:])
    random.shuffle(gen)
    result = compute_score(gen)
    print_result("11. Remove 10 jobs + shuffle", result)
    
    # 12. Duplicate a job (extra job)
    gen = copy.deepcopy(ref_jobs) + [copy.deepcopy(ref_jobs[0])]
    result = compute_score(gen)
    print_result("12. Add duplicate job", result)


if __name__ == "__main__":
    run_ablation_test()
