import ujson as json, os, fcntl, glob
from bson import ObjectId

def generate_response_id():
    return str(ObjectId())

def clean_model_name(model_name):
    return model_name.replace("_", "-").replace("/", "")

def get_results_filename(results_folder, sample_type, model_name):
    clean_name = clean_model_name(model_name)
    return os.path.join(results_folder, f"results_{sample_type}_{clean_name}.jsonl")

def get_results_count(results_folder, num_round_trips):
    """Count completed runs per (sample_id, model_name, distractor_included, single_edit_state_id) key.
    
    Results without a distractor_included field are treated as False (legacy data).
    single_edit_state_id is None for normal (round-robin) runs.
    """
    if not os.path.exists(results_folder):
        return {}

    result_counts = {}
    for filepath in glob.glob(os.path.join(results_folder, "results_*.jsonl")):
        with open(filepath, "r") as f:
            for line in f:
                result = json.loads(line)
                if result["round_trip_num"] != num_round_trips:
                    continue

                distractor = result.get("distractor_included", False)
                se_state = result.get("single_edit_state_id", None)
                key = (result["sample_id"], result["model_name"], distractor, se_state)
                
                if "rid_chain" in result and len(result["rid_chain"]) > 0:
                    first_rid = result["rid_chain"][0]
                    
                    if key not in result_counts:
                        result_counts[key] = set()
                    result_counts[key].add(first_rid)
    
    return {k: len(v) for k, v in result_counts.items()}

def save_result(result, results_folder):
    sample_type = result["sample_type"]
    model_name = result["model_name"]
    results_path = get_results_filename(results_folder, sample_type, model_name)
    
    os.makedirs(results_folder, exist_ok=True)
    
    with open(results_path, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(json.dumps(result) + "\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def load_domain_results(results_folder, sample_type, model_name=None):
    results = []
    fn_pattern = f"results_{sample_type}_*.jsonl" if model_name is None else f"results_{sample_type}_{clean_model_name(model_name)}.jsonl"
    for filepath in glob.glob(os.path.join(results_folder, fn_pattern)):
        with open(filepath, "r") as f:
            for line in f:
                results.append(json.loads(line))
    return results

if __name__ == "__main__":
    print(generate_response_id())
