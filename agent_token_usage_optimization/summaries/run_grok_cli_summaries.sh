#!/usr/bin/env bash
# Incremental file summaries via bash `grok` CLI (headless, tool-disabled).
#
# Proven path (no spawn_subagent, no AGY settings race, parallel-safe):
#   - parent builds prompt (template + source)
#   - `grok --prompt-file ... --tools "" --max-turns 3 ...` prints markdown
#   - parent writes summaries/repo/<path>.md and merges SHA-1 into manifest.json
#
# Usage (from target repo root, after install):
#   # dry-run work list, then summarize all new+changed:
#   bash skills/agent_token_usage_optimization/summaries/run_grok_cli_summaries.sh
#
#   # options via env:
#   PARALLEL=6 MODEL=grok-4.5 MAX_TURNS=3 \
#     bash skills/agent_token_usage_optimization/summaries/run_grok_cli_summaries.sh
#
#   # only a pre-built work list:
#   WORK_LIST=/tmp/my_work.txt \
#     bash skills/agent_token_usage_optimization/summaries/run_grok_cli_summaries.sh
#
# Requires: grok on PATH, python3, optional GNU parallel (else xargs -P).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# skills/agent_token_usage_optimization/summaries → repo root is ../../..
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

SUM_DIR="skills/agent_token_usage_optimization/summaries"
TEMPLATE="$SUM_DIR/prompt_template.txt"
MANIFEST="$SUM_DIR/manifest.json"
REPO_SUM="$SUM_DIR/repo"
SUMMARIZER_PY="$SUM_DIR/summarizer.py"

# Per-run scratch (repo-scoped so parallel runs on different repos don't collide)
REPO_SLUG="$(basename "$REPO_ROOT" | tr -c 'A-Za-z0-9._-' '_')"
SCRATCH="${SCRATCH:-/tmp/ai_summarizer_grok_${REPO_SLUG}_$$}"
WORK_LIST="${WORK_LIST:-$SCRATCH/work.txt}"
DELETED_LIST="${DELETED_LIST:-$SCRATCH/deleted.txt}"
HASHES_JSON="${HASHES_JSON:-$SCRATCH/hashes.json}"
RESULTS_DIR="${RESULTS_DIR:-$SCRATCH/results}"
LOG="${LOG:-$SCRATCH/batch.log}"

PARALLEL="${PARALLEL:-4}"
# Default: whatever `grok models` lists. Override with MODEL=...
MODEL="${MODEL:-grok-4.5}"
MAX_INPUT_BYTES="${MAX_INPUT_BYTES:-500000}"
GROK_TIMEOUT="${GROK_TIMEOUT:-180}"
MAX_TURNS="${MAX_TURNS:-3}"
AUTO_PLAN="${AUTO_PLAN:-1}"   # 1 = build work list from summarizer.plan if WORK_LIST not pre-seeded

mkdir -p "$RESULTS_DIR" "$REPO_SUM" "$SCRATCH"
: >"$LOG"

SYS_PROMPT='You are a single-file code summarizer for an automated code-search index. Do not use tools. Do not write files. Output ONLY the summary markdown matching the template sections. Under 250 words. No preamble. No whole-response code fences.'

DISALLOWED='Agent,run_terminal_cmd,search_replace,write,read_file,list_dir,grep,web_search,web_fetch,open_page,spawn_subagent'

# ── build work list from summarizer.plan (unless caller supplied WORK_LIST) ──
if [[ "$AUTO_PLAN" == "1" ]] && [[ ! -s "$WORK_LIST" || "${FORCE_PLAN:-0}" == "1" ]]; then
  python3 - "$SUMMARIZER_PY" "$WORK_LIST" "$DELETED_LIST" "$HASHES_JSON" <<'PY'
