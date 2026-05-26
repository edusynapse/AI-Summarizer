<!-- BEGIN agent_token_usage_optimization -->
<!-- profile: loose -->
<!-- managed-by: agent_token_usage_optimization — do not edit between BEGIN/END markers; switch profile with switch-agent-type.sh -->
# Agent Token-Usage Optimization (loose profile)

Before opening source files, consult the summary/broker layer under
[skills/agent_token_usage_optimization/](skills/agent_token_usage_optimization/). Open full source files only when the summaries aren't enough.

## Suggested workflow

- Skim repo orientation: [skills/agent_token_usage_optimization/summaries/repo_context/](skills/agent_token_usage_optimization/summaries/repo_context/)
- Search summaries before source: `rg -n "<concept>" skills/agent_token_usage_optimization/summaries`
- Read a handful of relevant file summaries under `skills/agent_token_usage_optimization/summaries/repo/` to decide what to actually open.
- Prefer broker symbol-level reads to full-file Reads when symbol-level is enough.

```bash
python3 skills/agent_token_usage_optimization/broker.py search  "<concept>"
python3 skills/agent_token_usage_optimization/broker.py outline <path>
python3 skills/agent_token_usage_optimization/broker.py summary <path>
```

Use your judgment — skip any step that doesn't help on the task at hand.
<!-- END agent_token_usage_optimization -->
