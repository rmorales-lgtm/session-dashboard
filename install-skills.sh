#!/usr/bin/env bash
# Link the dashboard's skills into ~/.claude/skills so every Claude session can use them.
# Safe to run again. Never replaces a real directory or a link that points elsewhere.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
mkdir -p "$dest"
for skill in "$here"/skills/*/; do
  name="$(basename "$skill")"
  target="$dest/$name"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "${skill%/}" ]; then
    echo "ok       $name (already linked)"
  elif [ -e "$target" ] || [ -L "$target" ]; then
    echo "SKIPPED  $name: $target exists and is not this link" >&2
  else
    ln -s "${skill%/}" "$target"
    echo "linked   $name -> ${skill%/}"
  fi
done
