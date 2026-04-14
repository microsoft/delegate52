"""
Standalone OpenAI / Azure OpenAI wrapper providing generate() and generate_json().

Set OPENAI_API_KEY (or AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT) in your
environment before running.
"""

from openai import OpenAI, AzureOpenAI
import os, time, json, re

# ── Prompt variable substitution ─────────────────────────────────────────

def _format_messages(messages, variables={}):
    """Replace [[KEY]] placeholders in the last user message."""
    if not variables:
        return messages
    last_user_msg = [msg for msg in messages if msg["role"] == "user"][-1]
    for k, v in variables.items():
        key_string = f"[[{k}]]"
        assert isinstance(v, str), f"Variable {k} is not a string"
        last_user_msg["content"] = last_user_msg["content"].replace(key_string, v)
    return messages


# ── Pricing ──────────────────────────────────────────────────────────────

# Per-1K-token costs: (input, output)
_PRICING = {
    "gpt-4o-mini":      (0.00015,  0.0006),
    "gpt-4o":           (0.0025,   0.01),
    "gpt-4.1":          (0.002,    0.008),
    "gpt-4.1-mini":     (0.0004,   0.0016),
    "gpt-4.1-nano":     (0.0001,   0.0004),
    "gpt-4.5-preview":  (0.075,    0.150),
    "o1-mini":          (0.003,    0.012),
    "o1":               (0.015,    0.06),
    "o3":               (0.010,    0.040),
    "o3-mini":          (0.0011,   0.0044),
    "o4-mini":          (0.0011,   0.0044),
}


def _estimate_cost(model, usage):
    """Best-effort cost estimate from usage dict. Returns 0 if model unknown."""
    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    cached = 0
    ptd = usage.get("prompt_tokens_details")
    if ptd and isinstance(ptd, dict):
        cached = ptd.get("cached_tokens", 0) or 0

    # Match model to pricing table (prefix match)
    inp_cost = out_cost = 0
    for prefix, (ic, oc) in _PRICING.items():
        if model.startswith(prefix):
            inp_cost, out_cost = ic, oc
            break
    if inp_cost == 0:
        return 0.0

    non_cached = prompt_tokens - cached
    return ((non_cached + cached * 0.5) / 1000) * inp_cost + (completion_tokens / 1000) * out_cost


# ── Model maps (alias → deployment name) ────────────────────────────────

model_maps = {
    # Add your own aliases here, e.g.:
    # "t-gpt-4o": "gpt-4o-2024-11-20",
}


def resolve_model_name(model_name):
    """Strip t- prefix and resolve aliases."""
    name = model_maps.get(model_name, model_name)
    if name.startswith("t-"):
        name = name[2:]
    return name


# ── Main class ───────────────────────────────────────────────────────────

class OpenAI_Model:
    def __init__(self, instance=None):
        """Create an OpenAI (or Azure) client.

        Args:
            instance: Ignored (for API compatibility with internal TRAPI).
        """
        if "AZURE_OPENAI_API_KEY" in os.environ and "AZURE_OPENAI_ENDPOINT" in os.environ:
            self.client = AzureOpenAI(
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_version="2024-10-01-preview",
            )
        else:
            assert "OPENAI_API_KEY" in os.environ, (
                "Set OPENAI_API_KEY (or AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT)"
            )
            self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def generate(
        self,
        messages,
        model="gpt-4o-mini",
        timeout=30,
        max_retries=3,
        temperature=1.0,
        is_json=False,
        return_metadata=False,
        max_tokens=None,
        variables={},
        instance=None,
    ):
        """Call the chat completions API.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.
            model: Model name (aliases in model_maps are resolved automatically).
            timeout: Per-request timeout in seconds.
            max_retries: Number of retries on transient failures.
            temperature: Sampling temperature.
            is_json: If True, request JSON output mode.
            return_metadata: If True, return dict with message + usage stats.
            max_tokens: Max completion tokens.
            variables: Dict of [[KEY]] → value replacements for the prompt.
            instance: Ignored (API compat).

        Returns:
            str if return_metadata=False, else dict with keys:
                message, elapsed_time, prompt_tokens, completion_tokens,
                reasoning_tokens, total_tokens, total_usd
        """
        resolved = resolve_model_name(model)
        kwargs = {}
        if is_json:
            kwargs["response_format"] = {"type": "json_object"}

        messages = _format_messages(messages, variables)

        # o1/o3 models don't support system messages — fold into first user msg
        if resolved.startswith(("o1", "o3", "o4")) and len(messages) > 1 and messages[0]["role"] == "system" and messages[1]["role"] == "user":
            system_message = messages[0]["content"]
            messages[1]["content"] = f"System Message: {system_message}\n{messages[1]['content']}"
            messages = messages[1:]

        t0 = time.time()
        last_err = None
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=resolved,
                    messages=messages,
                    timeout=timeout,
                    max_completion_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )
                break
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(4)
        else:
            raise RuntimeError(f"Failed after {max_retries} retries: {last_err}")

        elapsed = time.time() - t0
        resp = response.to_dict() if hasattr(response, "to_dict") else response.model_dump()
        usage = resp.get("usage", {})
        response_text = resp["choices"][0]["message"]["content"]
        total_usd = _estimate_cost(resolved, usage)

        # Extract reasoning tokens if present (o1/o3 models)
        reasoning_tokens = 0
        ctd = usage.get("completion_tokens_details")
        if ctd and isinstance(ctd, dict):
            reasoning_tokens = ctd.get("reasoning_tokens", 0) or 0

        if not return_metadata:
            return response_text

        return {
            "message": response_text,
            "elapsed_time": elapsed,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": usage.get("total_tokens", 0),
            "total_usd": total_usd,
        }

    def generate_json(self, messages, model="gpt-4o-mini", **kwargs):
        """Generate a JSON response and return the parsed dict."""
        response = self.generate(messages, model, is_json=True, return_metadata=True, **kwargs)
        return json.loads(response["message"])

    def cost_calculator(self, model, usage):
        """Compute cost from a usage dict (for model_agentic.py compat)."""
        resolved = resolve_model_name(model)
        return _estimate_cost(resolved, usage)


# ── Module-level convenience functions ───────────────────────────────────
_model = OpenAI_Model()
generate = _model.generate
generate_json = _model.generate_json


if __name__ == "__main__":
    response = generate(
        [{"role": "user", "content": "Tell me a one-line joke."}],
        model="t-gpt-4o-mini",
        return_metadata=True,
    )
    print(response)
