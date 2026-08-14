#!/usr/bin/env python3
"""LLM-based per-file summarizer (agy CLI backend).

Walks the repo per `config.json`, hashes each tracked file, compares against
`manifest.json`, and (re)generates summaries via the configured LLM CLI.

- Added file        → generate summary, record hash
- Hash changed      → regenerate, update hash
- Deleted file      → prune summary file + empty parent dirs, drop from manifest
- Unchanged file    → skip (no API call)

Output layout mirrors source tree:
  summaries/repo/<same/relative/path>.md

Run:
  python3 summarizer.py            # full incremental update
  python3 summarizer.py --dry-run  # show plan, no API calls
  python3 summarizer.py --limit N  # cap work this run (testing)
  python3 summarizer.py --only PATTERN  # fnmatch filter on relpath
  python3 summarizer.py --dir models    # restrict to a subdirectory
"""
import os
import sys
import json
import hashlib
import subprocess
import fnmatch
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SUMMARIES_REPO = os.path.join(HERE, "repo")
MANIFEST_PATH = os.path.join(HERE, "manifest.json")
CONFIG_PATH = os.path.join(HERE, "config.json")
PROMPT_PATH = os.path.join(HERE, "prompt_template.txt")
AGY_SETTINGS_PATH = os.environ.get(
    "AGY_SETTINGS_PATH",
    os.path.expanduser("~/.gemini/antigravity-cli/settings.json"),
)
DEFAULT_PROVIDER = "agy"
DEFAULT_AGY_MODEL = "Gemini 3.7 Flash (Low)"

AGY_HEADLESS_INSTRUCTION = (
    "Do not use tools, do not write files, and do not explain. "
    "Print only the requested summary markdown to stdout."
)

LANG_BY_EXT = {
    ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js",
    ".ts": "ts", ".tsx": "ts",
    ".py": "py", ".dart": "dart", ".rs": "rust", ".go": "go", ".java": "java",
}


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH) as f:
            return json.load(f)
    return {"files": {}}


def save_manifest(m):
    with open(MANIFEST_PATH, "w") as f:
        json.dump(m, f, indent=2, sort_keys=True)


def matches_any(s, patterns):
    return any(fnmatch.fnmatch(s, p) for p in patterns)


def detect_lang(path):
    return LANG_BY_EXT.get(os.path.splitext(path)[1], "unknown")


def walk_repo(cfg):
    include_exts = set(cfg["include_extensions"])
    exclude_files = cfg.get("exclude_files", [])
    exclude_dirs = cfg.get("exclude_dirs", [])
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        rel_dir = os.path.relpath(dirpath, REPO_ROOT)
        rel_dir = "" if rel_dir == "." else rel_dir
        kept = []
        for d in dirnames:
            sub = os.path.join(rel_dir, d) if rel_dir else d
            if d in exclude_dirs or matches_any(sub, exclude_dirs) or matches_any(d, exclude_dirs):
                continue
            kept.append(d)
        dirnames[:] = kept
        for fn in filenames:
            ext = os.path.splitext(fn)[1]
            if ext not in include_exts:
                continue
            rel = os.path.join(rel_dir, fn) if rel_dir else fn
            if matches_any(rel, exclude_files) or matches_any(fn, exclude_files):
                continue
            yield rel


