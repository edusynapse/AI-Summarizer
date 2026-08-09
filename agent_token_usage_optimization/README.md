# agent_token_usage_optimization — Layer 1: Context Broker

Agent-agnostic retrieval layer. Any coding agent (Claude, Codex, Antigravity,
Cursor, ...) calls these CLI tools instead of pasting whole files into context.

**Core principle:** Search the LLM summary layer first. Touch source only when necessary.

## Layout

```
agent_token_usage_optimization/
├── README.md              ← you are here
├── broker.py              ← original broker (symbols + source content)
├── summary_broker.py      ← summary-layer-first broker (recommended starting point)
├── mcp_server.py          ← optional MCP stdio server (both brokers)
├── embeddings_index.py    ← embeddings index build/search over summaries
├── context_manager.py     ← Layer 2: pinned / working / cold
├── minify.py              ← Layer 3: log + diff minifier
├── indexer.py
├── lib/
│   ├── outline.py         ← tree-sitter when available, else regex
│   ├── summary_search.py
│   ├── embeddings_search.py
│   ├── context_tiers.py
│   ├── minify.py
│   └── ...
└── repo/
    ├── ...
    ├── summaries/         ← the rich semantic layer (LLM-generated .md files + rollups)
    └── repo_context/      ← hand-curated high-level orientation
```

## Recommended Agent Workflow (2026+)

```bash
# 1. ALWAYS start here (summary layer)
python3 skills/agent_token_usage_optimization/summary_broker.py search "auth OR session OR scaling" --dir src

python3 .../summary_broker.py hotspots scaling
python3 .../summary_broker.py grep "rate.?limit|cache invalidat"

# 2. Read a specific high-value summary (no source code)
python3 .../summary_broker.py read src/auth/session.py
python3 .../summary_broker.py rollup src

# 3. Only when you need symbols or actual code:
python3 .../broker.py search "createSession"
python3 .../broker.py read src/auth/session.py --symbol createSession
```

Project-specific search examples (keep for monorepos with Redis/full-scan paths):
`search "reindexAll OR 'full scan'" --dir models`, `read models/usermodel.js`.

The `summary_broker.py` tool was created specifically because the original `broker.py search` only searched source + the symbol index. It ignored the far richer LLM summaries that the rest of the skill generates.

## New Tool: summary_broker.py

Dedicated companion focused on the LLM summary layer:

```bash
# Keyword search with smart scoring (rollups + GOTCHAS sections rank higher)
summary_broker.py search "auth OR 'rate limit'" --dir src --max 25

# Regex across every generated summary
summary_broker.py grep "scales with|cache invalidat"

# Heuristic risk scanner (extremely useful for audits)
summary_broker.py hotspots scaling
summary_broker.py hotspots maintenance

# Convenience accessors
summary_broker.py read src/auth/session.py
summary_broker.py rollup src
summary_broker.py list src
```

See `summary_broker.py --help` for the full set of commands.

## Grok Repo Worker — DISABLED

`grok_repo_agent.py` is **parked** under `scratch/parked/` in the AI-Summarizer
source repo and is **not** installed by `install.sh`. Agents must not invoke it
(max-turn thrash / token waste). Prefer `summary_broker.py` + `broker.py` +
direct edits. Optional: `low_tier_agent.py --provider agy` for tiny tasks.

## Low-Tier Repo Agent

`low_tier_agent.py` can offload small, bounded tasks to a cheaper model. For
repo-aware code generation, use `agent-edit`: Grok may browse with read-only
`grep`, `read_file`, and `list_dir`, but the final JSON contains only one file
creation or one file update proposal.

```bash
python3 skills/agent_token_usage_optimization/low_tier_agent.py \
  --action agent-edit \
  --instruction "Add server-side validation for the invoice status field" \
  --search-root . \
  --file src/billing/invoices.ts \
  --provider grok
```

If the requested task needs multiple files, run `agent-edit` repeatedly; each
response can set `requires_followup` and provide a concise `followup_query`.

## Setup per repo

