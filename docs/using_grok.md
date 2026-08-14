# Using Grok with AI-Summarizer

This skill talks to the **Grok CLI** (`grok` on your `$PATH`). The supported
model for this project is:

| Role | Model id |
|------|----------|
| Summaries, repo search, edit proposals | **`grok-4.5`** |

There is **no Composer model option** here anymore. Do not pass
`grok-composer-*` or similar — use `grok-4.5` only (or whatever single
successor `grok models` lists that you intentionally override).

---

## 1. Install the Grok CLI

Exact packaging changes over time; use the current xAI / Grok CLI install for
your OS, then confirm:

```bash
which grok
grok --version          # or: grok --help
grok models             # must list grok-4.5 (or your chosen default)
```

Authenticate however the CLI requires (API key / login). This skill never
embeds keys; it inherits the CLI’s normal auth from your environment.

### Optional: headless / CI

Ensure non-interactive calls work:

```bash
grok --prompt "Reply with exactly: ok" --tools "" --max-turns 1 --verbatim 2>/dev/null | head
```

If that hangs or prompts, fix CLI login before running batch summarizers.

---

## 2. Install this skill into a repo

From a clone of **AI-Summarizer**:

```bash
./install.sh /path/to/your/project
```

That drops `skills/agent_token_usage_optimization/` into the target and
installs/refreshes `CLAUDE.md` / `AGENTS.md` instruction blocks.

Then in the **target** repo:

```bash
# include/exclude rules (optional)
$EDITOR skills/agent_token_usage_optimization/repo/config.json
$EDITOR skills/agent_token_usage_optimization/summaries/config.json

# symbol index (no LLM)
python3 skills/agent_token_usage_optimization/broker.py index
```

---

## 3. What Grok is used for

| Tool | Purpose | Default model |
|------|---------|---------------|
| `summaries/run_grok_cli_summaries.sh` | Parallel **file summaries** (bulk) | `grok-4.5` |
| `low_tier_agent.py --provider grok` | Optional bounded tasks only (prefer `--provider agy`) | `grok-4.5` |

**`grok_repo_agent.py` is DISABLED** — parked at `scratch/parked/grok_repo_agent.py`
in the AI-Summarizer source tree; not installed into consumer repos.

Brokers (`summary_broker.py`, `broker.py`) do **not** call Grok; they only
read summaries / the symbol index / source.

---

## 4. Bulk summarization (recommended path)

From the **target repo root**:

```bash
# What would change (no API calls)
python3 skills/agent_token_usage_optimization/summaries/summarizer.py --dry-run

# Parallel Grok summaries — parent merges manifest (safe for N workers)
PARALLEL=4 MODEL=grok-4.5 \
  bash skills/agent_token_usage_optimization/summaries/run_grok_cli_summaries.sh

# Directory rollups (serial; uses summarizer’s agy path by default —
# for Grok-only environments prefer re-running after summaries exist,
# or use agy for rollups — see docs/using_agy_gemini_flash.md)
python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py --dry-run
```

Useful env vars for the Grok runner:

| Variable | Default | Meaning |
|----------|---------|---------|
| `MODEL` | `grok-4.5` | Model id passed to `grok` |
| `PARALLEL` | `4` | Concurrent workers |
| `MAX_TURNS` | `3` | CLI turn cap (`1` often fails with “Max turns reached”) |
| `GROK_TIMEOUT` | `180` | Per-file timeout (seconds) |
| `ONLY` | (empty) | Not used by the grok shell runner the same way as agy — prefer scoping via summarizer dry-run + custom `WORK_LIST` if needed |

Design notes:

- Tools are stripped (`--tools ""`, denylist, `--no-subagents`) so the model
  only returns summary markdown.
- The **parent** process writes `summaries/repo/<path>.md` and updates
  `manifest.json`. Never run N copies of `summarizer.py` in parallel.
- Prefer this runner over inventing a custom `spawn_subagent` loop.

---

## 5. Repo worker (search & edit proposals) — removed

Do not use `grok_repo_agent.py`. Use `summary_broker.py` / `broker.py` and
direct editor tools. Parked source: `scratch/parked/grok_repo_agent.py`.

---

## 6. Low-tier helper (`low_tier_agent.py`)

```bash
python3 skills/agent_token_usage_optimization/low_tier_agent.py \
  --provider grok \
  --model grok-4.5 \
  --action find-symbol \
  --file src/auth/session.py \
  --query "createSession"

python3 skills/agent_token_usage_optimization/low_tier_agent.py \
  --provider grok \
  --model grok-4.5 \
  --action search \
  --query "rate limit middleware"

python3 skills/agent_token_usage_optimization/low_tier_agent.py \
  --provider grok \
  --model grok-4.5 \
  --action agent-edit \
  --instruction "Add validation for the status field" \
  --file src/billing/invoices.ts \
  --search-root .
```

`search` / `agent-edit` enable read-only tools inside Grok; other actions are
single-shot JSON. The script **does not write** source files — the orchestrator
applies diffs after validating `original_content`.

---

## 7. After summaries exist

```bash
python3 skills/agent_token_usage_optimization/summary_broker.py search "auth OR session"
python3 skills/agent_token_usage_optimization/summary_broker.py read src/auth/session.py
python3 skills/agent_token_usage_optimization/broker.py search "createSession"
python3 skills/agent_token_usage_optimization/indexer.py
```

---

## 8. Troubleshooting

| Symptom | Likely fix |
|---------|------------|
| `grok: command not found` | Install CLI; fix `$PATH` |
| Model rejected / unknown | `grok models` — set `MODEL=grok-4.5` or the listed id |
| Hangs on large monorepos | Use `--cwd-strategy clean-copy`; extend `grok_clean_excludes.txt` |
| Empty / truncated summary | Raise `MAX_TURNS` (default 3); check quota |
| Manifest “forgets” files | Do not parallelize `summarizer.py`; use `run_grok_cli_summaries.sh` only |
| Composer model still in old docs/scripts | Treat as stale — always `grok-4.5` |

---

## 9. See also

- [using_agy_gemini_flash.md](using_agy_gemini_flash.md) — AGY + Gemini 3.7 Flash (Low)
- Root [README.md](../README.md) — install layout, profiles
- [summaries/README.md](../agent_token_usage_optimization/summaries/README.md) — cache / rollups design
