#!/usr/bin/env python3
"""
Summary Broker — summary-layer-first retrieval for AI coding agents.

Each repo keeps SEPARATE stores (summaries, index.sqlite, adjacency.sqlite).
Use --repo <sibling_id> to read a sibling's stores (from workspace.env).
Never merges DBs.

Usage:
  python3 summary_broker.py search "auth" --dir lib
  python3 summary_broker.py adjacent lib/foo.dart
  python3 summary_broker.py --repo api adjacent routes/foo.js
  python3 summary_broker.py workspace
"""

import argparse
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib import summary_search, embeddings_search, adjacency, workspace_config  # noqa: E402


def _skill_and_ws(repo_id=None):
    return workspace_config.resolve_skill_for_repo_flag(Path(HERE), repo_id)


def _summaries_root(skill: Path) -> str:
    return str(skill / "summaries")


def cmd_search(args):
    skill, _ws = _skill_and_ws(args.repo)
    root = _summaries_root(skill)
    if not os.path.isdir(root):
        print(f"(no summaries at {root})")
        return
    results = summary_search.search_summaries(
        query=args.query,
        summaries_root=root,
        dir_filter=args.dir,
        max_results=args.max,
    )
    print(summary_search.render_search_results(results))


def cmd_grep(args):
    skill, _ws = _skill_and_ws(args.repo)
    root = _summaries_root(skill)
    results = summary_search.grep_summaries(
        pattern=args.pattern,
        summaries_root=root,
        dir_filter=args.dir,
        max_results=args.max,
    )
    print(summary_search.render_grep_results(results))


def cmd_read(args):
    skill, _ws = _skill_and_ws(args.repo)
    root = _summaries_root(skill)
    target = args.target
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
                print(f.read())
            print(f"\n(source: {cand})")
            return
    print(f"(summary not found for: {target})")
    print(f"Looked under: {root}/repo/ and {root}/rollups/")


def cmd_rollup(args):
    skill, _ws = _skill_and_ws(args.repo)
    root = _summaries_root(skill)
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
    available = [f for f in os.listdir(rollups_dir) if f.endswith(".md")]
    print(f"(rollup not found: {name})")
    print("Available rollups:", ", ".join(sorted(available)) or "(none)")


def cmd_list(args):
    skill, _ws = _skill_and_ws(args.repo)
    root = _summaries_root(skill)
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


def cmd_hotspots(args):
    skill, _ws = _skill_and_ws(args.repo)
    root = _summaries_root(skill)
    category = (args.category or "all").lower()
    patterns = {
        "scaling": r"full scan|key scan|scales with|performance scales|in memory|large result|O\(n|slow at scale|N\+1|pagination",
        "security": r"PII|encryption|secret|password|token|key rotation|scrub|authz|authorization",
        "maintenance": r"reindex|migration|schema version|backfill|deprecat",
        "all": r"full scan|scales with|large result|key scan|migration|N\+1|PII|secret",
    }
    pat = patterns.get(category, patterns["all"])
    results = summary_search.grep_summaries(
        pattern=pat, summaries_root=root, max_results=80,
    )
    print(f"=== Hotspots for category: {category} ===\n")
    print(summary_search.render_grep_results(results))


def cmd_semantic(args):
    skill, _ws = _skill_and_ws(args.repo)
    root = _summaries_root(skill)
    results = embeddings_search.search_semantic(
        query=args.query,
        summaries_root=root,
        max_results=args.max,
        dir_filter=args.dir,
    )
    print(embeddings_search.render_semantic_results(results))


def cmd_adjacent(args):
    """In-repo adjacency for the selected skill root (current or --repo)."""
    skill, ws = _skill_and_ws(args.repo)
    data = adjacency.query_adjacent(skill, args.path, max_results=args.max)
    label = args.repo or ws.get("repo_id") or "local"
    print(f"(adjacency DB: {skill / 'repo' / 'adjacency.sqlite'}  repo={label})")
    print(adjacency.render_adjacent(data))


