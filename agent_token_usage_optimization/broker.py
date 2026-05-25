#!/usr/bin/env python3
"""Context Broker — single CLI entry point for agent retrieval.

Usage:
  broker.py index
  broker.py search <query> [--max N]
  broker.py outline <file>
  broker.py read <file> [--symbol NAME] [--lines A-B]
  broker.py diff [REV]
  broker.py summary [<file>]    # prefers LLM summary, falls back to regex
  broker.py context [<file>] [--list]   # hand-curated repo orientation

All output is plain text. Designed to be called by any coding agent.
"""
import os
import sys
import argparse
import subprocess
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import outline, search, summarize, languages  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REPO_DIR = os.path.join(HERE, "repo")
LLM_SUMMARIES_DIR = os.path.join(HERE, "summaries", "repo")
REPO_CONTEXT_DIR = os.path.join(HERE, "summaries", "repo_context")

def _read(path):
    full = path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)
    with open(full, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def cmd_index(args):
    from indexer import build
    build()

def cmd_search(args):
    results = search.search(REPO_ROOT, args.query, max_results=args.max)
    print(search.render(results))

def cmd_outline(args):
    text = _read(args.file)
    lang = languages.detect(args.file)
    if not lang:
        print(f"(no outline support for: {args.file})")
        return
    symbols = outline.extract(text, lang)
    print(f"FILE: {args.file}  lang={lang}  symbols={len(symbols)}")
    print(outline.render(symbols))

def cmd_read(args):
    text = _read(args.file)
    lang = languages.detect(args.file)
    if args.symbol:
        sliced = outline.slice_symbol(text, lang, args.symbol) if lang else None
        if sliced is None:
            print(f"(symbol not found: {args.symbol})")
            return
        print(sliced)
        return
    if args.lines:
        try:
            a, b = args.lines.split("-")
            a, b = int(a), int(b)
        except ValueError:
            print("--lines expects A-B"); return
        lines = text.splitlines()[a - 1:b]
        for i, line in enumerate(lines, start=a):
            print(f"{i}: {line}")
        return
    # default: print outline only, refuse full read to discourage waste
    cmd_outline(args)
    print("\n(use --symbol NAME or --lines A-B to read code; full-file read intentionally not provided)")

def cmd_diff(args):
    rev = args.rev or "HEAD"
    try:
        out = subprocess.run(
            ["git", "diff", f"--unified={args.context}", rev],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception as e:
        print(f"git diff failed: {e}"); return
    # strip the noisy `index abc..def` and `diff --git` repetition; keep file headers + hunks
    out_lines = []
    for line in out.splitlines():
        if line.startswith("index ") or line.startswith("diff --git "):
            continue
        out_lines.append(line)
    print("\n".join(out_lines))

def cmd_summary(args):
    if args.file:
        # 1. LLM summary (preferred — semantic, written by gemini)
        llm_path = os.path.join(LLM_SUMMARIES_DIR, args.file + ".md")
        if os.path.exists(llm_path):
            with open(llm_path) as f:
                print(f.read())
            print(f"\n(source: LLM summary @ summaries/repo/{args.file}.md)")
            return
        # 2. hash-cached regex summary (from indexer)
        text = _read(args.file)
        h = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        cache = os.path.join(REPO_DIR, "summaries", f"{h}.txt")
        if os.path.exists(cache):
            with open(cache) as f:
                print(f.read())
            print("\n(source: regex summary cache — run summarizer.py for a better LLM summary)")
            return
        # 3. live regex summary fallback
        print(summarize.summarize_file(text, args.file))
        print("\n(source: live regex summary — run summarizer.py for a better LLM summary)")
        return
    path = os.path.join(REPO_DIR, "SUMMARY.md")
    if not os.path.exists(path):
        print("(no SUMMARY.md yet — run: broker.py index)")
        return
    with open(path) as f:
        print(f.read())

def cmd_context(args):
    if not os.path.isdir(REPO_CONTEXT_DIR):
        print("(no repo_context/ — see summaries/repo_context/README.md)")
        return
    files = sorted(f for f in os.listdir(REPO_CONTEXT_DIR)
                   if f.endswith(".md") and f.lower() != "readme.md")
    if args.file:
        target = os.path.join(REPO_CONTEXT_DIR, args.file)
        if not os.path.exists(target):
            print(f"(not found: {args.file}); available: {', '.join(files) or '(none)'}")
            return
        with open(target) as f:
            print(f.read())
        return
    if args.list:
        if not files:
            print("(repo_context is empty — populate per summaries/repo_context/README.md)")
        for fn in files:
            print(fn)
        return
    # default: concatenate all curated context files
    if not files:
        print("(repo_context is empty — populate per summaries/repo_context/README.md)")
        return
    for fn in files:
        with open(os.path.join(REPO_CONTEXT_DIR, fn)) as f:
            print(f"\n=== {fn} ===\n")
            print(f.read())

def main():
    p = argparse.ArgumentParser(prog="broker", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("index").set_defaults(func=cmd_index)

    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--max", type=int, default=30)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("outline"); s.add_argument("file")
    s.set_defaults(func=cmd_outline)

    s = sub.add_parser("read"); s.add_argument("file")
    s.add_argument("--symbol"); s.add_argument("--lines")
    s.set_defaults(func=cmd_read)

    s = sub.add_parser("diff"); s.add_argument("rev", nargs="?")
    s.add_argument("--context", type=int, default=2)
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser("summary"); s.add_argument("file", nargs="?")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("context", help="dump hand-curated repo_context files")
    s.add_argument("file", nargs="?", help="specific file in repo_context/")
    s.add_argument("--list", action="store_true", help="list available context files")
    s.set_defaults(func=cmd_context)

    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
