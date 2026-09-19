## Pyright Diagnostics

Nothing type-checks an edit for you here. Codex names the files it changed inside the patch envelope, and decoding one validates its context against the document on disk -- which is already the rewritten version by the time an edit could be observed, so there is no reading of what changed to check. Run `uv run pyright` after every substantive change and act on what it reports.

The `codeintel` tools do answer definitions, usages, and types, resolving imports and aliases as the checker does. Prefer them over word-boundary searches, and confirm a guess against them rather than acting on it. A relative path resolves against the checkout being edited, which the hook publishes on every patch; pass an absolute path when you mean a file somewhere else.

