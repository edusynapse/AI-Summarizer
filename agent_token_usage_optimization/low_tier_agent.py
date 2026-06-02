#!/usr/bin/env python3
"""Low-tier LLM Agent helper script.

Provides common context-gathering and localized editing capabilities
by executing tasks against a low-cost, fast model via the agy or grok
CLI tools.

Providers:
  agy  — Antigravity CLI, uses Gemini 3.5 Flash (Low) by default.
  grok — Grok CLI, uses grok-composer-2.5-fast by default.

The `search` action spawns a grok sub-agent thread with read-only tools
(grep, read_file, list_dir) enabled so a cheap, fast model can browse the
repository and return structured findings as JSON.

Model selection (grok):
  composer (grok-composer-2.5-fast, the DEFAULT) — use for searching, locating,
    triangulating across code by reading it, and quick piece-by-piece edits.
    Composer wins whenever the required OUTPUT complexity is low; it is also
    faster and, in practice, more faithful at reproducing verbatim edit ranges.
  grok-build (--model grok-build) — reach for it only on heavy troubleshooting:
    reasoning across log files, hunting bugs, or multi-file investigation where
    the answer needs more sustained analysis.
"""
import os
import sys
import re
import json
import subprocess
import argparse
import fcntl

AGY_SETTINGS_PATH = os.environ.get(
    "AGY_SETTINGS_PATH",
    os.path.expanduser("~/.gemini/antigravity-cli/settings.json"),
)
LOCK_FILE = os.path.expanduser("~/.gemini/antigravity-cli/low_tier_agent.lock")

DEFAULT_AGY_MODEL = "Gemini 3.5 Flash (Low)"
DEFAULT_GROK_MODEL = "grok-composer-2.5-fast"

AGY_HEADLESS_INSTRUCTION = (
    "You are a code-editing tool. "
    "Respond with a single valid JSON object and nothing else. "
    "No code fences, no commentary before or after. "
    "All newlines inside JSON string values must be \\n-escaped. "
    "Do not use tools, do not write files."
)

GROK_DISALLOWED_TOOLS = (
    "run_terminal_cmd,search_replace,write,read_file,web_search,"
    "web_fetch,list_dir,grep,open_page,Agent"
)

# Search sub-agent: keep read-only navigation tools (grep, read_file, list_dir)
# ENABLED so the model can actually browse the repo; block everything that
# mutates state, runs shell, hits the network, or spawns more agents.
GROK_SEARCH_DISALLOWED_TOOLS = (
    "run_terminal_cmd,search_replace,write,web_search,web_fetch,open_page,Agent"
)

GROK_SEARCH_INSTRUCTION = (
    "You are a read-only codebase search sub-agent. "
    "You MAY use grep, read_file, and list_dir to investigate the repository. "
    "You MUST NOT modify, create, or delete any files, and MUST NOT run shell "
    "commands or fetch from the web. "
    "Your FINAL message must be a single valid JSON object and nothing else: "
    "no code fences, no commentary before or after."
)

# ── Negative constraints block (shared across all prompts) ─────────────────────
_NEGATIVE_CONSTRAINTS = """
Do NOT:
- Add imports or require statements unless the instruction explicitly asks.
- Rename symbols that the instruction did not mention.
- Add comments unless the instruction explicitly asks.
- Change formatting, indentation, or whitespace of lines the instruction did not ask you to modify.
- Emit prose, markdown, or commentary. Output ONLY the JSON object.
- Wrap the JSON in code fences (``` or ```json).
"""

# ── Indentation rule (shared) ──────────────────────────────────────────────────
_INDENTATION_RULE = (
    "Preserve the exact original indentation (spaces, not tabs; match the "
    "surrounding width character-for-character). Never re-indent unchanged lines."
)

FIND_SYMBOL_PROMPT = """You are a precise code search tool. Locate the start and end line numbers of the requested symbol in the provided code.
The code lines are numbered in the format '<line_number>: <code_line>'.
{constraints}

File Path: {path}
Symbol/Query: {query}

Code:
{code}

{indentation_rule}

Respond with a single valid JSON object and nothing else:
{{
  "found": true,
  "start_line": 42,
  "end_line": 85,
  "exact_match": "exact first-line content or signature of the match"
}}
If the symbol is not found:
{{
  "found": false,
  "start_line": null,
  "end_line": null,
  "exact_match": null
}}
"""

