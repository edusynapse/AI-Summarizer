# Embeddings-backed semantic search (summary corpus)

Keyword search (`summary_broker.py search`) finds exact tokens. Semantic search
ranks **LLM summaries** (and rollups) by vector similarity so paraphrases and
related concepts surface even without shared keywords.

## Quick start (zero extra deps)

Default backend is **`hashing`** — feature-hash bag-of-tokens, no API keys:

```bash
# after summaries exist under skills/.../summaries/repo/
python3 skills/agent_token_usage_optimization/embeddings_index.py build
python3 skills/agent_token_usage_optimization/embeddings_index.py search "session expiry middleware"
python3 skills/agent_token_usage_optimization/summary_broker.py semantic "session expiry middleware"
python3 skills/agent_token_usage_optimization/embeddings_index.py status
```

Index files (gitignored):

```text
skills/agent_token_usage_optimization/summaries/embeddings/index.json
skills/agent_token_usage_optimization/summaries/embeddings/vectors.bin
```

Rebuild after large summary refreshes:

```bash
python3 skills/agent_token_usage_optimization/embeddings_index.py build
# full re-embed:
python3 skills/agent_token_usage_optimization/embeddings_index.py build --force
```

Unchanged document SHA-1s reuse vectors when backend/model/dim match.

## Config

Template (preserved on reinstall):

```text
skills/agent_token_usage_optimization/summaries/embeddings_config.json
```

| Field | Meaning |
|-------|---------|
| `backend` | `hashing` \| `openai` \| `ollama` \| `st` |
| `dim` | Vector size for `hashing` (default 384) |
| `model` | OpenAI model id when `backend=openai` |
| `openai_base_url` | OpenAI-compatible base (default api.openai.com) |
| `ollama_base_url` / `ollama_model` | Local Ollama embeddings |
| `st_model` | sentence-transformers model name |
| `include_rollups` | Index `summaries/rollups/` too |
| `max_chars_per_doc` | Truncate long summaries before embed |

Env overrides: `EMBED_BACKEND`, `EMBED_MODEL`, `OPENAI_BASE_URL`,
`OPENAI_API_KEY` / `EMBED_API_KEY`.

## Better backends

### OpenAI-compatible API

```json
{ "backend": "openai", "model": "text-embedding-3-small" }
```

```bash
export OPENAI_API_KEY=sk-...
python3 skills/agent_token_usage_optimization/embeddings_index.py build --force
```

Works with any OpenAI-compatible `/v1/embeddings` host via `openai_base_url`.

### Ollama (local)

```json
{ "backend": "ollama", "ollama_model": "nomic-embed-text" }
```

```bash
ollama pull nomic-embed-text
python3 skills/agent_token_usage_optimization/embeddings_index.py build --force
```

### sentence-transformers (local)

```bash
pip install sentence-transformers
```

```json
{
  "backend": "st",
  "st_model": "sentence-transformers/all-MiniLM-L6-v2"
}
```

## MCP

Tool `summary_semantic` on the optional MCP server — see [mcp_brokers.md](mcp_brokers.md).

## Design choices

- Indexes **summaries**, not raw source (token-cheap, stable text).
- Stdlib-only path (`hashing` + struct-packed vectors) for open-source installs.
- True neural embeddings remain optional via HTTP or local packages.
