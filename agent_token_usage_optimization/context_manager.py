#!/usr/bin/env python3
"""Layer 2 — tiered context manager CLI (pinned / working / cold).

Usage (from target repo root):
  python3 skills/agent_token_usage_optimization/context_manager.py status
  python3 …/context_manager.py task "fix session expiry race"
  python3 …/context_manager.py pin repo_context/00_what_this_repo_is.md
  python3 …/context_manager.py pin src/auth/session.py --note "expiry bug"
  python3 …/context_manager.py work src/auth/middleware.py
  python3 …/context_manager.py cold tests/auth/test_session.py
  python3 …/context_manager.py pack --budget 20000
  python3 …/context_manager.py seed-context
  python3 …/context_manager.py promote PATH | demote PATH | rm PATH | clear [tier]
"""
from __future__ import annotations

import argparse
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib import context_tiers as ct  # noqa: E402


def main():
    p = argparse.ArgumentParser(
        prog="context_manager",
        description="Tiered context board: pinned vs working vs cold.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show tiers and task").set_defaults(func=cmd_status)

    t = sub.add_parser("task", help="Set current task label")
    t.add_argument("text")
    t.set_defaults(func=cmd_task)

    for name, tier in (("pin", "pinned"), ("work", "working"), ("cold", "cold")):
        s = sub.add_parser(name, help=f"Place path in {tier} tier")
        s.add_argument("path")
        s.add_argument("--note", default="")
        s.set_defaults(func=cmd_place, tier=tier)

    s = sub.add_parser("rm", help="Remove path from all tiers")
    s.add_argument("path")
    s.set_defaults(func=cmd_rm)

    s = sub.add_parser("touch", help="Bump last-used on a path")
    s.add_argument("path")
    s.set_defaults(func=cmd_touch)

    s = sub.add_parser("promote", help="cold→working→pinned")
    s.add_argument("path")
    s.set_defaults(func=cmd_promote)

    s = sub.add_parser("demote", help="pinned→working→cold")
    s.add_argument("path")
    s.set_defaults(func=cmd_demote)

    s = sub.add_parser("clear", help="Clear one tier or entire session")
    s.add_argument("tier", nargs="?", choices=list(ct.TIERS))
    s.set_defaults(func=cmd_clear)

    s = sub.add_parser("pack", help="Emit budgeted context pack for the agent")
    s.add_argument("--budget", type=int, default=ct.DEFAULT_BUDGET_CHARS)
    s.add_argument(
        "--source",
        action="store_true",
        help="Include source for working tier when summary missing / requested",
    )
    s.set_defaults(func=cmd_pack)

    sub.add_parser(
        "seed-context",
        help="Pin all summaries/repo_context/*.md orientation files",
    ).set_defaults(func=cmd_seed)

    args = p.parse_args()
    try:
        args.func(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    print(ct.status_text())


def cmd_task(args):
    ct.set_task(args.text)
    print(ct.status_text())


def cmd_place(args):
    ct.place(args.path, args.tier, note=args.note)
    print(ct.status_text())


def cmd_rm(args):
    ct.remove(args.path)
    print(ct.status_text())


def cmd_touch(args):
    ct.touch(args.path)
    print(ct.status_text())


def cmd_promote(args):
    ct.promote(args.path)
    print(ct.status_text())


def cmd_demote(args):
    ct.demote(args.path)
    print(ct.status_text())


def cmd_clear(args):
    ct.clear(args.tier)
    print(ct.status_text())


def cmd_pack(args):
    print(
        ct.pack(
            budget_chars=args.budget,
            include_source_for_working=args.source,
        )
    )


def cmd_seed(args):
    ct.seed_from_repo_context()
    print(ct.status_text())


if __name__ == "__main__":
    main()
