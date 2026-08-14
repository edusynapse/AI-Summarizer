#!/usr/bin/env python3
"""Directory rollup summarizer over existing per-file summaries.

Reads `rollups_config.json`, collects existing markdown summaries from
`summaries/repo/<dir>/**/*.md`, hashes the input summary content, compares
against `rollups_manifest.json`, and generates coarse directory rollups via
the configured LLM CLI.

Rollups are routing documents: they help agents choose which per-file summaries
or source files to inspect next. They never read source files directly.

Run:
  python3 rollup_summarizer.py --dry-run
  python3 rollup_summarizer.py
  python3 rollup_summarizer.py --dir lib/helpers
  python3 rollup_summarizer.py --dir src/api --model "Gemini 3.7 Flash (Low)"
  python3 rollup_summarizer.py --force --dir routes
  # Project ref: --dir libadmin  (or models, lib/widgets, …)
"""
import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SUMMARIES_REPO = os.path.join(HERE, "repo")
ROLLUPS_DIR = os.path.join(HERE, "rollups")
ROLLUPS_CONFIG_PATH = os.path.join(HERE, "rollups_config.json")
ROLLUPS_MANIFEST_PATH = os.path.join(HERE, "rollups_manifest.json")
ROLLUP_PROMPT_PATH = os.path.join(HERE, "rollup_prompt_template.txt")

sys.path.insert(0, HERE)
from summarizer import call_llm, load_config, DEFAULT_PROVIDER, DEFAULT_AGY_MODEL  # noqa: E402


def load_json(path, fallback):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return fallback


def save_json(path, body):
    with open(path, "w") as f:
        json.dump(body, f, indent=2, sort_keys=True)


