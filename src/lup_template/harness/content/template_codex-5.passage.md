## Editing Style

**Prefer small, atomic edits.** The PreToolUse hook decodes `apply_patch`'s complete command into before/after documents and applies the canonical edit policy. Safe changes with up to three real added lines are automatically allowed; protected paths, anti-patterns, marker changes, and full-file writes keep their guardrails.

- Split large changes into multiple small patches, one logical change each
- Separate concerns -- move imports in one patch, change logic in another
- Rename identifiers exhaustively and run `uv run pyright` to verify nothing dangles

