# Layer 2 — tiered context manager (pinned / working / cold)

Keep a **session board** of paths so agents pack only what the task needs.

| Tier | Role | Pack behavior |
|------|------|----------------|
| **pinned** | Orientation + always-needed modules | Prefer LLM summary / `repo_context`; include body up to budget |
| **working** | Files actively under change | Prefer summaries; optional source with `--source` |
| **cold** | Known but not loaded | One-line stub only (promote when needed) |

State (gitignored):

```text
skills/agent_token_usage_optimization/repo/context_session.json
```

## CLI

```bash
# from target repo root
CM=skills/agent_token_usage_optimization/context_manager.py

python3 $CM task "fix session expiry race"
python3 $CM seed-context          # pin all repo_context/*.md
python3 $CM pin src/auth/session.py --note "expiry bug"
python3 $CM work src/auth/middleware.py
python3 $CM cold tests/auth/test_session.py
python3 $CM status
python3 $CM pack --budget 20000
python3 $CM promote src/auth/middleware.py   # → pinned
python3 $CM demote src/auth/session.py       # → working
python3 $CM rm path/to/file
python3 $CM clear working                    # or clear all
```

## Pack output shape

```text
# Tiered context pack
task: …
budget: N chars | used: M

# PINNED …
# WORKING …
# COLD (stubs only)
- path: one-line note
```

Use `pack` when starting a turn or before a long edit so the model does not
re-open the whole tree.

## MCP tools

- `context_status`, `context_place`, `context_task`, `context_pack`

See [mcp_brokers.md](mcp_brokers.md).

## Tips

- Seed pinned orientation once per repo: `seed-context`.
- Keep working set small (3–8 paths). Move finished paths to cold.
- Prefer summaries in working/pinned; only `--source` when editing.