SUGGEST_EDIT_PROMPT = """You are a precise code-editing tool. Apply the requested edit to the exact line range given.
The code lines are numbered in the format '<line_number>: <code_line>'.
{constraints}

File Path: {path}
Requested range: lines {start_line}–{end_line}
Instruction: {instruction}

Target Code Block (lines {start_line}–{end_line}, verbatim):
{code}

CRITICAL RULES — read before responding:
1. "original_content" MUST be the EXACT, character-for-character text of lines {start_line}–{end_line} as shown above — same leading whitespace, same indentation width, no added/removed lines, no reflowing. Do not extend past or stop short of the range. If the range cuts a statement mid-expression, copy it as-is anyway; do not "complete" it.
2. Only modify what the instruction requires. Every other line in the block must appear byte-identical in "replacement_content".
3. {indentation_rule}
4. "start_line" and "end_line" in the response MUST equal the requested range ({start_line} and {end_line}).

Respond with a single valid JSON object and nothing else:
{{
  "success": true,
  "start_line": {start_line},
  "end_line": {end_line},
  "original_content": "exact verbatim text of lines {start_line}–{end_line} (newlines as \\n)",
  "replacement_content": "modified text with only the instructed changes applied (newlines as \\n)",
  "original_line_count": 0,
  "replacement_line_count": 0
}}
If the instruction cannot be applied or is invalid:
{{
  "success": false,
  "start_line": {start_line},
  "end_line": {end_line},
  "original_content": null,
  "replacement_content": null,
  "original_line_count": 0,
  "replacement_line_count": 0
}}
"""

INSPECT_ERRORS_PROMPT = """You are a precise code-fixing tool. Inspect the compiler/test error and suggest the minimal fix.
The code lines are numbered in the format '<line_number>: <code_line>'.
{constraints}

File Path: {path}
Error Output:
{error}

Code:
{code}

CRITICAL RULES:
1. "original_content" MUST be the EXACT, character-for-character text of the lines you are replacing — same leading whitespace, same indentation width. Do not add or remove lines beyond what the fix requires.
2. Only modify what the fix requires. Every other line must appear byte-identical.
3. {indentation_rule}
4. "start_line" and "end_line" must be the actual line numbers of the block you are replacing.

Respond with a single valid JSON object and nothing else:
{{
  "success": true,
  "suggested_fix": "one-line description of the fix",
  "start_line": 0,
  "end_line": 0,
  "original_content": "exact verbatim text of the lines being replaced (newlines as \\n)",
  "replacement_content": "fixed text with only the error-fixing changes (newlines as \\n)",
  "original_line_count": 0,
  "replacement_line_count": 0
}}
If the error cannot be resolved or is not related to this file:
{{
  "success": false,
  "suggested_fix": null,
  "start_line": null,
  "end_line": null,
  "original_content": null,
  "replacement_content": null,
  "original_line_count": 0,
  "replacement_line_count": 0
}}
"""

FIND_ANCHOR_PROMPT = """You are a precise code search tool. Find the target symbol/region and return short, unique text anchors that bound it.
The code lines are numbered in the format '<line_number>: <code_line>'.
{constraints}

File Path: {path}
Symbol/Query: {query}

Code:
{code}

Return a JSON object with:
- "before_anchor": a short (1-3 line) unique text snippet that appears IMMEDIATELY BEFORE the target region. Copy it character-for-character from the code.
- "after_anchor": a short (1-3 line) unique text snippet that appears IMMEDIATELY AFTER the target region. Copy it character-for-character from the code.
- "target_content": the exact, verbatim text of the target region itself (the symbol body). Copy character-for-character.
- "start_line" and "end_line": the line numbers of the target region.

The anchors must be unique in the file — not repeated elsewhere. Prefer structural boundaries (function signatures, closing braces, blank lines between blocks).

{indentation_rule}

Respond with a single valid JSON object and nothing else:
{{
  "found": true,
  "start_line": 42,
  "end_line": 85,
  "before_anchor": "unique text just before the target",
  "after_anchor": "unique text just after the target",
  "target_content": "exact verbatim content of the target region (newlines as \\n)",
  "target_line_count": 0
}}
If not found:
{{
  "found": false,
  "start_line": null,
  "end_line": null,
  "before_anchor": null,
  "after_anchor": null,
  "target_content": null,
  "target_line_count": 0
}}
"""

