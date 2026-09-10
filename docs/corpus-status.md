<!-- Generated from lup_template.writeups by `uv run lup-devtools ledger writeup` — edit the source, not this file. See docs/harness.md. -->

# Corpus status

What this repository has recorded about itself: the questions still open, the claims it is prepared to be held to and where each stands, what is waiting on a person, and what has been corrected. Every figure here is the ledger's, read at generation with its standing beside it — cite the node, not this page.

## Open questions

No question is open.

## Claims

| # | What | Standing | Node |
| --- | --- | --- | --- |
|  | **[The generated plugin registers a UserPromptSubmit group carrying a shell guard (coordination_changes.sh) that exits where the repository has no roster and otherwise runs the verbatim fold lup.coordination.changes, which keeps one last-look file per session under the coordination directory's looks/ and prints hookSpecificOutput.additionalContext holding only what differs from that session's previous prompt: contested paths under this checkout first, then paths a peer holds here, arrivals, departures and redescriptions; the first prompt is a baseline carrying one pointer to coordination_peers, and a quiet roster prints nothing. Measured by tests/unit/test_roster_prompt_hook.py, which runs the rendered guard from inside a git repository over a store the typed writers produced and reads the envelope back; the event's JSON shape is the one https://code.claude.com/docs/en/hooks documents under UserPromptSubmit. Not measured: the context's arrival in a live interactive session, which no non-interactive launch on this machine could observe.](lup:roster-at-prompt-claude)** — On Claude Code the roster's changes reach a session at each prompt, through a UserPromptSubmit hook whose stdout is measured | unsupported | `roster-at-prompt-claude` |
|  | **[https://developers.openai.com/codex/hooks redirects (308) to https://learn.chatgpt.com/docs/hooks, which lists SessionStart, SessionEnd, PreToolUse, PermissionRequest, PostToolUse, PreCompact, PostCompact, UserPromptSubmit, SubagentStart, SubagentStop, Stop and Interrupt, states that UserPromptSubmit runs when the user submits text with session_id, cwd, prompt and hook_event_name on stdin, that matcher is not read for this event, and that hookSpecificOutput.additionalContext on stdout at exit 0 is added as context under a default limit near 2,500 tokens per hook. So the Codex plugin registers the same coordination_changes.sh under UserPromptSubmit and carries the same verbatim fold, and the rendered script's stdout is measured by the same test as Claude's. What rests on the documentation alone is that Codex fires the event and delivers the context: no Codex session is signed in on this machine, so no live observation exists. Between prompts an idle Codex session is still reachable by coordination watch --as-run through codex queue, the wake path it declares, which is a nudge on top of the record rather than the roster's changes.](lup:roster-at-prompt-codex)** — On Codex the same guard and fold render under its documented UserPromptSubmit event; documented, not measured | unsupported | `roster-at-prompt-codex` |

## What needs a person

### Accounts to create

- [ ] Measure whether codex queue wakes an idle Codex session — docs/platform-differentiation.md carries the row and says what settles it. Needs a signed-in Codex session (codex login) on this machine.  `fe2634b9e4ab`

### Reviews owed

- [ ] Open the three surfaces in a real browser — ledger explore, dashboard, and resolve supervise against a persisted run, plus the exported explorer page from a file. The pages are type-checked, built, route-tested, and mounted under happy-dom; no human has opened one. Needs a machine with a browser.  `82e200567ada`

## Corrections

Nothing has been corrected.

Generated from this repository's ledger: 7 node(s), 2 edge(s); 2 corpus:claim; 0 corpus:correction; newest record 2026-09-10T11:58:26.857707+00:00. Regenerate with `uv run lup-devtools ledger writeup`.
