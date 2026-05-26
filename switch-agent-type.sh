#!/usr/bin/env bash
# Switch the agent instruction profile in a target repo between:
#   high → loose  (minimal guidance, trusts the model)
#   low  → strict (numbered enforcement, hard rules)
#
# Operates on both CLAUDE.md and AGENTS.md at the target repo root,
# refreshing only the content between the BEGIN/END markers so any
# surrounding user-authored content is preserved.
#
# Templates are read from <target>/skills/agent_token_usage_optimization/
# templates/ (installed by install.sh), so the switch is self-contained:
# you can run this against any repo that has the skill installed.
#
# Usage:
#   switch-agent-type.sh high|low  /path/to/target_repo [--force]
#   switch-agent-type.sh check     /path/to/target_repo
#
# --force overrides the "file is custom, no skill block" prompt and
# forces a full overwrite of CLAUDE.md / AGENTS.md.

set -euo pipefail

BEGIN_MARK="<!-- BEGIN agent_token_usage_optimization -->"
END_MARK="<!-- END agent_token_usage_optimization -->"

usage() {
  cat >&2 <<EOF
usage:
  $0 high|low  /path/to/target_repo [--force]
  $0 check     /path/to/target_repo

  high   → loose profile (minimal guidance, frontier-model friendly)
  low    → strict profile (numbered enforcement, small-model friendly)
  check  → report current profile of CLAUDE.md, AGENTS.md, and any stray
           AGENTS*.md / CLAUDE*.md found elsewhere in the tree
  --force  on a custom file (no skill block), overwrite without prompting
EOF
  exit 1
}

[[ $# -lt 2 ]] && usage

MODE="$1"
TARGET="$2"
FORCE=0
[[ "${3:-}" == "--force" ]] && FORCE=1

[[ ! -d "$TARGET" ]] && { echo "error: target repo not found: $TARGET" >&2; exit 1; }
TARGET="$(cd "$TARGET" && pwd)"

SKILL_DIR="$TARGET/skills/agent_token_usage_optimization"
TPL_DIR="$SKILL_DIR/templates"

if [[ ! -d "$TPL_DIR" ]]; then
  echo "error: templates not found at $TPL_DIR" >&2
  echo "       run install.sh against this repo first" >&2
  exit 1
fi

# Report which profile a given file currently carries.
# Echoes: loose | strict | unknown | custom | none
profile_of() {
  local f="$1"
  [[ ! -f "$f" ]] && { echo "none"; return; }
  if ! grep -qF "$BEGIN_MARK" "$f"; then
    echo "custom"; return
  fi
  local p
  p=$(awk '
    /<!-- profile: loose -->/  { print "loose";  exit }
    /<!-- profile: strict -->/ { print "strict"; exit }
  ' "$f")
  [[ -z "$p" ]] && p="unknown"
  echo "$p"
}

# List stray AGENTS*.md / CLAUDE*.md anywhere in the tree (excluding the
# two managed root files, the skill's own templates, .git, and node_modules).
list_strays() {
  find "$TARGET" -type f \( -iname 'AGENTS*.md' -o -iname 'CLAUDE*.md' \) \
    -not -path "$TARGET/CLAUDE.md" \
    -not -path "$TARGET/AGENTS.md" \
    -not -path "*/.git/*" \
    -not -path "*/node_modules/*" \
    -not -path "$SKILL_DIR/*" \
    2>/dev/null | sort
}

scan_strays() {
  local strays; strays="$(list_strays)"
  if [[ -z "$strays" ]]; then
    echo "stray instruction files: none"
    return
  fi
  echo "stray instruction files (these are ALSO read by agents — review them):"
  while IFS= read -r f; do
    echo "  $f → profile: $(profile_of "$f")"
  done <<< "$strays"
}

if [[ "$MODE" == "check" ]]; then
  echo "target: $TARGET"
  echo "  CLAUDE.md  → profile: $(profile_of "$TARGET/CLAUDE.md")"
  echo "  AGENTS.md  → profile: $(profile_of "$TARGET/AGENTS.md")"
  scan_strays
  exit 0
fi

case "$MODE" in
  high) PROFILE="loose"  ;;
  low)  PROFILE="strict" ;;
  *)    usage ;;
esac

TPL="$TPL_DIR/$PROFILE.md"
[[ ! -f "$TPL" ]] && { echo "error: template missing: $TPL" >&2; exit 1; }

apply_to() {
  local f="$1"
  local cur; cur="$(profile_of "$f")"
  case "$cur" in
    none)
      cp "$TPL" "$f"
      echo "created  $f [→ $PROFILE]"
      ;;
    loose|strict|unknown)
      # Has our marker block — refresh in place, preserve surrounding content.
      local tmp; tmp="$(mktemp)"
      awk -v begin="$BEGIN_MARK" -v end="$END_MARK" -v tpl="$TPL" '
        BEGIN { skip=0 }
        index($0, begin) { skip=1;
          while ((getline line < tpl) > 0) print line;
          close(tpl); next }
        index($0, end)   { skip=0; next }
        !skip { print }
      ' "$f" > "$tmp" && mv "$tmp" "$f"
      if [[ "$cur" == "$PROFILE" ]]; then
        echo "no-op    $f [already $PROFILE — block re-stamped]"
      else
        echo "switched $f [$cur → $PROFILE]"
      fi
      ;;
    custom)
      if [[ $FORCE -eq 1 ]]; then
        cp "$TPL" "$f"
        echo "FORCED overwrite $f [→ $PROFILE]"
        return
      fi
      echo "warning: $f exists with no skill block — file appears fully custom."
      if [[ -t 0 ]]; then
        printf "  choose: [a]ppend block / [o]verwrite file / [s]kip (default s): "
        read -r choice
      else
        choice="s"
        echo "  (non-interactive — defaulting to skip; pass --force to overwrite)"
      fi
      case "${choice,,}" in
        a|append)    { echo; cat "$TPL"; } >> "$f"; echo "  appended  $f [→ $PROFILE]" ;;
        o|overwrite) cp "$TPL" "$f";                echo "  overwrote $f [→ $PROFILE]" ;;
        *)                                           echo "  skipped   $f (untouched)" ;;
      esac
      ;;
  esac
}

apply_to "$TARGET/CLAUDE.md"
apply_to "$TARGET/AGENTS.md"

echo
echo "final state:"
echo "  CLAUDE.md  → profile: $(profile_of "$TARGET/CLAUDE.md")"
echo "  AGENTS.md  → profile: $(profile_of "$TARGET/AGENTS.md")"
scan_strays
echo
echo "note: open a NEW conversation/session in your IDE for the change to take effect."
echo "      (instruction files are loaded at session start, not per turn.)"
