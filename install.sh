#!/usr/bin/env bash
# Install / update the agent_token_usage_optimization skill in a target repo.
#
# Usage:  ./install.sh /path/to/target_repo
#
# Shared files (broker.py, indexer.py, lib/*, summaries/summarizer.py,
# summaries/rollup_summarizer.py, summaries/*_prompt_template.txt,
# summaries/README.md, repo_context/README.md,
# .gitignores, top-level READMEs) are always overwritten.
#
# Per-repo files (repo/config.json, summaries/config.json,
# summaries/rollups_config.json, and any hand-curated repo_context/*.md beyond
# the starter README) are NEVER overwritten if they already exist — only
# created on first install.
#
# Generated artifacts (repo/index.sqlite, repo/summaries/, summaries/manifest.json,
# summaries/repo/, summaries/rollups/, summaries/rollups_manifest.json) are
# never touched.

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/target_repo" >&2
  exit 1
fi

TARGET="$1"
if [[ ! -d "$TARGET" ]]; then
  echo "error: target repo not found: $TARGET" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "$0")" && pwd)/agent_token_usage_optimization"
DST_DIR="$TARGET/skills/agent_token_usage_optimization"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "error: source skill dir missing: $SRC_DIR" >&2
  exit 1
fi

mkdir -p "$DST_DIR/lib" "$DST_DIR/repo" "$DST_DIR/summaries/repo_context"

# --- always overwrite (shared) ---
copy_shared() {
  local rel="$1"
  cp "$SRC_DIR/$rel" "$DST_DIR/$rel"
  echo "  overwrote: $rel"
}

copy_shared "README.md"
copy_shared "broker.py"
copy_shared "indexer.py"
copy_shared "lib/__init__.py"
copy_shared "lib/languages.py"
copy_shared "lib/outline.py"
copy_shared "lib/search.py"
copy_shared "lib/summarize.py"
copy_shared "repo/.gitignore"
copy_shared "summaries/README.md"
copy_shared "summaries/prompt_template.txt"
copy_shared "summaries/rollup_prompt_template.txt"
copy_shared "summaries/summarizer.py"
copy_shared "summaries/rollup_summarizer.py"
copy_shared "summaries/.gitignore"
copy_shared "summaries/repo_context/README.md"

# --- never overwrite if present (per-repo) ---
copy_template() {
  local rel="$1"
  if [[ -e "$DST_DIR/$rel" ]]; then
    echo "  preserved (already exists): $rel"
  else
    cp "$SRC_DIR/$rel" "$DST_DIR/$rel"
    echo "  installed: $rel"
  fi
}

copy_template "repo/config.json"
copy_template "summaries/config.json"
copy_template "summaries/rollups_config.json"

chmod +x "$DST_DIR/broker.py" "$DST_DIR/indexer.py" "$DST_DIR/summaries/summarizer.py" "$DST_DIR/summaries/rollup_summarizer.py" || true

echo
echo "installed → $DST_DIR"
echo
echo "next steps in $TARGET:"
echo "  edit  skills/agent_token_usage_optimization/repo/config.json"
echo "  edit  skills/agent_token_usage_optimization/summaries/config.json"
echo "  edit  skills/agent_token_usage_optimization/summaries/rollups_config.json"
echo "  fill  skills/agent_token_usage_optimization/summaries/repo_context/*.md"
echo "  run   python3 skills/agent_token_usage_optimization/broker.py index"
echo "  run   python3 skills/agent_token_usage_optimization/summaries/summarizer.py"
echo "  run   python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py"