import importlib.util, json, pathlib, sys
sum_py, work_p, del_p, hash_p = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("summarizer", sum_py)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
cfg = mod.load_config()
manifest = mod.load_manifest()
current, todo_new, todo_changed, deleted = mod.plan(cfg, manifest)
work = todo_new + todo_changed
pathlib.Path(work_p).write_text("\n".join(work) + ("\n" if work else ""))
pathlib.Path(del_p).write_text("\n".join(deleted) + ("\n" if deleted else ""))
pathlib.Path(hash_p).write_text(json.dumps(current))
print(
    f"plan: new={len(todo_new)} changed={len(todo_changed)} "
    f"deleted={len(deleted)} work={len(work)}",
    flush=True,
)
PY
fi

if [[ ! -s "$WORK_LIST" ]]; then
  # still prune deletes if any
  if [[ -s "$DELETED_LIST" ]]; then
    echo "no new/changed files; will prune only" | tee -a "$LOG"
  else
    echo "nothing to do (empty work list)" | tee -a "$LOG"
    exit 0
  fi
fi

summarize_one() {
  local rel="$1"
  local src="$REPO_ROOT/$rel"
  local out="$REPO_SUM/${rel}.md"
  local safe="${rel//\//_}"
  local prompt="$SCRATCH/prompt_${safe}.txt"
  local raw="$SCRATCH/raw_${safe}.txt"
  local err="$SCRATCH/err_${safe}.txt"
  local res_file="$RESULTS_DIR/${rel//\//__}.json"

  if [[ ! -f "$src" ]]; then
    printf '%s\n' "{\"rel\":$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$rel"),\"ok\":false,\"error\":\"missing source\"}" >"$res_file"
    echo "FAIL missing $rel" | tee -a "$LOG"
    return 0
  fi

  python3 - "$src" "$TEMPLATE" "$rel" "$prompt" "$MAX_INPUT_BYTES" <<'PY'
import sys, pathlib
src_p, tmpl_p, rel, out_p, max_b = sys.argv[1:6]
max_b = int(max_b)
src = pathlib.Path(src_p).read_text(errors="replace")
tmpl = pathlib.Path(tmpl_p).read_text()
if len(src.encode("utf-8", errors="replace")) > max_b:
    b = src.encode("utf-8", errors="replace")[:max_b]
    src = b.decode("utf-8", errors="ignore") + "\n...[truncated]...\n"
prompt = f"""Follow the template rules exactly. Print ONLY the summary markdown.

=== TEMPLATE ===
{tmpl}

=== PATH ===
{rel}

=== SOURCE ===
{src}
"""
pathlib.Path(out_p).write_text(prompt)
PY

  set +e
  timeout "$GROK_TIMEOUT" grok \
    --prompt-file "$prompt" \
    --model "$MODEL" \
    --output-format plain \
    --always-approve \
    --permission-mode bypassPermissions \
    --no-memory \
    --no-plan \
    --no-subagents \
    --no-alt-screen \
    --max-turns "$MAX_TURNS" \
    --verbatim \
    --system-prompt-override "$SYS_PROMPT" \
    --tools "" \
    --disallowed-tools "$DISALLOWED" \
    --cwd /tmp \
    --disable-web-search \
    >"$raw" 2>"$err"
  local ec=$?
  set -e

  rm -f "$prompt"

  if [[ $ec -ne 0 ]]; then
    python3 - "$rel" "$err" "$res_file" "$ec" <<'PY'
import json, pathlib, sys
rel, err_p, res_p, ec = sys.argv[1:5]
stderr = pathlib.Path(err_p).read_text(errors="replace")[:500] if pathlib.Path(err_p).exists() else ""
pathlib.Path(res_p).write_text(json.dumps({
    "rel": rel, "ok": False, "error": f"grok exit {ec}", "stderr": stderr,
}))
PY
    echo "FAIL grok $rel exit=$ec" | tee -a "$LOG"
    return 0
  fi

  python3 - "$raw" "$out" "$src" "$rel" "$res_file" <<'PY'
import sys, re, hashlib, json, pathlib
raw_p, out_p, src_p, rel, res_p = sys.argv[1:6]
text = pathlib.Path(raw_p).read_text(errors="replace").strip()
if text.startswith("```"):
    text = re.sub(r"^```[a-zA-Z0-9_-]*\r?\n?", "", text)
    text = re.sub(r"```\s*$", "", text).strip()
