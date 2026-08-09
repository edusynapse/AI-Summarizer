#!/usr/bin/env bash
# Install / update the agent_token_usage_optimization skill in a target repo.
#
# Usage:  ./install.sh /path/to/target_repo
#
# Shared files (broker.py, indexer.py, mcp_server.py, embeddings_index.py,
# context_manager.py, minify.py, lib/*, summaries/summarizer.py, parallel runners,
# rollup_summarizer.py, summaries/postprocess_summaries.py,
# summaries/*_prompt_template.txt, summaries/README.md, repo_context/README.md,
# repo/workspace.env.example, .gitignores, top-level READMEs) are always overwritten.
# NOTE: grok_repo_agent.py is intentionally NOT installed (parked under scratch/parked/).
#
# Per-repo files (repo/config.json, summaries/config.json,
# summaries/rollups_config.json, summaries/embeddings_config.json,
# repo/workspace.env (local paths — never overwrite), and any
# hand-curated repo_context/*.md beyond the starter README) are NEVER
# overwritten if they already exist — only created on first install.
#
# Generated artifacts are never overwritten. `repo/index.sqlite` is intended to
# be tracked after `broker.py index`; Python bytecode stays ignored by the
# target repo's root .gitignore.

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

mkdir -p "$DST_DIR/lib" "$DST_DIR/repo" "$DST_DIR/summaries/repo_context" "$DST_DIR/templates"

# --- always overwrite (shared) ---
copy_shared() {
  local rel="$1"
  cp "$SRC_DIR/$rel" "$DST_DIR/$rel"
  echo "  overwrote: $rel"
}

copy_shared "README.md"
copy_shared "broker.py"
copy_shared "indexer.py"
copy_shared "summary_broker.py"
copy_shared "low_tier_agent.py"
# grok_repo_agent.py is PARKED under scratch/parked/ — do not install
copy_shared "mcp_server.py"
copy_shared "embeddings_index.py"
copy_shared "context_manager.py"
copy_shared "minify.py"
copy_shared "lib/__init__.py"
copy_shared "lib/languages.py"
copy_shared "lib/outline.py"
copy_shared "lib/search.py"
copy_shared "lib/summarize.py"
copy_shared "lib/summary_search.py"
copy_shared "lib/embeddings_search.py"
copy_shared "lib/context_tiers.py"
copy_shared "lib/minify.py"
copy_shared "lib/workspace_config.py"
copy_shared "lib/adjacency.py"
copy_shared "lib/summary_postprocess.py"
copy_shared "repo/.gitignore"
copy_shared "repo/workspace.env.example"
copy_shared "summaries/README.md"
copy_shared "summaries/prompt_template.txt"
copy_shared "summaries/rollup_prompt_template.txt"
copy_shared "summaries/summarizer.py"
copy_shared "summaries/rollup_summarizer.py"
copy_shared "summaries/postprocess_summaries.py"
copy_shared "summaries/run_grok_cli_summaries.sh"
copy_shared "summaries/run_agy_cli_summaries.sh"
copy_shared "summaries/.gitignore"
copy_shared "summaries/repo_context/README.md"
copy_shared "templates/loose.md"
copy_shared "templates/strict.md"

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
# repo/grok_clean_excludes.txt parked with grok_repo_agent
copy_template "summaries/config.json"
copy_template "summaries/rollups_config.json"
copy_template "summaries/embeddings_config.json"
# workspace.env: copy from example once only (local machine paths)
if [[ ! -e "$DST_DIR/repo/workspace.env" ]]; then
  if [[ -f "$DST_DIR/repo/workspace.env.example" ]]; then
    cp "$DST_DIR/repo/workspace.env.example" "$DST_DIR/repo/workspace.env"
    echo "  installed: repo/workspace.env (from example — edit WORKSPACE_SIBLINGS)"
  fi
else
  echo "  preserved (already exists): repo/workspace.env"
fi

chmod +x \
  "$DST_DIR/broker.py" \
  "$DST_DIR/indexer.py" \
  "$DST_DIR/summary_broker.py" \
  "$DST_DIR/low_tier_agent.py" \
  "$DST_DIR/mcp_server.py" \
  "$DST_DIR/embeddings_index.py" \
  "$DST_DIR/context_manager.py" \
  "$DST_DIR/minify.py" \
  "$DST_DIR/summaries/summarizer.py" \
  "$DST_DIR/summaries/rollup_summarizer.py" \
  "$DST_DIR/summaries/postprocess_summaries.py" \
  "$DST_DIR/summaries/run_grok_cli_summaries.sh" \
  "$DST_DIR/summaries/run_agy_cli_summaries.sh" \
  || true