```bash
# 1. drop this folder into <repo>/skills/agent_token_usage_optimization/
# 2. customize the two config files
$EDITOR skills/agent_token_usage_optimization/repo/config.json
$EDITOR skills/agent_token_usage_optimization/summaries/config.json
$EDITOR skills/agent_token_usage_optimization/summaries/rollups_config.json

# 3. Build the symbol index (still useful)
python3 skills/agent_token_usage_optimization/broker.py index

# 4. Generate the LLM summary layer (the real power)
python3 skills/agent_token_usage_optimization/summaries/summarizer.py
python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py
```

Re-run the index + summarizers after large refactors.

Commit `repo/index.sqlite` if you want instant symbol search after clone.
Python bytecode stays ignored.

## Refreshing LLM summaries

The semantic summaries in `summaries/repo/` are incremental and hash-based.
Use them as the first-pass map before opening full source files, and refresh
them after code changes so agents do not make decisions from stale summaries.

```bash
# Preview what would change; no LLM calls.
python3 skills/agent_token_usage_optimization/summaries/summarizer.py --dry-run

# Full incremental refresh; unchanged files are skipped.
python3 skills/agent_token_usage_optimization/summaries/summarizer.py

# Prefer scoped refreshes when you worked in one area.
python3 skills/agent_token_usage_optimization/summaries/summarizer.py --dir lib/helpers
python3 skills/agent_token_usage_optimization/summaries/summarizer.py --only "lib/widgets/*.dart"
```

Model can be selected per run (provider is always `agy`):

```bash
python3 skills/agent_token_usage_optimization/summaries/summarizer.py \
  --dir src/api \
  --model "Gemini 3.6 Flash (Low)" \
  --timeout 300
# Project ref: --dir libadmin  (or models, lib/helpers, …)
```

`manifest.json` records the source hash for each summarized file. Changed or
new files are summarized; deleted files are pruned on unscoped runs. Failures
do not update the hash, so rerunning retries only unfinished work.

Directory rollups sit one level above file summaries. Configure only high-value
large directories in `summaries/rollups_config.json`, then run:

```bash
python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py --dry-run
python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py
python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py --dir lib/helpers --force
```

Rollups use existing `summaries/repo/**/*.md` content as input and write to
`summaries/rollups/<dir>.md`. `rollups_manifest.json` stores the digest of the
input summaries, so unchanged directories are skipped.

## The Two Brokers (2026 model)

| Tool                    | Primary Purpose                          | When to Use                                      | Searches Source? |
|-------------------------|------------------------------------------|--------------------------------------------------|------------------|
| `summary_broker.py`     | **Summary layer first** (new)            | Almost everything. Audits, exploration, "does this have X risk?" | Never           |
| `broker.py`             | Symbol index + targeted source reads     | When you need function signatures or a specific slice of code | Yes             |

**Strong recommendation:** Wire agents to prefer `summary_broker.py` for the first 1–3 retrievals on any task.

## MCP (optional)

```bash
# Host cwd must be the target repo root
python3 skills/agent_token_usage_optimization/mcp_server.py
```

See `docs/mcp_brokers.md` in the AI-Summarizer repo.

## Semantic search over summaries

```bash
python3 skills/agent_token_usage_optimization/embeddings_index.py build
python3 skills/agent_token_usage_optimization/summary_broker.py semantic "session expiry"
```

See `docs/embeddings_semantic_search.md`.

## Layer 2 — tiered context

```bash
python3 skills/agent_token_usage_optimization/context_manager.py task "fix expiry"
python3 skills/agent_token_usage_optimization/context_manager.py pin src/auth/session.py
python3 skills/agent_token_usage_optimization/context_manager.py pack --budget 20000
```

See `docs/context_tiers.md`.

## Layer 3 — minify logs / diffs

```bash
git diff | python3 skills/agent_token_usage_optimization/minify.py diff -
python3 skills/agent_token_usage_optimization/broker.py diff
```

See `docs/log_diff_minifier.md`.

## Why this works for any agent

Every modern coding agent can shell out. The broker is a CLI; an optional MCP
stdio wrapper exposes the same surface. The contract is plain stdout / MCP
tool text, so the same logic works for Claude Code, Codex CLI, Aider,
Antigravity, Cursor, or a human.
