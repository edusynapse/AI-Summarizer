#!/usr/bin/env python3
"""Embeddings-backed semantic search over the LLM summary corpus.

Index lives under summaries/embeddings/ (generated, gitignored by default).

Backends (pick via summaries/embeddings_config.json or env):
  hashing   — zero-dep feature-hash TF vectors (always available; good baseline)
  openai    — OpenAI-compatible embeddings HTTP API (OPENAI_API_KEY)
  ollama    — local Ollama /api/embeddings
  st        — sentence-transformers if installed (local models)

CLI is embeddings_index.py; summary_broker.py exposes `semantic`.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import summary_search

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,48}|[A-Za-z]{2,}")
DEFAULT_DIM = 384
DEFAULT_CONFIG = {
    "backend": "hashing",
    "dim": DEFAULT_DIM,
    "model": "text-embedding-3-small",
    "openai_base_url": "https://api.openai.com/v1",
    "ollama_base_url": "http://127.0.0.1:11434",
    "ollama_model": "nomic-embed-text",
    "st_model": "sentence-transformers/all-MiniLM-L6-v2",
    "include_rollups": True,
    "max_chars_per_doc": 6000,
}


def embeddings_dir(summaries_root: Optional[str] = None) -> Optional[Path]:
    root = summaries_root or summary_search.find_summaries_root()
    if not root:
        return None
    return Path(root) / "embeddings"


def load_config(summaries_root: Optional[str] = None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    root = summaries_root or summary_search.find_summaries_root()
    if root:
        path = Path(root) / "embeddings_config.json"
        if path.is_file():
            try:
                user = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(user, dict):
                    cfg.update({k: v for k, v in user.items() if not str(k).startswith("_")})
            except Exception:
                pass
    # env overrides
    if os.environ.get("EMBED_BACKEND"):
        cfg["backend"] = os.environ["EMBED_BACKEND"]
    if os.environ.get("EMBED_MODEL"):
        cfg["model"] = os.environ["EMBED_MODEL"]
    if os.environ.get("OPENAI_BASE_URL"):
        cfg["openai_base_url"] = os.environ["OPENAI_BASE_URL"]
    return cfg


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


def _l2_normalize(vec: List[float]) -> List[float]:
    s = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / s for x in vec]


def embed_hashing(text: str, dim: int = DEFAULT_DIM) -> List[float]:
    """Feature-hash bag-of-tokens (no external deps)."""
    vec = [0.0] * dim
    for tok in _tokenize(text):
        h = hashlib.sha1(tok.encode("utf-8")).digest()
        idx = struct.unpack(">I", h[:4])[0] % dim
        sign = 1.0 if (h[4] & 1) == 0 else -1.0
        # mild TF boost via log count — accumulate
        vec[idx] += sign
    return _l2_normalize(vec)


def embed_openai(texts: Sequence[str], cfg: dict) -> List[List[float]]:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("EMBED_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY (or EMBED_API_KEY) required for openai backend")
    base = cfg.get("openai_base_url", "https://api.openai.com/v1").rstrip("/")
    model = cfg.get("model") or "text-embedding-3-small"
    url = f"{base}/embeddings"
    body = json.dumps({"model": model, "input": list(texts)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    data = sorted(payload.get("data") or [], key=lambda d: d.get("index", 0))
    out = []
    for item in data:
        emb = item.get("embedding") or []
        out.append(_l2_normalize([float(x) for x in emb]))
    if len(out) != len(texts):
        raise RuntimeError(f"openai embeddings count mismatch: got {len(out)} want {len(texts)}")
    return out


def embed_ollama(texts: Sequence[str], cfg: dict) -> List[List[float]]:
    base = cfg.get("ollama_base_url", "http://127.0.0.1:11434").rstrip("/")
    model = cfg.get("ollama_model") or cfg.get("model") or "nomic-embed-text"
    out = []
    for text in texts:
        body = json.dumps({"model": model, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        emb = payload.get("embedding") or []
        out.append(_l2_normalize([float(x) for x in emb]))
    return out


def embed_st(texts: Sequence[str], cfg: dict) -> List[List[float]]:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "sentence-transformers not installed; pip install sentence-transformers"
        ) from e
    model_name = cfg.get("st_model") or "sentence-transformers/all-MiniLM-L6-v2"
    # cache model on function attr
    cache = getattr(embed_st, "_model", None)
    if cache is None or getattr(embed_st, "_name", None) != model_name:
        embed_st._model = SentenceTransformer(model_name)  # type: ignore[attr-defined]
        embed_st._name = model_name  # type: ignore[attr-defined]
    model = embed_st._model  # type: ignore[attr-defined]
    vectors = model.encode(list(texts), normalize_embeddings=True)
    return [[float(x) for x in row] for row in vectors]


def embed_texts(texts: Sequence[str], cfg: Optional[dict] = None) -> List[List[float]]:
    cfg = cfg or load_config()
    backend = (cfg.get("backend") or "hashing").lower()
    if backend == "hashing":
        dim = int(cfg.get("dim") or DEFAULT_DIM)
        return [embed_hashing(t, dim) for t in texts]
    if backend == "openai":
        return embed_openai(texts, cfg)
    if backend == "ollama":
        return embed_ollama(texts, cfg)
    if backend in ("st", "sentence_transformers", "sentence-transformers"):
        return embed_st(texts, cfg)
    raise ValueError(f"unknown embeddings backend: {backend}")


def _doc_text(path: Path, max_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def _iter_docs(summaries_root: str, include_rollups: bool) -> List[Tuple[str, Path]]:
    root = Path(summaries_root)
    docs: List[Tuple[str, Path]] = []
    repo = root / "repo"
    if repo.is_dir():
        for p in sorted(repo.rglob("*.md")):
            rel = str(p.relative_to(root))
            docs.append((rel, p))
    if include_rollups:
        roll = root / "rollups"
        if roll.is_dir():
            for p in sorted(roll.rglob("*.md")):
                rel = str(p.relative_to(root))
                docs.append((rel, p))
    return docs


def _index_paths(edir: Path) -> Tuple[Path, Path]:
    return edir / "index.json", edir / "vectors.bin"


def _write_vectors(path: Path, vectors: List[List[float]]) -> None:
    if not vectors:
        path.write_bytes(b"")
        return
    dim = len(vectors[0])
    with path.open("wb") as f:
        f.write(struct.pack("<II", len(vectors), dim))
        for v in vectors:
            if len(v) != dim:
                raise ValueError("ragged vectors")
            f.write(struct.pack("<" + "f" * dim, *v))


def _read_vectors(path: Path) -> List[List[float]]:
    data = path.read_bytes()
    if len(data) < 8:
        return []
    n, dim = struct.unpack_from("<II", data, 0)
    out = []
    offset = 8
    row_bytes = dim * 4
    for _ in range(n):
        vals = struct.unpack_from("<" + "f" * dim, data, offset)
        out.append(list(vals))
        offset += row_bytes
    return out


def build_index(
    summaries_root: Optional[str] = None,
    cfg: Optional[dict] = None,
    force: bool = False,
) -> dict:
    """Build or refresh the embeddings index. Returns stats dict."""
    root = summaries_root or summary_search.find_summaries_root()
    if not root:
        raise RuntimeError("could not locate summaries/ directory")
    cfg = cfg or load_config(root)
    edir = Path(root) / "embeddings"
    edir.mkdir(parents=True, exist_ok=True)
    meta_path, vec_path = _index_paths(edir)

    docs = _iter_docs(root, bool(cfg.get("include_rollups", True)))
    max_chars = int(cfg.get("max_chars_per_doc") or 6000)
    items = []
    texts = []
    for rel, path in docs:
        text = _doc_text(path, max_chars)
        if not text.strip():
            continue
        sha = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()
        items.append({"rel_path": rel, "sha1": sha, "chars": len(text)})
        texts.append(text)

    # Incremental: reuse vectors for unchanged sha1 when backend/dim match
    old_meta = {}
    old_vectors: List[List[float]] = []
    if meta_path.is_file() and vec_path.is_file() and not force:
        try:
            old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            old_vectors = _read_vectors(vec_path)
        except Exception:
            old_meta = {}
            old_vectors = []

    old_by_rel = {}
    if (
        old_meta.get("backend") == cfg.get("backend")
        and old_meta.get("model") == cfg.get("model")
        and old_meta.get("dim") == cfg.get("dim")
        and isinstance(old_meta.get("docs"), list)
        and len(old_meta["docs"]) == len(old_vectors)
    ):
        for i, d in enumerate(old_meta["docs"]):
            old_by_rel[d.get("rel_path")] = (d.get("sha1"), old_vectors[i])

    new_vectors: List[List[float]] = []
    to_embed_idx: List[int] = []
    to_embed_texts: List[str] = []
    placeholders: List[Optional[List[float]]] = [None] * len(items)

    for i, item in enumerate(items):
        prev = old_by_rel.get(item["rel_path"])
        if prev and prev[0] == item["sha1"] and prev[1] is not None:
            placeholders[i] = prev[1]
        else:
            to_embed_idx.append(i)
            to_embed_texts.append(texts[i])

    if to_embed_texts:
        # batch embed in chunks for API backends
        batch = 32
        embedded: List[List[float]] = []
        for start in range(0, len(to_embed_texts), batch):
            chunk = to_embed_texts[start:start + batch]
            embedded.extend(embed_texts(chunk, cfg))
        for j, i in enumerate(to_embed_idx):
            placeholders[i] = embedded[j]

    for p in placeholders:
        assert p is not None
        new_vectors.append(p)

    dim = len(new_vectors[0]) if new_vectors else int(cfg.get("dim") or DEFAULT_DIM)
    meta = {
        "version": 1,
        "backend": cfg.get("backend"),
        "model": cfg.get("model"),
        "dim": dim,
        "docs": items,
        "count": len(items),
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    _write_vectors(vec_path, new_vectors)
    return {
        "summaries_root": root,
        "count": len(items),
        "embedded_now": len(to_embed_texts),
        "reused": len(items) - len(to_embed_texts),
        "backend": cfg.get("backend"),
        "dim": dim,
        "index": str(meta_path),
    }


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(a[i] * b[i] for i in range(n))


def search_semantic(
    query: str,
    summaries_root: Optional[str] = None,
    max_results: int = 20,
    dir_filter: Optional[str] = None,
    cfg: Optional[dict] = None,
) -> List[Dict]:
    root = summaries_root or summary_search.find_summaries_root()
    if not root:
        return []
    cfg = cfg or load_config(root)
    edir = Path(root) / "embeddings"
    meta_path, vec_path = _index_paths(edir)
    if not meta_path.is_file() or not vec_path.is_file():
        return [{"error": "no embeddings index — run embeddings_index.py build"}]

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    vectors = _read_vectors(vec_path)
    docs = meta.get("docs") or []
    if len(docs) != len(vectors):
        return [{"error": "embeddings index corrupt (docs/vectors length mismatch); rebuild"}]

    # align config backend for query embedding
    qcfg = dict(cfg)
    qcfg["backend"] = meta.get("backend") or qcfg.get("backend")
    qcfg["model"] = meta.get("model") or qcfg.get("model")
    if meta.get("dim"):
        qcfg["dim"] = meta["dim"]

    qvec = embed_texts([query], qcfg)[0]
    scored = []
    df = (dir_filter or "").replace("\\", "/").rstrip("/")
    for doc, vec in zip(docs, vectors):
        rel = (doc.get("rel_path") or "").replace("\\", "/")
        if df:
            tail = rel[5:] if rel.startswith("repo/") else rel
            if not (
                tail == df
                or tail.startswith(df + "/")
                or rel.startswith(df + "/")
                or rel == df
            ):
                continue
        score = cosine(qvec, vec)
        scored.append((score, doc, rel))

    scored.sort(key=lambda x: -x[0])
    results = []
    for score, doc, rel in scored[:max_results]:
        path = Path(root) / rel
        snippet = ""
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                snippet = " ".join(text.split())[:220]
            except Exception:
                pass
        results.append({
            "rel_path": rel,
            "path": str(path),
            "score": round(float(score), 4),
            "snippet": snippet,
            "is_rollup": "rollups/" in rel.replace("\\", "/"),
            "sha1": doc.get("sha1"),
        })
    return results


def render_semantic_results(results: List[Dict]) -> str:
    if not results:
        return "(no semantic matches — build the index or broaden the query)"
    if "error" in results[0]:
        return results[0]["error"]
    lines = []
    for r in results:
        marker = "📁 " if r.get("is_rollup") else "   "
        lines.append(f"{marker}{r['rel_path']}  (cos={r['score']})")
        if r.get("snippet"):
            lines.append(f"    {r['snippet']}")
        lines.append("")
    return "\n".join(lines).rstrip()
