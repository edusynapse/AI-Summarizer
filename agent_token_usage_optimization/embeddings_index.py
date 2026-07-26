#!/usr/bin/env python3
"""Build / search embeddings over the LLM summary corpus.

  python3 embeddings_index.py build [--force]
  python3 embeddings_index.py search "auth session middleware" [--max 20] [--dir src]
  python3 embeddings_index.py status

Config: skills/.../summaries/embeddings_config.json
Docs: docs/embeddings_semantic_search.md (repo root of AI-Summarizer)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib import embeddings_search, summary_search  # noqa: E402


def cmd_build(args):
    stats = embeddings_search.build_index(force=args.force)
    print(json.dumps(stats, indent=2))


def cmd_search(args):
    results = embeddings_search.search_semantic(
        query=args.query,
        max_results=args.max,
        dir_filter=args.dir,
    )
    print(embeddings_search.render_semantic_results(results))


def cmd_status(args):
    root = summary_search.find_summaries_root()
    cfg = embeddings_search.load_config(root)
    print(f"summaries_root: {root or '(not found)'}")
    print(f"config backend: {cfg.get('backend')} model={cfg.get('model')} dim={cfg.get('dim')}")
    if not root:
        return
    edir = embeddings_search.embeddings_dir(root)
    meta = edir / "index.json" if edir else None
    if meta and meta.is_file():
        data = json.loads(meta.read_text(encoding="utf-8"))
        print(f"index: {meta}")
        print(f"  docs={data.get('count')} backend={data.get('backend')} dim={data.get('dim')}")
    else:
        print("index: (missing — run: embeddings_index.py build)")


def main():
    p = argparse.ArgumentParser(prog="embeddings_index", description="Semantic index over summaries/")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Build or refresh embeddings index")
    b.add_argument("--force", action="store_true", help="Re-embed everything")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("search", help="Semantic search over the index")
    s.add_argument("query")
    s.add_argument("--max", type=int, default=20)
    s.add_argument("--dir", help="optional path filter")
    s.set_defaults(func=cmd_search)

    st = sub.add_parser("status", help="Show config + index stats")
    st.set_defaults(func=cmd_status)

    args = p.parse_args()
    try:
        args.func(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
