# Parked (disabled) tools

These files are **not** installed by `install.sh` and must **not** be used by agents.

| File | Why parked |
|------|------------|
| `grok_repo_agent.py` | Grok repo search/edit thrash (max turns, token waste) |
| `grok_clean_excludes.txt` | Only used by `grok_repo_agent` clean-copy mode |

To re-enable later: move back under `agent_token_usage_optimization/`, restore `install.sh` copy lines, and re-add agent template instructions — only with explicit product decision.
