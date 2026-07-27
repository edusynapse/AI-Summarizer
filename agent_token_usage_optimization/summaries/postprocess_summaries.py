#!/usr/bin/env python3
"""Batch postprocess existing summaries: resolve NAVIGATION lines + inject ADJACENT.

  python3 postprocess_summaries.py
  python3 postprocess_summaries.py --only libadmin/app_settings_page.dart
  python3 postprocess_summaries.py --no-adjacent

No LLM. Uses outline (tree-sitter if installed) + this repo's adjacency.sqlite.
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, SKILL)

from pathlib import Path  # noqa: E402
from lib import summary_postprocess, workspace_config  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Postprocess summary markdown (lines + ADJACENT)")
    ap.add_argument("--only", help="single relative source path")
    ap.add_argument("--no-adjacent", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    skill = Path(SKILL)
    ws = workspace_config.load_workspace(skill)
    repo_root = Path(ws["repo_root"])
    sum_repo = skill / "summaries" / "repo"
    if not sum_repo.is_dir():
        print(f"no summaries/repo at {sum_repo}")
        sys.exit(1)

    if args.only:
        rel = args.only.replace("\\", "/").lstrip("./")
        md = sum_repo / (rel + ".md")
        src = repo_root / rel
        st = summary_postprocess.postprocess_summary_file(
            md, src, rel, skill, inject_adjacent=not args.no_adjacent,
        )
        print(st)
        return

    n = 0
    ok = 0
    resolved = 0
    for md in sorted(sum_repo.rglob("*.md")):
        rel_md = md.relative_to(sum_repo).as_posix()
        if not rel_md.endswith(".md"):
            continue
        rel = rel_md[:-3]  # strip .md
        src = repo_root / rel
        if not src.is_file():
            continue
        st = summary_postprocess.postprocess_summary_file(
            md, src, rel, skill, inject_adjacent=not args.no_adjacent,
        )
        n += 1
        if st.get("ok"):
            ok += 1
            resolved += st.get("resolved", 0)
        if args.limit and n >= args.limit:
            break
        if n % 100 == 0:
            print(f"  … {n} files", flush=True)

    print(f"postprocess done: files={n} ok={ok} nav_lines_resolved≈{resolved}")
    print(f"outline backend: tree-sitter if installed; adjacency: {skill / 'repo' / 'adjacency.sqlite'}")


if __name__ == "__main__":
    main()
