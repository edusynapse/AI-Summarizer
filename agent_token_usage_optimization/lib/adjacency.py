"""Per-repo import adjacency. Stores ONLY edges for the skill's own repo.

DB: <skill>/repo/adjacency.sqlite  (never holds foreign-repo symbols/summaries)

Discovery: parse import-like statements from source (no LLM).
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ── extractors ─────────────────────────────────────────────────────────────

_RE_DART_IMPORT = re.compile(
    r"""^\s*import\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_RE_DART_EXPORT = re.compile(
    r"""^\s*export\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_RE_JS_FROM = re.compile(
    r"""(?:import|export)\s+(?:type\s+)?(?:[\w*\s{},]+)\s+from\s+['"]([^'"]+)['"]""",
)
_RE_JS_REQUIRE = re.compile(
    r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
)
_RE_JS_SIDE = re.compile(
    r"""^\s*import\s+['"]([^'"]+)['"]\s*;?""",
    re.MULTILINE,
)
_RE_PY_FROM = re.compile(
    r"""^\s*from\s+([.\w]+)\s+import\s+""",
    re.MULTILINE,
)
_RE_PY_IMPORT = re.compile(
    r"""^\s*import\s+([.\w]+)""",
    re.MULTILINE,
)


def extract_import_specs(text: str, lang: Optional[str]) -> List[str]:
    """Return raw import specifiers (as written in source)."""
    if not text or not lang:
        return []
    specs: List[str] = []
    if lang in ("dart",):
        specs.extend(_RE_DART_IMPORT.findall(text))
        specs.extend(_RE_DART_EXPORT.findall(text))
    elif lang in ("js", "ts"):
        specs.extend(_RE_JS_FROM.findall(text))
        specs.extend(_RE_JS_REQUIRE.findall(text))
        specs.extend(_RE_JS_SIDE.findall(text))
    elif lang in ("py",):
        specs.extend(_RE_PY_FROM.findall(text))
        specs.extend(_RE_PY_IMPORT.findall(text))
    # dedupe preserve order
    seen = set()
    out = []
    for s in specs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def resolve_import(
    spec: str,
    src_rel: str,
    package_prefixes: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Map import specifier → repo-relative path candidate (best effort).

    Returns None for unresolved / external packages.
    May return path without extension; caller can still store the string.
    """
    package_prefixes = package_prefixes or {}
    spec = spec.strip()
    if not spec:
        return None

    # Dart package:name/...
    if spec.startswith("package:"):
        rest = spec[len("package:"):]
        # package:foo/bar.dart → try prefixes
        for _key, prefix in package_prefixes.items():
            # prefix like package:know_to_win/ or package:know_to_win
            p = prefix if prefix.endswith("/") else prefix + "/"
            if not p.startswith("package:"):
                p = "package:" + p
            if spec.startswith(p.rstrip("/") + "/") or spec.startswith(p):
                tail = spec[len(p.rstrip("/")) + 1:] if spec.startswith(p.rstrip("/") + "/") else spec[len(p):]
                # map to lib/tail
                if not tail.startswith("lib/"):
                    return ("lib/" + tail).replace("\\", "/")
                return tail.replace("\\", "/")
        # generic package:foo/x → lib/x if single-package app
        if "/" in rest:
            pkg, _, tail = rest.partition("/")
            return ("lib/" + tail).replace("\\", "/")
        return None

    # relative
    if spec.startswith("."):
        src_dir = os.path.dirname(src_rel.replace("\\", "/"))
        joined = os.path.normpath(os.path.join(src_dir, spec)).replace("\\", "/")
        if joined.startswith("../"):
            return None
        return joined

    # dart relative without ./
    if lang_is_pathlike(spec):
        src_dir = os.path.dirname(src_rel.replace("\\", "/"))
        if "/" in spec or spec.endswith((".dart", ".js", ".ts", ".tsx", ".py")):
            joined = os.path.normpath(os.path.join(src_dir, spec)).replace("\\", "/")
            if not joined.startswith(".."):
                return joined

    # Python absolute module → path guess
    if re.match(r"^[a-zA-Z_][\w.]*$", spec) and "." in spec:
        return spec.replace(".", "/") + ".py"

    return None


def lang_is_pathlike(spec: str) -> bool:
    return "/" in spec or spec.endswith((".dart", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".py"))


def normalize_dst_path(dst: str, known_files: Optional[set] = None) -> str:
    """Add common extensions if known_files provided."""
    dst = dst.replace("\\", "/")
    if known_files is None:
        return dst
    if dst in known_files:
        return dst
    for ext in (".dart", ".js", ".ts", ".tsx", ".jsx", ".py", ".mjs", ".cjs"):
        cand = dst if dst.endswith(ext) else dst + ext
        if cand in known_files:
            return cand
        # index
        idx = dst.rstrip("/") + "/index" + ext
        if idx in known_files:
            return idx
    return dst


# ── sqlite ─────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS file_edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    kind TEXT NOT NULL,
    PRIMARY KEY (src, dst, kind)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON file_edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON file_edges(dst);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON file_edges(kind);

-- HTTP path literals found in THIS repo only (call sites and route regs).
-- Cross-repo join = match path_key across two separate adjacency.sqlite files.
CREATE TABLE IF NOT EXISTS path_hits (
    file_rel TEXT NOT NULL,
    path_key TEXT NOT NULL,
    method TEXT,
    kind TEXT NOT NULL,
    line INTEGER,
    PRIMARY KEY (file_rel, path_key, method, kind, line)
);
CREATE INDEX IF NOT EXISTS idx_path_hits_key ON path_hits(path_key);
CREATE INDEX IF NOT EXISTS idx_path_hits_file ON path_hits(file_rel);
"""

# SessionURI.get('/admin/settings') / .post("...")
_RE_SESSION_URI = re.compile(
    r"""SessionURI\.(get|post|put|patch|delete)\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
# fetch('/api/...')  axios.get('/...')
_RE_FETCH = re.compile(
    r"""(?:fetch|axios\.(get|post|put|patch|delete))\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
# .get('/path'  .post("/path"  router.get('...')
_RE_ROUTE_METHOD = re.compile(
    r"""(?:\b(?:app|router|server)\.)?(get|post|put|patch|delete|use|all)\s*\(\s*['"](/[^'"]*)['"]""",
    re.IGNORECASE,
)
# standalone path-looking strings that look like API routes (conservative)
_RE_PATH_LITERAL = re.compile(
    r"""['"](/(?:api|admin|v\d+)[^'"]{0,200})['"]""",
)
# JSDoc / comments: GET /admin/settings
_RE_DOC_ROUTE = re.compile(
    r"""\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./\-]{2,200})""",
    re.IGNORECASE,
)

# Skip indexing path hits from these path fragments (noise)
_SKIP_PATH_FRAGMENTS = (
    "skills/agent_token_usage_optimization/",
    "node_modules/",
    "dev_plans/",
    "__pycache__/",
)


def normalize_http_path(path: str) -> str:
    p = (path or "").strip()
    if not p.startswith("/"):
        return ""
    # strip query/hash
    p = p.split("?", 1)[0].split("#", 1)[0]
    if len(p) > 1 and p.endswith("/"):
        p = p.rstrip("/")
    return p


def _admin_mount_variants(file_rel: str, key: str) -> List[str]:
    """Express often mounts adminroutes under /admin with router.get('/settings')."""
    keys = [key]
    rel = file_rel.replace("\\", "/")
    if "adminroutes/" in rel or rel.startswith("adminroutes/"):
        if key.startswith("/admin/") or key.startswith("/api/"):
            return keys
        # '/settings' → '/admin/settings'
        if key.startswith("/"):
            keys.append(normalize_http_path("/admin" + key))
    return [k for k in keys if k]


def extract_http_path_hits(
    text: str,
    lang: Optional[str] = None,
    file_rel: str = "",
) -> List[Tuple[str, str, str, int]]:
    """Return list of (path_key, method, kind, line_no).

    kind: call | route
    method: GET/POST/… or *
    """
    if not text:
        return []
    hits: List[Tuple[str, str, str, int]] = []

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    def add(key: str, method: str, kind: str, line: int):
        for k in _admin_mount_variants(file_rel, key):
            hits.append((k, method, kind, line))

    for m in _RE_SESSION_URI.finditer(text):
        method = m.group(1).upper()
        key = normalize_http_path(m.group(2))
        if key:
            add(key, method, "call", line_of(m.start()))

    for m in _RE_FETCH.finditer(text):
        method = (m.group(1) or "GET").upper()
        key = normalize_http_path(m.group(2))
        if key:
            add(key, method, "call", line_of(m.start()))

    for m in _RE_ROUTE_METHOD.finditer(text):
        verb = m.group(1).lower()
        key = normalize_http_path(m.group(2))
        if not key:
            continue
        method = "*" if verb in ("use", "all") else verb.upper()
        kind = "route"
        if lang in ("dart",):
            kind = "call"
        add(key, method, kind, line_of(m.start()))

    for m in _RE_DOC_ROUTE.finditer(text):
        method = m.group(1).upper()
        key = normalize_http_path(m.group(2))
        if key:
            add(key, method, "route", line_of(m.start()))

    # Extra path literals (admin/api) as call kind if not already captured
    seen_keys = {h[0] for h in hits}
    for m in _RE_PATH_LITERAL.finditer(text):
        key = normalize_http_path(m.group(1))
        if not key or key in seen_keys:
            continue
        add(key, "*", "call", line_of(m.start()))
        seen_keys.add(key)

    # dedupe
    uniq = []
    seen = set()
    for h in hits:
        t = (h[0], h[1], h[2], h[3])
        if t not in seen:
            seen.add(t)
            uniq.append(h)
    return uniq


def adjacency_db_path(skill_dir: Path) -> Path:
    return Path(skill_dir) / "repo" / "adjacency.sqlite"


def connect(skill_dir: Path, *, reset: bool = False) -> sqlite3.Connection:
    path = adjacency_db_path(skill_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if reset and path.is_file():
        path.unlink()
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    return conn


def rebuild_adjacency(
    skill_dir: Path,
    repo_root: Path,
    files: Sequence[Tuple[str, str, Optional[str]]],
    package_prefixes: Optional[Dict[str, str]] = None,
) -> dict:
    """Rebuild adjacency for this repo only.

    files: iterable of (rel_path, full_path, lang)
    """
    package_prefixes = package_prefixes or {}
    known = {rel.replace("\\", "/") for rel, _, _ in files}
    conn = connect(skill_dir, reset=True)
    edge_count = 0
    path_hit_count = 0
    for rel, full, lang in files:
        rel = rel.replace("\\", "/")
        if any(frag in rel for frag in _SKIP_PATH_FRAGMENTS):
            continue
        try:
            text = Path(full).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for spec in extract_import_specs(text, lang):
            dst = resolve_import(spec, rel, package_prefixes)
            if not dst:
                # store external as dst with kind import_ext for visibility
                conn.execute(
                    "INSERT OR IGNORE INTO file_edges(src, dst, kind) VALUES (?,?,?)",
                    (rel, f"ext:{spec}", "import_ext"),
                )
                edge_count += 1
                continue
            dst = normalize_dst_path(dst, known)
            conn.execute(
                "INSERT OR IGNORE INTO file_edges(src, dst, kind) VALUES (?,?,?)",
                (rel, dst, "import"),
            )
            edge_count += 1
        for path_key, method, kind, line_no in extract_http_path_hits(text, lang, rel):
            conn.execute(
                "INSERT OR IGNORE INTO path_hits(file_rel, path_key, method, kind, line) "
                "VALUES (?,?,?,?,?)",
                (rel, path_key, method or "*", kind, line_no),
            )
            path_hit_count += 1
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('edge_count', ?)",
        (str(edge_count),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('path_hit_count', ?)",
        (str(path_hit_count),),
    )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM file_edges").fetchone()[0]
    np = conn.execute("SELECT COUNT(*) FROM path_hits").fetchone()[0]
    conn.close()
    return {
        "path": str(adjacency_db_path(skill_dir)),
        "edges": n,
        "path_hits": np,
        "files": len(files),
    }


def query_adjacent(
    skill_dir: Path,
    path: str,
    *,
    max_results: int = 40,
) -> dict:
    """Return imports and importers for path in THIS skill's adjacency.sqlite."""
    path = path.replace("\\", "/").lstrip("./")
    db = adjacency_db_path(skill_dir)
    if not db.is_file():
        return {
            "path": path,
            "error": f"no adjacency.sqlite at {db} — run broker.py index / indexer",
            "imports": [],
            "importers": [],
            "import_ext": [],
        }
    conn = sqlite3.connect(str(db))
    imports = [
        r[0]
        for r in conn.execute(
            "SELECT dst FROM file_edges WHERE src=? AND kind='import' ORDER BY dst LIMIT ?",
            (path, max_results),
        )
    ]
    import_ext = [
        r[0]
        for r in conn.execute(
            "SELECT dst FROM file_edges WHERE src=? AND kind='import_ext' ORDER BY dst LIMIT ?",
            (path, max_results),
        )
    ]
    # also try without extension variants for importers matching
    importers = [
        r[0]
        for r in conn.execute(
            "SELECT src FROM file_edges WHERE dst=? AND kind='import' ORDER BY src LIMIT ?",
            (path, max_results),
        )
    ]
    # importers that point at path without ext
    base = path
    for ext in (".dart", ".js", ".ts", ".tsx", ".py"):
        if path.endswith(ext):
            base = path[: -len(ext)]
            break
    extra = [
        r[0]
        for r in conn.execute(
            "SELECT src FROM file_edges WHERE dst=? AND kind='import' ORDER BY src LIMIT ?",
            (base, max_results),
        )
    ]
    for e in extra:
        if e not in importers:
            importers.append(e)
    conn.close()
    return {
        "path": path,
        "imports": imports[:max_results],
        "importers": importers[:max_results],
        "import_ext": import_ext[:max_results],
    }


def render_adjacent(data: dict) -> str:
    if data.get("error"):
        return data["error"]
    lines = [f"path: {data['path']}", ""]
    lines.append(f"## imports ({len(data.get('imports') or [])})")
    if data.get("imports"):
        for p in data["imports"]:
            lines.append(f"  → {p}")
    else:
        lines.append("  (none resolved)")
    lines.append("")
    lines.append(f"## importers ({len(data.get('importers') or [])})")
    if data.get("importers"):
        for p in data["importers"]:
            lines.append(f"  ← {p}")
    else:
        lines.append("  (none)")
    if data.get("import_ext"):
        lines.append("")
        lines.append(f"## external / unresolved ({len(data['import_ext'])})")
        for p in data["import_ext"][:30]:
            lines.append(f"  · {p}")
    return "\n".join(lines)


ADJACENT_BEGIN = "<!-- ADJACENT BEGIN -->"
ADJACENT_END = "<!-- ADJACENT END -->"


def format_adjacent_md_block(data: dict) -> str:
    body = []
    body.append("## ADJACENT")
    body.append(f"(this repo only; path `{data.get('path')}`)")
    if data.get("error"):
        body.append(data["error"])
    else:
        imps = data.get("imports") or []
        importers = data.get("importers") or []
        body.append("### imports")
        if imps:
            for p in imps:
                body.append(f"- `{p}`")
        else:
            body.append("- none resolved")
        body.append("### importers")
        if importers:
            for p in importers:
                body.append(f"- `{p}`")
        else:
            body.append("- none")
    return "\n".join(body)


def inject_adjacent_block(md_text: str, data: dict) -> str:
    block = (
        f"{ADJACENT_BEGIN}\n"
        f"{format_adjacent_md_block(data)}\n"
        f"{ADJACENT_END}\n"
    )
    if ADJACENT_BEGIN in md_text and ADJACENT_END in md_text:
        pre, _, rest = md_text.partition(ADJACENT_BEGIN)
        _, _, post = rest.partition(ADJACENT_END)
        # post may start with newline
        if post.startswith("\n"):
            post = post[1:]
        return pre.rstrip() + "\n\n" + block + post.lstrip("\n")
    return md_text.rstrip() + "\n\n" + block


def paths_for_file(skill_dir: Path, file_rel: str) -> List[dict]:
    """HTTP path_hits for a file in THIS repo's adjacency.sqlite."""
    file_rel = file_rel.replace("\\", "/").lstrip("./")
    db = adjacency_db_path(skill_dir)
    if not db.is_file():
        return []
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT path_key, method, kind, line FROM path_hits WHERE file_rel=? "
        "ORDER BY path_key, method",
        (file_rel,),
    ).fetchall()
    conn.close()
    return [
        {"path": r[0], "method": r[1], "kind": r[2], "line": r[3]}
        for r in rows
    ]


