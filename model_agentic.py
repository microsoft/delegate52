"""
Agentic editing mode for reverse_edits benchmark.

Instead of a single-shot LLM call, the model gets a file listing + edit
instruction, and iterates in a tool-use loop (read/write/delete files,
run Python scripts) until it signals completion or hits a budget cap.

Usage: pass model names prefixed with "agentic-" (e.g., "agentic-t-gpt-5.2")
to run_ten_rounds.py or run_edit_testing.py.  The prefix is stripped and the
underlying model is used for the agentic loop.

Integration point: domain_base.py's run_single_step_edit() intercepts the
"agentic-" prefix and delegates here.
"""

from model_openai import OpenAI_Model, model_maps, resolve_model_name
from utils_context import stringify_context
import json, time, os, subprocess, tempfile, shutil, sys

# ── Budget caps ──────────────────────────────────────────────────────────
MAX_TURNS = 25          # max LLM round-trips
MAX_TOTAL_TOKENS = 500_000  # hard stop on cumulative token usage

# ── Tool definitions (OpenAI function-calling schema) ────────────────────
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a file in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to read.",
                    },
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to create or overwrite.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file content to write.",
                    },
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to delete.",
                    },
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Execute a Python script. Workspace files are accessible at "
                "'./workspace/<filename>'. Write changes back to './workspace/' "
                "to update files. Use print() for any output you want to see."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute.",
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Signal that editing is complete. The current state of all "
                "files in the workspace will be used as the final output."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

SYSTEM_PROMPT = """\
You are a document editing assistant. You have a workspace containing files \
that you need to transform according to the user's instructions.

Available tools:
- read_file(filename): read a file's full contents
- write_file(filename, content): create or overwrite a file
- delete_file(filename): remove a file from the workspace
- run_python(code): run a Python script (workspace files are at ./workspace/<name>)
- finish(): call this when you're done editing

You can approach the task in whatever way you find most effective: programmatically or directly by writing files.

After editing, your workspace must contain exactly these files: {target_filenames}
IMPORTANT: Double-check that your output filenames match the target filenames \
exactly (including spelling, extensions, and casing). Incorrect filenames will \
cause evaluation to fail.
Do NOT create or modify files named __init__.py or testing.py — these are \
scaffold files managed by the evaluation harness and must not be touched.
Call finish() when you are satisfied with the result.
"""


# ── Virtual filesystem ───────────────────────────────────────────────────

class VirtualFS:
    """In-memory filesystem backing the agentic loop."""

    def __init__(self, context: dict):
        self.files = dict(context)

    def list_files(self):
        return sorted(self.files.keys())

    def read_file(self, filename):
        if filename not in self.files:
            return f"Error: file '{filename}' not found. Available files: {', '.join(sorted(self.files.keys()))}"
        return self.files[filename]

    def write_file(self, filename, content):
        self.files[filename] = content
        return "OK"

    def delete_file(self, filename):
        if filename not in self.files:
            return f"Error: file '{filename}' not found."
        del self.files[filename]
        return "OK"

    def snapshot(self):
        return dict(self.files)


# ── Python execution ─────────────────────────────────────────────────────

def _build_bwrap_cmd(tmpdir: str, script_path: str) -> list:
    """Build a bwrap command for sandboxed Python execution.
    
    Provides: read-only system libs + Python, read-write tmpdir only, no network.
    """
    python_exe = sys.executable
    python_prefix = sys.prefix

    return [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", python_prefix, python_prefix,
        "--tmpfs", "/tmp",
        "--bind", tmpdir, tmpdir,        # r/w access to sandbox only
        "--proc", "/proc",
        "--dev", "/dev",
        "--unshare-net",                 # no network
        "--die-with-parent",
        "--chdir", tmpdir,
        python_exe, script_path,
    ]


