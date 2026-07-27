"""Load per-repo workspace.env for multi-repo tooling.

Each repo keeps its OWN summaries / index.sqlite / adjacency.sqlite.
workspace.env only lists sibling checkout paths so tools can open
those separate stores (never merge DBs).

Load order for each key: process environment > repo/workspace.env > default.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SKILL_DIRNAME = "agent_token_usage_optimization"


def skill_dir_from_here(start: Optional[Path] = None) -> Path:
    """Directory containing this file's skill root (…/agent_token_usage_optimization)."""
    if start is not None:
        p = Path(start).resolve()
    else:
        p = Path(__file__).resolve().parent.parent
    return p


def repo_root_from_skill(skill: Path) -> Path:
    """Consumer repo root: …/skills/agent_token_usage_optimization → …/"""
    skill = skill.resolve()
    if skill.parent.name == "skills":
        return skill.parent.parent
    return skill.parent


def _parse_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key:
            out[key] = val
    return out


def _parse_siblings(raw: str) -> Dict[str, Path]:
    """id=/abs/path,id2=/other → dict."""
    result: Dict[str, Path] = {}
    if not raw or not raw.strip():
        return result
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            continue
        sid, _, path_s = part.partition("=")
        sid = sid.strip()
        path_s = path_s.strip().strip("'").strip('"')
        if not sid or not path_s:
            continue
        path_s = os.path.expanduser(path_s)
        result[sid] = Path(path_s).resolve()
    return result


def _parse_package_prefixes(raw: str) -> Dict[str, str]:
    """id:prefix or package:name/ → map. Format: pkg=package:pkg/ or know_to_win:package:know_to_win/"""
    result: Dict[str, str] = {}
    if not raw or not raw.strip():
        return result
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, _, v = part.partition("=")
        k, v = k.strip(), v.strip()
        if k and v:
            result[k] = v
    return result


def load_workspace(skill_dir: Optional[Path] = None) -> dict:
    """Return workspace config for this skill install."""
    skill = skill_dir_from_here(skill_dir)
    env_path = skill / "repo" / "workspace.env"
    file_vals = _parse_env_file(env_path)

    def get(key: str, default: str = "") -> str:
        if key in os.environ and os.environ[key] != "":
            return os.environ[key]
        return file_vals.get(key, default)

    siblings_raw = get("WORKSPACE_SIBLINGS", "")
    siblings = _parse_siblings(siblings_raw)
    prefixes = _parse_package_prefixes(get("WORKSPACE_PACKAGE_PREFIXES", ""))

    cross = get("WORKSPACE_CROSS_CONTRACTS", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )

    default_id = (
        skill.parent.parent.name
        if skill.parent.name == "skills"
        else skill.name
    )
    return {
        "skill_dir": skill,
        "repo_root": repo_root_from_skill(skill),
        "env_path": env_path,
        "repo_id": get("WORKSPACE_REPO_ID", "") or default_id,
        "role": get("WORKSPACE_ROLE", "") or "other",
        "siblings": siblings,  # id -> Path
        "package_prefixes": prefixes,
        "cross_contracts": cross,
        "warnings": _validate_siblings(siblings),
    }


def _validate_siblings(siblings: Dict[str, Path]) -> List[str]:
    warnings = []
    for sid, path in siblings.items():
        if not path.is_dir():
            warnings.append(f"sibling {sid!r} path missing: {path}")
            continue
        skill = path / "skills" / SKILL_DIRNAME
        if not skill.is_dir():
            warnings.append(
                f"sibling {sid!r} has no skills/{SKILL_DIRNAME} at {skill}"
            )
    return warnings


def sibling_skill_dir(ws: dict, sibling_id: str) -> Optional[Path]:
    path = (ws.get("siblings") or {}).get(sibling_id)
    if path is None:
        return None
    skill = Path(path) / "skills" / SKILL_DIRNAME
    if skill.is_dir():
        return skill
    return None


def sibling_repo_root(ws: dict, sibling_id: str) -> Optional[Path]:
    return (ws.get("siblings") or {}).get(sibling_id)


def resolve_skill_for_repo_flag(
    skill_dir: Optional[Path] = None,
    repo_id: Optional[str] = None,
) -> Tuple[Path, dict]:
    """Return (skill_dir, workspace) for current or --repo sibling.

    Never merges stores: caller uses returned skill_dir for paths.
    """
    local_skill = skill_dir_from_here(skill_dir)
    ws = load_workspace(local_skill)
    if not repo_id:
        return local_skill, ws
    sib = sibling_skill_dir(ws, repo_id)
    if sib is None:
        raise FileNotFoundError(
            f"unknown or unusable sibling repo id {repo_id!r}; "
            f"known: {list((ws.get('siblings') or {}).keys())}; "
            f"warnings: {ws.get('warnings')}"
        )
    # load sibling's own workspace.env for its id/role (optional)
    sib_ws = load_workspace(sib)
    return sib, sib_ws


def format_workspace_status(ws: dict) -> str:
    lines = [
        f"repo_id: {ws.get('repo_id')}",
        f"role: {ws.get('role')}",
        f"repo_root: {ws.get('repo_root')}",
        f"skill_dir: {ws.get('skill_dir')}",
        f"workspace.env: {ws.get('env_path')} "
        f"({'exists' if Path(ws['env_path']).is_file() else 'MISSING — copy workspace.env.example'})",
        f"cross_contracts: {ws.get('cross_contracts')}",
        "siblings:",
    ]
    sibs = ws.get("siblings") or {}
    if not sibs:
        lines.append("  (none — single-repo mode)")
    for sid, path in sorted(sibs.items()):
        skill = Path(path) / "skills" / SKILL_DIRNAME
        ok = path.is_dir() and skill.is_dir()
        lines.append(f"  {sid} → {path}  skill={'ok' if ok else 'MISSING'}")
    for w in ws.get("warnings") or []:
        lines.append(f"warning: {w}")
    return "\n".join(lines)