SEARCH_PROMPT = """You are a codebase search sub-agent running inside the repository at the current working directory.
Use your read-only tools (grep, read_file, list_dir) to locate the code most relevant to the query. Investigate before answering: grep for symbols and strings, list directories, and read only the smallest snippets you need. Do not modify any files.

Query: {query}
{scope_hint}
When you have gathered enough, stop and report ONLY the most relevant findings. Paths must be relative to the repository root. Prefer a small number of high-signal results over an exhaustive dump.

Respond with a single valid JSON object as your FINAL message and nothing else:
{{
  "found": true,
  "summary": "1-3 sentence synthesis that directly answers the query",
  "results": [
    {{"file": "relative/path.ext", "start_line": 10, "end_line": 25, "symbol": "name or null", "why": "why this is relevant to the query"}}
  ]
}}
If nothing relevant is found:
{{
  "found": false,
  "summary": "brief note on what was searched and why nothing matched",
  "results": []
}}
"""


def detect_lang(path):
    ext = os.path.splitext(path)[1].lower()
    mapping = {
        ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js",
        ".ts": "ts", ".tsx": "ts",
        ".py": "py", ".dart": "dart", ".rs": "rust", ".go": "go", ".java": "java",
    }
    return mapping.get(ext, "unknown")


def compress_code_with_line_numbers(content, language):
    lines = content.splitlines()
    n_lines = len(lines)
    chars = list(content)
    n_chars = len(chars)

    char_to_line = []
    current_line = 0
    for c in chars:
        char_to_line.append(current_line)
        if c == '\n':
            current_line += 1

    is_comment = [False] * n_chars
    idx = 0
    in_string = None
    escaped = False

    while idx < n_chars:
        c = chars[idx]
        if in_string is not None:
            if escaped:
                escaped = False
                idx += 1
                continue
            if c == '\\':
                escaped = True
                idx += 1
                continue
            if c == in_string:
                in_string = None
                idx += 1
                continue
            idx += 1
            continue

        if c == '"':
            in_string = '"'
            idx += 1
            continue
        if c == "'":
            in_string = "'"
            idx += 1
            continue

        if language == "py":
            if c == '#':
                while idx < n_chars and chars[idx] != '\n':
                    is_comment[idx] = True
                    idx += 1
                continue
        else:
            if idx + 1 < n_chars and c == '/' and chars[idx + 1] == '/':
                while idx < n_chars and chars[idx] != '\n':
                    is_comment[idx] = True
                    idx += 1
                continue
            if idx + 1 < n_chars and c == '/' and chars[idx + 1] == '*':
                is_comment[idx] = True
                is_comment[idx + 1] = True
                idx += 2
                while idx + 1 < n_chars and not (chars[idx] == '*' and chars[idx + 1] == '/'):
                    is_comment[idx] = True
                    idx += 1
                if idx < n_chars:
                    is_comment[idx] = True
                if idx + 1 < n_chars:
                    is_comment[idx + 1] = True
                idx += 2
                continue
        idx += 1

    line_contents = [[] for _ in range(n_lines)]
    for idx, c in enumerate(chars):
        line_idx = char_to_line[idx]
        if line_idx < n_lines and not is_comment[idx]:
            line_contents[line_idx].append(c)

    processed_lines = []
    for line_idx, char_list in enumerate(line_contents):
        line_str = "".join(char_list).rstrip()
        if line_str:
            processed_lines.append((line_idx + 1, line_str))
    return processed_lines


def format_numbered_lines(numbered_lines):
    return "\n".join(f"{line_num}: {line_content}" for line_num, line_content in numbered_lines)


def read_agy_settings():
    with open(AGY_SETTINGS_PATH) as f:
        return json.load(f)


def write_agy_settings(settings):
    with open(AGY_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2, sort_keys=True)
        f.write("\n")


def set_agy_model(model):
    settings = read_agy_settings()
    if settings.get("model") == model:
        return None
    snapshot = {
        "had": "model" in settings,
        "previous": settings.get("model"),
    }
    settings["model"] = model
    write_agy_settings(settings)
    return snapshot


def restore_agy_model(snapshot):
    if not snapshot:
        return
    try:
        settings = read_agy_settings()
        if snapshot["had"]:
            settings["model"] = snapshot["previous"]
        else:
            settings.pop("model", None)
        write_agy_settings(settings)
    except Exception as e:
        sys.stderr.write(f"Warning: failed to restore model settings: {e}\n")


