# repo_context — agent orientation

This folder holds **hand-curated, high-level orientation** for any AI coding
agent landing in this repo. The summarizer does **not** touch these files.

Purpose: give the agent a "thought line" — what this repo is, how it fits
into the larger system, who the users are, what the deployment shape looks
like — *before* it starts pattern-matching from filenames.

## Suggested files (create what's relevant)

| File | Content |
|------|---------|
| `00_what_this_repo_is.md` | One paragraph: the repo's role in one breath. Standalone vs. service vs. library. The single sentence that, if missing, would make every other decision worse. |
| `01_system_context.md` | Where this repo sits in the larger system. Sibling repos, upstream/downstream services, shared infra. A small ASCII diagram is worth 500 tokens of prose. |
| `02_runtime_shape.md` | How it runs in prod: process model, hosting (DO droplet, k8s, Lambda…), entry points, ports, scheduled jobs, queues. |
| `03_data_model.md` | The 5-10 core domain entities and their relationships. Skip schema details — those are in the code. Focus on the *concepts*. |
| `04_critical_flows.md` | The 3-5 user/business flows that, if broken, the product is broken. One bullet each: trigger → path → outcome. |
| `05_conventions.md` | Non-obvious conventions: error-handling style, logging discipline, "we never do X here", file/folder naming rules. |
| `06_glossary.md` | Domain vocabulary. Acronyms, internal terms, codename-to-real-name mappings. |
| `99_known_landmines.md` | Things that have bitten the team. Subtle race conditions, deceptive APIs, places where the obvious fix is wrong. |

## Guidelines

- **Terse.** Each file should be readable in under a minute. If it grows past
  ~400 lines, split it.
- **Decisions over descriptions.** Tell the agent what to do/avoid, not just
  what exists.
- **Update when reality changes**, not on a schedule.
- The agent should be instructed (via its system prompt or initial query) to
  read this folder before tackling non-trivial work.
