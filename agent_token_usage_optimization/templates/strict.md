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

## Preflight — verify Grok before use

```bash
grok --version &>/dev/null && echo "grok: ok" || echo "grok: UNAVAILABLE"
```

If Grok is unavailable, skip `grok_repo_agent.py` steps entirely and fall back to `low_tier_agent.py` or direct Read + Edit. Do not attempt `grok_repo_agent.py` calls when preflight fails — they will hang until timeout.

## Edits — primary path: grok_repo_agent.py agent-edit

You MUST route edit tasks through `grok_repo_agent.py` before considering manual edits. Grok navigates the repo itself in a clean rsync'd workspace, reads whatever source it needs, and returns a JSON diff (`original_content` → `replacement_content`). Do not read source files yourself for edit tasks.

```bash
python3 skills/agent_token_usage_optimization/grok_repo_agent.py \
  --action agent-edit \
  --instruction "<precise description of what to change and why>" \
  [--file <focus-hint>] [--search-root <dir>]
```

Multi-file edits can take up to 5 minutes — when invoking via an agent Bash tool, set the tool timeout to at least 400000 ms (the script's own `--timeout` defaults to 360s).

Response shape: `{success, operation, file, original_content, replacement_content, requires_followup, followup_query, _validation_warnings?}`

**Apply loop:**
1. Check `_validation_warnings` — if `original_content` not found verbatim, discard and refine instruction.
2. Apply via `Edit` tool using `original_content` as `old_string`.
3. If `requires_followup: true`, call `agent-edit` again with `followup_query` as `--instruction`.

For tasks that span several files, use `--action agent-edit-multi` instead — same flags, but the response returns a `files` array (`[{operation, file, summary, original_content, replacement_content}]`) covering the whole batch in one call. Validate and apply each entry with the same loop; `_validation_warnings` entries are prefixed with the offending file path.

Repo-wide search (use BEFORE grepping the source tree yourself):

```bash
python3 skills/agent_token_usage_optimization/grok_repo_agent.py \
  --action search --query "<what you're looking for>" [--file <focus-hint>]
```

## Offload Context & Edits to Low-Tier Model (single-file, known line range only)

You MUST offload simple context-gathering or localized editing tasks to a low-cost model using `low_tier_agent.py`:
- Locate symbol line numbers:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action find-symbol --file <file> --query "<name>"`
- Find text anchors (drift-resistant alternative to line numbers — prefer this when the file may have been edited since you last read it):
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action find-anchor --file <file> --query "<name>"`
- Propose edits for a line range:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action suggest-edit --file <file> --start-line <num> --end-line <num> --instruction "<text>"`
- Fix lint/compiler errors:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action inspect-errors --file <file> --error "<message>"`
- Search the repo with a Grok sub-agent BEFORE grepping the source tree yourself:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action search --query "<what you're looking for>"`
  Spawns a grok thread (`grok-4.5`) with read-only tools (grep/read_file/list_dir) that browses the repo and returns structured JSON `{found, summary, results:[{file,start_line,end_line,symbol,why}]}`. Add `--search-root <dir>` to scope it; `--file <dir>` as a focus hint.
- Use Grok instead of Antigravity (optional):
  Add `--provider grok` (and optionally `--model grok-4.5`) to actions that support it.
  Default Grok model is **`grok-4.5`** only — Composer is not an option.

**Validation**: `suggest-edit` and `inspect-errors` responses include `_validation_warnings` if drift or line-count mismatches are detected. If `_validation_warnings` is present, DO NOT apply the edit blindly — re-read the target range and retry or fall back to manual editing.

## Hard rules — do not violate

- DO NOT read broad source directories (`src/`, `lib/`, etc.) directly. Always go through summaries first.
- DO NOT grep the source tree before searching the summaries tree.
- DO NOT Read a full source file when `broker.py outline` or `broker.py summary` would suffice.
- DO NOT skip step 1, even when the task seems familiar.
- DO NOT silently ignore this workflow because you "know" the answer — verify against summaries first.
- DO NOT locate functions/classes manually or propose multi-line block changes on high models if `grok_repo_agent.py` or `low_tier_agent.py` can perform them.

## When summaries are stale or missing

If summaries appear stale or missing for a path you need:

1. Note it in your reply.
2. Run `python3 skills/agent_token_usage_optimization/summaries/summarizer.py` to refresh.
3. Only then fall back to reading source.
<!-- END agent_token_usage_optimization -->