def files_for_path_key(skill_dir: Path, path_key: str, *, max_results: int = 40) -> List[dict]:
    """Files in THIS repo that mention path_key."""
    path_key = normalize_http_path(path_key)
    db = adjacency_db_path(skill_dir)
    if not db.is_file() or not path_key:
        return []
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT file_rel, method, kind, line FROM path_hits WHERE path_key=? "
        "ORDER BY kind DESC, file_rel LIMIT ?",
        (path_key, max_results),
    ).fetchall()
    conn.close()
    return [
        {"file": r[0], "method": r[1], "kind": r[2], "line": r[3]}
        for r in rows
    ]


def cross_repo_for_file(
    local_skill: Path,
    file_rel: str,
    siblings: Dict[str, Path],
    *,
    max_per_path: int = 15,
) -> dict:
    """Join this file's path literals to each sibling's separate path_hits table.

    Does NOT merge DBs. Reads sibling adjacency.sqlite only.
    """
    file_rel = file_rel.replace("\\", "/").lstrip("./")
    local_paths = paths_for_file(local_skill, file_rel)
    # If DB empty for file, try live extract from source
    if not local_paths:
        # best-effort: skill → repo root
        root = local_skill.parent.parent if local_skill.parent.name == "skills" else local_skill.parent
        src = root / file_rel
        if src.is_file():
            text = src.read_text(encoding="utf-8", errors="ignore")
            local_paths = [
                {"path": k, "method": m, "kind": kind, "line": ln}
                for k, m, kind, ln in extract_http_path_hits(text, None, file_rel)
            ]

    results = {
        "file": file_rel,
        "paths": local_paths,
        "siblings": {},
    }
    if not local_paths:
        results["note"] = (
            "no HTTP path literals found in this file "
            "(need SessionURI.get/post('…') or similar string paths)"
        )
        return results

    for sid, sib_root in (siblings or {}).items():
        sib_skill = Path(sib_root) / "skills" / "agent_token_usage_optimization"
        sib_db = adjacency_db_path(sib_skill)
        entry = {
            "skill": str(sib_skill),
            "adjacency_db": str(sib_db),
            "db_ok": sib_db.is_file(),
            "matches": [],
        }
        if not sib_db.is_file():
            entry["error"] = (
                f"sibling {sid!r} has no adjacency.sqlite — "
                f"cd {sib_root} && python3 skills/agent_token_usage_optimization/broker.py index"
            )
            results["siblings"][sid] = entry
            continue
        for lp in local_paths:
            key = lp["path"]
            hits = files_for_path_key(sib_skill, key, max_results=max_per_path)
            if not hits:
                entry["matches"].append({
                    "path": key,
                    "method": lp.get("method"),
                    "client_line": lp.get("line"),
                    "server_files": [],
                    "miss": True,
                })
                continue
            entry["matches"].append({
                "path": key,
                "method": lp.get("method"),
                "client_line": lp.get("line"),
                "server_files": hits,
                "miss": False,
            })
        results["siblings"][sid] = entry
    return results


