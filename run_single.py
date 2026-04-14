"""
Edit Testing Script

This script tests individual forward/backward edits to evaluate their feasibility.
Unlike run_relay.py which runs multiple round trips, this focuses on single
round trip testing of each edit direction to identify:
- Lossy edits (information loss in the round trip)
- Ambiguous edit instructions
- Parser/evaluator issues

Results are stored in logs/edit_testing/ with one file per (model, sample_id).
"""

from utils_context import parse_context_string
from utils_results import generate_response_id
from utils_env import shuffle_context, load_sample, get_initial_context, run_single_edit, load_distractor_context, merge_distractor
from domains import get_domain
from datetime import datetime
from multiprocessing import Pool
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
import os
import random
import tiktoken
import tqdm

# Global encoding for token counting
TOKEN_ENCODING = tiktoken.encoding_for_model("gpt-4")


def count_tokens(text):
    """Count the number of tokens in a string."""
    if text is None:
        return None
    return len(TOKEN_ENCODING.encode(text))


def get_edit_testing_filename(output_folder, sample_id, model_name):
    """Generate filename for edit testing results: logs/edit_testing/{sample_id}_{model}.jsonl"""
    clean_model = model_name.replace("_", "-").replace("/", "")
    return os.path.join(output_folder, f"{sample_id}_{clean_model}.jsonl")


def load_existing_results(filepath, include_distractor=True):
    """Load existing results from a file and return a dict keyed by (target_state_id, run_idx).
    
    Only returns results matching the given include_distractor value.
    Results without a distractor_included field are treated as False (legacy data).
    """
    existing = {}
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            for line in f:
                try:
                    result = json.loads(line)
                    if result.get("distractor_included", False) != include_distractor:
                        continue
                    key = (result["target_state_id"], result.get("run_idx", 0))
                    existing[key] = result
                except json.JSONDecodeError:
                    continue
    return existing


def save_edit_testing_result(result, output_folder):
    """Save a single result to the appropriate file."""
    sample_id = result["sample_id"]
    model_name = result["model_name"]
    filepath = get_edit_testing_filename(output_folder, sample_id, model_name)
    
    os.makedirs(output_folder, exist_ok=True)
    
    with open(filepath, "a") as f:
        f.write(json.dumps(result) + "\n")


def run_single_edit_test(domain, sample_id, model_name, current_context, current_state, 
                         target_state_id, id2state, direction, run_idx, target_length=None, printing=True, distractor_filenames=None):
    """
    Run a single edit (forward or backward) and return the result.
    """
    response_id = generate_response_id()
    
    llm_response, evaluation_result, llm_metadata, target_state, edit_operation = run_single_edit(
        domain, sample_id, model_name, current_context, current_state,
        target_state_id, id2state, printing=printing, target_length=target_length,
        distractor_filenames=distractor_filenames
    )
    
    result = {
        "sample_id": sample_id,
        "model_name": model_name,
        "response_id": response_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
        "direction": direction,
        "target_state_id": target_state_id,
        "source_state_id": current_state["state_id"],
        "edit_prompt": edit_operation,
        "run_idx": run_idx,
        "raw_llm_response": llm_response,
        "evaluation": evaluation_result,
        "output_tokens": count_tokens(llm_response),
        "llm_latency": llm_metadata.get("latency"),
        "prompt_tokens": llm_metadata.get("prompt_tokens"),
        "completion_tokens": llm_metadata.get("completion_tokens"),
        "reasoning_tokens": llm_metadata.get("reasoning_tokens"),
        "total_tokens": llm_metadata.get("total_tokens"),
        "total_usd": llm_metadata.get("total_usd"),
    }
    # Persist chain-of-thought reasoning content when present
    if llm_metadata.get("reasoning_content"):
        result["reasoning_content"] = llm_metadata["reasoning_content"]
    
    return result, llm_response


