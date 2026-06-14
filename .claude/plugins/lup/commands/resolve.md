---
allowed-tools: Bash(uv run lup-devtools:*), Read, Edit, Glob, Grep, AskUserQuestion
description: Work through inline review comments and clear them all
---

# Resolve Inline Feedback

Address every `# claude:` / `// claude:` note left in the codebase, then ensure none remain.

These notes are how the user queues feedback: they read through files and drop `# claude: <note>` comments anywhere (any language — the keyword `ignore` is reserved for the anti-pattern escape hatch, everything else is for you). Your job is to act on each one and remove it.

## Phase 1: Snapshot the prompts

Before changing anything, capture the notes in their own commit so there is a record of what was asked (squash or rebase it away later if you like):

```
uv run lup-devtools dev comments --commit
```

This stages the comment-bearing files and commits them with a message listing every prompt. If the working tree has unrelated uncommitted changes you do not want swept into that snapshot, stop and tell the user first.

## Phase 2: Scan

Run `uv run lup-devtools dev comments --json`. Each item has:

- `file`, `start_line`, `end_line` — where the note lives (a marker plus any comment lines merged below it)
- `read_start`, `read_end` — the window to read for context
- `text` — the merged note

If the list is empty, report that and stop.

## Phase 3: Address each note

Work file by file, top to bottom. For each note:

1. **Read** the `read_start`-`read_end` window so you understand what the note refers to. Read wider if the answer needs it.
2. **Classify and act:**
   - **Instruction** ("simplify this", "rename to X", "drop this field") → make the change.
   - **Question** ("why is this here?", "is this still needed?", "any problems?") → investigate and answer. If the answer implies a change, make it. If it is a judgment call, present your finding and recommendation with `AskUserQuestion` and act on the reply.
   - **Brainstorm / open-ended** ("brainstorm more X", "run me through this") → engage the user with `AskUserQuestion` (or a written answer if they only asked for an explanation). Do not silently guess.
   - **Ambiguous / underspecified** → do NOT guess. Use `AskUserQuestion` to confirm intent first.
3. **Remove the note** (the marker line and any merged continuation lines) in the same edit that addresses it.

Each edit that removes a marker triggers a permission prompt by design — that is the verification checkpoint. Keep edits small and self-explanatory so they can be approved at a glance.

## Phase 4: Confirm none remain

1. Re-run `uv run lup-devtools dev comments`.
2. If any remain:
   - The user explicitly deferred them → list them and say why.
   - Otherwise → keep going. The job is not done until the scan is clean.
3. Run `uv run lup-devtools dev check` to confirm nothing broke (it also fails while any notes remain).

## Guidelines

- **The note is the spec** — do exactly what it asks, nothing more.
- **One concern per edit** — do not fold unrelated fixes together.
- **When in doubt, ask** — a wrong "fix" is worse than a question.
- **Never delete a note you did not address** — removing the marker without doing the work defeats the entire purpose.
- **A note may be wrong** — if acting on it would break something or contradicts the code, surface that instead of blindly complying.
