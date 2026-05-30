# agent_token_usage_optimization — Layer 1: Context Broker

Agent-agnostic retrieval layer. Any coding agent (Claude, Codex, Antigravity,
Cursor, ...) calls these CLI tools instead of pasting whole files into context.

**Core principle:** Search the LLM summary layer first. Touch source only when necessary.

## Layout

```
agent_token_usage_optimization/
├── README.md              ← you are here
├── broker.py              ← original broker (symbols + source content)
├── summary_broker.py      ← NEW: summary-layer-first broker (recommended starting point)
├── indexer.py
├── lib/
│   ├── ...
│   └── summary_search.py  ← NEW: reusable summary search engine
└── repo/
    ├── ...
    ├── summaries/         ← the rich semantic layer (LLM-generated .md files + rollups)
    └── repo_context/      ← hand-curated high-level orientation
```

## Recommended Agent Workflow (2026+)

```bash
# 1. ALWAYS start here (summary layer)
python3 skills/agent_token_usage_optimization/summary_broker.py search "reindexAll OR 'full scan' OR scaling" --dir models

python3 .../summary_broker.py hotspots scaling
python3 .../summary_broker.py grep "performance scales|in-app after"

# 2. Read a specific high-value summary (no source code)
python3 .../summary_broker.py read models/playedgamebyusermodel.js
python3 .../summary_broker.py rollup models

# 3. Only when you need symbols or actual code:
python3 .../broker.py search "createPlaySession"
python3 .../broker.py read models/foo.js --symbol someFunction
```

The `summary_broker.py` tool was created specifically because the original `broker.py search` only searched source + the symbol index. It ignored the far richer LLM summaries that the rest of the skill generates.

## New Tool: summary_broker.py

Dedicated companion focused on the LLM summary layer:

```bash
# Keyword search with smart scoring (rollups + GOTCHAS sections rank higher)
summary_broker.py search "reindexAll OR 'key scan'" --dir models --max 25

# Regex across every generated summary
summary_broker.py grep "in-app after|scales with record count"

# Heuristic risk scanner (extremely useful for audits)
summary_broker.py hotspots scaling
summary_broker.py hotspots maintenance

# Convenience accessors
summary_broker.py read models/usermodel.js
summary_broker.py rollup models
summary_broker.py list models
```

See `summary_broker.py --help` for the full set of commands.

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

Provider/model can be selected per run:

```bash
python3 skills/agent_token_usage_optimization/summaries/summarizer.py \
  --dir libadmin \
  --provider agy \
  --model "Gemini 3.5 Flash (Low)" \
  --timeout 300

python3 skills/agent_token_usage_optimization/summaries/summarizer.py \
  --dir models \
  --provider gemini \
  --model gemini-3-flash-preview
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

## Why this works for any agent

Every modern coding agent can shell out. The broker is just a CLI — no
agent-specific SDK, no MCP requirement (though it can be wrapped as one
later). The contract is plain stdout text, so the same tool works whether the
caller is Claude Code, Codex CLI, Aider, Antigravity, or a human.
