#!/usr/bin/env bash
# Incremental file summaries via the `agy` CLI, run in parallel.
#
# Why this exists: `summarizer.py --provider agy` is SERIAL and cannot be run
# N-way in parallel — it loads manifest.json at start and whole-dict overwrites
# it at the end, so concurrent processes silently drop each other's hashes.
# This runner uses the parallel-safe shape instead:
#   - each worker writes ONLY its own result JSON (rel + sha1)
#   - the parent merges every result into manifest.json ONCE at the end
#
# Model handling — deliberately different from summarizer.py:
#   summarizer.py temporarily rewrites ~/.gemini/antigravity-cli/settings.json
#   to set the model, which races with a human using `agy` on the console.
#   This script NEVER writes that file. It asserts the configured model is
#   already selected and aborts otherwise. Set the model once via agy /model.
#
# Usage (from target repo root):
#   bash skills/agent_token_usage_optimization/summaries/run_agy_cli_summaries.sh
#
#   PARALLEL=5 MODEL="Gemini 3.7 Flash (Low)" \
#     bash skills/agent_token_usage_optimization/summaries/run_agy_cli_summaries.sh
#
#   # restrict scope (fnmatch on relpath); pruning is suppressed when scoped:
#   ONLY='routes/*' bash .../run_agy_cli_summaries.sh
#
# Requires: agy on PATH and authenticated, python3.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# skills/agent_token_usage_optimization/summaries → repo root is ../../..
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

SUM_DIR="skills/agent_token_usage_optimization/summaries"
MANIFEST="$SUM_DIR/manifest.json"
REPO_SUM="$SUM_DIR/repo"
SUMMARIZER_PY="$SUM_DIR/summarizer.py"
AGY_SETTINGS="$HOME/.gemini/antigravity-cli/settings.json"

REPO_SLUG="$(basename "$REPO_ROOT" | tr -c 'A-Za-z0-9._-' '_')"
SCRATCH="${SCRATCH:-/tmp/ai_summarizer_agy_${REPO_SLUG}_$$}"
WORK_LIST="${WORK_LIST:-$SCRATCH/work.txt}"
DELETED_LIST="${DELETED_LIST:-$SCRATCH/deleted.txt}"
RESULTS_DIR="${RESULTS_DIR:-$SCRATCH/results}"
LOG="${LOG:-$SCRATCH/batch.log}"

PARALLEL="${PARALLEL:-5}"
MODEL="${MODEL:-Gemini 3.7 Flash (Low)}"
AGY_TIMEOUT="${AGY_TIMEOUT:-300}"
ONLY="${ONLY:-}"

mkdir -p "$RESULTS_DIR" "$REPO_SUM" "$SCRATCH"
: >"$LOG"

# ── guard: model must ALREADY be selected; never mutate settings under a human ──
python3 - "$AGY_SETTINGS" "$MODEL" <<'PY'
import json, pathlib, sys
p, want = pathlib.Path(sys.argv[1]), sys.argv[2]
if not p.exists():
    print(f"ABORT: {p} not found — is agy installed/authenticated?")
    raise SystemExit(1)
have = json.loads(p.read_text()).get("model")
if have != want:
    print(f"ABORT: agy model is {have!r} but this run wants {want!r}.")
    print("Set it once via agy /model (this script will not rewrite settings).")
    raise SystemExit(1)
print(f"model OK: {have!r} (settings untouched)")
PY

# ── build work list (reuses summarizer.plan so scoping/exclusions match) ──
python3 - "$SUMMARIZER_PY" "$WORK_LIST" "$DELETED_LIST" "$ONLY" <<'PY'
import importlib.util, pathlib, sys
sum_py, work_p, del_p, only = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("summarizer", sum_py)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
cfg = mod.load_config()
current, todo_new, todo_changed, deleted = mod.plan(
    cfg, mod.load_manifest(), only=only or None
)
work = todo_new + todo_changed
pathlib.Path(work_p).write_text("\n".join(work) + ("\n" if work else ""))
pathlib.Path(del_p).write_text("\n".join(deleted) + ("\n" if deleted else ""))
print(f"plan: new={len(todo_new)} changed={len(todo_changed)} "
      f"deleted={len(deleted)} work={len(work)}", flush=True)
PY