def file_hash(full):
    h = hashlib.sha1()
    with open(full, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def summary_path(rel):
    return os.path.join(SUMMARIES_REPO, rel + ".md")


def read_prompt_template():
    with open(PROMPT_PATH) as f:
        return f.read()


def read_agy_settings():
    with open(AGY_SETTINGS_PATH) as f:
        return json.load(f)


def write_agy_settings(settings):
    with open(AGY_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2, sort_keys=True)
        f.write("\n")


def set_agy_model(model):
    settings = read_agy_settings()
    if settings.get("model") == model:
        return None
    snapshot = {
        "had": "model" in settings,
        "previous": settings.get("model"),
    }
    settings["model"] = model
    write_agy_settings(settings)
    return snapshot


def restore_agy_model(snapshot):
    if not snapshot:
        return
    try:
        settings = read_agy_settings()
        if snapshot["had"]:
            settings["model"] = snapshot["previous"]
        else:
            settings.pop("model", None)
        write_agy_settings(settings)
    except Exception:
        pass


def call_agy(prompt, model, timeout):
    full_prompt = f"{AGY_HEADLESS_INSTRUCTION}\n\n{prompt}"
    snapshot = None
    if model:
        try:
            snapshot = set_agy_model(model)
        except Exception as e:
            raise RuntimeError(f"agy cannot set model in {AGY_SETTINGS_PATH}: {e}")
    try:
        res = subprocess.run(
            ["agy"],
            input=full_prompt,
            capture_output=True, text=True, timeout=timeout,
        )
    finally:
        restore_agy_model(snapshot)
    if res.returncode != 0:
        raise RuntimeError(f"agy exit={res.returncode}: {res.stderr[:400].strip()}")
    out = (res.stdout or "").strip()
    if not out:
        raise RuntimeError("agy returned empty output")
    return out


def call_llm(prompt, provider, model, timeout):
    if provider == "agy":
        return call_agy(prompt, model, timeout)
    raise ValueError(f"unsupported provider: {provider}")


def build_prompt(template, rel, content_str):
    lang = detect_lang(rel)
    loc = content_str.count("\n") + 1
    return template.format(path=rel, lang=lang, loc=loc, content=content_str)


def read_file_bounded(full, max_bytes):
    with open(full, "rb") as f:
        raw = f.read(max_bytes + 1)
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    text = raw.decode("utf-8", errors="ignore")
    if truncated:
        text += f"\n\n[TRUNCATED — original file exceeded {max_bytes} bytes]"
    return text


def write_summary(rel, body):
    out = summary_path(rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(body.rstrip() + "\n")
    # Resolve NAVIGATION lines + inject ADJACENT (this repo only; no LLM)
    try:
        skill = os.path.abspath(os.path.join(HERE, ".."))
        sys.path.insert(0, skill)
        from lib import summary_postprocess  # noqa: WPS433
        from pathlib import Path
        summary_postprocess.postprocess_summary_file(
            Path(out),
            Path(REPO_ROOT) / rel,
            rel,
            Path(skill),
            inject_adjacent=True,
        )
    except Exception as e:
        print(f"    postprocess skip: {e}", flush=True)


def prune_summary(rel):
    out = summary_path(rel)
    if os.path.exists(out):
        os.remove(out)
    d = os.path.dirname(out)
    while d and os.path.abspath(d).startswith(os.path.abspath(SUMMARIES_REPO) + os.sep):
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            d = os.path.dirname(d)
        else:
            break


def plan(cfg, manifest, only=None, subdir=None):
    current, todo_new, todo_changed = {}, [], []
    subdir_norm = None
    if subdir:
        subdir_norm = subdir.strip("/").replace(os.sep, "/")
    for rel in walk_repo(cfg):
        rel_posix = rel.replace(os.sep, "/")
        if subdir_norm and not (rel_posix == subdir_norm or rel_posix.startswith(subdir_norm + "/")):
            continue
        if only and not fnmatch.fnmatch(rel, only):
            continue
        full = os.path.join(REPO_ROOT, rel)
        h = file_hash(full)
        current[rel] = h
        prev = manifest["files"].get(rel)
        if prev is None:
            todo_new.append(rel)
        elif prev != h:
            todo_changed.append(rel)
    # Suppress deletion pruning when scoped — files outside the scope aren't
    # in `current` but shouldn't be treated as deleted.
    if only or subdir_norm:
        deleted = []
    else:
        deleted = [r for r in manifest["files"] if r not in current]
    return current, todo_new, todo_changed, deleted


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="cap files processed this run")
    ap.add_argument("--only", help="fnmatch pattern on relative path")
    ap.add_argument("--dir", help="restrict to one subdirectory (e.g. models, lib/crossword)")
    ap.add_argument("--provider", choices=["agy"], help="LLM provider (agy only)")
    ap.add_argument("--model", help="override config model")
    ap.add_argument("--timeout", type=int, help="override provider timeout in seconds")
    args = ap.parse_args()

    cfg = load_config()
    manifest = load_manifest()
    current, todo_new, todo_changed, deleted = plan(cfg, manifest, only=args.only, subdir=args.dir)

    print(f"summarizer: tracked={len(current)} new={len(todo_new)} changed={len(todo_changed)} deleted={len(deleted)}")

    if args.dry_run:
        for r in todo_new[:20]:
            print(f"  + {r}")
        if len(todo_new) > 20:
            print(f"  + ... and {len(todo_new) - 20} more new")
        for r in todo_changed[:20]:
            print(f"  ~ {r}")
        if len(todo_changed) > 20:
            print(f"  ~ ... and {len(todo_changed) - 20} more changed")
        for r in deleted[:20]:
            print(f"  - {r}")
        if len(deleted) > 20:
            print(f"  - ... and {len(deleted) - 20} more deleted")
        return

    for rel in deleted:
        prune_summary(rel)
        manifest["files"].pop(rel, None)
    if deleted:
        print(f"  pruned {len(deleted)} stale summaries")
        save_manifest(manifest)

    work = [(r, "new") for r in todo_new] + [(r, "changed") for r in todo_changed]
    cap = args.limit or cfg.get("max_files_per_run") or 0
    if cap and len(work) > cap:
        print(f"  capping work at {cap} files (config max_files_per_run / --limit)")
        work = work[:cap]

    if not work:
        # still update manifest to refresh hashes (e.g. after restoring a file)
        manifest["files"] = {**manifest["files"], **{r: h for r, h in current.items()}}
        save_manifest(manifest)
        print("  nothing to summarize")
        return

    template = read_prompt_template()
    provider = args.provider or cfg.get("provider", DEFAULT_PROVIDER)
    model = args.model or cfg.get("model")
    if not model:
        model = DEFAULT_AGY_MODEL
    timeout_key = "agy_timeout_sec"
    timeout = args.timeout or cfg.get(timeout_key, cfg.get("timeout_sec", 120))
    max_bytes = cfg.get("max_input_bytes", 60000)
    print(f"  provider={provider} model=\"{model}\" timeout={timeout}s")
    ok, fail = 0, 0
    for i, (rel, why) in enumerate(work, 1):
        full = os.path.join(REPO_ROOT, rel)
        print(f"  [{i}/{len(work)}] {why}: {rel}", flush=True)
        try:
            content = read_file_bounded(full, max_bytes)
            prompt = build_prompt(template, rel, content)
            body = call_llm(prompt, provider, model, timeout)
            write_summary(rel, body)
            manifest["files"][rel] = current[rel]
            ok += 1
            if ok % 10 == 0:
                save_manifest(manifest)
        except subprocess.TimeoutExpired:
            print(f"    TIMEOUT after {timeout}s")
            fail += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            fail += 1

    save_manifest(manifest)
    print(f"done: ok={ok} fail={fail} (re-run to retry failures)")


if __name__ == "__main__":
    main()
