# Using AGY + Gemini 3.6 Flash (Low)

This skill’s default summarization path uses the **Antigravity CLI** (`agy`)
with model:

| Role | Model display name (exact string) |
|------|-----------------------------------|
| File summaries, rollups, many low-tier tasks | **`Gemini 3.6 Flash (Low)`** |

That name must match what `agy` stores in its settings (including spaces and
parentheses). Prefer Flash (Low) for this workload: short structured
summaries gain little from thinking tiers and cost more.

---

## 1. Install and authenticate AGY

Install the Antigravity / `agy` CLI for your environment, then:

```bash
which agy
agy --help
```

Complete whatever login/auth the CLI requires. Settings live under:

```text
~/.gemini/antigravity-cli/settings.json
```

(Override path with env `AGY_SETTINGS_PATH` if your install uses another
location.)

### Select the model once (required for the parallel runner)

Interactive:

```bash
agy /model
# choose: Gemini 3.6 Flash (Low)
```

Or ensure `settings.json` contains:

```json
{
  "model": "Gemini 3.6 Flash (Low)"
}
```

The parallel script **asserts** this value and **never rewrites** settings
(so it can run beside a human using `agy` on the console).

---

## 2. Install this skill into a repo

From a clone of **AI-Summarizer**:

```bash
./install.sh /path/to/your/project
```

In the **target** repo, templates already default to agy + Flash (Low):

```json
// skills/agent_token_usage_optimization/summaries/config.json
{
  "provider": "agy",
  "model": "Gemini 3.6 Flash (Low)",
  "agy_timeout_sec": 300
}
```

Edit include/exclude rules for your tree, then:

```bash
python3 skills/agent_token_usage_optimization/broker.py index
```

---

## 3. What AGY is used for

| Tool | Purpose | Notes |
|------|---------|--------|
| `summaries/run_agy_cli_summaries.sh` | Parallel **file summaries** | Preferred bulk path; does **not** touch settings |
| `summaries/summarizer.py` | Serial summaries | Temporarily may rewrite settings; **not** parallel-safe |
| `summaries/rollup_summarizer.py` | Directory rollups | Serial; same agy provider |
| `low_tier_agent.py` (default provider) | find-symbol, suggest-edit, … | Default model Flash (Low); uses a lock + settings swap |

`grok_repo_agent.py` is **disabled** (parked; not installed). Prefer brokers + agy low-tier if needed.

---

## 4. Bulk summarization (recommended)

From the **target repo root**, after `agy /model` is Flash (Low):

```bash
# Plan only (no LLM)
python3 skills/agent_token_usage_optimization/summaries/summarizer.py --dry-run

# Parallel AGY — parent owns manifest.json
PARALLEL=5 MODEL="Gemini 3.6 Flash (Low)" \
  bash skills/agent_token_usage_optimization/summaries/run_agy_cli_summaries.sh

# Scope (fnmatch on relative path; pruning suppressed when scoped)
ONLY='src/*' PARALLEL=4 \
  bash skills/agent_token_usage_optimization/summaries/run_agy_cli_summaries.sh

# Directory rollups (after file summaries exist)
python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py --dry-run
python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py
python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py \
  --dir src/api \
  --model "Gemini 3.6 Flash (Low)" \
  --timeout 300
```

Useful env vars for the AGY runner:

| Variable | Default | Meaning |
|----------|---------|---------|
| `MODEL` | `Gemini 3.6 Flash (Low)` | Must match selected agy model exactly |
| `PARALLEL` | `5` | Concurrent workers |
| `AGY_TIMEOUT` | `300` | Per-file timeout (seconds) |
| `ONLY` | (empty) | `fnmatch` filter on relpath |

### Why not N× `summarizer.py`?

`summarizer.py` loads `manifest.json` at start and whole-dict writes it at
end. Concurrent processes **drop each other’s hashes**. Always use
`run_agy_cli_summaries.sh` for bulk work.

### Serial path (small / scoped only)

```bash
python3 skills/agent_token_usage_optimization/summaries/summarizer.py \
  --dir src/api \
  --model "Gemini 3.6 Flash (Low)" \
  --timeout 300
```

**Caveat:** serial `summarizer.py` may temporarily write
`~/.gemini/antigravity-cli/settings.json` to select the model, then restore.
Do **not** run two serial jobs (or serial + interactive agy) under the same
user at once. The parallel runner avoids that by asserting the model is
already selected.

---

## 5. Low-tier helper (`low_tier_agent.py`)

Default provider is `agy` / Flash (Low):

```bash
python3 skills/agent_token_usage_optimization/low_tier_agent.py \
  --action find-symbol \
  --file src/auth/session.py \
  --query "createSession"

python3 skills/agent_token_usage_optimization/low_tier_agent.py \
  --action suggest-edit \
  --file src/auth/session.py \
  --start-line 40 --end-line 80 \
  --instruction "Return early if session is expired"

python3 skills/agent_token_usage_optimization/low_tier_agent.py \
  --action inspect-errors \
  --file src/auth/session.py \
  --error "NameError: name 'ttl' is not defined"
```

Repo-wide `search` / `agent-edit` actions always use the **Grok** CLI (see
[using_grok.md](using_grok.md)); other actions honor `--provider agy|grok`.

AGY actions use a file lock under `~/.gemini/antigravity-cli/` so concurrent
settings swaps do not clobber each other as badly as unlocked parallel
`summarizer.py` would.

---

## 6. After summaries exist

```bash
python3 skills/agent_token_usage_optimization/summary_broker.py search "auth OR session"
python3 skills/agent_token_usage_optimization/summary_broker.py hotspots scaling
python3 skills/agent_token_usage_optimization/summary_broker.py read src/auth/session.py
python3 skills/agent_token_usage_optimization/broker.py outline src/auth/session.py
python3 skills/agent_token_usage_optimization/indexer.py
```

---

## 7. Quota and quality tips

- Flash (Low) is the intended cost/quality point for **structured** summaries.
- One quota window is on the order of a few hundred successful calls; a full
  monorepo refresh can approach that — use `ONLY=…` or `--dir` when iterating.
- Failures do **not** update the SHA-1 in the manifest → next run retries only
  unfinished files.
- Keep `prompt_template.txt` stable; changing it without clearing
  `manifest.json` leaves mixed summary styles.

---

## 8. Troubleshooting

| Symptom | Likely fix |
|---------|------------|
| `ABORT: agy model is … but this run wants …` | `agy /model` → **Gemini 3.6 Flash (Low)** (exact string) |
| `settings.json` not found | Install/auth agy; check `AGY_SETTINGS_PATH` |
| Summaries missing sections / no hash | Refusal or quota; re-run after window resets |
| Interactive `agy` model flips mid-batch | Use parallel runner only (never serial) while you work in another terminal |
| Manifest shrinks after parallel jobs | You ran multiple `summarizer.py` processes — switch to `run_agy_cli_summaries.sh` |

---

## 9. See also

- [using_grok.md](using_grok.md) — Grok CLI + `grok-4.5`
- Root [README.md](../README.md) — install layout, profiles
- [summaries/README.md](../agent_token_usage_optimization/summaries/README.md) — cache / rollups design
