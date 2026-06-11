#!/usr/bin/env python3
"""Grok-only repo worker for orchestrator-led coding workflows.

This script is intentionally separate from low_tier_agent.py. It lets a high
model such as Codex or Claude orchestrate work while Grok Composer does bounded
repo search or proposes one-file edits.

The script never applies edits. It returns JSON for the orchestrator to inspect,
retry, reject, or apply itself.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


DEFAULT_MODEL = "grok-composer-2.5-fast"
DEFAULT_MAX_TURNS = 8
DEFAULT_EXCLUDES = [
    ".git/",
    "node_modules/",
    "logs/",
    "coverage/",
    "dist/",
    "build/",
    ".next/",
    ".cache/",
    "tmp/",
    "test/",
    "tests/",
    "native/",
    "masterdata/",
    "lang/",
    "**/.do_batch/",
    "**/__pycache__/",
    "*.pyc",
    "*.log",
    "tests/**/*.pdf",
    "tests/**/*.zip",
    "tests/**/*.7z",
    "tests/**/*.tar",
    "tests/**/*.gz",
    "tests/**/*.png",
    "tests/**/*.jpg",
    "tests/**/*.jpeg",
    "tests/**/*.gif",
    "tests/**/*.webp",
    "tests/**/*.mp4",
    "tests/**/*.mov",
    "tests/**/*.mkv",
    "tests/**/*.webm",
]
DEFAULT_EXCLUDE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "repo",
    "grok_clean_excludes.txt",
)

READ_ONLY_DENY_TOOLS = (
    "run_terminal_cmd,search_replace,write,web_search,web_fetch,open_page,Agent"
)

SEARCH_SYSTEM = (
    "You are a read-only codebase search worker. You MAY use grep, read_file, "
    "and list_dir. You MUST NOT modify files, run shell commands, use the web, "
    "or spawn agents. Your final answer must be a single valid JSON object and "
    "nothing else."
)

EDIT_SYSTEM = (
    "You are a read-only codebase edit-proposal worker. You MAY use grep, "
    "read_file, and list_dir. You MUST NOT modify files, run shell commands, "
    "use the web, or spawn agents. Your final answer must be a single valid "
    "JSON object and nothing else."
)

SEARCH_PROMPT = """Search the repository at the current working directory.

Query: {query}
{scope}
Investigate before answering. Prefer a few high-signal findings over an
exhaustive dump. Paths must be relative to the repository root.

Return only this JSON shape:
{{
  "found": true,
  "summary": "1-3 sentence answer",
  "results": [
    {{
      "file": "relative/path.ext",
      "start_line": 10,
      "end_line": 25,
      "symbol": "name or null",
      "why": "why this location matters"
    }}
  ]
}}

If nothing relevant is found:
{{
  "found": false,
  "summary": "what was searched and why nothing matched",
  "results": []
}}
"""

EDIT_PROMPT = """Investigate the repository and propose exactly ONE file
creation or ONE file update. Do not modify files yourself.

Task: {instruction}
{scope}
Rules:
- Return one file only.
- If the task needs more files, return the best first file and set
  "requires_followup": true with a concise "followup_query".
- For updates, copy "original_content" character-for-character from the target
  file.
- For creates, use "operation": "create", null line numbers, and null
  "original_content".
- Paths must be relative to the repository root.

Return only this JSON shape for updates:
{{
  "success": true,
  "operation": "update",
  "summary": "one-line description",
  "file": "relative/path.ext",
  "start_line": 10,
  "end_line": 25,
  "original_content": "exact text being replaced with newlines escaped",
  "replacement_content": "replacement text with newlines escaped",
  "original_line_count": 0,
  "replacement_line_count": 0,
  "requires_followup": false,
  "followup_query": null
}}

Return only this JSON shape for creates:
{{
  "success": true,
  "operation": "create",
  "summary": "one-line description",
  "file": "relative/path.ext",
  "start_line": null,
  "end_line": null,
  "original_content": null,
  "replacement_content": "complete file content with newlines escaped",
  "original_line_count": 0,
  "replacement_line_count": 0,
  "requires_followup": false,
  "followup_query": null
}}