idx = text.find("## PURPOSE")
if idx >= 0:
    text = text[idx:]
if not text.strip().startswith("## PURPOSE"):
    pathlib.Path(res_p).write_text(json.dumps({
        "rel": rel, "ok": False, "error": "bad summary shape", "preview": text[:300],
    }))
    raise SystemExit(0)
out = pathlib.Path(out_p)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(text.rstrip() + "\n")
h = hashlib.sha1(pathlib.Path(src_p).read_bytes()).hexdigest()
pathlib.Path(res_p).write_text(json.dumps({
    "rel": rel, "ok": True, "hash": h, "bytes": len(text),
}))
print(f"OK {rel} {h}", flush=True)
PY
  if [[ $? -ne 0 ]]; then
    echo "FAIL parse $rel" | tee -a "$LOG"
  else
    echo "OK $rel" | tee -a "$LOG"
  fi
  rm -f "$raw" "$err"
}

export -f summarize_one
export REPO_ROOT SUM_DIR TEMPLATE REPO_SUM RESULTS_DIR LOG MODEL MAX_INPUT_BYTES GROK_TIMEOUT MAX_TURNS SYS_PROMPT DISALLOWED SCRATCH

# 1) prune deleted
if [[ -s "$DELETED_LIST" ]]; then
  while IFS= read -r rel || [[ -n "$rel" ]]; do
    [[ -z "$rel" ]] && continue
    rm -f "$REPO_SUM/${rel}.md"
    d="$(dirname "$REPO_SUM/${rel}.md")"
    while [[ "$d" != "$REPO_SUM" && -d "$d" ]]; do
      rmdir "$d" 2>/dev/null || break
      d="$(dirname "$d")"
    done
    echo "PRUNE $rel" | tee -a "$LOG"
  done <"$DELETED_LIST"
fi

# 2) parallel summarize
work_n=0
[[ -s "$WORK_LIST" ]] && work_n="$(grep -cve '^\s*$' "$WORK_LIST" || true)"
echo "START model=$MODEL parallel=$PARALLEL max_turns=$MAX_TURNS work=$work_n repo=$REPO_ROOT scratch=$SCRATCH" | tee -a "$LOG"

if [[ "$work_n" -gt 0 ]]; then
  if command -v parallel >/dev/null 2>&1; then
    parallel -j "$PARALLEL" --halt soon,fail=0 summarize_one {} :::: "$WORK_LIST"
  else
    # xargs -P: strip blank lines
    grep -v '^\s*$' "$WORK_LIST" | xargs -P "$PARALLEL" -I{} bash -c 'summarize_one "$@"' _ {}
  fi
fi

# 3) merge manifest
python3 - "$MANIFEST" "$HASHES_JSON" "$RESULTS_DIR" "$DELETED_LIST" <<'PY'
import json, pathlib, sys
man_path, hashes_path, results_dir, deleted_path = sys.argv[1:5]
man = json.loads(pathlib.Path(man_path).read_text()) if pathlib.Path(man_path).exists() else {"files": {}}
files = man.setdefault("files", {})

ok = fail = 0
for p in pathlib.Path(results_dir).glob("*.json"):
    try:
        r = json.loads(p.read_text())
    except Exception:
        fail += 1
        continue
    if r.get("ok") and r.get("rel") and r.get("hash"):
        files[r["rel"]] = r["hash"]
        ok += 1
    else:
        fail += 1

if pathlib.Path(deleted_path).exists():
    for rel in pathlib.Path(deleted_path).read_text().splitlines():
        rel = rel.strip()
        if rel:
            files.pop(rel, None)

pathlib.Path(man_path).write_text(json.dumps(man, indent=2) + "\n")
print(f"MANIFEST updated ok={ok} fail={fail} keys={len(files)}", flush=True)
PY

echo "DONE log=$LOG" | tee -a "$LOG"
if [[ -f "$SUMMARIZER_PY" ]]; then
  python3 "$SUMMARIZER_PY" --dry-run 2>&1 | head -3 | tee -a "$LOG"
fi
