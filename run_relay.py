from utils_env import shuffle_context, load_sample, get_initial_context, run_single_edit, load_distractor_context, merge_distractor
from utils_results import get_results_count, save_result, generate_response_id
from utils_context import parse_context_string
import argparse, os, random, tqdm
from multiprocessing import Pool
from domains import get_domain
from datetime import datetime

def build_forward_state_sequence(possible_forward_states, num_round_trips):
    """Build a forward state sequence ensuring even coverage across states."""
    num_states = len(possible_forward_states)
    full_cycles = num_round_trips // num_states
    remainder = num_round_trips % num_states
    sequence = []
    for _ in range(full_cycles):
        shuffled = possible_forward_states.copy()
        random.shuffle(shuffled)
        sequence.extend(shuffled)
    if remainder > 0:
        shuffled_remainder = possible_forward_states.copy()
        random.shuffle(shuffled_remainder)
        sequence.extend(shuffled_remainder[:remainder])
    return sequence

def process_sample(args_tuple, printing=True):
    todo_sample, num_round_trips, results_folder, include_distractor, samples_folder, max_tokens = args_tuple

    model_name = todo_sample["model_name"]
    sample_id = todo_sample["sample_id"]

    sample, sample_folder, id2state = load_sample(sample_id, samples_folder=samples_folder)
    sample_type = sample["sample_type"]
    target_length = sample["target_length"] if sample_type == "fiction" else None

    # Get domain-specific handler
    domain = get_domain(sample_type)
    domain.samples_folder = os.path.join(samples_folder, "")

    # Load distractor context once for re-injection after each parse
    distractor_context = load_distractor_context(sample_folder) if include_distractor else {}
    distractor_filenames = list(distractor_context.keys()) if distractor_context else None

    initial_state_id = sample["start_state"]
    
    # Determine possible forward states (from the initial/start state's prompts)
    initial_state_for_prompts = id2state[initial_state_id]
    possible_forward_states = [p["target_state"] for p in initial_state_for_prompts["prompts"]]

    current_context, current_state = get_initial_context(sample, sample_folder, id2state, include_distractor=include_distractor)
    state_chain, rid_chain = [], []
    forward_state_sequence = build_forward_state_sequence(possible_forward_states, num_round_trips)

    def run_edit_step(current_state, current_context, target_state_id, direction, round_trip_num, target_length=None):
        response_id = generate_response_id()
        
        llm_response, evaluation_result, llm_metadata, target_state, edit_operation = run_single_edit(
            domain, sample_id, model_name, current_context, current_state,
            target_state_id, id2state, printing=printing, target_length=target_length,
            distractor_filenames=distractor_filenames, max_tokens=max_tokens
        )
        
        if printing:
            ts = datetime.now().strftime("%H:%M:%S")
            score = evaluation_result.get("score", evaluation_result.get("error", "?"))
            print(f"\033[94m[{ts}] RT{round_trip_num} {direction} → score={score}\033[0m")
        
        state_chain.append(target_state_id)
        rid_chain.append(response_id)
        result_sample = {"sample_id": sample_id, "sample_type": sample_type, "response_id": response_id, "model_name": model_name, "timestamp": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"), "raw_llm_response": llm_response, "target_state_id": target_state_id, "initial_state_id": initial_state_id, "evaluation": evaluation_result, "state_chain": state_chain, "rid_chain": rid_chain, "round_trip_num": round_trip_num, "round_trip_direction": direction, "num_retries": 1,
        
        "llm_latency": llm_metadata.get("latency"), "prompt_tokens": llm_metadata.get("prompt_tokens"), "completion_tokens": llm_metadata.get("completion_tokens"), "reasoning_tokens": llm_metadata.get("reasoning_tokens"), "total_tokens": llm_metadata.get("total_tokens"), "total_usd": llm_metadata.get("total_usd"),
        "distractor_included": include_distractor,
        }
        # Persist chain-of-thought reasoning content when present (e.g. DeepSeek R1, Qwen thinking)
        if llm_metadata.get("reasoning_content"):
            result_sample["reasoning_content"] = llm_metadata["reasoning_content"]
        # Persist agentic-specific telemetry when present
        for agentic_key in ("agentic_num_turns", "agentic_num_tool_calls", "agentic_tool_calls",
                            "agentic_operation_sequence", "agentic_finished_cleanly", "agentic_files_read"):
            if agentic_key in llm_metadata:
                result_sample[agentic_key] = llm_metadata[agentic_key]
        save_result(result_sample, results_folder)
        
        return llm_response, target_state_id

    for round_trip_idx in range(num_round_trips):
        round_trip_num = round_trip_idx + 1
        
        # Step 1: forward
        forward_target_state_id = forward_state_sequence[round_trip_idx]
        llm_response, target_state_id = run_edit_step(current_state, current_context, forward_target_state_id, "forward", round_trip_num, target_length=target_length)
        if llm_response is None:
            return "aborted_length_validation_failed"
        current_context = shuffle_context(merge_distractor(
            parse_context_string(llm_response), distractor_context
        ))
        current_state = id2state[target_state_id]
        
        # Step 2: backward
        llm_response, target_state_id = run_edit_step(current_state, current_context, initial_state_id, "backward", round_trip_num, target_length=target_length)
        if llm_response is None:
            return "aborted_length_validation_failed"
        current_context = shuffle_context(merge_distractor(
            parse_context_string(llm_response), distractor_context
        ))
        current_state = id2state[target_state_id]

    return "done"

