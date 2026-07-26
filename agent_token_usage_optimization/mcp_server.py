#!/usr/bin/env python3
"""Optional MCP (Model Context Protocol) stdio server for both brokers.

Exposes tools that mirror:
  summary_broker.py  — search, grep, read, rollup, list, hotspots, semantic
  broker.py          — search, outline, read, summary, context (list)

No third-party MCP SDK required — speaks JSON-RPC 2.0 over stdin/stdout
compatible with Claude Desktop / Cursor / other MCP hosts.

Configure (example Claude Desktop snippet):

  {
    "mcpServers": {
      "ai-summarizer": {
        "command": "python3",
        "args": [
          "/abs/path/to/repo/skills/agent_token_usage_optimization/mcp_server.py"
        ],
        "cwd": "/abs/path/to/repo"
      }
    }
  }

Run manually for smoke test:
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' | python3 mcp_server.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib import (  # noqa: E402
    outline,
    search,
    summarize,
    languages,
    summary_search,
    embeddings_search,
    context_tiers,
    minify as mz,
)

REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
# When skill is at <repo>/skills/agent_token_usage_optimization, parents[2] is repo root.
# install layout: skill under skills/ → join(HERE, "..", "..") is correct.
if os.path.basename(os.path.dirname(HERE)) == "skills":
    REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
else:
    # Running from AI-Summarizer source tree itself (skill at repo root)
    REPO_ROOT = os.environ.get("AI_SUMMARIZER_REPO_ROOT") or os.getcwd()

REPO_DIR = os.path.join(HERE, "repo")
LLM_SUMMARIES_DIR = os.path.join(HERE, "summaries", "repo")
REPO_CONTEXT_DIR = os.path.join(HERE, "summaries", "repo_context")

SERVER_NAME = "ai-summarizer-brokers"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"


def _read_source(path: str) -> str:
    full = path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)
    with open(full, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _tool_defs() -> List[Dict[str, Any]]:
    return [
        {
            "name": "summary_search",
            "description": "Keyword search over LLM file summaries and directory rollups (start here).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "dir": {"type": "string", "description": "optional subdirectory filter"},
                    "max": {"type": "integer", "default": 40},
                },
                "required": ["query"],
            },
        },
        {
            "name": "summary_grep",
            "description": "Regex search across the summary layer only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "dir": {"type": "string"},
                    "max": {"type": "integer", "default": 60},
                },
                "required": ["pattern"],
            },
        },
        {
            "name": "summary_read",
            "description": "Read one file summary or rollup markdown.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "e.g. src/auth/session.py or rollups/src.md"},
                },
                "required": ["target"],
            },
        },
        {
            "name": "summary_rollup",
            "description": "Print a directory rollup by name.",
            "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
        {
            "name": "summary_list",
            "description": "List available summary .md files under repo/ (optional subdir).",
            "inputSchema": {
                "type": "object",
                "properties": {"dir": {"type": "string"}},
            },
        },
        {
            "name": "summary_hotspots",
            "description": "Heuristic risk scan over summaries (scaling, security, maintenance).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["all", "scaling", "security", "maintenance"],
                        "default": "all",
                    },
                },
            },
        },
        {
            "name": "summary_semantic",
            "description": "Embeddings semantic search over the summary corpus (requires embeddings_index.py build).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "dir": {"type": "string"},
                    "max": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
        },
        {
            "name": "broker_search",
            "description": "Symbol/source search via the classic broker (use after summary tools).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max": {"type": "integer", "default": 40},
                },
                "required": ["query"],
            },
        },
        {
            "name": "broker_outline",
            "description": "Symbol outline for a source file (tree-sitter when available, else regex).",
            "inputSchema": {
                "type": "object",
                "properties": {"file": {"type": "string"}},
                "required": ["file"],
            },
        },
        {
            "name": "broker_read",
            "description": "Read a symbol body or line range from source (not full-file dump).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "symbol": {"type": "string"},
                    "lines": {"type": "string", "description": "A-B inclusive line range"},
                },
                "required": ["file"],
            },
        },
        {
            "name": "broker_summary",
            "description": "LLM summary if present, else cached/regex summary for a file.",
            "inputSchema": {
                "type": "object",
                "properties": {"file": {"type": "string"}},
                "required": ["file"],
            },
        },
        {
            "name": "broker_context_list",
            "description": "List hand-curated repo_context orientation files.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "context_status",
            "description": "Layer 2: show pinned/working/cold context board and task.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "context_place",
            "description": "Layer 2: place a path in pinned, working, or cold tier.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "tier": {"type": "string", "enum": ["pinned", "working", "cold"]},
                    "note": {"type": "string"},
                },
                "required": ["path", "tier"],
            },
        },
        {
            "name": "context_pack",
            "description": "Layer 2: emit a budgeted context pack (pinned full, working summaries, cold stubs).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "budget": {"type": "integer", "default": 24000},
                    "source": {"type": "boolean", "default": False},
                },
            },
        },
        {
            "name": "context_task",
            "description": "Layer 2: set the current task label on the context board.",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
        {
            "name": "minify_diff",
            "description": "Layer 3: minify a unified diff string for cheap agent intake.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "max_hunk": {"type": "integer", "default": 80},
                    "max_total": {"type": "integer", "default": 800},
                },
                "required": ["text"],
            },
        },
        {
            "name": "minify_log",
            "description": "Layer 3: minify a log dump (collapse repeats, drop DEBUG noise, cap lines).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "max_lines": {"type": "integer", "default": 400},
                    "keep_debug": {"type": "boolean", "default": False},
                },
                "required": ["text"],
            },
        },
    ]


def _text_result(text: str, is_error: bool = False) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    args = arguments or {}
    try:
        if name == "summary_search":
            root = summary_search.find_summaries_root(REPO_ROOT)
            results = summary_search.search_summaries(
                query=args["query"],
                summaries_root=root,
                dir_filter=args.get("dir"),
                max_results=int(args.get("max") or 40),
            )
            return _text_result(summary_search.render_search_results(results))

        if name == "summary_grep":
            root = summary_search.find_summaries_root(REPO_ROOT)
            results = summary_search.grep_summaries(
                pattern=args["pattern"],
                summaries_root=root,
                dir_filter=args.get("dir"),
                max_results=int(args.get("max") or 60),
            )
            return _text_result(summary_search.render_grep_results(results))

        if name == "summary_read":
            root = summary_search.find_summaries_root(REPO_ROOT)
            if not root:
                return _text_result("(could not locate summaries/)", True)
            target = args["target"]
            target_md = target if target.endswith(".md") else target + ".md"
            candidates = [
                os.path.join(root, "repo", target_md),
                os.path.join(root, "repo", target),
                os.path.join(root, target_md),
                os.path.join(root, "rollups", target_md.replace("rollups/", "")),
            ]
            for cand in candidates:
                if os.path.isfile(cand):
                    with open(cand, encoding="utf-8", errors="ignore") as f:
                        body = f.read()
                    return _text_result(body + f"\n\n(source: {cand})")
            return _text_result(f"(summary not found for: {target})", True)

        if name == "summary_rollup":
            root = summary_search.find_summaries_root(REPO_ROOT)
            if not root:
                return _text_result("(could not locate summaries/)", True)
            rollups_dir = os.path.join(root, "rollups")
            n = args["name"]
            if not n.endswith(".md"):
                n += ".md"
            path = os.path.join(rollups_dir, n)
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="ignore") as f:
                    return _text_result(f.read())
            available = []
            if os.path.isdir(rollups_dir):
                available = [f for f in os.listdir(rollups_dir) if f.endswith(".md")]
            return _text_result(
                f"(rollup not found: {n})\nAvailable: {', '.join(sorted(available)) or '(none)'}",
                True,
            )

        if name == "summary_list":
            root = summary_search.find_summaries_root(REPO_ROOT)
            if not root:
                return _text_result("(could not locate summaries/)", True)
            target_dir = args.get("dir") or ""
            base = os.path.join(root, "repo", target_dir)
            if not os.path.isdir(base):
                base = os.path.join(root, target_dir)
            if not os.path.isdir(base):
                return _text_result(f"(directory not found: {target_dir or 'repo/'})", True)
            lines = []
            for dirpath, _, filenames in os.walk(base):
                for fn in sorted(filenames):
                    if fn.endswith(".md"):
                        lines.append(os.path.relpath(os.path.join(dirpath, fn), root))
            return _text_result("\n".join(lines) or "(none)")

        if name == "summary_hotspots":
            root = summary_search.find_summaries_root(REPO_ROOT)
            category = (args.get("category") or "all").lower()
            patterns = {
                "scaling": r"full scan|key scan|scales with|performance scales|in memory|large result|O\(n|slow at scale|N\+1|pagination",
                "security": r"PII|encryption|secret|password|token|key rotation|scrub|authz|authorization",
                "maintenance": r"reindex|migration|schema version|backfill|deprecat",
                "all": r"full scan|scales with|large result|key scan|migration|N\+1|PII|secret",
            }
            pat = patterns.get(category, patterns["all"])
            results = summary_search.grep_summaries(pattern=pat, summaries_root=root, max_results=80)
            body = f"=== Hotspots for category: {category} ===\n\n"
            body += summary_search.render_grep_results(results)
            return _text_result(body)

        if name == "summary_semantic":
            root = summary_search.find_summaries_root(REPO_ROOT)
            results = embeddings_search.search_semantic(
                query=args["query"],
                summaries_root=root,
                max_results=int(args.get("max") or 20),
                dir_filter=args.get("dir"),
            )
            return _text_result(embeddings_search.render_semantic_results(results))

        if name == "broker_search":
            results = search.search(REPO_ROOT, args["query"], max_results=int(args.get("max") or 40))
            return _text_result(search.render(results))

        if name == "broker_outline":
            text = _read_source(args["file"])
            lang = languages.detect(args["file"])
            if not lang:
                return _text_result(f"(no outline support for: {args['file']})")
            symbols = outline.extract(text, lang)
            header = f"FILE: {args['file']}  lang={lang}  backend={outline.backend_name()}  symbols={len(symbols)}"
            return _text_result(header + "\n" + outline.render(symbols))

        if name == "broker_read":
            text = _read_source(args["file"])
            lang = languages.detect(args["file"])
            if args.get("symbol"):
                sliced = outline.slice_symbol(text, lang, args["symbol"]) if lang else None
                if sliced is None:
                    return _text_result(f"(symbol not found: {args['symbol']})", True)
                return _text_result(sliced)
            if args.get("lines"):
                a, b = args["lines"].split("-")
                a, b = int(a), int(b)
                lines = text.splitlines()[a - 1:b]
                return _text_result("\n".join(f"{i}: {line}" for i, line in enumerate(lines, start=a)))
            # default outline
            symbols = outline.extract(text, lang) if lang else []
            body = outline.render(symbols) if lang else "(no lang)"
            body += "\n\n(use symbol or lines to read code; full-file read not provided)"
            return _text_result(body)

        if name == "broker_summary":
            fpath = args["file"]
            llm_path = os.path.join(LLM_SUMMARIES_DIR, fpath + ".md")
            if os.path.exists(llm_path):
                with open(llm_path, encoding="utf-8", errors="ignore") as f:
                    return _text_result(f.read() + f"\n\n(source: LLM summary)")
            text = _read_source(fpath)
            h = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
            cache = os.path.join(REPO_DIR, "summaries", f"{h}.txt")
            if os.path.exists(cache):
                with open(cache, encoding="utf-8", errors="ignore") as f:
                    return _text_result(f.read() + "\n\n(source: regex summary cache)")
            return _text_result(summarize.summarize_file(text, fpath) + "\n\n(source: live regex summary)")

        if name == "broker_context_list":
            if not os.path.isdir(REPO_CONTEXT_DIR):
                return _text_result("(no repo_context/)")
            files = sorted(fn for fn in os.listdir(REPO_CONTEXT_DIR) if fn.endswith(".md"))
            return _text_result("\n".join(files) or "(none)")

        if name == "context_status":
            return _text_result(context_tiers.status_text())

        if name == "context_place":
            context_tiers.place(
                args["path"],
                args["tier"],
                note=args.get("note") or "",
            )
            return _text_result(context_tiers.status_text())

        if name == "context_task":
            context_tiers.set_task(args["text"])
            return _text_result(context_tiers.status_text())

        if name == "context_pack":
            body = context_tiers.pack(
                budget_chars=int(args.get("budget") or context_tiers.DEFAULT_BUDGET_CHARS),
                include_source_for_working=bool(args.get("source")),
            )
            return _text_result(body)

        if name == "minify_diff":
            text, stats = mz.minify_diff(
                args["text"],
                max_hunk_lines=int(args.get("max_hunk") or 80),
                max_total_lines=int(args.get("max_total") or 800),
            )
            return _text_result(text + "\n" + mz.format_stats("diff", stats))

        if name == "minify_log":
            drop = set() if args.get("keep_debug") else None
            text, stats = mz.minify_log(
                args["text"],
                max_lines=int(args.get("max_lines") or 400),
                drop_levels=drop,
            )
            return _text_result(text + "\n" + mz.format_stats("log", stats))

        return _text_result(f"unknown tool: {name}", True)
    except Exception as e:
        return _text_result(f"{type(e).__name__}: {e}\n{traceback.format_exc()}", True)


def _handle(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    # notifications have no id
    if method == "notifications/initialized":
        return None
    if method == "notifications/cancelled":
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": _tool_defs()},
        }

    if method == "tools/call":
        name = params.get("name") or ""
        arguments = params.get("arguments") or {}
        result = _call_tool(name, arguments)
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"resources": []}}

    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"prompts": []}}

    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    # Ensure cwd-based discovery works when host sets cwd to repo root
    os.chdir(os.environ.get("AI_SUMMARIZER_REPO_ROOT") or REPO_ROOT)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            err = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"parse error: {e}"},
            }
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
            continue
        # Support Content-Length framed batches later; line-delimited is fine for many hosts.
        # Some hosts send a single JSON object per line; others may send arrays — handle both.
        messages = msg if isinstance(msg, list) else [msg]
        for m in messages:
            if not isinstance(m, dict):
                continue
            resp = _handle(m)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
