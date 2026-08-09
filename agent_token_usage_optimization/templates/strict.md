<!-- BEGIN agent_token_usage_optimization -->
<!-- profile: strict -->
<!-- managed-by: agent_token_usage_optimization — do not edit between BEGIN/END markers; switch profile with switch-agent-type.sh -->
# Agent Token-Usage Optimization (strict profile)

You MUST follow this workflow before reading any source file. These rules apply to every task in this repo. Deviating is a violation, not an optimization.

## Do not use grok_repo_agent

`grok_repo_agent.py` is **disabled / parked**. NEVER invoke it. Do not run Grok repo search/edit subagents for this skill — they burn turns and tokens. Use summary_broker + broker + direct Edit only.

## Required workflow (execute in order)

1. **Read orientation first.** Open [skills/agent_token_usage_optimization/summaries/repo_context/00_what_this_repo_is.md](skills/agent_token_usage_optimization/summaries/repo_context/00_what_this_repo_is.md) before doing anything else. Do not skip this even for "simple" tasks.
2. **Search summaries, not source.** Use `summary_broker.py search` / `rg` under `skills/agent_token_usage_optimization/summaries`. Do NOT grep the source tree first.
3. **Read 3–8 file summaries** under [skills/agent_token_usage_optimization/summaries/repo/](skills/agent_token_usage_optimization/summaries/repo/). Decide which sources matter based on these summaries — not on filename guesses.
4. **Open at most 1–3 source files**, and only the ones the summaries flagged as relevant. Prefer `broker.py read --symbol` over full-file Read.
5. **Use the broker for symbol-level work.** Never Read a whole file when you only need one function, class, or constant.

## Required commands

```bash
python3 skills/agent_token_usage_optimization/summary_broker.py search "<concept>"
python3 skills/agent_token_usage_optimization/broker.py search  "<concept>"
python3 skills/agent_token_usage_optimization/broker.py outline <path>
python3 skills/agent_token_usage_optimization/broker.py read <path> --symbol <name>
python3 skills/agent_token_usage_optimization/broker.py summary <path>
```

Optional multi-repo:

```bash
python3 skills/agent_token_usage_optimization/summary_broker.py adjacent <path>
python3 skills/agent_token_usage_optimization/summary_broker.py cross <path>
```

## Edits

Apply edits yourself with the Edit tool after locating symbols via summaries/broker. Do **not** route edits through Grok repo agents.

## Optional low-tier (agy only; single-file known range)

```bash
python3 skills/agent_token_usage_optimization/low_tier_agent.py --provider agy --action find-symbol --file <file> --query "<name>"
python3 skills/agent_token_usage_optimization/low_tier_agent.py --provider agy --action find-anchor --file <file> --query "<name>"
python3 skills/agent_token_usage_optimization/low_tier_agent.py --provider agy --action suggest-edit --file <file> --start-line <num> --end-line <num> --instruction "<text>"
python3 skills/agent_token_usage_optimization/low_tier_agent.py --provider agy --action inspect-errors --file <file> --error "<message>"
```

Do **not** use `low_tier_agent.py --action search` or `--provider grok` unless the user explicitly requests it.

**Validation**: if `_validation_warnings` is present on suggest-edit, do not apply blindly.

## Hard rules — do not violate

- DO NOT call `grok_repo_agent.py` (disabled).
- DO NOT read broad source directories (`src/`, `lib/`, etc.) directly. Always go through summaries first.
- DO NOT grep the source tree before searching the summaries tree.
- DO NOT Read a full source file when `broker.py outline` or `broker.py read --symbol` would suffice.
- DO NOT skip step 1, even when the task seems familiar.

## When summaries are stale or missing

If summaries appear stale or missing for a path you need:

1. Note it in your reply.
2. Run `python3 skills/agent_token_usage_optimization/summaries/summarizer.py` to refresh (or ask the user).
3. Only then fall back to reading source.
<!-- END agent_token_usage_optimization -->
