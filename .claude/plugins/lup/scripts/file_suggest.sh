#!/bin/bash
# File suggestion provider for Claude Code @ completion.
# Uses git ls-files + fzf for fuzzy matching. Includes refs/ entries.
# Dependencies: jq (parses the {"query": ...} payload on stdin), fzf, git.
# A missing refs/ directory or zero fzf matches yields empty output, exit 0.

# claude: Do I need to do anything for this to work? Does it work out of the blue?
set -euo pipefail

QUERY=$(jq -r '.query // ""')
cd "${CLAUDE_PROJECT_DIR:-.}"

{
  git --no-pager ls-files
  if [ -d refs ]; then
    for d in refs/*/; do
      if [ -L "${d%/}" ]; then
        echo "${d%/}"
      fi
    done
  fi
} | fzf --filter "$QUERY" | head -15 || true
