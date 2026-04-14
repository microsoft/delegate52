from utils_context import stringify_context, parse_context_string, is_context_complete, validate_wildcard_context, format_file_names_for_prompt, is_wildcard
from model_openai import generate


class DomainBase:
    supports_visual = False  # override in subclasses that implement render_context_visual

    def __init__(self, prompt_file):
        self.sample_type = None
        self.description = ""          # short (<5 word) domain description
        self.file_format = []           # list of file extensions, e.g. [".ledger"]
        self.domain_parser = "custom"   # parsing library name, or "custom"
        self.category = ""             # one of: science, code, creative, records, everyday
        self.samples_folder = "samples/"  # base folder for sample directories
        with open(prompt_file, "r") as f:
            self.prompt_template = f.read()
    
    def preprocess_context(self, context):
        """Normalize raw context string before parsing. Override in subclasses to fix common LLM syntax issues."""
        return context

    def parse_context(self, context):
        # Override this method in subclasses
        raise NotImplementedError("Subclasses must implement parse_context()")

    def compute_domain_statistics(self, context):
        # Override this method in subclasses
        raise NotImplementedError("Subclasses must implement compute_domain_statistics()")
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        # Override this method in subclasses
        raise NotImplementedError("Subclasses must implement evaluate_context()")

    def render_context_visual(self, context, outfile):
        """Render a context dict to a visual image.

        Args:
            context: dict mapping filename -> file content string
            outfile: output path *without* extension; the method appends the
                     appropriate suffix (e.g. '.png').

        Returns:
            The actual output file path (with extension), or None if this
            domain does not support visual rendering.

        Override in subclasses and set ``supports_visual = True``.
        """
        return None


    def prepare_prompt(self, current_context, target_state, edit_operation, **kwargs):
        context_str = stringify_context(current_context)
        target_context = target_state["context"]
        file_names = format_file_names_for_prompt(target_context)
        
        prompt_populated = self.prompt_template.replace("[[INPUT_CONTEXT]]", context_str).replace("[[FILE_NAMES]]", file_names).replace("[[EDITING_OPERATION]]", edit_operation)
        return prompt_populated
    
    
    def run_single_step_edit(self, sample_id, model_name, current_context, target_state, edit_operation, printing=True, trapi_instance=None, **kwargs):
        # ── Agentic routing: "agentic-<model>" uses tool-use loop ──
        if model_name.startswith("agentic-"):
            from model_agentic import run_agentic_edit
            actual_model = model_name[len("agentic-"):]
            target_filenames = list(target_state["context"])
            agentic_result = run_agentic_edit(
                model=actual_model,
                context=current_context,
                edit_instruction=edit_operation,
                target_filenames=target_filenames,
                trapi_instance=trapi_instance,
                printing=printing,
                target_length=kwargs.get("target_length"),
                distractor_filenames=kwargs.get("distractor_filenames"),
            )
            llm_response = agentic_result["response"]
            llm_metadata = agentic_result["metadata"]
        else:
            # ── Standard single-shot path ──
            prompt_populated = self.prepare_prompt(current_context, target_state, edit_operation, **kwargs)

            max_tokens = kwargs.get("max_tokens") or (16000 if "gpt-4o" in model_name else 20000)

            llm_output = generate([{"role": "user", "content": prompt_populated}], model=model_name, max_tokens=max_tokens, return_metadata=True, instance=trapi_instance, timeout=1800, max_retries=10)
            llm_response = llm_output["message"]

            llm_metadata = {
                "latency": llm_output.get("elapsed_time"),
                "prompt_tokens": llm_output.get("prompt_tokens"),
                "completion_tokens": llm_output.get("completion_tokens"),
                "reasoning_tokens": llm_output.get("reasoning_tokens"),
                "total_tokens": llm_output.get("total_tokens"),
                "total_usd": llm_output.get("total_usd"),
            }
            # Preserve chain-of-thought content when returned by the provider (e.g. DeepInfra reasoning models)
            if llm_output.get("thinking"):
                llm_metadata["reasoning_content"] = llm_output["thinking"]
        
        generated_context = parse_context_string(llm_response)
        target_context = target_state["context"]
        
        has_wildcards = any(is_wildcard(f) for f in target_context)
        
        if not is_context_complete(generated_context, target_context):
            evaluation_result = {"error": "context_mismatch", "detailed_error": "One or more files are missing from the generated context."}
        elif has_wildcards:
            valid, err_msg = validate_wildcard_context(generated_context, target_context)
            if not valid:
                evaluation_result = {"error": "wildcard_mismatch", "detailed_error": err_msg}
            else:
                evaluation_result = self.evaluate_context(sample_id, generated_context, target_state)
        else:
            evaluation_result = self.evaluate_context(sample_id, generated_context, target_state)
        
        return llm_response, evaluation_result, llm_metadata
  