# --- agent instruction files (CLAUDE.md + AGENTS.md) ---
# Both are auto-loaded by their respective runtimes into every session in the
# target repo (CLAUDE.md → Claude Code & Antigravity-on-Claude;
# AGENTS.md → Codex, Antigravity, Cursor, Aider). Install uses the LOOSE
# profile by default; flip a repo with switch-agent-type.sh.
TEMPLATE="$SRC_DIR/templates/loose.md"
BEGIN_MARK="<!-- BEGIN agent_token_usage_optimization -->"
END_MARK="<!-- END agent_token_usage_optimization -->"

install_instruction_file() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    cp "$TEMPLATE" "$f"
    echo "created: $f [profile=loose]"
    return
  fi
  if grep -qF "$BEGIN_MARK" "$f"; then
    local tmp; tmp="$(mktemp)"
    awk -v begin="$BEGIN_MARK" -v end="$END_MARK" -v tpl="$TEMPLATE" '
      BEGIN { skip=0 }
      index($0, begin) { skip=1;
        while ((getline line < tpl) > 0) print line;
        close(tpl); next }
      index($0, end)   { skip=0; next }
      !skip { print }
    ' "$f" > "$tmp" && mv "$tmp" "$f"
    echo "refreshed block in: $f [profile=loose]"
    return
  fi
  echo "warning: $f exists and has no agent_token_usage_optimization block."
  if [[ -t 0 ]]; then
    printf "  choose: [a]ppend block / [o]verwrite file / [s]kip (default s): "
    read -r choice
  else
    choice="s"
    echo "  (non-interactive shell — defaulting to skip)"
  fi
  case "${choice,,}" in
    a|append)    { echo; cat "$TEMPLATE"; } >> "$f"; echo "  appended block to: $f" ;;
    o|overwrite) cp "$TEMPLATE" "$f";                echo "  overwrote: $f" ;;
    *)                                                echo "  skipped: $f (left untouched)" ;;
  esac
}

echo
install_instruction_file "$TARGET/CLAUDE.md"
install_instruction_file "$TARGET/AGENTS.md"

echo
echo "installed → $DST_DIR"
echo
echo "next steps in $TARGET:"
echo "  edit  skills/agent_token_usage_optimization/repo/config.json"
echo "  edit  skills/agent_token_usage_optimization/summaries/config.json"
echo "  edit  skills/agent_token_usage_optimization/summaries/rollups_config.json"
echo "  fill  skills/agent_token_usage_optimization/summaries/repo_context/*.md"
echo "  edit  skills/agent_token_usage_optimization/repo/workspace.env   # multi-repo siblings (optional)"
echo "  or    $(cd "$(dirname "$0")" && pwd)/configure_workspace.sh $TARGET --id … --sibling id=/path"
echo "  run   python3 skills/agent_token_usage_optimization/broker.py index   # symbols + adjacency.sqlite (THIS repo only)"
echo "  run   python3 skills/agent_token_usage_optimization/summaries/postprocess_summaries.py"
echo "  run   python3 skills/agent_token_usage_optimization/summaries/summarizer.py --dry-run"
echo "  run   bash skills/agent_token_usage_optimization/summaries/run_grok_cli_summaries.sh"
echo "        # parallel path via grok CLI. MODEL=… PARALLEL=…"
echo "  run   bash skills/agent_token_usage_optimization/summaries/run_agy_cli_summaries.sh"
echo "        # parallel path via agy CLI. Select the model ONCE with agy /model first;"
echo "        # this runner asserts it and never writes settings.json. PARALLEL=… ONLY=…"
echo "  run   python3 skills/agent_token_usage_optimization/summaries/summarizer.py   # agy/gemini serial"
echo "  run   python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py"
echo "  run   python3 skills/agent_token_usage_optimization/indexer.py"
echo "  track skills/agent_token_usage_optimization/repo/index.sqlite if you commit the broker index"
echo "  ignore __pycache__/ and *.py[cod] in the target repo root .gitignore"
echo
echo "instruction profile: loose (default)"
echo "  switch with: $(cd "$(dirname "$0")" && pwd)/switch-agent-type.sh low  $TARGET"
echo "  check  with: $(cd "$(dirname "$0")" && pwd)/switch-agent-type.sh check $TARGET"
