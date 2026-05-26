# agent_token_usage_optimization — Layer 1: Context Broker

Agent-agnostic retrieval layer. Any coding agent (Claude, Codex, Antigravity,
Cursor, ...) calls these CLI tools instead of pasting whole files into context.

## Layout

```
agent_token_usage_optimization/
├── README.md           ← you are here
├── broker.py           ← single CLI entry point (search/outline/read/diff/index/summary)
├── indexer.py          ← (re)builds the repo index
├── lib/                ← shared helpers, identical across all repos
│   ├── languages.py
│   ├── outline.py
│   ├── search.py
│   └── summarize.py
└── repo/               ← REPO-SPECIFIC. Same shape in every repo, unique content.
    ├── config.json     ← include/exclude globs, language hints
    ├── index.sqlite    ← symbol → file:line index (generated)
    ├── summaries/      ← file-hash → summary cache (generated)
    └── SUMMARY.md      ← human-readable repo overview (generated, hand-editable)
```

Top-level files are the **same in every repo**. The `repo/` subdir holds the
**repo-specific** artifacts (same shape, different content).

## How agents should use it

Instead of reading 5 whole files (~20k tokens), the agent calls:

```bash
python3 skills/agent_token_usage_optimization/broker.py search "createPlaySession"
# → ranked list:  path:line  one-line snippet

python3 .../broker.py outline models/crossword/crossworddatamodel.js
# → all symbols + signatures only (~5% of file size)

python3 .../broker.py read models/crossword/crossworddatamodel.js --symbol upsertCrosswordMaster
# → just that function, not the whole file

python3 .../broker.py diff
# → minified unstaged diff (hunks only, no unchanged context spam)

python3 .../broker.py summary
# → repo-level overview from repo/SUMMARY.md
```

## Setup per repo

```bash
# 1. drop this folder into <repo>/skills/agent_token_usage_optimization/
# 2. customize repo/config.json (include/exclude globs)
# 3. build the index:
python3 skills/agent_token_usage_optimization/broker.py index
```

Re-run `broker.py index` after large refactors, or wire into a git post-commit
hook.

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

## Why this works for any agent

Every modern coding agent can shell out. The broker is just a CLI — no
agent-specific SDK, no MCP requirement (though it can be wrapped as one
later). The contract is plain stdout text, so the same tool works whether the
caller is Claude Code, Codex CLI, Aider, Antigravity, or a human.
