#!/usr/bin/env python3
"""
Summary-layer search utilities for the agent_token_usage_optimization skill.

Designed to let agents search the rich LLM-generated summaries + rollups
*before* touching source code, per the documented workflow.

This is the core of the "better summary broker".
"""

import os
import re
import fnmatch
from pathlib import Path
from typing import List, Dict, Optional, Iterable


def find_summaries_root(start_path: Optional[str] = None) -> Optional[str]:
    """
    Locate the summaries/ directory.

    Works whether called from repo root or from inside skills/agent_token_usage_optimization/.
    Returns the absolute path to the 'summaries' directory (the one containing README.md + repo/ + rollups/).
    """
    if start_path is None:
        start_path = os.getcwd()

    p = Path(start_path).resolve()

    # Walk up looking for the skill marker or the summaries dir
    for _ in range(10):
        # Case 1: we are inside the skill dir already
        candidate = p / "summaries"
        if (candidate / "README.md").exists() and (candidate / "repo").exists():
            return str(candidate)

        # Case 2: standard layout - skills/agent_token_usage_optimization/summaries
        if (p / "skills" / "agent_token_usage_optimization" / "summaries" / "README.md").exists():
            return str(p / "skills" / "agent_token_usage_optimization" / "summaries")

        # Case 3: we are at repo root and summaries lives under skills/...
        if (p / "skills" / "agent_token_usage_optimization" / "summaries").exists():
            return str(p / "skills" / "agent_token_usage_optimization" / "summaries")

        if p.parent == p:
            break
        p = p.parent

    return None


def _iter_summary_files(summaries_root: str, dir_filter: Optional[str] = None) -> Iterable[Path]:
    """Yield .md files under summaries/repo/ and summaries/rollups/."""
    root = Path(summaries_root)

    search_roots = []
    repo_dir = root / "repo"
    rollups_dir = root / "rollups"

    if repo_dir.exists():
        search_roots.append(repo_dir)
    if rollups_dir.exists():
        search_roots.append(rollups_dir)

    for base in search_roots:
        for path in base.rglob("*.md"):
            if dir_filter:
                # dir_filter like "models" or "lib/helpers"
                rel = path.relative_to(base)
                if not str(rel).startswith(dir_filter.rstrip("/") + "/") and str(rel) != dir_filter:
                    # also allow matching top level like "models/xxx.md"
                    if not fnmatch.fnmatch(str(rel), f"{dir_filter}*"):
                        continue
            yield path


def _score_result(text: str, path: Path, query_terms: List[str]) -> int:
    """Simple but effective scoring for summary results."""
    score = 0
    lower_text = text.lower()
    lower_name = path.name.lower()
    rel = str(path).lower()

    # Strong signals from the curated summary structure
    if "invariants & gotchas" in lower_text:
        score += 35
    if "gotcha" in lower_text:
        score += 20
    if "performance" in lower_text or "scale" in lower_text or "slow" in lower_text:
        score += 15
    if "reindex" in lower_text or "scan" in lower_text:
        score += 12

    # Rollups are high-value routing documents
    if "/rollups/" in rel:
        score += 25

    # Filename / path matches
    for term in query_terms:
        t = term.lower()
        if t in lower_name:
            score += 18
        if t in rel:
            score += 10
        if t in lower_text:
            # count occurrences (capped)
            score += min(8, lower_text.count(t))

    return score


def search_summaries(
    query: str,
    summaries_root: Optional[str] = None,
    dir_filter: Optional[str] = None,
    max_results: int = 40,
) -> List[Dict]:
    """
    Search across all LLM-generated file summaries and rollups.

    Returns list of dicts sorted by relevance:
      {path, rel_path, snippet, score, is_rollup}
    """
    if summaries_root is None:
        summaries_root = find_summaries_root()
    if not summaries_root:
        return []

    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    if not terms:
        return []

    pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)

    results = []
    seen = set()

    for md_path in _iter_summary_files(summaries_root, dir_filter):
        try:
            text = md_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if not pattern.search(text):
            continue

        # Build a useful snippet around the first match
        match = pattern.search(text)
        start = max(0, match.start() - 80)
        end = min(len(text), match.end() + 120)
        snippet = text[start:end].replace("\n", " ").strip()[:220]

        rel_from_repo = md_path.relative_to(Path(summaries_root))
        key = str(rel_from_repo)
        if key in seen:
            continue
        seen.add(key)

        score = _score_result(text, md_path, terms)
        is_rollup = "rollups" in str(md_path)

        results.append({
            "path": str(md_path),
            "rel_path": str(rel_from_repo),
            "snippet": snippet,
            "score": score,
            "is_rollup": is_rollup,
        })

    results.sort(key=lambda r: (-r["score"], r["rel_path"]))
    return results[:max_results]


def grep_summaries(
    pattern: str,
    summaries_root: Optional[str] = None,
    dir_filter: Optional[str] = None,
    max_results: int = 60,
    context: int = 1,
) -> List[Dict]:
    """
    Regex grep across the summary layer (like rg, but only on .md summaries).
    """
    if summaries_root is None:
        summaries_root = find_summaries_root()
    if not summaries_root:
        return []

    try:
        rx = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    except re.error as e:
        return [{"error": f"Invalid regex: {e}"}]

    results = []

    for md_path in _iter_summary_files(summaries_root, dir_filter):
        try:
            text = md_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for m in rx.finditer(text):
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 60)
            snippet = text[start:end].replace("\n", " ").strip()[:200]

            rel = str(md_path.relative_to(Path(summaries_root)))
            results.append({
                "path": str(md_path),
                "rel_path": rel,
                "line": text[:m.start()].count("\n") + 1,
                "snippet": snippet,
                "match": m.group(0)[:80],
            })
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    return results


def render_search_results(results: List[Dict]) -> str:
    if not results:
        return "(no matching summaries found)"

    lines = []
    for r in results:
        marker = "📁 " if r.get("is_rollup") else "   "
        lines.append(f"{marker}{r['rel_path']}  (score={r['score']})")
        lines.append(f"    {r['snippet']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_grep_results(results: List[Dict]) -> str:
    if not results:
        return "(no matches)"
    if "error" in results[0]:
        return results[0]["error"]

    lines = []
    for r in results:
        lines.append(f"{r['rel_path']}:{r.get('line', '?')}")
        lines.append(f"    {r['snippet']}")
        lines.append("")
    return "\n".join(lines).rstrip()