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

## Offload Context & Edits to Low-Tier Model

To reduce high-tier model token usage, offload simple context-gathering or localized editing tasks to a low-cost model using `low_tier_agent.py`:
- Locate symbol line numbers:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action find-symbol --file <file> --query "<name>"`
- Propose edits for a line range:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action suggest-edit --file <file> --start-line <num> --end-line <num> --instruction "<text>"`
- Fix lint/compiler errors:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action inspect-errors --file <file> --error "<message>"`
- Use Grok instead of Antigravity (optional):
  Add `--provider grok` to any command above (uses `grok-build` model by default).

Use your judgment — skip any step that doesn't help on the task at hand.
<!-- END agent_token_usage_optimization -->
