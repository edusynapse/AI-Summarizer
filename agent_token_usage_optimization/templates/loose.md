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
- Find text anchors (drift-resistant alternative to line numbers):
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action find-anchor --file <file> --query "<name>"`
- Propose edits for a line range:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action suggest-edit --file <file> --start-line <num> --end-line <num> --instruction "<text>"`
- Fix lint/compiler errors:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action inspect-errors --file <file> --error "<message>"`
- Search the repo with a fast sub-agent (Composer 2.5) instead of grepping yourself:
  `python3 skills/agent_token_usage_optimization/low_tier_agent.py --action search --query "<what you're looking for>"`
  Spawns a grok thread (`grok-composer-2.5-fast`) with read-only tools (grep/read_file/list_dir) that browses the repo and returns structured JSON `{found, summary, results:[{file,start_line,end_line,symbol,why}]}`. Add `--search-root <dir>` to scope it; `--file <dir>` as a focus hint.
- Use Grok instead of Antigravity (optional):
  Add `--provider grok` to any command above.
  - **Composer (`grok-composer-2.5-fast`, the default)** — use for searching, locating, triangulating across code by reading it, and quick piece-by-piece edits. It's the right choice whenever the required output complexity is low (faster, and more faithful at reproducing verbatim edit ranges).
  - **`--model grok-build`** — reach for it only on heavy troubleshooting: reasoning across log files, hunting bugs, or multi-file investigation that needs sustained analysis.

**Validation**: `suggest-edit` and `inspect-errors` responses include `_validation_warnings` if drift or line-count mismatches are detected. Check this field before blindly applying edits.

Use your judgment — skip any step that doesn't help on the task at hand.
<!-- END agent_token_usage_optimization -->
