<!-- BEGIN agent_token_usage_optimization -->
<!-- profile: strict -->
<!-- managed-by: agent_token_usage_optimization — do not edit between BEGIN/END markers; switch profile with switch-agent-type.sh -->
# Agent Token-Usage Optimization (strict profile)

You MUST follow this workflow before reading any source file. These rules apply to every task in this repo. Deviating is a violation, not an optimization.

## Required workflow (execute in order)

1. **Read orientation first.** Open [skills/agent_token_usage_optimization/summaries/repo_context/00_what_this_repo_is.md](skills/agent_token_usage_optimization/summaries/repo_context/00_what_this_repo_is.md) before doing anything else. Do not skip this even for "simple" tasks.
2. **Search summaries, not source.** Use `rg -n "<concept>" skills/agent_token_usage_optimization/summaries`. Do NOT grep or list the source tree first.
3. **Read 3–8 file summaries** under [skills/agent_token_usage_optimization/summaries/repo/](skills/agent_token_usage_optimization/summaries/repo/). Decide which sources matter based on these summaries — not on filename guesses.
4. **Open at most 1–3 source files**, and only the ones the summaries flagged as relevant. If you find yourself reaching for a fourth, stop and re-search summaries.
5. **Use the broker for symbol-level work.** Never Read a whole file when you only need one function, class, or constant — use `broker.py outline` and `broker.py summary` instead.

## Required commands

```bash
python3 skills/agent_token_usage_optimization/broker.py search  "<concept>"
python3 skills/agent_token_usage_optimization/broker.py outline <path>
python3 skills/agent_token_usage_optimization/broker.py summary <path>
```

## Offload Context & Edits to Low-Tier Model

You MUST offload simple context-gathering or localized editing tasks to a low-cost model using `low_tier_agent.py`:
- Locate symbol line numbers:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action find-symbol --file <file> --query "<name>"`
- Find text anchors (drift-resistant alternative to line numbers — prefer this when the file may have been edited since you last read it):
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action find-anchor --file <file> --query "<name>"`
- Propose edits for a line range:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action suggest-edit --file <file> --start-line <num> --end-line <num> --instruction "<text>"`
- Fix lint/compiler errors:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action inspect-errors --file <file> --error "<message>"`
- Search the repo with a fast sub-agent (Composer 2.5) BEFORE grepping the source tree yourself:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action search --query "<what you're looking for>"`
  Spawns a grok thread (`grok-composer-2.5-fast`) with read-only tools (grep/read_file/list_dir) that browses the repo and returns structured JSON `{found, summary, results:[{file,start_line,end_line,symbol,why}]}`. Add `--search-root <dir>` to scope it; `--file <dir>` as a focus hint.
- Use Grok instead of Antigravity (optional):
  Add `--provider grok` to any command above.
  - **Composer (`grok-composer-2.5-fast`, the default)** — use for searching, locating, triangulating across code by reading it, and quick piece-by-piece edits. It's the right choice whenever the required output complexity is low (faster, and more faithful at reproducing verbatim edit ranges).
  - **`--model grok-build`** — reach for it only on heavy troubleshooting: reasoning across log files, hunting bugs, or multi-file investigation that needs sustained analysis.

**Validation**: `suggest-edit` and `inspect-errors` responses include `_validation_warnings` if drift or line-count mismatches are detected. If `_validation_warnings` is present, DO NOT apply the edit blindly — re-read the target range and retry or fall back to manual editing.

## Hard rules — do not violate

- DO NOT read broad source directories (`src/`, `lib/`, etc.) directly. Always go through summaries first.
- DO NOT grep the source tree before searching the summaries tree.
- DO NOT Read a full source file when `broker.py outline` or `broker.py summary` would suffice.
- DO NOT skip step 1, even when the task seems familiar.
- DO NOT silently ignore this workflow because you "know" the answer — verify against summaries first.
- DO NOT locate functions/classes manually or propose multi-line block changes on high models if `low_tier_agent.py` can perform them.

## When summaries are stale or missing

If summaries appear stale or missing for a path you need:

1. Note it in your reply.
2. Run `python3 skills/agent_token_usage_optimization/summaries/summarizer.py` to refresh.
3. Only then fall back to reading source.
<!-- END agent_token_usage_optimization -->
