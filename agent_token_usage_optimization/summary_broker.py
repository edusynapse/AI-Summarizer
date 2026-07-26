#!/usr/bin/env python3
"""
Summary Broker — summary-layer-first retrieval for AI coding agents.

This is the companion / alternate to broker.py focused on the LLM-generated
summaries, rollups, and repo_context. Use this first (per AGENTS.md / CLAUDE.md)
before falling back to broker.py for symbol-level source inspection.

Usage examples:
  python3 skills/.../summary_broker.py search "auth OR session" --dir src
  python3 .../summary_broker.py grep "rate.?limit|cache invalidat"
  python3 .../summary_broker.py rollup src
  python3 .../summary_broker.py read src/auth/session.py
  python3 .../summary_broker.py hotspots scaling
  # Project ref (KTW-style): search "reindexAll OR 'full scan'" --dir models
"""

import argparse
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib import summary_search, embeddings_search


def find_repo_root() -> str:
    """Best-effort repo root (directory containing the skill or .git)."""
    p = Path(HERE).resolve()
    for _ in range(8):
        if (p / ".git").exists() or (p / "skills").exists():
            return str(p)
        if p.parent == p:
            break
        p = p.parent
    return str(Path(HERE).resolve().parents[2])  # rough fallback


def cmd_search(args):
    root = summary_search.find_summaries_root()
    if not root:
        print("(could not locate summaries/ directory)")
        return

    results = summary_search.search_summaries(
        query=args.query,
        summaries_root=root,
        dir_filter=args.dir,
        max_results=args.max,
    )
    print(summary_search.render_search_results(results))


def cmd_grep(args):
    root = summary_search.find_summaries_root()
    if not root:
        print("(could not locate summaries/ directory)")
        return

    results = summary_search.grep_summaries(
        pattern=args.pattern,
        summaries_root=root,
        dir_filter=args.dir,
        max_results=args.max,
    )
    print(summary_search.render_grep_results(results))


def cmd_read(args):
    root = summary_search.find_summaries_root()
    if not root:
        print("(could not locate summaries/ directory)")
        return

    target = args.target
    # Accept both "models/foo.js" and "models/foo.js.md"
    if not target.endswith(".md"):
        target_md = target + ".md"
    else:
        target_md = target

    candidates = [
        os.path.join(root, "repo", target_md),
        os.path.join(root, "repo", target),           # already has .md
        os.path.join(root, target_md),
        os.path.join(root, "rollups", target_md.replace("rollups/", "")),
    ]

    for cand in candidates:
        if os.path.isfile(cand):
            with open(cand, encoding="utf-8", errors="ignore") as f:
                print(f.read())
            print(f"\n(source: {cand})")
            return

    print(f"(summary not found for: {target})")
    print(f"Looked under: {root}/repo/ and {root}/rollups/")


def cmd_rollup(args):
    root = summary_search.find_summaries_root()
    if not root:
        print("(could not locate summaries/ directory)")
        return

    rollups_dir = os.path.join(root, "rollups")
    if not os.path.isdir(rollups_dir):
        print("(no rollups/ directory yet — run rollup_summarizer.py)")
        return

    name = args.name
    if not name.endswith(".md"):
        name += ".md"

    path = os.path.join(rollups_dir, name)
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="ignore") as f:
            print(f.read())
        return

    # List available rollups
    available = [f for f in os.listdir(rollups_dir) if f.endswith(".md")]
    print(f"(rollup not found: {name})")
    print("Available rollups:", ", ".join(sorted(available)) or "(none)")


def cmd_list(args):
    root = summary_search.find_summaries_root()
    if not root:
        print("(could not locate summaries/ directory)")
        return

    target_dir = args.dir or ""
    base = os.path.join(root, "repo", target_dir)

    if not os.path.isdir(base):
        base = os.path.join(root, target_dir)

    if not os.path.isdir(base):
        print(f"(directory not found under summaries: {target_dir or 'repo/'})")
        return

    for dirpath, _, filenames in os.walk(base):
        for fn in sorted(filenames):
            if fn.endswith(".md"):
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                print(rel)


