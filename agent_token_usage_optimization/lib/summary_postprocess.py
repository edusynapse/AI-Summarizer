"""Post-process LLM summaries: resolve NAVIGATION line numbers via outline.

No LLM. Optional ADJACENT block inject from adjacency.sqlite.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import adjacency, languages, outline

# Bullet like: - role — `Symbol` — approx lines 10-20
_NAV_LINE = re.compile(
    r"^(\s*[-*]\s+.*?—\s*`([^`]+)`\s*—\s*)(?:approx\s+)?lines?\s+[^;\n]*(.*)$",
    re.IGNORECASE,
)
_NAV_LINE_LOOSE = re.compile(
    r"^(\s*[-*]\s+.*?`([^`]+)`.*?)(?:approx\s+)?lines?\s+\S+(.*)$",
    re.IGNORECASE,
)
_SYM_IN_BACKTICKS = re.compile(r"`([^`]+)`")


def _symbol_candidates(raw: str) -> List[str]:
    """From `A.B._fetch` produce [_fetch, B._fetch, A.B._fetch, …]."""
    raw = raw.strip()
    parts = re.split(r"[.#]", raw)
    parts = [p for p in parts if p]
    cands = [raw]
    if parts:
        cands.append(parts[-1])
    if len(parts) >= 2:
        cands.append(".".join(parts[-2:]))
    # unique
    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _build_symbol_map(source_text: str, lang: Optional[str]) -> Dict[str, Tuple[int, str]]:
    """name → (line, kind). Prefer first occurrence."""
    m: Dict[str, Tuple[int, str]] = {}
    if not lang:
        return m
    for line_no, kind, name, _sig in outline.extract(source_text, lang):
        if name not in m:
            m[name] = (line_no, kind)
    return m


def _resolve_name(name: str, sym_map: Dict[str, Tuple[int, str]]) -> Optional[Tuple[int, str]]:
    for cand in _symbol_candidates(name):
        if cand in sym_map:
            return sym_map[cand]
    return None


def resolve_navigation_lines(
    md_text: str,
    source_text: str,
    source_rel: str,
) -> Tuple[str, dict]:
    """Rewrite NAVIGATION (and similar) bullets with outline line numbers."""
    lang = languages.detect(source_rel)
    sym_map = _build_symbol_map(source_text, lang)
    stats = {
        "resolved": 0,
        "unresolved": 0,
        "backend": outline.backend_name() if lang else "none",
        "symbols_indexed": len(sym_map),
    }
    if not sym_map:
        return md_text, stats

    lines = md_text.splitlines(keepends=True)
    out = []
    for line in lines:
        stripped = line.rstrip("\n")
        m = _NAV_LINE.match(stripped) or _NAV_LINE_LOOSE.match(stripped)
        if not m:
            # still try any bullet with backticks + "lines"
            if "lines" in stripped.lower() and "`" in stripped and stripped.lstrip().startswith(("-", "*")):
                syms = _SYM_IN_BACKTICKS.findall(stripped)
                hit = None
                for s in syms:
                    hit = _resolve_name(s, sym_map)
                    if hit:
                        break
                if hit:
                    line_no, kind = hit
                    # replace last "lines …" chunk
                    new = re.sub(
                        r"(?:approx\s+)?lines?\s+\S+",
                        f"lines {line_no}",
                        stripped,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                    if new == stripped:
                        new = stripped + f" — lines {line_no}"
                    out.append(new + ("\n" if line.endswith("\n") else ""))
                    stats["resolved"] += 1
                    continue
            out.append(line)
            continue

        prefix, sym, suffix = m.group(1), m.group(2), m.group(3) if m.lastindex >= 3 else ""
        hit = _resolve_name(sym, sym_map)
        if not hit:
            stats["unresolved"] += 1
            # keep symbol, mark unknown range
            new = f"{prefix}lines ?{suffix}"
            out.append(new + ("\n" if line.endswith("\n") else ""))
            continue
        line_no, _kind = hit
        new = f"{prefix}lines {line_no}{suffix}"
        out.append(new + ("\n" if line.endswith("\n") else ""))
        stats["resolved"] += 1

    # NEXT HOP synthesis if missing
    text = "".join(out)
    if "## NEXT HOP" not in text and sym_map:
        # prefer first class or first function
        pick = None
        for name, (ln, kind) in sym_map.items():
            if kind == "class":
                pick = name
                break
        if not pick:
            pick = next(iter(sym_map.keys()))
        hop = (
            f"\n## NEXT HOP\n"
            f"`broker.py read {source_rel} --symbol {pick}`\n"
        )
        text = text.rstrip() + "\n" + hop

    return text, stats


def postprocess_summary_file(
    md_path: Path,
    source_full: Path,
    source_rel: str,
    skill_dir: Optional[Path] = None,
    *,
    inject_adjacent: bool = True,
) -> dict:
    """Postprocess one summary markdown file in place."""
    if not md_path.is_file() or not source_full.is_file():
        return {"ok": False, "error": "missing md or source"}
    md = md_path.read_text(encoding="utf-8", errors="ignore")
    src = source_full.read_text(encoding="utf-8", errors="ignore")
    new_md, stats = resolve_navigation_lines(md, src, source_rel)

    if inject_adjacent and skill_dir is not None:
        adj = adjacency.query_adjacent(skill_dir, source_rel)
        if not adj.get("error"):
            new_md = adjacency.inject_adjacent_block(new_md, adj)
            stats["adjacent_injected"] = True
        else:
            stats["adjacent_injected"] = False
            stats["adjacent_note"] = adj.get("error")

    if new_md != md:
        md_path.write_text(new_md, encoding="utf-8")
        stats["wrote"] = True
    else:
        stats["wrote"] = False
    stats["ok"] = True
    stats["path"] = source_rel
    return stats
