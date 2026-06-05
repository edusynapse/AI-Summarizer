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
copy_shared "grok_repo_agent.py"
copy_shared "lib/__init__.py"
copy_shared "lib/languages.py"
copy_shared "lib/outline.py"
copy_shared "lib/search.py"
copy_shared "lib/summarize.py"
copy_shared "lib/summary_search.py"
copy_shared "repo/.gitignore"
copy_shared "summaries/README.md"
copy_shared "summaries/prompt_template.txt"
copy_shared "summaries/rollup_prompt_template.txt"
copy_shared "summaries/summarizer.py"
copy_shared "summaries/rollup_summarizer.py"
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
copy_template "repo/grok_clean_excludes.txt"
copy_template "summaries/config.json"
copy_template "summaries/rollups_config.json"

chmod +x "$DST_DIR/broker.py" "$DST_DIR/indexer.py" "$DST_DIR/summary_broker.py" "$DST_DIR/low_tier_agent.py" "$DST_DIR/grok_repo_agent.py" "$DST_DIR/summaries/summarizer.py" "$DST_DIR/summaries/rollup_summarizer.py" || true

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
echo "  run   python3 skills/agent_token_usage_optimization/broker.py index"
echo "  run   python3 skills/agent_token_usage_optimization/summaries/summarizer.py"
echo "  run   python3 skills/agent_token_usage_optimization/summaries/rollup_summarizer.py"
echo "  track skills/agent_token_usage_optimization/repo/index.sqlite if you commit the broker index"
echo "  ignore __pycache__/ and *.py[cod] in the target repo root .gitignore"
echo
echo "instruction profile: loose (default)"
echo "  switch with: $(cd "$(dirname "$0")" && pwd)/switch-agent-type.sh low  $TARGET"
echo "  check  with: $(cd "$(dirname "$0")" && pwd)/switch-agent-type.sh check $TARGET"
