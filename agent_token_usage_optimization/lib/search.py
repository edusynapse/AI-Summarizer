import subprocess
import shutil
import os
import sqlite3

def _have_rg():
    return shutil.which("rg") is not None

def search(repo_root, query, max_results=30, excludes=None):
    """Returns list of dicts: {path, line, snippet, score}."""
    excludes = excludes or []
    results = []

    # 1) symbol index hit (exact + prefix)
    db_path = os.path.join(repo_root, "skills", "agent_token_usage_optimization", "repo", "index.sqlite")
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT path, line, kind, name, signature FROM symbols "
            "WHERE name = ? OR name LIKE ? LIMIT ?",
            (query, query + "%", max_results),
        ).fetchall()
        for path, line, kind, name, sig in rows:
            score = 100 if name == query else 70
            results.append({
                "path": path, "line": line,
                "snippet": f"[{kind}] {name}{sig}",
                "score": score,
            })
        conn.close()

    # 2) content search via ripgrep
    if _have_rg():
        cmd = ["rg", "--line-number", "--no-heading", "--max-count", "5",
               "--smart-case", "-g", "!**/node_modules/**", "-g", "!**/.git/**"]
        for ex in excludes:
            cmd.extend(["-g", f"!{ex}"])
        cmd.extend(["--", query, repo_root])
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
        except subprocess.TimeoutExpired:
            out = ""
        for line in out.splitlines()[:max_results]:
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            path, lineno, snippet = parts
            rel = os.path.relpath(path, repo_root)
            score = 40
            if query.lower() in os.path.basename(path).lower():
                score = 60
            results.append({
                "path": rel, "line": int(lineno),
                "snippet": snippet.strip()[:160],
                "score": score,
            })

    # dedupe by (path, line) keeping highest score
    best = {}
    for r in results:
        key = (r["path"], r["line"])
        if key not in best or r["score"] > best[key]["score"]:
            best[key] = r
    ranked = sorted(best.values(), key=lambda r: -r["score"])[:max_results]
    return ranked

def render(results):
    if not results:
        return "(no results)"
    lines = []
    for r in results:
        lines.append(f"{r['path']}:{r['line']}  {r['snippet']}")
    return "\n".join(lines)