def render_cross(data: dict) -> str:
    lines = [
        f"client file: {data.get('file')}",
        f"http paths in client: {len(data.get('paths') or [])}",
        "",
    ]
    if data.get("note"):
        lines.append(data["note"])
        return "\n".join(lines)
    if data.get("paths"):
        lines.append("## paths extracted (this repo)")
        for p in data["paths"]:
            lines.append(
                f"  {p.get('method') or '*':4} {p['path']}  (line {p.get('line')}, {p.get('kind')})"
            )
        lines.append("")
    for sid, ent in (data.get("siblings") or {}).items():
        lines.append(f"## sibling {sid!r}")
        lines.append(f"  db: {ent.get('adjacency_db')}  ok={ent.get('db_ok')}")
        if ent.get("error"):
            lines.append(f"  ERROR: {ent['error']}")
            lines.append("")
            continue
        for m in ent.get("matches") or []:
            if m.get("miss"):
                lines.append(
                    f"  {m.get('method') or '*':4} {m['path']}  → (no file in sibling path_hits)"
                )
                continue
            lines.append(f"  {m.get('method') or '*':4} {m['path']}  (client line {m.get('client_line')})")
            for sf in m.get("server_files") or []:
                lines.append(
                    f"       → {sf['file']}:{sf.get('line')}  "
                    f"[{sf.get('kind')} {sf.get('method')}]"
                )
        lines.append("")
    lines.append(
        "Note: each sibling keeps its own adjacency.sqlite; join is path string equality only."
    )
    return "\n".join(lines)
