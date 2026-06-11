<!-- BEGIN agent_token_usage_optimization -->
<!-- profile: loose -->
<!-- managed-by: agent_token_usage_optimization — do not edit between BEGIN/END markers; switch profile with switch-agent-type.sh -->
# Agent Token-Usage Optimization (loose profile)

Before opening source files, consult the summary/broker layer under
[skills/agent_token_usage_optimization/](skills/agent_token_usage_optimization/). Open full source files only when the summaries aren't enough.

## Preflight — verify Grok before use

```bash
grok --version &>/dev/null && echo "grok: ok" || echo "grok: UNAVAILABLE"
```

If Grok is unavailable, skip `grok_repo_agent.py` steps entirely and fall back to `low_tier_agent.py` or direct Read + Edit. Do not attempt `grok_repo_agent.py` calls when preflight fails — they will hang until timeout.

## Workflow (apply in order — skip steps that don't add value)

### 1. Locate via summary layer (never grep source directly)

```bash
python3 skills/agent_token_usage_optimization/summary_broker.py search "<concept>"
python3 skills/agent_token_usage_optimization/summary_broker.py hotspots <topic>
python3 skills/agent_token_usage_optimization/summary_broker.py read <relative/path>
python3 skills/agent_token_usage_optimization/summary_broker.py rollup <directory>
```

Only fall back to symbol-level source when summaries are insufficient:

```bash
python3 skills/agent_token_usage_optimization/broker.py search "<concept>"
python3 skills/agent_token_usage_optimization/broker.py outline <path>
python3 skills/agent_token_usage_optimization/broker.py read <path> --symbol <name>
```

### 2. Edits — primary path: grok_repo_agent.py agent-edit

Grok navigates the repo itself in a clean rsync'd workspace, reads whatever
source it needs, and returns a JSON diff (`original_content` →
`replacement_content`). Claude never reads source files for edit tasks.

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

### 3. Search — use grok_repo_agent.py search (not raw grep)

```bash
python3 skills/agent_token_usage_optimization/grok_repo_agent.py \
  --action search --query "<what you're looking for>" [--file <focus-hint>]
```

### 4. Low-tier fallbacks (single-file, line-range tasks only)

```bash
# Locate symbol / find anchor
python3 skills/agent_token_usage_optimization/low_tier_agent.py --action find-symbol --file <file> --query "<name>"
python3 skills/agent_token_usage_optimization/low_tier_agent.py --action find-anchor --file <file> --query "<name>"

# Suggest edit for a known line range (weaker than agent-edit — use only when range is already known)
python3 skills/agent_token_usage_optimization/low_tier_agent.py --action suggest-edit \
  --file <file> --start-line <n> --end-line <n> --instruction "<text>"

# Fix lint/compiler errors
python3 skills/agent_token_usage_optimization/low_tier_agent.py --action inspect-errors \
  --file <file> --error "<message>"
```

**Model guidance:**
- `grok-composer-2.5-fast` (default) — searching, locating, edits
- `--model grok-build` — heavy multi-file troubleshooting, log analysis, bug hunting

Use your judgment — skip any step that doesn't help on the task at hand.
<!-- END agent_token_usage_optimization -->