def run_round_trip_test(domain, sample_id, model_name, initial_context, initial_state,
                        target_state_id, id2state, run_idx, target_length=None, printing=True, distractor_context=None):
    """
    Run a complete forward-backward round trip for a specific target state.
    Returns both forward and backward results, plus a combined round trip result.
    """
    distractor_filenames = list(distractor_context.keys()) if distractor_context else None
    results = []
    
    # Forward edit: basic_state -> target_state
    forward_result, forward_response = run_single_edit_test(
        domain, sample_id, model_name, initial_context, initial_state,
        target_state_id, id2state, "forward", run_idx, target_length, printing,
        distractor_filenames=distractor_filenames
    )
    results.append(forward_result)
    
    if forward_response is None:
        # Forward failed completely
        return results
    
    # Parse the forward response to get intermediate context
    intermediate_context = parse_context_string(forward_response)
    if not intermediate_context:
        # Parsing failed
        return results
    
    intermediate_context = shuffle_context(intermediate_context)
    target_state = id2state[target_state_id]
    
    # Re-inject distractor context if it was included in the initial context
    if distractor_context:
        intermediate_context = shuffle_context(merge_distractor(intermediate_context, distractor_context))
    
    # Backward edit: target_state -> basic_state
    backward_result, backward_response = run_single_edit_test(
        domain, sample_id, model_name, intermediate_context, target_state,
        initial_state["state_id"], id2state, "backward", run_idx, target_length, printing,
        distractor_filenames=distractor_filenames
    )
    results.append(backward_result)
    
    # Create a combined round trip summary result
    forward_eval = forward_result.get("evaluation", {})
    backward_eval = backward_result.get("evaluation", {})
    
    forward_score = forward_eval.get("score") if forward_eval.get("error", "no_error") == "no_error" else None
    backward_score = backward_eval.get("score") if backward_eval.get("error", "no_error") == "no_error" else None
    
    round_trip_summary = {
        "sample_id": sample_id,
        "model_name": model_name,
        "response_id": generate_response_id(),
        "timestamp": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
        "direction": "round_trip",
        "target_state_id": target_state_id,
        "source_state_id": initial_state["state_id"],
        "run_idx": run_idx,
        "forward_response_id": forward_result["response_id"],
        "backward_response_id": backward_result["response_id"],
        "forward_score": forward_score,
        "backward_score": backward_score,
        "forward_error": forward_eval.get("error"),
        "backward_error": backward_eval.get("error"),
        "round_trip_success": (forward_score is not None and backward_score is not None),
        "total_latency": (forward_result.get("llm_latency") or 0) + (backward_result.get("llm_latency") or 0),
        "total_tokens": (forward_result.get("total_tokens") or 0) + (backward_result.get("total_tokens") or 0),
        "total_usd": (forward_result.get("total_usd") or 0) + (backward_result.get("total_usd") or 0),
    }
    results.append(round_trip_summary)
    
    return results


def process_edit_test(args_tuple):
    """
    Process a single edit test job.
    Job contains: sample_id, model_name, target_state_id, run_idx
    """
    job, output_folder, include_distractor, samples_folder = args_tuple
    sample_id = job["sample_id"]
    model_name = job["model_name"]
    target_state_id = job["target_state_id"]
    run_idx = job["run_idx"]
    
    sample, sample_folder, id2state = load_sample(sample_id, samples_folder=samples_folder)
    sample_type = sample["sample_type"]
    target_length = sample.get("target_length") if sample_type == "fiction" else None
    
    domain = get_domain(sample_type)
    domain.samples_folder = os.path.join(samples_folder, "")
    initial_context, initial_state = get_initial_context(sample, sample_folder, id2state, include_distractor=include_distractor)
    distractor_ctx = load_distractor_context(sample_folder) if include_distractor else {}
    
    # Run the round trip test
    results = run_round_trip_test(
        domain, sample_id, model_name, initial_context, initial_state,
        target_state_id, id2state, run_idx, target_length, printing=False,
        distractor_context=distractor_ctx
    )
    
    # Save all results
    for result in results:
        result["sample_type"] = sample_type
        result["distractor_included"] = include_distractor
        save_edit_testing_result(result, output_folder)
    
    return f"{sample_id}/{target_state_id}/run{run_idx}"


def get_pending_jobs(sample_ids, model_names, num_runs, output_folder, include_distractor=True, samples_folder="samples/"):
    """
    Build list of jobs that need to be run, skipping already completed ones.
    Only counts completions matching the given include_distractor value.
    """
    all_jobs = []
    
    for sample_id in sample_ids:
        sample_folder = os.path.join(samples_folder, sample_id, "")
        sample_fn = os.path.join(sample_folder, "sample.json")
        
        if not os.path.exists(sample_fn):
            print(f"Warning: sample.json not found for {sample_id}, skipping")
            continue
        
        with open(sample_fn, "r") as f:
            sample = json.load(f)
        
        initial_state_id = sample["start_state"]
        id2state = {state["state_id"]: state for state in sample["states"]}
        initial_state = id2state[initial_state_id]
        
        # Get all target states from the initial state's prompts
        target_states = [p["target_state"] for p in initial_state["prompts"]]
        
        for model_name in model_names:
            # Check what's already been completed for this (sample, model, distractor)
            filepath = get_edit_testing_filename(output_folder, sample_id, model_name)
            existing = load_existing_results(filepath, include_distractor=include_distractor)
            
            # Count completed round_trip results per target_state
            completed_runs = {}
            for (target_state_id, run_idx), result in existing.items():
                if result.get("direction") == "round_trip":
                    if target_state_id not in completed_runs:
                        completed_runs[target_state_id] = set()
                    completed_runs[target_state_id].add(run_idx)
            
            for target_state_id in target_states:
                completed = completed_runs.get(target_state_id, set())
                for run_idx in range(num_runs):
                    if run_idx not in completed:
                        all_jobs.append({
                            "sample_id": sample_id,
                            "model_name": model_name,
                            "target_state_id": target_state_id,
                            "run_idx": run_idx,
                        })
    
    return all_jobs


