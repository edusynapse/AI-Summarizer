<!-- BEGIN agent_token_usage_optimization -->
<!-- profile: loose -->
<!-- managed-by: agent_token_usage_optimization — do not edit between BEGIN/END markers; switch profile with switch-agent-type.sh -->
# Agent Token-Usage Optimization (loose profile)

Before opening source files, consult the summary/broker layer under
[skills/agent_token_usage_optimization/](skills/agent_token_usage_optimization/). Open full source files only when the summaries aren't enough.

## Do not use grok_repo_agent

`grok_repo_agent.py` is **disabled / parked**. Do **not** invoke it (max-turns thrash and token waste). Use summary_broker + broker + direct Read/Edit instead. Optional: `low_tier_agent.py` with `--provider agy` for tiny bounded tasks.

## Workflow (apply in order — skip steps that don't add value)

### 1. Locate via summary layer (never grep source directly)

```bash
python3 skills/agent_token_usage_optimization/summary_broker.py search "<concept>"
python3 skills/agent_token_usage_optimization/summary_broker.py hotspots <topic>
python3 skills/agent_token_usage_optimization/summary_broker.py read <relative/path>
python3 skills/agent_token_usage_optimization/summary_broker.py rollup <directory>
python3 skills/agent_token_usage_optimization/summary_broker.py adjacent <path>
python3 skills/agent_token_usage_optimization/summary_broker.py cross <path>   # multi-repo HTTP join if workspace.env set
```

Only fall back to symbol-level source when summaries are insufficient:

```bash
python3 skills/agent_token_usage_optimization/broker.py search "<concept>"
python3 skills/agent_token_usage_optimization/broker.py outline <path>
python3 skills/agent_token_usage_optimization/broker.py read <path> --symbol <name>
```

### 2. Edits — direct Edit after broker/summary targeting

Prefer: summary_broker / broker to find the symbol → `broker.py read --symbol` or a tight line range → apply the change with your normal Edit tool. Do not spawn Grok repo agents.

### 3. Optional low-tier helpers (bounded only; prefer agy)

```bash
python3 skills/agent_token_usage_optimization/low_tier_agent.py --provider agy \
  --action find-symbol --file <file> --query "<name>"
python3 skills/agent_token_usage_optimization/low_tier_agent.py --provider agy \
  --action find-anchor --file <file> --query "<name>"
python3 skills/agent_token_usage_optimization/low_tier_agent.py --provider agy \
  --action suggest-edit --file <file> --start-line <n> --end-line <n> --instruction "<text>"
python3 skills/agent_token_usage_optimization/low_tier_agent.py --provider agy \
  --action inspect-errors --file <file> --error "<message>"
```

Avoid `low_tier_agent.py --action search` / `--provider grok` unless the user explicitly asks — same thrash risk.

Use your judgment — skip any step that doesn't help on the task at hand.
<!-- END agent_token_usage_optimization -->
