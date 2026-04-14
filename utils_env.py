"""
Shared experiment utilities used by run_ten_rounds.py, run_edit_testing.py,
and analysis notebooks.

Provides core building blocks:
- Sample loading (load_sample, get_initial_context)
- Context manipulation (shuffle_context, merge_distractor, load_distractor_context)
- Single-edit execution (run_single_edit)
"""

from utils_context import build_context_from_folder
from domains import get_domain
import json
import os
import random


def shuffle_context(context):
    """Shuffle the key order of a context dict."""
    keys = list(context.keys())
    random.shuffle(keys)
    return {k: context[k] for k in keys}


def load_sample(sample_id, samples_folder="samples/"):
    """Load sample.json and return (sample, sample_folder, id2state)."""
    sample_folder = os.path.join(samples_folder, sample_id, "")
    sample_fn = f"{sample_folder}sample.json"
    with open(sample_fn, "r") as f:
        sample = json.load(f)
    id2state = {state["state_id"]: state for state in sample["states"]}
    return sample, sample_folder, id2state


def load_distractor_context(sample_folder):
    """Load distractor context files from a sample's distractor_context/ folder.
    Returns a dict of {filename: content} or empty dict if folder doesn't exist."""
    distractor_folder = os.path.join(sample_folder, "distractor_context")
    if os.path.isdir(distractor_folder):
        return build_context_from_folder(distractor_folder)
    return {}


def merge_distractor(context, distractor_context):
    """Merge distractor files into a context dict (non-destructive copy)."""
    if distractor_context:
        merged = dict(context)
        merged.update(distractor_context)
        return merged
    return context


def get_initial_context(sample, sample_folder, id2state, include_distractor=True):
    """Get the shuffled initial context for a sample.

    If include_distractor is True and the sample has a distractor_context/ folder,
    the distractor files are merged into the context before shuffling.
    """
    initial_state_id = sample["start_state"]
    initial_state = id2state[initial_state_id]
    context = build_context_from_folder(os.path.join(sample_folder, initial_state["solution_folder"]))

    if include_distractor:
        context = merge_distractor(context, load_distractor_context(sample_folder))

    initial_context = shuffle_context(context)
    return initial_context, initial_state


def run_single_edit(domain, sample_id, model_name, current_context, current_state,
                    target_state_id, id2state, printing=True, target_length=None, trapi_instance=None, distractor_filenames=None, max_tokens=None):
    """
    Run a single edit step and return (llm_response, evaluation_result, llm_metadata, target_state, edit_operation).
    This is the core edit logic shared across experiment scripts.
    
    distractor_filenames: list of filenames that are distractors (only used by agentic mode
        to strip them from the output, preventing context bloat across rounds).
    """
    selected_prompt = [p for p in current_state["prompts"] if p["target_state"] == target_state_id][0]
    target_state = id2state[target_state_id]
    edit_operation = selected_prompt["prompt"]

    llm_response, evaluation_result, llm_metadata = domain.run_single_step_edit(
        sample_id, model_name, current_context, target_state, edit_operation,
        printing=printing, target_length=target_length, trapi_instance=trapi_instance,
        distractor_filenames=distractor_filenames, max_tokens=max_tokens
    )

    return llm_response, evaluation_result, llm_metadata, target_state, edit_operation
