# Optional MCP wrapper around both brokers

`agent_token_usage_optimization/mcp_server.py` speaks **MCP JSON-RPC over stdio**
(no extra Python package required). Hosts like Claude Desktop, Cursor, and
other MCP clients can call the same tools as the CLI brokers.

## Tools

| Tool | Maps to |
|------|---------|
| `summary_search` | `summary_broker.py search` |
| `summary_grep` | `summary_broker.py grep` |
| `summary_read` | `summary_broker.py read` |
| `summary_rollup` | `summary_broker.py rollup` |
| `summary_list` | `summary_broker.py list` |
| `summary_hotspots` | `summary_broker.py hotspots` |
| `summary_semantic` | `summary_broker.py semantic` (needs embeddings index) |
| `broker_search` | `broker.py search` |
| `broker_outline` | `broker.py outline` |
| `broker_read` | `broker.py read` |
| `broker_summary` | `broker.py summary` |
| `broker_context_list` | list `summaries/repo_context/*.md` |
| `context_status` / `context_place` / `context_task` / `context_pack` | Layer 2 tiered context board |
| `minify_diff` / `minify_log` | Layer 3 minifiers |

## Install the skill first

```bash
./install.sh /path/to/your/project
```

The MCP server expects the skill under:

```text
<project>/skills/agent_token_usage_optimization/mcp_server.py
```

and uses **`cwd` = project root** so summary discovery and the symbol index resolve correctly.

## Claude Desktop example

Edit the Claude Desktop MCP config (path varies by OS) and add:

```json
{
  "mcpServers": {
    "ai-summarizer": {
      "command": "python3",
      "args": [
        "/abs/path/to/your/project/skills/agent_token_usage_optimization/mcp_server.py"
      ],
      "cwd": "/abs/path/to/your/project"
    }
  }
}
```

Optional env:

| Variable | Meaning |
|----------|---------|
| `AI_SUMMARIZER_REPO_ROOT` | Force repo root if `cwd` is wrong |

## Cursor / other hosts

Same pattern: command `python3`, args → absolute path to `mcp_server.py`,
working directory → the repo that contains `skills/agent_token_usage_optimization/`.

## Smoke test (line-delimited JSON-RPC)

```bash
cd /path/to/your/project
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 skills/agent_token_usage_optimization/mcp_server.py
```

You should see `initialize` result, then a `tools/list` result containing
`summary_search` and `broker_outline`.

## Notes

- The server is **read-oriented** (search/outline/read summaries and source slices).
  It does not run summarizers or apply edits.
- Prefer summary tools first; use `broker_*` when you need symbols or code slices.
- For `summary_semantic`, build the index first (see [embeddings_semantic_search.md](embeddings_semantic_search.md)).