def cmd_cross(args):
    """HTTP path-literal join: this file → sibling path_hits (separate DBs)."""
    # always extract from CURRENT skill; match against siblings from CURRENT workspace.env
    local_skill, ws = _skill_and_ws(None)
    siblings = ws.get("siblings") or {}
    if args.sibling:
        if args.sibling not in siblings:
            print(
                f"error: unknown sibling {args.sibling!r}; known {list(siblings.keys())}",
                file=sys.stderr,
            )
            sys.exit(1)
        siblings = {args.sibling: siblings[args.sibling]}
    if not siblings:
        print(
            "error: no WORKSPACE_SIBLINGS in workspace.env — "
            "configure_workspace.sh --sibling id=/path",
            file=sys.stderr,
        )
        sys.exit(1)
    data = adjacency.cross_repo_for_file(
        local_skill, args.path, siblings, max_per_path=args.max,
    )
    print(adjacency.render_cross(data))


def cmd_workspace(args):
    skill, ws = _skill_and_ws(None)
    print(workspace_config.format_workspace_status(ws))
    print()
    print("Each sibling must have its OWN summaries + index.sqlite + adjacency.sqlite.")
    print("Use: summary_broker.py --repo <id> search|adjacent|read …")
    print("     summary_broker.py cross <client_file>   # path-literal join to siblings")


def main():
    p = argparse.ArgumentParser(
        prog="summary_broker",
        description="Summary-layer-first retrieval. Separate stores per repo; --repo selects sibling.",
    )
    p.add_argument(
        "--repo",
        default=None,
        help="sibling id from workspace.env WORKSPACE_SIBLINGS (read that repo's stores only)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="Search LLM summaries + rollups (keyword)")
    s.add_argument("query")
    s.add_argument("--dir")
    s.add_argument("--max", type=int, default=40)
    s.set_defaults(func=cmd_search)

    g = sub.add_parser("grep", help="Regex search across summaries")
    g.add_argument("pattern")
    g.add_argument("--dir")
    g.add_argument("--max", type=int, default=60)
    g.set_defaults(func=cmd_grep)

    r = sub.add_parser("read", help="Print a file summary or rollup")
    r.add_argument("target")
    r.set_defaults(func=cmd_read)

    ru = sub.add_parser("rollup", help="Print a directory rollup")
    ru.add_argument("name")
    ru.set_defaults(func=cmd_rollup)

    ls = sub.add_parser("list", help="List summary files")
    ls.add_argument("dir", nargs="?")
    ls.set_defaults(func=cmd_list)

    hs = sub.add_parser("hotspots", help="Heuristic risk patterns")
    hs.add_argument("category", nargs="?", default="all",
                    choices=["all", "scaling", "security", "maintenance"])
    hs.add_argument("--max", type=int, default=50)
    hs.set_defaults(func=cmd_hotspots)

    sem = sub.add_parser("semantic", help="Embeddings search")
    sem.add_argument("query")
    sem.add_argument("--dir")
    sem.add_argument("--max", type=int, default=20)
    sem.set_defaults(func=cmd_semantic)

    adj = sub.add_parser(
        "adjacent",
        help="Import adjacency for a path (this repo's adjacency.sqlite, or --repo sibling's)",
    )
    adj.add_argument("path", help="repo-relative source path")
    adj.add_argument("--max", type=int, default=40)
    adj.set_defaults(func=cmd_adjacent)

    cr = sub.add_parser(
        "cross",
        help="HTTP path join: extract paths from THIS file, match sibling adjacency path_hits",
    )
    cr.add_argument("path", help="client file in the CURRENT repo")
    cr.add_argument("--sibling", help="only this sibling id (default: all WORKSPACE_SIBLINGS)")
    cr.add_argument("--max", type=int, default=15, help="max server files per path")
    cr.set_defaults(func=cmd_cross)

    ws = sub.add_parser("workspace", help="Show workspace.env / siblings status")
    ws.set_defaults(func=cmd_workspace)

    args = p.parse_args()
    try:
        args.func(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