def main():
    parser = argparse.ArgumentParser(description="Test individual edit feasibility")
    
    parser.add_argument("--model_names", nargs='+', 
                        default=["gpt-4o-mini"],
                        help="Models to test with")
    parser.add_argument("--sample_id", default=None, type=str,
                        help="Specific sample ID to test (e.g., 'subtitles1')")
    parser.add_argument("--domain", default=None, type=str,
                        help="Task name to test all samples for (e.g., 'subtitles')")
    parser.add_argument("--num_runs", default=5, type=int,
                        help="Number of times to run each forward/backward pair")
    parser.add_argument("--num_workers", default=10, type=int,
                        help="Number of parallel workers per model")
    parser.add_argument("--output_folder", default="logs/edit_testing/", type=str,
                        help="Output folder for results")
    parser.add_argument("--list_only", action="store_true",
                        help="Only list pending jobs without running them")
    parser.add_argument("--skip_domains", nargs='+', default=[],
                        help="Task prefixes to skip")
    parser.add_argument("--skip_distractor", action="store_true",
                        help="Skip including distractor context files in the input (distractor is included by default)")
    parser.add_argument("--input_path", default=None, type=str,
                        help="Path to samples folder or .jsonl dataset file. "
                             "If not set, downloads from HuggingFace (microsoft/delegate52). ")
    
    args = parser.parse_args()
    
    # --- Resolve input_path → samples_folder ---
    from utils_dataset import resolve_input_path
    samples_folder, _ = resolve_input_path(args.input_path)
    
    # Determine which samples to run
    all_sample_ids = [d for d in os.listdir(samples_folder) 
                      if os.path.isdir(os.path.join(samples_folder, d))]
    
    if args.sample_id is not None:
        sample_ids = [args.sample_id]
    elif args.domain is not None:
        sample_ids = [s for s in all_sample_ids if s.startswith(args.domain)]
    else:
        sample_ids = all_sample_ids
    
    # Filter out skipped domains
    if args.skip_domains:
        sample_ids = [s for s in sample_ids 
                      if not any(s.startswith(skip) for skip in args.skip_domains)]
    
    # Get pending jobs
    include_distractor = not args.skip_distractor
    jobs = get_pending_jobs(sample_ids, args.model_names, args.num_runs, args.output_folder, include_distractor=include_distractor, samples_folder=samples_folder)
    
    if args.list_only:
        print(f"\nPending jobs: {len(jobs)}")
        # Group by sample and model for summary
        from collections import defaultdict
        summary = defaultdict(lambda: defaultdict(list))
        for job in jobs:
            summary[job["sample_id"]][job["model_name"]].append(job["target_state_id"])
        
        for sample_id in sorted(summary.keys()):
            for model_name in sorted(summary[sample_id].keys()):
                targets = summary[sample_id][model_name]
                target_counts = {}
                for t in targets:
                    target_counts[t] = target_counts.get(t, 0) + 1
                print(f"  {sample_id} / {model_name}: {target_counts}")
        return
    
    if not jobs:
        print("No pending jobs to run.")
        return
    
    # Print counter of pending runs grouped by task and sample
    from collections import defaultdict, Counter
    jobs_by_domain = defaultdict(lambda: defaultdict(int))
    for job in jobs:
        # Extract task name (everything before the trailing digits)
        sid = job["sample_id"]
        domain_name = sid.rstrip("0123456789")
        jobs_by_domain[domain_name][sid] += 1
    
    print(f"\nPending runs by domain/sample:")
    for domain_name in sorted(jobs_by_domain.keys()):
        samples = jobs_by_domain[domain_name]
        domain_total = sum(samples.values())
        sample_parts = ", ".join(f"{sid}:{count}" for sid, count in sorted(samples.items()))
        print(f"  {domain_name} ({domain_total}): {sample_parts}")
    print()
    
    print(f"Running {len(jobs)} edit tests across {len(sample_ids)} samples with {len(args.model_names)} models")
    print(f"Output folder: {args.output_folder}")
    print(f"Models: {args.model_names}")
    print()
    
    os.makedirs(args.output_folder, exist_ok=True)
    
    # Run separate pools per model to ensure even distribution
    from collections import defaultdict
    jobs_by_model = defaultdict(list)
    for job in jobs:
        jobs_by_model[job["model_name"]].append(job)
    
    print(f"Using {args.num_workers} workers per model ({len(jobs_by_model)} models)")
    for model_name, model_jobs in jobs_by_model.items():
        print(f"  {model_name}: {len(model_jobs)} jobs")
    print()
    
    def run_model_jobs(model_name, pbar):
        model_jobs = jobs_by_model[model_name]
        random.shuffle(model_jobs)
        worker_args = [(job, args.output_folder, include_distractor, samples_folder) for job in model_jobs]
        with Pool(args.num_workers) as pool:
            for _ in pool.imap_unordered(process_edit_test, worker_args):
                pbar.update(1)
        return model_name
    
    with ThreadPoolExecutor(max_workers=len(jobs_by_model)) as executor:
        total_jobs = len(jobs)
        with tqdm.tqdm(total=total_jobs, desc="All models") as pbar:
            futures = {executor.submit(run_model_jobs, model, pbar): model for model in jobs_by_model.keys()}
            for future in futures:
                future.result()
    
    print(f"\nDone! Results saved to {args.output_folder}")


if __name__ == "__main__":
    main()