def _execute_python(code: str, fs: VirtualFS) -> str:
    """Run a Python snippet in a sandboxed subprocess with workspace file access.
    
    Uses bwrap (bubblewrap) if available for filesystem + network isolation.
    Falls back to direct subprocess if bwrap is not installed.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_dir = os.path.join(tmpdir, "workspace")
        os.makedirs(ws_dir)

        # Write current files to temp workspace
        for fname, content in fs.files.items():
            path = os.path.join(ws_dir, fname)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)

        # Write and execute the script
        script_path = os.path.join(tmpdir, "_script.py")
        with open(script_path, "w") as f:
            f.write(code)

        # Use bwrap sandbox if available, otherwise fall back to direct subprocess
        if shutil.which("bwrap"):
            cmd = _build_bwrap_cmd(tmpdir, script_path)
        else:
            cmd = [sys.executable, script_path]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=30, cwd=tmpdir,
            )
            output = result.stdout
            if result.stderr:
                output += "\nSTDERR:\n" + result.stderr
            if result.returncode != 0:
                output += f"\n(exit code {result.returncode})"
        except subprocess.TimeoutExpired:
            output = "Error: script timed out after 30 seconds."
        except Exception as e:
            output = f"Error executing script: {e}"

        # Sync filesystem back from disk
        disk_files = set()
        if os.path.isdir(ws_dir):
            for root, _, filenames in os.walk(ws_dir):
                for fname in filenames:
                    full_path = os.path.join(root, fname)
                    rel = os.path.relpath(full_path, ws_dir)
                    try:
                        with open(full_path, "r") as f:
                            fs.files[rel] = f.read()
                    except (UnicodeDecodeError, IOError):
                        pass  # skip binary or unreadable files
                    disk_files.add(rel)

            # Remove files that were deleted by the script
            for fname in list(fs.files.keys()):
                if fname not in disk_files:
                    del fs.files[fname]

        return output[:10_000]  # truncate to prevent context blowup


# ── Tool dispatch ────────────────────────────────────────────────────────

def _dispatch_tool(fs: VirtualFS, name: str, args: dict) -> str:
    """Execute a tool call against the virtual filesystem."""
    if name == "read_file":
        return fs.read_file(args.get("filename", ""))
    elif name == "write_file":
        return fs.write_file(args.get("filename", ""), args.get("content", ""))
    elif name == "delete_file":
        return fs.delete_file(args.get("filename", ""))
    elif name == "run_python":
        return _execute_python(args.get("code", ""), fs)
    elif name == "finish":
        return "DONE"
    return f"Unknown tool: {name}"


def _parse_inline_tool_calls(text: str):
    """Try to extract tool calls from a model response that embedded them as text.

    Handles responses like:
        {"filename": "foo.csv"}
        {"filename": "bar.txt", "content": "hello"}
    
    Returns a list of (tool_name, args_dict) tuples, or [] if nothing parseable.
    """
    import re
    # Find all top-level JSON objects in the text
    calls = []
    for m in re.finditer(r'\{[^{}]*\}', text):
        try:
            obj = json.loads(m.group())
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        # Classify by keys
        if "code" in obj:
            calls.append(("run_python", obj))
        elif "filename" in obj and "content" in obj:
            calls.append(("write_file", obj))
        elif "filename" in obj:
            calls.append(("read_file", obj))
    return calls


# ── Resolve model name ───────────────────────────────────────────────────

# Model name resolution is handled by resolve_model_name() from model_openai.


# ── Main entry point ─────────────────────────────────────────────────────

def run_agentic_edit(
    model: str,
    context: dict,
    edit_instruction: str,
    target_filenames: list,
    trapi_instance=None,
    printing=True,
    max_turns=MAX_TURNS,
    target_length=None,
    distractor_filenames=None,
):
    """
    Run an agentic editing loop.

    Args:
        model: Model name (e.g. "gpt-5.2"). The "agentic-"
               prefix should already be stripped by the caller.
        context: Dict of {filename: content} — may include distractor files.
        edit_instruction: The natural language editing task.
        target_filenames: List of filenames expected in the output.
        trapi_instance: Ignored (kept for API compatibility).
        printing: Whether to print progress.
        max_turns: Maximum number of LLM round-trips.
        target_length: Optional target word count (for fiction samples).
        distractor_filenames: Set/list of distractor filenames to strip from output.
            These files are present in the workspace for the agent to encounter,
            but are excluded from the final snapshot to prevent context bloat
            across round trips.

    Returns:
        dict with keys:
            "response": str — serialized context (```filename\\ncontent``` blocks)
            "metadata": dict — aggregated token/cost/latency stats + agentic fields
    """
    openai_model = resolve_model_name(model)
    oai = OpenAI_Model()
    fs = VirtualFS(context)

    # Build the initial prompt: file list only (agent must read_file to see contents)
    file_list_str = "\n".join(f"  - {f}" for f in sorted(context.keys()))

    system_msg = SYSTEM_PROMPT.format(
        target_filenames=", ".join(target_filenames),
    )

    task_str = edit_instruction
    if target_length is not None:
        task_str += f"\n\nNote: the target word count for the output is approximately {target_length} words."

    user_content = (
        f"Your workspace contains the following files:\n{file_list_str}\n\n"
        f"Use read_file to inspect any files you need before editing.\n\n"
        f"TASK:\n{task_str}"
    )

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]

    # ── Aggregated stats ──
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_reasoning_tokens = 0
    total_tokens = 0
    total_usd = 0.0
    total_latency = 0.0
    num_turns = 0
    tool_calls_log = []   # [{"tool": name, "turn": int, "args_keys": [str]}]
    operation_sequence = []  # ordered list of tool names for high-level tracing
    files_read = []       # every read_file filename (for distractor analysis)
    has_written = False   # must be True before finish() is accepted
    finished = False

    if printing:
        print(f"  [agentic] Starting loop: model={model}, files={len(context)}, "
              f"target_files={target_filenames}")

    for turn_idx in range(max_turns):
        num_turns += 1
        t0 = time.time()

        # ── Call the LLM ──
        try:
            response = oai.client.chat.completions.create(
                model=openai_model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                temperature=1.0,
                max_completion_tokens=16_000,
                timeout=1800,
            )
        except Exception as e:
            if printing:
                print(f"  [agentic] T{num_turns}: API error: {e}, retrying in 30s...")
            time.sleep(30)
            try:
                response = oai.client.chat.completions.create(
                    model=openai_model,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    temperature=1.0,
                    max_completion_tokens=16_000,
                    timeout=1800,
                )
            except Exception as e2:
                if printing:
                    print(f"  [agentic] T{num_turns}: retry failed: {e2}, aborting.")
                break

        elapsed = time.time() - t0
        total_latency += elapsed

        # ── Accumulate usage stats ──
        usage = response.usage
        if usage:
            u = usage.model_dump()
            total_prompt_tokens += u.get("prompt_tokens", 0) or 0
            total_completion_tokens += u.get("completion_tokens", 0) or 0
            ct_details = u.get("completion_tokens_details") or {}
            total_reasoning_tokens += ct_details.get("reasoning_tokens", 0) or 0
            turn_total = u.get("total_tokens", 0) or 0
            total_tokens += turn_total
            try:
                total_usd += oai.cost_calculator(openai_model, u)
            except Exception:
                pass  # pricing not configured for this model

        assistant_msg = response.choices[0].message

        # Serialize assistant message for the conversation history
        msg_dict = {"role": "assistant", "content": assistant_msg.content}
        if assistant_msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_msg.tool_calls
            ]
        messages.append(msg_dict)

        # ── No tool calls → model is done (only if it has written something) ──
        if not assistant_msg.tool_calls:
            if has_written:
                if printing:
                    print(f"  [agentic] T{num_turns}: no tool calls → treating as finish")
                finished = True
                break
            else:
                content_text = assistant_msg.content or ""
                # Try to parse inline JSON as tool calls (model sometimes
                # embeds tool arguments as text instead of using the API)
                parsed_calls = _parse_inline_tool_calls(content_text)
                if parsed_calls:
                    if printing:
                        names = [c[0] for c in parsed_calls]
                        print(f"  [agentic] T{num_turns}: parsed {len(parsed_calls)} inline tool call(s): {names}")
                    for fn_name, fn_args in parsed_calls:
                        if fn_name == "finish" and not has_written:
                            continue
                        tool_result = _dispatch_tool(fs, fn_name, fn_args)
                        if fn_name in ("write_file", "run_python"):
                            has_written = True
                        if fn_name == "read_file":
                            files_read.append(fn_args.get("filename", "?"))
                        tool_calls_log.append({"tool": fn_name, "turn": num_turns, "args_keys": list(fn_args.keys())})
                        operation_sequence.append(fn_name)
                        if fn_name == "finish" and has_written:
                            finished = True
                            break
                    if finished:
                        break
                    # If we executed some calls, continue the loop
                    # (add a synthetic user message so the model sees the results)
                    messages.append({"role": "user", "content": "Tool calls executed. Continue editing or call finish() when done."})
                    continue
                else:
                    # Genuinely no tool calls and nothing parseable — nudge
                    if printing:
                        print(f"  [agentic] T{num_turns}: no tool calls, no writes → nudging")
                    messages.append({
                        "role": "user",
                        "content": (
                            "You haven't made any edits yet. Please use the tools "
                            "(read_file, write_file, run_python) to complete the task, "
                            "then call finish()."
                        ),
                    })
                    continue

        # ── Process tool calls ──
        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                fn_args = {}

            # Reject finish() if no write operation has been performed
            if fn_name == "finish" and not has_written:
                tool_result = (
                    "Error: you must make at least one change (via write_file or "
                    "run_python) before calling finish(). Read the files, apply "
                    "the requested edits, then call finish()."
                )
            else:
                tool_result = _dispatch_tool(fs, fn_name, fn_args)

            # Track write operations
            if fn_name in ("write_file", "run_python"):
                has_written = True

            # Track which files were read (for distractor analysis)
            if fn_name == "read_file":
                files_read.append(fn_args.get("filename", "?"))

            tool_calls_log.append({
                "tool": fn_name,
                "turn": num_turns,
                "args_keys": list(fn_args.keys()),
            })
            operation_sequence.append(fn_name)

            # Add tool response to conversation
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })

            if printing:
                args_summary = ", ".join(
                    f"{k}={'...' if k in ('content', 'code') else repr(fn_args[k])}"
                    for k in fn_args
                )
                print(f"  [agentic] T{num_turns}: {fn_name}({args_summary})")

            if fn_name == "finish" and has_written:
                finished = True
                break

        if finished:
            break

        # ── Budget check ──
        if total_tokens > MAX_TOTAL_TOKENS:
            if printing:
                print(f"  [agentic] Token budget exceeded ({total_tokens:,} > {MAX_TOTAL_TOKENS:,}), stopping.")
            break

    if printing:
        status = "finished" if finished else "budget/turn limit"
        print(f"  [agentic] Done ({status}): {num_turns} turns, "
              f"{len(tool_calls_log)} tool calls, {total_tokens:,} tokens, ${total_usd:.4f}")

    # ── Build output ──
    final_context = fs.snapshot()

    # Strip distractor files from output to prevent context bloat across rounds.
    # In single-shot mode, the LLM only outputs target files, so distractors are
    # naturally excluded. Here we must do it explicitly since the VirtualFS
    # retains files the agent didn't delete.
    if distractor_filenames:
        distractor_set = set(distractor_filenames)
        stripped = [f for f in final_context if f in distractor_set]
        for f in stripped:
            del final_context[f]
        if printing and stripped:
            print(f"  [agentic] Stripped {len(stripped)} distractor files from output: {stripped}")

    response_str = stringify_context(final_context)

    metadata = {
        # Standard fields (same as single-shot)
        "latency": total_latency,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "reasoning_tokens": total_reasoning_tokens,
        "total_tokens": total_tokens,
        "total_usd": total_usd,
        # Agentic-specific fields
        "agentic_num_turns": num_turns,
        "agentic_num_tool_calls": len(tool_calls_log),
        "agentic_tool_calls": tool_calls_log,
        "agentic_operation_sequence": operation_sequence,
        "agentic_finished_cleanly": finished,
        "agentic_files_read": files_read,
    }

    return {"response": response_str, "metadata": metadata}
