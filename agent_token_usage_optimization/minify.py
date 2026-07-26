#!/usr/bin/env python3
"""Layer 3 — minify logs and diffs for cheap agent context.

  python3 minify.py diff [file|-] [--max-hunk 80] [--max-total 800]
  python3 minify.py log  [file|-] [--max-lines 400] [--keep-debug]
  git diff | python3 minify.py diff -
  tail -n 2000 app.log | python3 minify.py log -
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib import minify as mz  # noqa: E402


def _read_input(path: str) -> str:
    if path == "-" or path is None:
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def cmd_diff(args):
    text = _read_input(args.path)
    out, stats = mz.minify_diff(
        text,
        max_hunk_lines=args.max_hunk,
        max_file_lines=args.max_file,
        max_total_lines=args.max_total,
        collapse_context=not args.full_context,
    )
    sys.stdout.write(out)
    if not args.quiet:
        print(mz.format_stats("diff", stats), file=sys.stderr)


def cmd_log(args):
    text = _read_input(args.path)
    drop = set() if args.keep_debug else None
    out, stats = mz.minify_log(
        text,
        max_lines=args.max_lines,
        max_line_chars=args.max_line_chars,
        collapse_repeats=not args.no_collapse,
        strip_timestamps=not args.keep_timestamps,
        drop_levels=drop,
        drop_noise=not args.keep_noise,
        keep_tail=not args.head,
    )
    sys.stdout.write(out)
    if not args.quiet:
        print(mz.format_stats("log", stats), file=sys.stderr)


def main():
    p = argparse.ArgumentParser(prog="minify", description="Log/diff minifier (Layer 3)")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diff", help="Minify a unified diff")
    d.add_argument("path", nargs="?", default="-", help="file or - for stdin")
    d.add_argument("--max-hunk", type=int, default=80)
    d.add_argument("--max-file", type=int, default=200)
    d.add_argument("--max-total", type=int, default=800)
    d.add_argument("--full-context", action="store_true", help="do not thin context lines")
    d.add_argument("-q", "--quiet", action="store_true", help="no stats on stderr")
    d.set_defaults(func=cmd_diff)

    lg = sub.add_parser("log", help="Minify a log dump")
    lg.add_argument("path", nargs="?", default="-", help="file or - for stdin")
    lg.add_argument("--max-lines", type=int, default=400)
    lg.add_argument("--max-line-chars", type=int, default=240)
    lg.add_argument("--keep-debug", action="store_true", help="keep DEBUG/TRACE lines")
    lg.add_argument("--keep-timestamps", action="store_true")
    lg.add_argument("--keep-noise", action="store_true", help="keep healthcheck-like lines")
    lg.add_argument("--no-collapse", action="store_true")
    lg.add_argument("--head", action="store_true", help="keep head instead of tail when truncating")
    lg.add_argument("-q", "--quiet", action="store_true")
    lg.set_defaults(func=cmd_log)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
