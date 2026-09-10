<!-- Generated from lup_template.writeups by `uv run lup-devtools ledger writeup` — edit the source, not this file. See docs/harness.md. -->

# Corpus status

What this repository has recorded about itself: the questions still open, the claims it is prepared to be held to and where each stands, what is waiting on a person, and what has been corrected. Every figure here is the ledger's, read at generation with its standing beside it — cite the node, not this page.

## Open questions

| # | What | Standing | Node |
| --- | --- | --- | --- |
| 1 | **[A UserPromptSubmit hook on Claude Code could fold the roster and inject only what changed since the session's last prompt. Codex's generated plugin declares PreToolUse, PostToolUse and PermissionRequest and no prompt-time event, so its substitute needs measuring: the watcher's codex queue nudge, or nothing.](lup:roster-at-prompt)** — Should the roster reach a session at prompt time, and how on Codex? | open | `roster-at-prompt` |

## Claims

No claim is recorded.

## What needs a person

### Accounts to create

- [ ] Measure whether codex queue wakes an idle Codex session — docs/platform-differentiation.md carries the row and says what settles it. Needs a signed-in Codex session (codex login) on this machine.  `fe2634b9e4ab`

### Reviews owed

- [ ] Open the three surfaces in a real browser — ledger explore, dashboard, and resolve supervise against a persisted run, plus the exported explorer page from a file. The pages are type-checked, built, route-tested, and mounted under happy-dom; no human has opened one. Needs a machine with a browser.  `82e200567ada`

## Corrections

Nothing has been corrected.

Generated from this repository's ledger: 5 node(s), 0 edge(s); 0 corpus:claim; 0 corpus:correction; newest record 2026-09-10T11:18:02.172406+00:00. Regenerate with `uv run lup-devtools ledger writeup`.