def main():
    parser = argparse.ArgumentParser(description="Run round-trip relay simulations on Delegate52 benchmark.")

    parser.add_argument("--model_names", nargs='+', default=["gpt-4o-mini"], type=str,
                        help="Model name(s) to evaluate (e.g., 'gpt-4o-mini gpt-4o')")
    parser.add_argument("--domains", nargs='+', default=None, type=str,
                        help="Domain names to run (e.g., 'subtitles calendar'). Runs all if not set.")
    parser.add_argument("--sample_id", default=None, type=str,
                        help="Specific sample ID to run (e.g., 'subtitles1')")
    parser.add_argument("--num_samples", default=1, type=int,
                        help="Number of independent relay runs per (sample, model) pair")
    parser.add_argument("--num_workers", default=5, type=int,
                        help="Number of parallel workers per model")
    parser.add_argument("--num_round_trips", default=10, type=int,
                        help="Number of round trips per relay (default: 10 = 20 interactions)")
    parser.add_argument("--results_folder", default="logs/relay/", type=str,
                        help="Folder to store results")
    parser.add_argument("--skip_distractor", action="store_true",
                        help="Exclude distractor context files from input (included by default)")
    parser.add_argument("--input_path", default=None, type=str,
                        help="Path to samples folder or .jsonl dataset file. "
                             "If not set, downloads from HuggingFace (microsoft/delegate52). ")
    parser.add_argument("--max_tokens", default=None, type=int,
                        help="Override max output tokens for LLM generation")
    args = parser.parse_args()

    # --- Resolve input_path → samples_folder ---
    from utils_dataset import resolve_input_path
    samples_folder, _ = resolve_input_path(args.input_path)

    include_distractor = not args.skip_distractor
    os.makedirs(args.results_folder, exist_ok=True)

    # --- Determine which samples to run ---
    all_sample_ids = [d for d in os.listdir(samples_folder) if os.path.isdir(os.path.join(samples_folder, d))]

    if args.sample_id is not None:
        sample_ids = [args.sample_id]
    elif args.domains is not None:
        sample_ids = [s for s in all_sample_ids if any(s.startswith(domain) for domain in args.domains)]
    else:
        sample_ids = all_sample_ids

    result_counts = get_results_count(args.results_folder, num_round_trips=args.num_round_trips)

    # --- Build job list ---
    todo_samples = []
    for sample_id in sample_ids:
        for model_name in args.model_names:
            key = (sample_id, model_name, include_distractor, None)
            complete_count = result_counts.get(key, 0)
            fresh_needed = args.num_samples - complete_count
            if fresh_needed > 0:
                todo_samples += [{"sample_id": sample_id, "model_name": model_name}] * fresh_needed

    if not todo_samples:
        print("All runs are done, nothing to do.")
        return

    random.shuffle(todo_samples)

    worker_args = [(todo_sample, args.num_round_trips, args.results_folder, include_distractor, samples_folder, args.max_tokens) for todo_sample in todo_samples]

    print(f"Running {len(worker_args)} jobs with {args.num_workers} workers")
    with Pool(args.num_workers) as pool:
        for _ in tqdm.tqdm(pool.imap_unordered(process_sample, worker_args), total=len(worker_args)):
            pass


if __name__ == "__main__":
    main()