If no useful one-file proposal can be made:
{{
  "success": false,
  "operation": null,
  "summary": "brief reason",
  "file": null,
  "start_line": null,
  "end_line": null,
  "original_content": null,
  "replacement_content": null,
  "original_line_count": 0,
  "replacement_line_count": 0,
  "requires_followup": false,
  "followup_query": null
}}
"""


def read_exclude_file(path):
    excludes = []
    if not path or not os.path.exists(path):
        return excludes
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            excludes.append(line)
    return excludes


def parse_excludes(values, exclude_file):
    excludes = list(DEFAULT_EXCLUDES)
    excludes.extend(read_exclude_file(exclude_file))
    for value in values or []:
        for item in value.split(","):
            item = item.strip()
            if item:
                excludes.append(item)
    result = []
    seen = set()
    for item in excludes:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def write_clean_grok_config(workspace):
    config_dir = os.path.join(workspace, ".grok")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "config.toml")
    with open(config_path, "a", encoding="utf-8") as fh:
        fh.write("\n[features]\ncodebase_indexing = false\n")
        fh.write("\n[tools]\nrespect_gitignore = true\n")


def init_clean_git_repo(workspace):
    if shutil.which("git") is None:
        return
    subprocess.run(
        ["git", "init", "-q"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=30,
    )


def materialize_clean_workspace(source_root, excludes, disable_indexing=True, init_git=True):
    if shutil.which("rsync") is None:
        raise RuntimeError("rsync is required for --cwd-strategy clean-copy")

    tmp_parent = tempfile.mkdtemp(prefix="grok-repo-agent-")
    workspace = os.path.join(tmp_parent, "workspace")
    os.makedirs(workspace, exist_ok=True)

    cmd = ["rsync", "-a", "--delete"]
    for pattern in excludes:
        cmd.extend(["--exclude", pattern])
    cmd.extend([os.path.join(source_root, ""), os.path.join(workspace, "")])

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        shutil.rmtree(tmp_parent, ignore_errors=True)
        raise RuntimeError(f"rsync failed: {res.stderr[:600].strip()}")

    if disable_indexing:
        write_clean_grok_config(workspace)
    if init_git:
        init_clean_git_repo(workspace)
    return workspace, tmp_parent


def resolve_workspace(args):
    source_root = os.path.abspath(args.search_root or os.getcwd())
    if not os.path.isdir(source_root):
        raise RuntimeError(f"search root is not a directory: {source_root}")

    if args.cwd_strategy == "source":
        return source_root, None, source_root

    excludes = parse_excludes(args.exclude, args.exclude_file)
    workspace, tmp_parent = materialize_clean_workspace(
        source_root,
        excludes,
        disable_indexing=not args.keep_codebase_indexing,
        init_git=not args.no_init_clean_git,
    )
    return workspace, tmp_parent, source_root


def extract_json_object(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    obj = re.search(r"(\{.*\})", text, re.DOTALL)
    if obj:
        return json.loads(obj.group(1))

    raise ValueError("no JSON object found in Grok output")


def decode_grok_stdout(stdout):
    text = stdout.strip()
    if not text:
        raise RuntimeError("grok returned empty stdout")

    try:
        envelope = json.loads(text)
        if isinstance(envelope, dict) and isinstance(envelope.get("text"), str):
            return envelope["text"]
    except json.JSONDecodeError:
        pass

    return text


def build_grok_cmd(prompt, args, workspace):
    cmd = [
        "grok",
        "-p",
        prompt,
        "--model",
        args.model,
        "--output-format",
        "json",
        "--always-approve",
        "--no-memory",
        "--no-plan",
        "--no-subagents",
        "--no-alt-screen",
        "--disable-web-search",
        "--cwd",
        workspace,
        "--disallowed-tools",
        READ_ONLY_DENY_TOOLS,
        "--max-turns",
        str(args.max_turns),
    ]
    if args.check:
        cmd.append("--check")
    if args.best_of_n:
        cmd.extend(["--best-of-n", str(args.best_of_n)])
    if args.agent:
        cmd.extend(["--agent", args.agent])
    return cmd


def run_grok(prompt, args, workspace):
    cmd = build_grok_cmd(prompt, args, workspace)
    env = {**os.environ, "GROK_RESPECT_GITIGNORE": "1"}
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=args.timeout,
        env=env,
    )
    if res.returncode != 0:
        stderr = (res.stderr or "").strip()
        stdout = (res.stdout or "").strip()
        detail = stderr
        if stdout:
            detail = f"{detail}\n--- stdout ---\n{stdout}" if detail else stdout
        raise RuntimeError(f"grok exit={res.returncode}: {detail[:4000]}")
    return extract_json_object(decode_grok_stdout(res.stdout))


def validate_search(parsed, source_root):
    warnings = []
    for idx, item in enumerate(parsed.get("results") or []):
        file_path = item.get("file")
        if not file_path or os.path.isabs(file_path) or ".." in file_path.split(os.sep):
            warnings.append(f"results[{idx}].file is not a safe relative path")
            continue
        full_path = os.path.abspath(os.path.join(source_root, file_path))
        if not full_path.startswith(source_root + os.sep) and full_path != source_root:
            warnings.append(f"results[{idx}].file escapes search root")
        elif not os.path.exists(full_path):
            warnings.append(f"results[{idx}].file does not exist in source root")
    return warnings


def validate_edit(parsed, source_root):
    warnings = []
    if not parsed.get("success"):
        return warnings

    file_path = parsed.get("file")
    if not file_path or os.path.isabs(file_path) or ".." in file_path.split(os.sep):
        return ["file is not a safe relative path"]

    full_path = os.path.abspath(os.path.join(source_root, file_path))
    if not full_path.startswith(source_root + os.sep) and full_path != source_root:
        return ["file escapes search root"]

    operation = parsed.get("operation")
    if operation == "create":
        if os.path.exists(full_path):
            warnings.append("create target already exists")
        return warnings

    if operation != "update":
        return [f"unsupported operation: {operation}"]

    if not os.path.exists(full_path):
        return ["update target does not exist"]

    with open(full_path, "r", encoding="utf-8", errors="ignore") as fh:
        content = fh.read()
    original = parsed.get("original_content")
    if not isinstance(original, str) or original not in content:
        warnings.append("original_content was not found verbatim in source file")
    return warnings


def path_size(path):
    total = 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in {".git"}]
        for name in files:
            full_path = os.path.join(root, name)
            try:
                total += os.path.getsize(full_path)
            except OSError:
                pass
    return total


def workspace_stats(workspace):
    entries = []
    total_files = 0
    for root, dirs, files in os.walk(workspace):
        total_files += len(files)
        if ".git" in dirs:
            dirs.remove(".git")
    for entry in os.scandir(workspace):
        if entry.name == ".git":
            continue
        entries.append({
            "path": entry.name,
            "bytes": path_size(entry.path),
        })
    entries.sort(key=lambda item: item["bytes"], reverse=True)
    return {
        "workspace": workspace,
        "total_bytes": path_size(workspace),
        "total_files": total_files,
        "largest_top_level": entries[:20],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True, choices=["search", "agent-edit", "inspect-workspace"])
    parser.add_argument("--query", help="Search query; alias for agent-edit instruction")
    parser.add_argument("--instruction", help="Edit proposal instruction")
    parser.add_argument("--file", help="Optional focus path hint")
    parser.add_argument("--search-root", default=None, help="Root to search; default: cwd")
    parser.add_argument("--cwd-strategy", choices=["source", "clean-copy"], default="clean-copy")
    parser.add_argument("--exclude", action="append", default=[],
                        help="Extra rsync exclude for clean-copy; repeat or comma-separate")
    parser.add_argument("--exclude-file", default=DEFAULT_EXCLUDE_FILE,
                        help="Path to repo-specific clean-copy exclude file")
    parser.add_argument("--keep-workspace", action="store_true",
                        help="Keep the temporary clean-copy workspace for debugging")
    parser.add_argument("--keep-codebase-indexing", action="store_true",
                        help="Do not write clean-copy .grok/config.toml disabling codebase_indexing")
    parser.add_argument("--no-init-clean-git", action="store_true",
                        help="Do not git init the temporary clean-copy workspace")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--check", action="store_true", help="Pass --check to Grok")
    parser.add_argument("--best-of-n", type=int, default=None)
    parser.add_argument("--agent", default=None,
                        help="Optional Grok agent name/path for experiments; default avoids agents")

    args = parser.parse_args()

    tmp_parent = None
    try:
        workspace, tmp_parent, source_root = resolve_workspace(args)
        if tmp_parent and args.keep_workspace:
            sys.stderr.write(f"Clean workspace: {workspace}\n")

        if args.action == "inspect-workspace":
            parsed = workspace_stats(workspace)
            if tmp_parent and args.keep_workspace:
                parsed["_workspace"] = workspace
            print(json.dumps(parsed, indent=2))
            return

        scope = f"Focus near: {args.file}\n" if args.file else ""
        if args.action == "search":
            if not args.query:
                raise RuntimeError("--query is required for search")
            prompt = f"{SEARCH_SYSTEM}\n\n{SEARCH_PROMPT.format(query=args.query, scope=scope)}"
            parsed = run_grok(prompt, args, workspace)
            warnings = validate_search(parsed, source_root)
        else:
            instruction = args.instruction or args.query
            if not instruction:
                raise RuntimeError("--instruction or --query is required for agent-edit")
            prompt = f"{EDIT_SYSTEM}\n\n{EDIT_PROMPT.format(instruction=instruction, scope=scope)}"
            parsed = run_grok(prompt, args, workspace)
            warnings = validate_edit(parsed, source_root)

        if warnings:
            parsed["_validation_warnings"] = warnings
        if tmp_parent and args.keep_workspace:
            parsed["_workspace"] = workspace
        print(json.dumps(parsed, indent=2))
    except Exception as exc:
        sys.stderr.write(f"Execution Error: {exc}\n")
        sys.exit(1)
    finally:
        if tmp_parent and not args.keep_workspace:
            shutil.rmtree(tmp_parent, ignore_errors=True)


if __name__ == "__main__":
    main()
