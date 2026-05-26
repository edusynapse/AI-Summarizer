# AI-Summarizer

Canonical, repo-agnostic source of the **`agent_token_usage_optimization`**
skill — a token-reduction architecture for AI coding agents
(Claude, Codex, Antigravity, Cursor, Aider, …).

This repo is the **single source of truth**. Every product repo gets a copy
of `agent_token_usage_optimization/` dropped into its `skills/` folder.
Improvements land here first, then propagate via `install.sh`.

## What's in the skill

Three layers, each independently useful:

1. **Context Broker (`broker.py`)** — CLI tools that any agent can shell out
   to: `search / outline / read --symbol / diff / summary / context`. Cuts
   per-task token spend by 60–90% vs. pasting whole files.
2. **LLM Summary Cache (`summaries/`)** — provider-backed, hash-keyed,
   incremental file summaries. Lets agents decide *whether* to open a file
   from a 200-token summary instead of reading 5k tokens.
3. **Directory Rollups (`summaries/rollups/`)** — optional hash-keyed
   summaries of selected large directories, generated from existing file
   summaries. Helps agents choose an area before reading dozens of per-file
   summaries.

Full architecture rationale is in `agent_token_usage_optimization/README.md`.

## Repo layout

```
AI-Summarizer/
├── README.md                              ← you are here
├── install.sh                             ← copy skill into a target repo
└── agent_token_usage_optimization/        ← the skill (drop-in to any repo)
    ├── README.md
    ├── broker.py                          ← shared
    ├── indexer.py                         ← shared
    ├── lib/                               ← shared
    │   ├── languages.py
    │   ├── outline.py
    │   ├── search.py
    │   └── summarize.py
    ├── repo/                              ← per-repo (template + generated)
    │   ├── config.json                    ← TEMPLATE — edit per repo
    │   └── .gitignore
    └── summaries/
        ├── README.md                      ← shared
        ├── summarizer.py                  ← shared
        ├── rollup_summarizer.py           ← shared
        ├── prompt_template.txt            ← shared
        ├── rollup_prompt_template.txt     ← shared
        ├── config.json                    ← TEMPLATE — edit per repo
        ├── rollups_config.json            ← TEMPLATE — edit per repo
        ├── .gitignore                     ← shared
        └── repo_context/                  ← per-repo, hand-curated
            └── README.md                  ← shared starter
```

**Shared** files are byte-identical across every repo and are overwritten by
`install.sh`. **Per-repo** files (`config.json` in `repo/`,
`summaries/config.json`, `summaries/rollups_config.json`, and
`repo_context/*.md` beyond the README) are NEVER overwritten — see
`install.sh` for the exact rule.

## Install into a product repo

```bash
./install.sh /path/to/target_repo
```

First run: drops the full tree into `<target_repo>/skills/agent_token_usage_optimization/`.

Subsequent runs: overwrite shared files only. Per-repo configs and curated
`repo_context/` content are preserved.

After install, in the target repo:

```bash
# 1. customize include/exclude rules
$EDITOR skills/agent_token_usage_optimization/repo/config.json
$EDITOR skills/agent_token_usage_optimization/summaries/config.json
$EDITOR skills/agent_token_usage_optimization/summaries/rollups_config.json

# 2. populate orientation (see repo_context/README.md for suggested files)
$EDITOR skills/agent_token_usage_optimization/summaries/repo_context/00_what_this_repo_is.md

# 3. build the symbol index
python3 skills/agent_token_usage_optimization/broker.py index

# 4. backfill LLM summaries
python3 skills/agent_token_usage_optimization/summaries/summarizer.py

# 5. build selected directory rollups from existing file summaries
python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py
```

## Improvement workflow

1. Edit the shared files **here**, in this repo.
2. Test in one product repo (copy or symlink during iteration).
3. When stable, commit here.
4. Run `./install.sh <repo>` against each consuming repo to propagate.

Per-repo customization (configs, orientation files) stays in the consuming
repos — never push it back here.

## Roadmap

- Layer 2: tiered context manager (pinned vs. working vs. cold).
- Layer 3: log/diff minifier.
- Optional MCP wrapper around `broker.py` for agents that prefer MCP over
  shell.
- Tree-sitter outline (replace regex `lib/outline.py` for higher accuracy).
- Embeddings-backed semantic search (FAISS, when lexical search starts to
  miss).
