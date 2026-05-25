#!/usr/bin/env python3
"""Build the symbol index for the current repo.

Reads repo/config.json for include/exclude globs, walks the tree,
extracts symbols via lib.outline, writes them to repo/index.sqlite.
"""
import os
import sys
import json
import fnmatch
import hashlib
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import outline, languages, summarize  # noqa: E402

REPO_DIR = os.path.join(HERE, "repo")
DEFAULT_CONFIG = {
    "include": ["**/*.js", "**/*.mjs", "**/*.ts", "**/*.tsx", "**/*.py",
                "**/*.dart", "**/*.rs", "**/*.go", "**/*.java"],
    "exclude": ["**/node_modules/**", "**/.git/**", "**/dist/**", "**/build/**",
                "**/.next/**", "**/coverage/**", "**/*.min.js",
                "**/skills/agent_token_usage_optimization/repo/**"],
    "summary_max_files": 200,
}

def _repo_root():
    # repo root = three levels above this file: <root>/skills/agent_token_usage_optimization/indexer.py
    return os.path.abspath(os.path.join(HERE, "..", ".."))

def _load_config():
    path = os.path.join(REPO_DIR, "config.json")
    if not os.path.exists(path):
        os.makedirs(REPO_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG
    with open(path) as f:
        return json.load(f)

def _matches_any(path, patterns):
    return any(fnmatch.fnmatch(path, p) for p in patterns)

def _walk(root, cfg):
    for dirpath, dirnames, filenames in os.walk(root):
        # prune common heavy dirs early
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "dist", "build", ".next", "coverage")]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            if _matches_any(rel, cfg["exclude"]):
                continue
            if not _matches_any(rel, cfg["include"]):
                continue
            yield full, rel

def _init_db(db_path):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE files (
            path TEXT PRIMARY KEY,
            hash TEXT NOT NULL,
            loc INTEGER NOT NULL,
            lang TEXT
        );
        CREATE TABLE symbols (
            path TEXT NOT NULL,
            line INTEGER NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            signature TEXT
        );
        CREATE INDEX idx_symbols_name ON symbols(name);
        CREATE INDEX idx_symbols_path ON symbols(path);
    """)
    return conn

def build():
    cfg = _load_config()
    root = _repo_root()
    db_path = os.path.join(REPO_DIR, "index.sqlite")
    summaries_dir = os.path.join(REPO_DIR, "summaries")
    os.makedirs(summaries_dir, exist_ok=True)
    conn = _init_db(db_path)

    file_count = 0
    sym_count = 0
    summary_entries = []

    for full, rel in _walk(root, cfg):
        try:
            with open(full, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            continue
        lang = languages.detect(rel)
        h = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        loc = text.count("\n") + 1
        conn.execute("INSERT OR REPLACE INTO files(path, hash, loc, lang) VALUES (?,?,?,?)",
                     (rel, h, loc, lang))
        symbols = outline.extract(text, lang) if lang else []
        for line_no, kind, name, sig in symbols:
            conn.execute("INSERT INTO symbols(path, line, kind, name, signature) VALUES (?,?,?,?,?)",
                         (rel, line_no, kind, name, sig))
        sym_count += len(symbols)
        file_count += 1

        # cache per-file summary keyed by hash
        cache_path = os.path.join(summaries_dir, f"{h}.txt")
        if not os.path.exists(cache_path):
            with open(cache_path, "w") as cf:
                cf.write(summarize.summarize_file(text, rel))
        summary_entries.append((rel, loc, len(symbols)))

    conn.commit()
    conn.close()

    _write_repo_summary(summary_entries, cfg)
    print(f"indexed {file_count} files, {sym_count} symbols → {db_path}")

def _write_repo_summary(entries, cfg):
    entries.sort(key=lambda e: -e[1])
    top = entries[:cfg.get("summary_max_files", 200)]
    path = os.path.join(REPO_DIR, "SUMMARY.md")
    if os.path.exists(path):
        with open(path) as f:
            existing = f.read()
        if "<!-- AUTO:BEGIN -->" not in existing:
            existing += "\n\n<!-- AUTO:BEGIN -->\n<!-- AUTO:END -->\n"
    else:
        existing = ("# Repo Summary\n\n"
                    "Hand-edit the top section. Everything between AUTO markers is regenerated.\n\n"
                    "<!-- AUTO:BEGIN -->\n<!-- AUTO:END -->\n")
    auto = ["<!-- AUTO:BEGIN -->",
            f"## File Index ({len(entries)} files, showing top {len(top)} by LOC)",
            ""]
    auto.append("| File | LOC | Symbols |")
    auto.append("|------|-----|---------|")
    for rel, loc, nsym in top:
        auto.append(f"| `{rel}` | {loc} | {nsym} |")
    auto.append("<!-- AUTO:END -->")
    new_block = "\n".join(auto)
    import re
    out = re.sub(r"<!-- AUTO:BEGIN -->.*?<!-- AUTO:END -->", new_block,
                 existing, flags=re.DOTALL)
    with open(path, "w") as f:
        f.write(out)

if __name__ == "__main__":
    build()