def call_agy(prompt, model, timeout):
    full_prompt = f"{AGY_HEADLESS_INSTRUCTION}\n\n{prompt}"
    snapshot = None
    if model:
        try:
            snapshot = set_agy_model(model)
        except Exception as e:
            raise RuntimeError(f"agy cannot set model in {AGY_SETTINGS_PATH}: {e}")
    try:
        res = subprocess.run(
            ["agy"],
            input=full_prompt,
            capture_output=True, text=True, timeout=timeout,
        )
    finally:
        restore_agy_model(snapshot)
    if res.returncode != 0:
        raise RuntimeError(f"agy exit={res.returncode}: {res.stderr[:400].strip()}")
    out = (res.stdout or "").strip()
    if not out:
        raise RuntimeError("agy returned empty output")
    return out


def clean_grok_output(raw):
    """Strip grok CLI noise (timestamps, ERROR lines, markdown fences)."""
    text = raw.strip()
    lines = text.split("\n")
    filtered = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip grok stderr-like lines that leak into stdout
        if re.match(r"^\d{4}-\d{2}-\d{2}T", stripped):
            continue
        if "ERROR" in stripped or "failed to watch" in stripped or "watch root" in stripped:
            continue
        filtered.append(line)
    text = "\n".join(filtered).strip()
    # Strip markdown code fences
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\r?\n?", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    return text


def call_grok(prompt, model, timeout):
    """Call the Grok CLI with tool-disabled headless flags."""
    grok_model = model or DEFAULT_GROK_MODEL
    full_prompt = f"{AGY_HEADLESS_INSTRUCTION}\n\n{prompt}"
    args = [
        "grok",
        "-p", full_prompt,
        "--model", grok_model,
        "--output-format", "plain",
        "--always-approve",
        "--no-memory",
        "--no-plan",
        "--no-subagents",
        "--no-alt-screen",
        "--cwd", "/tmp",
        "--disallowed-tools", GROK_DISALLOWED_TOOLS,
    ]
    res = subprocess.run(
        args,
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ},
    )
    if res.returncode != 0:
        raise RuntimeError(f"grok exit={res.returncode}: {res.stderr[:400].strip()}")
    out = clean_grok_output(res.stdout or "")
    if not out:
        raise RuntimeError("grok returned empty output")
    return out


def call_grok_search(prompt, model, timeout, cwd):
    """Spawn a grok sub-agent thread with read-only tools enabled to search a repo.

    Unlike call_grok (which disables every tool for single-shot edits), this
    runs the cheap/fast model as an actual agent inside `cwd`, letting it
    grep/read/list to gather context, then return a final JSON object.
    """
    grok_model = model or DEFAULT_GROK_MODEL
    full_prompt = f"{GROK_SEARCH_INSTRUCTION}\n\n{prompt}"
    args = [
        "grok",
        "-p", full_prompt,
        "--model", grok_model,
        "--output-format", "plain",
        "--always-approve",
        "--no-memory",
        "--no-plan",
        "--no-subagents",
        "--no-alt-screen",
        "--disable-web-search",
        "--cwd", cwd,
        "--disallowed-tools", GROK_SEARCH_DISALLOWED_TOOLS,
    ]
    res = subprocess.run(
        args,
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ},
    )
    if res.returncode != 0:
        raise RuntimeError(f"grok search exit={res.returncode}: {res.stderr[:400].strip()}")
    out = clean_grok_output(res.stdout or "")
    if not out:
        raise RuntimeError("grok search returned empty output")
    return out


def call_llm(prompt, provider, model, timeout):
    """Dispatch to the configured provider."""
    if provider == "agy":
        return call_agy(prompt, model, timeout)
    if provider == "grok":
        return call_grok(prompt, model, timeout)
    raise ValueError(f"unsupported provider: {provider}")


def extract_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from output: {text}")


