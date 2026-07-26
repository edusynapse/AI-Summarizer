"""Layer 3 — log and diff minifiers for token-cheap agent intake.

Functions return (minified_text, stats_dict).
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

# ── Diff minifier ───────────────────────────────────────────────────────────

_RE_INDEX = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+")
_RE_GIT_HEADER = re.compile(r"^diff --git ")
_RE_BINARY = re.compile(r"^Binary files .* differ")
_RE_SIMILARITY = re.compile(r"^similarity index ")
_RE_RENAME = re.compile(r"^rename (from|to) ")
_RE_NEW_FILE = re.compile(r"^new file mode ")
_RE_DEL_FILE = re.compile(r"^deleted file mode ")
_RE_OLD_MODE = re.compile(r"^(old|new) mode ")
_RE_HUNK = re.compile(r"^@@ ")


def minify_diff(
    text: str,
    *,
    max_hunk_lines: int = 80,
    max_file_lines: int = 200,
    max_total_lines: int = 800,
    collapse_context: bool = True,
    keep_file_headers: bool = True,
) -> Tuple[str, Dict]:
    """Compress unified diffs: drop noise headers, cap hunks, summarize overflow."""
    if not text:
        return "", {"input_lines": 0, "output_lines": 0, "files": 0, "truncated_hunks": 0}

    lines = text.splitlines()
    out: List[str] = []
    stats = {
        "input_lines": len(lines),
        "output_lines": 0,
        "files": 0,
        "truncated_hunks": 0,
        "skipped_noise": 0,
        "binary_files": 0,
    }

    file_line_count = 0
    hunk_line_count = 0
    in_hunk = False
    file_truncated = False
    total_cap = False

    def emit(line: str) -> bool:
        nonlocal total_cap
        if len(out) >= max_total_lines:
            if not total_cap:
                out.append("… [diff truncated: max_total_lines]")
                total_cap = True
            return False
        out.append(line)
        return True

    i = 0
    while i < len(lines):
        line = lines[i]

        # Noise lines
        if (
            _RE_INDEX.match(line)
            or _RE_SIMILARITY.match(line)
            or _RE_OLD_MODE.match(line)
            or _RE_NEW_FILE.match(line)
            or _RE_DEL_FILE.match(line)
            or line.startswith("diff --git ")
        ):
            stats["skipped_noise"] += 1
            # Keep a slim file banner from --- / +++ instead
            i += 1
            continue

        if _RE_BINARY.match(line):
            stats["binary_files"] += 1
            emit(f"[binary] {line}")
            in_hunk = False
            i += 1
            continue

        if line.startswith("--- ") or line.startswith("+++ "):
            if keep_file_headers:
                # new file region
                if line.startswith("--- "):
                    stats["files"] += 1
                    file_line_count = 0
                    file_truncated = False
                if not emit(line):
                    break
            i += 1
            continue

        if _RE_RENAME.match(line):
            emit(line)
            i += 1
            continue

        if _RE_HUNK.match(line):
            in_hunk = True
            hunk_line_count = 0
            if file_truncated:
                i += 1
                continue
            if not emit(line):
                break
            i += 1
            continue

        # Content lines
        if file_truncated or total_cap:
            i += 1
            continue

        if file_line_count >= max_file_lines:
            if not file_truncated:
                emit("… [file truncated: max_file_lines]")
                file_truncated = True
                stats["truncated_hunks"] += 1
            i += 1
            continue

        if in_hunk and hunk_line_count >= max_hunk_lines:
            # skip rest of hunk until next hunk/file
            if hunk_line_count == max_hunk_lines:
                emit("… [hunk truncated: max_hunk_lines]")
                stats["truncated_hunks"] += 1
                hunk_line_count += 1
            # skip until next header-ish
            while i < len(lines):
                nxt = lines[i]
                if (
                    _RE_HUNK.match(nxt)
                    or nxt.startswith("--- ")
                    or nxt.startswith("diff --git ")
                    or _RE_BINARY.match(nxt)
                ):
                    break
                i += 1
            in_hunk = False
            continue

        # Optionally drop pure context lines deep in large hunks
        if collapse_context and in_hunk and line.startswith(" ") and hunk_line_count > 12:
            # keep every 3rd context line
            if hunk_line_count % 3 != 0:
                hunk_line_count += 1
                file_line_count += 1
                i += 1
                continue

        if not emit(line):
            break
        if in_hunk:
            hunk_line_count += 1
        file_line_count += 1
        i += 1

    stats["output_lines"] = len(out)
    return "\n".join(out) + ("\n" if out else ""), stats


# ── Log minifier ────────────────────────────────────────────────────────────

_RE_TS = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\s*)"
)
_RE_TS_BRACKET = re.compile(r"^\[\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[^\]]*\]\s*")
_RE_LEVEL = re.compile(r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|TRACE|FATAL)\b")
_RE_HEX_ID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_RE_LONG_HEX = re.compile(r"\b[0-9a-f]{32,}\b", re.I)
_RE_REQUEST_ID = re.compile(r"\b(request[_-]?id|trace[_-]?id|correlation[_-]?id)=([^\s,]+)", re.I)

DEFAULT_DROP_LEVELS = {"DEBUG", "TRACE"}
DEFAULT_NOISE_SUBSTR = (
    "healthcheck",
    "health check",
    "/health",
    "favicon.ico",
    "metrics scrape",
)


def minify_log(
    text: str,
    *,
    max_lines: int = 400,
    max_line_chars: int = 240,
    collapse_repeats: bool = True,
    strip_timestamps: bool = True,
    drop_levels: Optional[Iterable[str]] = None,
    drop_noise: bool = True,
    keep_tail: bool = True,
) -> Tuple[str, Dict]:
    """Compress logs: strip noise, collapse runs, cap length."""
    if not text:
        return "", {"input_lines": 0, "output_lines": 0}

    drop = {x.upper() for x in (drop_levels if drop_levels is not None else DEFAULT_DROP_LEVELS)}
    raw_lines = text.splitlines()
    stats = {
        "input_lines": len(raw_lines),
        "output_lines": 0,
        "dropped_level": 0,
        "dropped_noise": 0,
        "collapsed_runs": 0,
        "truncated_lines": 0,
        "omitted_head": 0,
    }

    normalized: List[str] = []
    for line in raw_lines:
        orig = line
        if strip_timestamps:
            line = _RE_TS.sub("", line)
            line = _RE_TS_BRACKET.sub("", line)
        # redact high-cardinality ids (keep structure)
        line = _RE_HEX_ID.sub("<uuid>", line)
        line = _RE_LONG_HEX.sub("<hex>", line)
        line = _RE_REQUEST_ID.sub(lambda m: f"{m.group(1)}=<id>", line)

        mlevel = _RE_LEVEL.search(orig) or _RE_LEVEL.search(line)
        if mlevel and mlevel.group(1).upper() in drop:
            stats["dropped_level"] += 1
            continue

        if drop_noise:
            low = line.lower()
            if any(n in low for n in DEFAULT_NOISE_SUBSTR):
                stats["dropped_noise"] += 1
                continue

        if len(line) > max_line_chars:
            line = line[: max_line_chars - 1] + "…"
            stats["truncated_lines"] += 1

        line = line.rstrip()
        if not line:
            continue
        normalized.append(line)

    # Collapse consecutive identical lines
    collapsed: List[str] = []
    if collapse_repeats:
        i = 0
        while i < len(normalized):
            line = normalized[i]
            j = i + 1
            while j < len(normalized) and normalized[j] == line:
                j += 1
            run = j - i
            if run > 1:
                collapsed.append(f"{line}  ×{run}")
                stats["collapsed_runs"] += run - 1
            else:
                collapsed.append(line)
            i = j
    else:
        collapsed = normalized

    # Keep tail if over max_lines (logs are usually end-relevant)
    if len(collapsed) > max_lines:
        omit = len(collapsed) - max_lines
        stats["omitted_head"] = omit
        if keep_tail:
            collapsed = [f"… [{omit} earlier lines omitted]"] + collapsed[-max_lines:]
        else:
            collapsed = collapsed[:max_lines] + [f"… [{omit} later lines omitted]"]

    stats["output_lines"] = len(collapsed)
    return "\n".join(collapsed) + ("\n" if collapsed else ""), stats


def format_stats(kind: str, stats: Dict) -> str:
    if kind == "diff":
        return (
            f"(minify diff: in={stats.get('input_lines')} out={stats.get('output_lines')} "
            f"files≈{stats.get('files')} trunc_hunks={stats.get('truncated_hunks')} "
            f"binary={stats.get('binary_files')} noise_skip={stats.get('skipped_noise')})"
        )
    return (
        f"(minify log: in={stats.get('input_lines')} out={stats.get('output_lines')} "
        f"drop_level={stats.get('dropped_level')} drop_noise={stats.get('dropped_noise')} "
        f"collapse={stats.get('collapsed_runs')} omit_head={stats.get('omitted_head')})"
    )
