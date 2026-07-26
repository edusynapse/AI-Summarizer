"""Layer 2 — tiered context manager (pinned / working / cold).

Agents keep a small session board of paths so packed prompts stay under budget:

  pinned   — always include (orientation, critical modules). Highest priority.
  working  — active task files; include summaries and optional source slices.
  cold     — known paths kept as one-line stubs (do not paste full text).

State file (session-local, gitignored):
  skills/agent_token_usage_optimization/repo/context_session.json
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TIERS = ("pinned", "working", "cold")

DEFAULT_BUDGET_CHARS = 24_000
DEFAULT_PINNED_MAX_CHARS = 8_000
DEFAULT_WORKING_MAX_CHARS = 12_000
DEFAULT_COLD_LINE_CHARS = 160
DEFAULT_SUMMARY_CHARS = 2_500


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def repo_root(start: Optional[str] = None) -> Path:
    """Best-effort consumer repo root (parent of skills/ or cwd)."""
    if start:
        p = Path(start).resolve()
    else:
        p = Path.cwd().resolve()
    for _ in range(10):
        if (p / "skills" / "agent_token_usage_optimization").is_dir():
            return p
        if (p / ".git").exists() and (p / "skills").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    # skill checked out as AI-Summarizer source
    skill = skill_dir()
    if skill.name == "agent_token_usage_optimization":
        parent = skill.parent
        if parent.name == "skills":
            return parent.parent
        return Path.cwd().resolve()
    return Path.cwd().resolve()


def session_path(root: Optional[Path] = None) -> Path:
    root = root or repo_root()
    # Prefer installed skill under root/skills/...
    installed = root / "skills" / "agent_token_usage_optimization" / "repo" / "context_session.json"
    if (root / "skills" / "agent_token_usage_optimization").is_dir():
        return installed
    # Running inside skill tree
    return skill_dir() / "repo" / "context_session.json"


def summaries_repo_dir(root: Optional[Path] = None) -> Path:
    root = root or repo_root()
    installed = root / "skills" / "agent_token_usage_optimization" / "summaries" / "repo"
    if installed.is_dir():
        return installed
    return skill_dir() / "summaries" / "repo"


def repo_context_dir(root: Optional[Path] = None) -> Path:
    root = root or repo_root()
    installed = root / "skills" / "agent_token_usage_optimization" / "summaries" / "repo_context"
    if installed.is_dir():
        return installed
    return skill_dir() / "summaries" / "repo_context"


def _empty_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "task": "",
        "updated_at": time.time(),
        "pinned": {},
        "working": {},
        "cold": {},
    }


def load_state(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or session_path()
    if not path.is_file():
        return _empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty_state()
        for t in TIERS:
            data.setdefault(t, {})
            if not isinstance(data[t], dict):
                data[t] = {}
        data.setdefault("task", "")
        data.setdefault("version", 1)
        return data
    except Exception:
        return _empty_state()


def save_state(state: Dict[str, Any], path: Optional[Path] = None) -> Path:
    path = path or session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updated_at"] = time.time()
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _norm_path(path: str) -> str:
    p = path.strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _entry(note: str = "", meta: Optional[dict] = None) -> dict:
    return {
        "note": note or "",
        "added_at": time.time(),
        "touched_at": time.time(),
        "meta": meta or {},
    }


def set_task(task: str, path: Optional[Path] = None) -> Dict[str, Any]:
    state = load_state(path)
    state["task"] = task.strip()
    save_state(state, path)
    return state


def place(
    path: str,
    tier: str,
    note: str = "",
    state_path: Optional[Path] = None,
    meta: Optional[dict] = None,
) -> Dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}")
    rel = _norm_path(path)
    state = load_state(state_path)
    # remove from other tiers
    for t in TIERS:
        state[t].pop(rel, None)
    state[tier][rel] = _entry(note, meta)
    save_state(state, state_path)
    return state


def remove(path: str, state_path: Optional[Path] = None) -> Dict[str, Any]:
    rel = _norm_path(path)
    state = load_state(state_path)
    for t in TIERS:
        state[t].pop(rel, None)
    save_state(state, state_path)
    return state


def touch(path: str, state_path: Optional[Path] = None) -> Dict[str, Any]:
    rel = _norm_path(path)
    state = load_state(state_path)
    for t in TIERS:
        if rel in state[t]:
            state[t][rel]["touched_at"] = time.time()
            save_state(state, state_path)
            return state
    raise KeyError(f"not in any tier: {rel}")


def clear(tier: Optional[str] = None, state_path: Optional[Path] = None) -> Dict[str, Any]:
    state = load_state(state_path)
    if tier:
        if tier not in TIERS:
            raise ValueError(f"tier must be one of {TIERS}")
        state[tier] = {}
    else:
        state = _empty_state()
        # keep task if we only want clear all tiers but preserve task? full clear resets task
    save_state(state, state_path)
    return state


def promote(path: str, state_path: Optional[Path] = None) -> Dict[str, Any]:
    """cold → working → pinned."""
    rel = _norm_path(path)
    state = load_state(state_path)
    if rel in state["cold"]:
        note = state["cold"][rel].get("note", "")
        return place(rel, "working", note, state_path)
    if rel in state["working"]:
        note = state["working"][rel].get("note", "")
        return place(rel, "pinned", note, state_path)
    if rel in state["pinned"]:
        return state
    return place(rel, "working", "", state_path)


def demote(path: str, state_path: Optional[Path] = None) -> Dict[str, Any]:
    """pinned → working → cold."""
    rel = _norm_path(path)
    state = load_state(state_path)
    if rel in state["pinned"]:
        note = state["pinned"][rel].get("note", "")
        return place(rel, "working", note, state_path)
    if rel in state["working"]:
        note = state["working"][rel].get("note", "")
        return place(rel, "cold", note, state_path)
    if rel in state["cold"]:
        return state
    return place(rel, "cold", "", state_path)


def status_text(state: Optional[Dict[str, Any]] = None, state_path: Optional[Path] = None) -> str:
    state = state or load_state(state_path)
    lines = []
    task = state.get("task") or "(no task set)"
    lines.append(f"task: {task}")
    lines.append(f"session: {state_path or session_path()}")
    for t in TIERS:
        items = state.get(t) or {}
        lines.append(f"\n## {t} ({len(items)})")
        if not items:
            lines.append("  (empty)")
            continue
        for path, meta in sorted(items.items(), key=lambda kv: -kv[1].get("touched_at", 0)):
            note = meta.get("note") or ""
            suffix = f"  — {note}" if note else ""
            lines.append(f"  {path}{suffix}")
    return "\n".join(lines)


def _read_text(path: Path, max_chars: int) -> Tuple[str, bool]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"(unreadable: {e})", True
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + f"\n… [truncated {len(text) - max_chars} chars]"
    return text, truncated


def _resolve_summary(rel: str, root: Path) -> Optional[Path]:
    sdir = summaries_repo_dir(root)
    candidates = [
        sdir / f"{rel}.md",
        sdir / rel if rel.endswith(".md") else None,
    ]
    for c in candidates:
        if c is not None and c.is_file():
            return c
    return None


def _resolve_source(rel: str, root: Path) -> Optional[Path]:
    p = root / rel
    if p.is_file():
        return p
    return None


def _resolve_repo_context(rel: str, root: Path) -> Optional[Path]:
    # allow pinning bare names from repo_context
    rc = repo_context_dir(root)
    if rel.startswith("repo_context/"):
        p = rc / rel[len("repo_context/"):]
        if p.is_file():
            return p
    p = rc / rel
    if p.is_file():
        return p
    return None


def pack(
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    include_source_for_working: bool = False,
    state_path: Optional[Path] = None,
    root: Optional[Path] = None,
) -> str:
    """Render a budgeted context pack for the agent prompt."""
    root = root or repo_root()
    state = load_state(state_path)
    parts: List[str] = []
    used = 0

    def add(block: str) -> bool:
        nonlocal used
        if used >= budget_chars:
            return False
        room = budget_chars - used
        if len(block) > room:
            block = block[: max(0, room - 40)] + "\n… [budget cut]"
        parts.append(block)
        used += len(block)
        return used < budget_chars

    header = (
        f"# Tiered context pack\n"
        f"task: {state.get('task') or '(unset)'}\n"
        f"budget: {budget_chars} chars | used will follow\n"
    )
    add(header)

    # PINNED — full summaries / repo_context; source only if no summary
    add("\n# PINNED (always keep)\n")
    for rel, meta in sorted(
        (state.get("pinned") or {}).items(),
        key=lambda kv: -kv[1].get("touched_at", 0),
    ):
        note = meta.get("note") or ""
        body = _body_for_path(rel, root, max_chars=DEFAULT_SUMMARY_CHARS, prefer_summary=True, allow_source=True)
        block = f"\n## pinned: {rel}\n"
        if note:
            block += f"note: {note}\n"
        block += body + "\n"
        if not add(block):
            break

    # WORKING — summaries preferred; optional source
    if used < budget_chars:
        add("\n# WORKING (active task)\n")
        for rel, meta in sorted(
            (state.get("working") or {}).items(),
            key=lambda kv: -kv[1].get("touched_at", 0),
        ):
            note = meta.get("note") or ""
            body = _body_for_path(
                rel,
                root,
                max_chars=DEFAULT_SUMMARY_CHARS,
                prefer_summary=True,
                allow_source=include_source_for_working,
            )
            block = f"\n## working: {rel}\n"
            if note:
                block += f"note: {note}\n"
            block += body + "\n"
            if not add(block):
                break

    # COLD — stubs only
    if used < budget_chars:
        add("\n# COLD (stubs only — fetch if needed)\n")
        for rel, meta in sorted(
            (state.get("cold") or {}).items(),
            key=lambda kv: -kv[1].get("touched_at", 0),
        ):
            note = meta.get("note") or ""
            stub = note or _cold_stub(rel, root)
            if len(stub) > DEFAULT_COLD_LINE_CHARS:
                stub = stub[: DEFAULT_COLD_LINE_CHARS - 1] + "…"
            block = f"- {rel}: {stub}\n"
            if not add(block):
                break

    # rewrite used line
    out = "".join(parts)
    out = out.replace(
        "budget: %d chars | used will follow" % budget_chars,
        f"budget: {budget_chars} chars | used: {len(out)}",
        1,
    )
    return out


def _cold_stub(rel: str, root: Path) -> str:
    sp = _resolve_summary(rel, root)
    if sp:
        try:
            first = sp.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            for line in first[:8]:
                if line.strip() and not line.startswith("#"):
                    return line.strip()[:DEFAULT_COLD_LINE_CHARS]
        except Exception:
            pass
    return "(no summary — promote to working to load)"


def _body_for_path(
    rel: str,
    root: Path,
    max_chars: int,
    prefer_summary: bool,
    allow_source: bool,
) -> str:
    rc = _resolve_repo_context(rel, root)
    if rc:
        text, _ = _read_text(rc, max_chars)
        return f"(repo_context: {rc.name})\n{text}"

    if prefer_summary:
        sp = _resolve_summary(rel, root)
        if sp:
            text, _ = _read_text(sp, max_chars)
            return f"(summary)\n{text}"

    if allow_source:
        src = _resolve_source(rel, root)
        if src:
            text, _ = _read_text(src, max_chars)
            return f"(source)\n{text}"

    # fallback stub
    sp = _resolve_summary(rel, root)
    if sp:
        text, _ = _read_text(sp, max_chars)
        return f"(summary)\n{text}"
    src = _resolve_source(rel, root)
    if src:
        return f"(path exists; not loaded — use broker read) size≈{src.stat().st_size}"
    return "(path not found on disk or in summaries)"


def seed_from_repo_context(state_path: Optional[Path] = None, root: Optional[Path] = None) -> Dict[str, Any]:
    """Pin all curated repo_context/*.md files (except README)."""
    root = root or repo_root()
    rc = repo_context_dir(root)
    state = load_state(state_path)
    if not rc.is_dir():
        return state
    for fn in sorted(os.listdir(rc)):
        if not fn.endswith(".md") or fn.lower() == "readme.md":
            continue
        rel = f"repo_context/{fn}"
        if rel not in state["pinned"]:
            state["pinned"][rel] = _entry("seeded from repo_context")
    save_state(state, state_path)
    return state