def validate_self_verify(parsed, action, args):
    """Orchestrator-side validation of self-verify fields.

    Checks echo-range guard and line-count consistency. Emits warnings to
    stderr but does NOT fail — the caller decides whether to reject.
    """
    warnings = []

    if action == "suggest-edit" and parsed.get("success"):
        # Echo-range guard: start_line / end_line must match requested range
        resp_start = parsed.get("start_line")
        resp_end = parsed.get("end_line")
        if resp_start is not None and resp_start != args.start_line:
            warnings.append(
                f"DRIFT: response start_line={resp_start} != requested {args.start_line}"
            )
        if resp_end is not None and resp_end != args.end_line:
            warnings.append(
                f"DRIFT: response end_line={resp_end} != requested {args.end_line}"
            )
        # Line-count self-verify
        orig_count = parsed.get("original_line_count")
        repl_count = parsed.get("replacement_line_count")
        orig_content = parsed.get("original_content") or ""
        repl_content = parsed.get("replacement_content") or ""
        actual_orig = orig_content.count("\n") + 1 if orig_content else 0
        actual_repl = repl_content.count("\n") + 1 if repl_content else 0
        if orig_count is not None and orig_count != actual_orig:
            warnings.append(
                f"LINE_COUNT: claimed original_line_count={orig_count}, actual={actual_orig}"
            )
        if repl_count is not None and repl_count != actual_repl:
            warnings.append(
                f"LINE_COUNT: claimed replacement_line_count={repl_count}, actual={actual_repl}"
            )
        # Verify original_content matches the actual file content for the range
        if orig_content and hasattr(args, '_raw_target_text'):
            if orig_content != args._raw_target_text:
                warnings.append("ANCHOR_MISMATCH: original_content does not match file content for requested range")

    elif action == "inspect-errors" and parsed.get("success"):
        orig_count = parsed.get("original_line_count")
        repl_count = parsed.get("replacement_line_count")
        orig_content = parsed.get("original_content") or ""
        repl_content = parsed.get("replacement_content") or ""
        actual_orig = orig_content.count("\n") + 1 if orig_content else 0
        actual_repl = repl_content.count("\n") + 1 if repl_content else 0
        if orig_count is not None and orig_count != actual_orig:
            warnings.append(
                f"LINE_COUNT: claimed original_line_count={orig_count}, actual={actual_orig}"
            )
        if repl_count is not None and repl_count != actual_repl:
            warnings.append(
                f"LINE_COUNT: claimed replacement_line_count={repl_count}, actual={actual_repl}"
            )

    if warnings:
        for w in warnings:
            sys.stderr.write(f"VALIDATION WARNING: {w}\n")
    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True,
                        choices=["find-symbol", "suggest-edit", "inspect-errors", "find-anchor", "search"])
    parser.add_argument("--file", help="Target file path (required for all actions except search)")
    parser.add_argument("--search-root", default=None,
                        help="Repo root the search sub-agent runs in (search action; default: cwd)")
    parser.add_argument("--query", help="Symbol name or search query (for find-symbol, find-anchor, search)")
    parser.add_argument("--start-line", type=int, help="Start line number (for suggest-edit)")
    parser.add_argument("--end-line", type=int, help="End line number (for suggest-edit)")
    parser.add_argument("--instruction", help="Edit instruction description (for suggest-edit)")
    parser.add_argument("--error", help="Error message output (for inspect-errors)")
    parser.add_argument("--provider", choices=["agy", "grok"], default="agy",
                        help="LLM provider: agy (Antigravity CLI) or grok (Grok CLI)")
    parser.add_argument("--model", default=None,
                        help="Model override (default: auto per provider — 'Gemini 3.5 Flash (Low)' for agy, 'grok-composer-2.5-fast' for grok)")
    parser.add_argument("--timeout", type=int, default=120, help="Process timeout in seconds")

    args = parser.parse_args()

    # ── search: a grok sub-agent thread (read-only tools) over a whole repo ──
    # Self-contained: always uses grok (the fast composer model), needs no
    # --file, and returns structured JSON findings.
    if args.action == "search":
        if not args.query:
            sys.stderr.write("Error: --query is required for search action\n")
            sys.exit(1)
        search_root = os.path.abspath(args.search_root or os.getcwd())
        if not os.path.isdir(search_root):
            sys.stderr.write(f"Error: search root is not a directory: {search_root}\n")
            sys.exit(1)
        # search always runs on grok; honor --model only when it's a grok override
        search_model = args.model if (args.model and args.provider == "grok") else DEFAULT_GROK_MODEL
        scope_hint = f"Focus your search under: {args.file}\n" if args.file else ""
        prompt = SEARCH_PROMPT.format(query=args.query, scope_hint=scope_hint)
        try:
            response_text = call_grok_search(prompt, search_model, args.timeout, search_root)
            parsed_json = extract_json(response_text)
            print(json.dumps(parsed_json, indent=2))
        except Exception as e:
            sys.stderr.write(f"Execution Error: {e}\n")
            sys.exit(1)
        return

    # Resolve default model per provider if not explicitly set
    if args.model is None:
        args.model = DEFAULT_GROK_MODEL if args.provider == "grok" else DEFAULT_AGY_MODEL

    if not args.file:
        sys.stderr.write(f"Error: --file is required for {args.action} action\n")
        sys.exit(1)

    if not os.path.exists(args.file):
        sys.stderr.write(f"Error: file not found: {args.file}\n")
        sys.exit(1)

    try:
        with open(args.file, "r", encoding="utf-8", errors="ignore") as f:
            file_content = f.read()
    except Exception as e:
        sys.stderr.write(f"Error reading file {args.file}: {e}\n")
        sys.exit(1)

    lang = detect_lang(args.file)
    prompt_vars = {
        "constraints": _NEGATIVE_CONSTRAINTS,
        "indentation_rule": _INDENTATION_RULE,
    }

    # 1. Compile prompt based on action
    if args.action == "find-symbol":
        if not args.query:
            sys.stderr.write("Error: --query is required for find-symbol action\n")
            sys.exit(1)
        compressed = compress_code_with_line_numbers(file_content, lang)
        formatted_code = format_numbered_lines(compressed)
        prompt = FIND_SYMBOL_PROMPT.format(
            path=args.file, query=args.query, code=formatted_code, **prompt_vars
        )

    elif args.action == "find-anchor":
        if not args.query:
            sys.stderr.write("Error: --query is required for find-anchor action\n")
            sys.exit(1)
        compressed = compress_code_with_line_numbers(file_content, lang)
        formatted_code = format_numbered_lines(compressed)
        prompt = FIND_ANCHOR_PROMPT.format(
            path=args.file, query=args.query, code=formatted_code, **prompt_vars
        )

    elif args.action == "suggest-edit":
        if args.start_line is None or args.end_line is None or not args.instruction:
            sys.stderr.write("Error: --start-line, --end-line, and --instruction are required for suggest-edit\n")
            sys.exit(1)
        lines = file_content.splitlines()
        if args.start_line < 1 or args.end_line > len(lines) or args.start_line > args.end_line:
            sys.stderr.write(f"Error: invalid line range {args.start_line}-{args.end_line} (file has {len(lines)} lines)\n")
            sys.exit(1)
        # Extract raw target text for orchestrator-side anchor verification
        raw_target_lines = lines[args.start_line - 1 : args.end_line]
        args._raw_target_text = "\n".join(raw_target_lines)
        target_lines = [(i + 1, lines[i]) for i in range(args.start_line - 1, args.end_line)]
        formatted_code = format_numbered_lines(target_lines)
        prompt = SUGGEST_EDIT_PROMPT.format(
            path=args.file,
            start_line=args.start_line,
            end_line=args.end_line,
            instruction=args.instruction,
            code=formatted_code,
            **prompt_vars
        )

    elif args.action == "inspect-errors":
        if not args.error:
            sys.stderr.write("Error: --error is required for inspect-errors action\n")
            sys.exit(1)
        compressed = compress_code_with_line_numbers(file_content, lang)
        formatted_code = format_numbered_lines(compressed)
        prompt = INSPECT_ERRORS_PROMPT.format(
            path=args.file, error=args.error, code=formatted_code, **prompt_vars
        )

    # 2. Execute against the selected provider
    try:
        if args.provider == "agy":
            os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
            with open(LOCK_FILE, "w") as lock_f:
                try:
                    fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    sys.stderr.write("Waiting for low-tier agent model settings lock...\n")
                    fcntl.flock(lock_f, fcntl.LOCK_EX)
                response_text = call_llm(prompt, args.provider, args.model, args.timeout)
        else:
            response_text = call_llm(prompt, args.provider, args.model, args.timeout)
        parsed_json = extract_json(response_text)

        # 3. Orchestrator-side self-verify validation
        validation_warnings = validate_self_verify(parsed_json, args.action, args)
        if validation_warnings:
            parsed_json["_validation_warnings"] = validation_warnings

        print(json.dumps(parsed_json, indent=2))
    except Exception as e:
        sys.stderr.write(f"Execution Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
