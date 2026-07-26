# Layer 3 — log / diff minifier

Shrink noisy diffs and logs before they enter the agent context window.

## CLI

```bash
M=skills/agent_token_usage_optimization/minify.py

# Diff (stdin or file)
git diff | python3 $M diff -
python3 $M diff /tmp/change.diff --max-hunk 60 --max-total 500

# Log
tail -n 5000 app.log | python3 $M log -
python3 $M log /tmp/app.log --max-lines 300 --keep-debug
```

Stats print to **stderr** by default (`-q` to silence).

## Also via broker

```bash
python3 skills/agent_token_usage_optimization/broker.py diff
python3 skills/agent_token_usage_optimization/broker.py diff HEAD~3 --max-hunk 40
python3 skills/agent_token_usage_optimization/broker.py diff --raw   # light strip only
```

## What the diff minifier does

- Drops `diff --git`, `index …`, mode / similarity noise
- Keeps `---` / `+++` and hunk headers
- Caps lines per hunk / per file / total
- Thins pure context lines in large hunks
- Labels binary file diffs without dumping content

## What the log minifier does

- Strips leading timestamps (optional keep)
- Drops DEBUG/TRACE by default
- Drops healthcheck / metrics noise substrings
- Redacts UUIDs / long hex / request ids → placeholders
- Collapses consecutive identical lines (`×N`)
- Keeps the **tail** when over `--max-lines` (usually where failures land)

## MCP tools

- `minify_diff` — pass `{ "text": "..." }`
- `minify_log` — pass `{ "text": "..." }`

## Library

```python
from lib.minify import minify_diff, minify_log, format_stats
text, stats = minify_diff(raw)
text, stats = minify_log(raw)
```