summarize_one() {
  local rel="$1"
  local safe="${rel//\//_}"
  local prompt="$SCRATCH/prompt_${safe}.txt"
  local raw="$SCRATCH/raw_${safe}.txt"
  local err="$SCRATCH/err_${safe}.txt"
  local res_file="$RESULTS_DIR/${rel//\//__}.json"

  # Build the prompt through summarizer.build_prompt so cached summaries stay
  # consistent with the serial path (same template, same lang/loc fields).
  python3 - "$SUMMARIZER_PY" "$REPO_ROOT" "$rel" "$prompt" "$res_file" <<'PY'
import importlib.util, json, pathlib, sys
sum_py, root, rel, out_p, res_p = sys.argv[1:6]
spec = importlib.util.spec_from_file_location("summarizer", sum_py)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
full = pathlib.Path(root) / rel
if not full.is_file():
    pathlib.Path(res_p).write_text(json.dumps(
        {"rel": rel, "ok": False, "error": "missing source"}))
    raise SystemExit(3)
cfg = mod.load_config()
content = mod.read_file_bounded(str(full), cfg.get("max_input_bytes", 500000))
prompt = mod.build_prompt(mod.read_prompt_template(), rel, content)
pathlib.Path(out_p).write_text(f"{mod.AGY_HEADLESS_INSTRUCTION}\n\n{prompt}")
PY
  if [[ $? -ne 0 ]]; then
    echo "FAIL prompt $rel" | tee -a "$LOG"
    return 0
  fi

  set +e
  timeout "$AGY_TIMEOUT" agy <"$prompt" >"$raw" 2>"$err"
  local ec=$?
  set -e
  rm -f "$prompt"

  if [[ $ec -ne 0 ]]; then
    python3 - "$rel" "$err" "$res_file" "$ec" <<'PY'
import json, pathlib, sys
rel, err_p, res_p, ec = sys.argv[1:5]
ep = pathlib.Path(err_p)
stderr = ep.read_text(errors="replace")[:500] if ep.exists() else ""
pathlib.Path(res_p).write_text(json.dumps(
    {"rel": rel, "ok": False, "error": f"agy exit {ec}", "stderr": stderr}))
PY
    echo "FAIL agy $rel exit=$ec" | tee -a "$LOG"
    rm -f "$raw" "$err"
    return 0
  fi

  python3 - "$raw" "$REPO_SUM/${rel}.md" "$REPO_ROOT/$rel" "$rel" "$res_file" <<'PY'
import hashlib, json, pathlib, re, sys
raw_p, out_p, src_p, rel, res_p = sys.argv[1:6]
text = pathlib.Path(raw_p).read_text(errors="replace").strip()
if text.startswith("```"):
    text = re.sub(r"^```[a-zA-Z0-9_-]*\r?\n?", "", text)
    text = re.sub(r"```\s*$", "", text).strip()
idx = text.find("## PURPOSE")
if idx >= 0:
    text = text[idx:]
# An empty/!PURPOSE body means quota-blocked or refusal — do NOT record a hash,
# so the next run retries this file instead of caching a bad summary.
if not text.startswith("## PURPOSE"):
    pathlib.Path(res_p).write_text(json.dumps(
        {"rel": rel, "ok": False, "error": "bad summary shape",
         "preview": text[:300]}))
    raise SystemExit(0)
out = pathlib.Path(out_p)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(text.rstrip() + "\n")
pathlib.Path(res_p).write_text(json.dumps({
    "rel": rel, "ok": True,
    "hash": hashlib.sha1(pathlib.Path(src_p).read_bytes()).hexdigest(),
}))
PY
  if grep -q '"ok": true' "$res_file" 2>/dev/null; then
    echo "OK $rel" | tee -a "$LOG"
  else
    echo "FAIL shape $rel" | tee -a "$LOG"
  fi
  rm -f "$raw" "$err"
}

export -f summarize_one
export REPO_ROOT SUM_DIR REPO_SUM RESULTS_DIR LOG AGY_TIMEOUT SCRATCH SUMMARIZER_PY

# 1) prune summaries whose source is gone (empty when scoped — see summarizer.plan)
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
[[ -s "$WORK_LIST" ]] && work_n="$(grep -cve '^[[:space:]]*$' "$WORK_LIST" || true)"
echo "START model=\"$MODEL\" parallel=$PARALLEL work=$work_n repo=$REPO_ROOT scratch=$SCRATCH" | tee -a "$LOG"

if [[ "$work_n" -gt 0 ]]; then
  grep -v '^[[:space:]]*$' "$WORK_LIST" \
    | xargs -P "$PARALLEL" -I{} bash -c 'summarize_one "$@"' _ {}
fi

# 3) merge manifest ONCE in the parent (the whole point of this runner)
python3 - "$MANIFEST" "$RESULTS_DIR" "$DELETED_LIST" <<'PY'
import json, pathlib, sys
man_path, results_dir, deleted_path = sys.argv[1:4]
mp = pathlib.Path(man_path)
man = json.loads(mp.read_text()) if mp.exists() else {"files": {}}
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
dp = pathlib.Path(deleted_path)
if dp.exists():
    for rel in dp.read_text().splitlines():
        if rel.strip():
            files.pop(rel.strip(), None)
mp.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
print(f"MANIFEST updated ok={ok} fail={fail} keys={len(files)}", flush=True)
PY

echo "DONE log=$LOG" | tee -a "$LOG"
python3 "$SUMMARIZER_PY" --dry-run 2>&1 | head -3 | tee -a "$LOG"