def read_text(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def normalize_dir(d):
    return d.strip().strip("/").replace(os.sep, "/")


def rollup_path(dir_rel):
    return os.path.join(ROLLUPS_DIR, dir_rel + ".md")


def summary_source_path(summary_rel):
    if not summary_rel.endswith(".md"):
        return summary_rel
    return summary_rel[:-3]


def matches_any(s, patterns):
    return any(fnmatch.fnmatch(s, p) for p in patterns)


def collect_summary_files(dir_rel, exclude_patterns):
    base = os.path.join(SUMMARIES_REPO, dir_rel)
    if not os.path.isdir(base):
        return []
    out = []
    for dirpath, _, filenames in os.walk(base):
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            full = os.path.join(dirpath, fn)
            rel_summary = os.path.relpath(full, SUMMARIES_REPO).replace(os.sep, "/")
            rel_source = summary_source_path(rel_summary)
            if matches_any(rel_summary, exclude_patterns) or matches_any(rel_source, exclude_patterns):
                continue
            out.append((rel_source, full))
    out.sort(key=lambda x: x[0])
    return out


def input_digest(summary_files, prompt_text, opts):
    h = hashlib.sha1()
    h.update(prompt_text.encode("utf-8"))
    h.update(json.dumps(opts, sort_keys=True).encode("utf-8"))
    for rel, full in summary_files:
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(read_text(full).encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()


def build_input(summary_files, max_bytes):
    parts = []
    used = 0
    truncated = 0
    for rel, full in summary_files:
        body = read_text(full).strip()
        block = f"\n\n===== {rel} =====\n{body}\n"
        size = len(block.encode("utf-8"))
        if used + size > max_bytes:
            truncated += 1
            continue
        parts.append(block)
        used += size
    return "".join(parts).strip(), truncated


def build_prompt(template, dir_rel, summary_files, summary_text, cfg):
    return template.format(
        dir=dir_rel,
        count=len(summary_files),
        max_words=int(cfg.get("max_words", 700)),
        max_files=int(cfg.get("max_important_files", 14)),
        summaries=summary_text,
    )


def write_rollup(dir_rel, body):
    out = rollup_path(dir_rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(body.rstrip() + "\n")


def plan_dirs(args, cfg):
    dirs = []
    if args.dir:
        dirs.extend(args.dir)
    else:
        dirs.extend(cfg.get("include_dirs", []))
    seen = set()
    out = []
    for d in dirs:
        norm = normalize_dir(d)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="regenerate even when inputs are unchanged")
    ap.add_argument("--dir", action="append", help="directory to roll up; may be repeated")
    ap.add_argument("--limit", type=int, default=0, help="cap rollups processed this run")
    ap.add_argument("--provider", choices=["agy"], help="LLM provider (agy only)")
    ap.add_argument("--model", help="override summaries/config.json model")
    ap.add_argument("--timeout", type=int, help="override provider timeout in seconds")
    args = ap.parse_args()

    cfg = load_json(ROLLUPS_CONFIG_PATH, {"include_dirs": []})
    llm_cfg = load_config()
    manifest = load_json(ROLLUPS_MANIFEST_PATH, {"rollups": {}})
    template = read_text(ROLLUP_PROMPT_PATH)
    dirs = plan_dirs(args, cfg)

    if not dirs:
        print("rollups: no dirs configured; edit rollups_config.json or pass --dir")
        return

    exclude = cfg.get("exclude_summary_files", [])
    max_bytes = int(cfg.get("max_input_bytes", 120000))
    digest_opts = {
        "max_input_bytes": max_bytes,
        "max_words": int(cfg.get("max_words", 700)),
        "max_important_files": int(cfg.get("max_important_files", 14)),
    }

    planned = []
    skipped = []
    missing = []
    for dir_rel in dirs:
        summary_files = collect_summary_files(dir_rel, exclude)
        if not summary_files:
            missing.append(dir_rel)
            continue
        digest = input_digest(summary_files, template, digest_opts)
        prev = manifest.get("rollups", {}).get(dir_rel, {})
        changed = prev.get("digest") != digest
        out_exists = os.path.exists(rollup_path(dir_rel))
        if args.force or changed or not out_exists:
            planned.append((dir_rel, summary_files, digest, changed, out_exists))
        else:
            skipped.append(dir_rel)

    cap = args.limit or int(cfg.get("max_rollups_per_run") or 0)
    if cap and len(planned) > cap:
        planned = planned[:cap]

    print(
        f"rollups: configured={len(dirs)} planned={len(planned)} "
        f"skipped={len(skipped)} missing={len(missing)}"
    )
    if missing:
        for d in missing[:20]:
            print(f"  ! no summaries found: {d}")
    if args.dry_run:
        for dir_rel, summary_files, _, changed, out_exists in planned:
            reason = "force" if args.force else "changed" if changed else "missing-output" if not out_exists else "planned"
            print(f"  ~ {dir_rel} ({len(summary_files)} files, {reason})")
        for d in skipped[:20]:
            print(f"  = {d}")
        return

    if not planned:
        print("  nothing to roll up")
        return

    provider = args.provider or llm_cfg.get("provider", DEFAULT_PROVIDER)
    model = args.model or llm_cfg.get("model")
    if not model:
        model = DEFAULT_AGY_MODEL
    timeout_key = "agy_timeout_sec"
    timeout = args.timeout or llm_cfg.get(timeout_key, llm_cfg.get("timeout_sec", 120))
    print(f"  provider={provider} model=\"{model}\" timeout={timeout}s")

    ok, fail = 0, 0
    for i, (dir_rel, summary_files, digest, _, _) in enumerate(planned, 1):
        print(f"  [{i}/{len(planned)}] rollup: {dir_rel} ({len(summary_files)} summaries)", flush=True)
        try:
            summary_text, truncated = build_input(summary_files, max_bytes)
            if truncated:
                print(f"    input capped: skipped {truncated} summaries after {max_bytes} bytes")
            prompt = build_prompt(template, dir_rel, summary_files, summary_text, cfg)
            body = call_llm(prompt, provider, model, timeout)
            write_rollup(dir_rel, body)
            manifest.setdefault("rollups", {})[dir_rel] = {
                "digest": digest,
                "summary_count": len(summary_files),
                "output": os.path.relpath(rollup_path(dir_rel), HERE).replace(os.sep, "/"),
            }
            ok += 1
            save_json(ROLLUPS_MANIFEST_PATH, manifest)
        except subprocess.TimeoutExpired:
            print(f"    TIMEOUT after {timeout}s")
            fail += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            fail += 1

    save_json(ROLLUPS_MANIFEST_PATH, manifest)
    print(f"done: ok={ok} fail={fail} (re-run to retry failures)")


if __name__ == "__main__":
    main()