def cmd_semantic(args):
    """Embeddings-backed semantic search over the summary corpus."""
    root = summary_search.find_summaries_root()
    results = embeddings_search.search_semantic(
        query=args.query,
        summaries_root=root,
        max_results=args.max,
        dir_filter=args.dir,
    )
    print(embeddings_search.render_semantic_results(results))


def cmd_hotspots(args):
    """Heuristic scan for common scaling / maintenance / risk patterns."""
    root = summary_search.find_summaries_root()
    if not root:
        print("(could not locate summaries/ directory)")
        return

    category = (args.category or "all").lower()

    # Generic risk patterns. Project-specific tokens (KTW ref: reindexAll,
    # SMEMBERS, patchToLatest, model_version, DEK/admin key) can be re-added
    # here or layered via summary_broker.py grep with a custom regex.
    patterns = {
        "scaling": r"full scan|key scan|scales with|performance scales|in memory|large result|O\(n|slow at scale|N\+1|pagination",
        "security": r"PII|encryption|secret|password|token|key rotation|scrub|authz|authorization",
        "maintenance": r"reindex|migration|schema version|backfill|deprecat",
        "all": r"full scan|scales with|large result|key scan|migration|N\+1|PII|secret",
        # Project ref (uncomment / merge when useful):
        # "scaling": r"...|reindexAll|SMEMBERS|...",
        # "security": r"...|DEK|admin key|...",
        # "maintenance": r"...|patchToLatest|model_version|...",
    }

    pat = patterns.get(category, patterns["all"])

    results = summary_search.grep_summaries(
        pattern=pat,
        summaries_root=root,
        max_results=80,
    )
    print(f"=== Hotspots for category: {category} ===\n")
    print(summary_search.render_grep_results(results))


def main():
    p = argparse.ArgumentParser(
        prog="summary_broker",
        description="Summary-layer-first retrieval (use before touching source code)."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # search (the primary new command)
    s = sub.add_parser("search", help="Search LLM summaries + rollups (keyword)")
    s.add_argument("query")
    s.add_argument("--dir", help="scope to a subdirectory under summaries/repo/ (e.g. models, lib)")
    s.add_argument("--max", type=int, default=40)
    s.set_defaults(func=cmd_search)

    # grep (regex)
    g = sub.add_parser("grep", help="Regex search across all summaries")
    g.add_argument("pattern")
    g.add_argument("--dir")
    g.add_argument("--max", type=int, default=60)
    g.set_defaults(func=cmd_grep)

    # read a specific summary file
    r = sub.add_parser("read", help="Print a specific file summary or rollup")
    r.add_argument("target", help="e.g. src/auth/session.py  or  rollups/src.md")
    r.set_defaults(func=cmd_read)

    # rollup convenience
    ru = sub.add_parser("rollup", help="Print a directory rollup")
    ru.add_argument("name", help="e.g. models or lib")
    ru.set_defaults(func=cmd_rollup)

    # list summaries
    ls = sub.add_parser("list", help="List available summary files")
    ls.add_argument("dir", nargs="?", help="optional subdirectory filter")
    ls.set_defaults(func=cmd_list)

    # hotspots (very useful for the exact use case that motivated this tool)
    hs = sub.add_parser("hotspots", help="Heuristic search for risk patterns (scaling, maintenance, etc.)")
    hs.add_argument("category", nargs="?", default="all",
                    choices=["all", "scaling", "security", "maintenance"])
    hs.add_argument("--max", type=int, default=50)
    hs.set_defaults(func=cmd_hotspots)

    # semantic (embeddings index — build with embeddings_index.py)
    sem = sub.add_parser("semantic", help="Embeddings semantic search over summaries (see embeddings_index.py)")
    sem.add_argument("query")
    sem.add_argument("--dir", help="optional subdirectory filter")
    sem.add_argument("--max", type=int, default=20)
    sem.set_defaults(func=cmd_semantic)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
