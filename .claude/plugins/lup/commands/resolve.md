---
allowed-tools: Bash(uv run lup-devtools:*), Read, Edit, Glob, Grep, AskUserQuestion, Agent
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

Work file by file, top to bottom. Two habits before you start editing:

- **Interview first.** For any non-trivial concern, ask precise questions (`AskUserQuestion`) to pin down exactly what the user means. Several small clarifying questions beat one wrong fix.
- **Fan out for breadth.** When a concern spans many files or calls for an ontology revision, dispatch subagents (`Agent`) to investigate and/or implement in parallel, then synthesize.

For each note:

1. **Read** the `read_start`-`read_end` window so you understand what the note refers to. Read wider if the answer needs it.
2. **Classify and act:**
   - **Clarity complaint** ("unclear why this is here", "what is this for?", "confusing", "hard to follow") → the fix is **structural, never an explanatory comment**. Do not annotate the code to explain it. Instead:
     - Revise the *ontology*: is this function/class even needed? Is the control flow straight, or tangled? Could it be renamed, inlined, split, or deleted?
     - Rewrite so the code reads clearly **from scratch** — understandable with no comments and no knowledge of its history. A file should read like a workflow.
     - A comment is usually a patch over unclear structure; reach for one only when the structure genuinely cannot carry the meaning.
   - **Instruction** ("simplify this", "rename to X", "drop this field") → make the change.
   - **Question** ("why is this here?", "is this still needed?", "any problems?") → investigate and answer. If the answer implies a change, make it. If it is a judgment call, present your finding and recommendation with `AskUserQuestion` and act on the reply.
   - **Brainstorm / open-ended** ("brainstorm more X", "run me through this") → engage the user with `AskUserQuestion` (or a written answer if they only asked for an explanation). Do not silently guess.
   - **Ambiguous / underspecified** → do NOT guess. Use `AskUserQuestion` to confirm intent first.
3. **Remove the note** (the marker line and any merged continuation lines) in the same edit that addresses it.

Each edit that removes a marker triggers a permission prompt by design — that is the verification checkpoint. Keep edits small and self-explanatory so they can be approved at a glance.

## Phase 4: Confirm and report

1. Re-run `uv run lup-devtools dev comments`.
2. Keep going while notes remain that you can resolve — address each, then remove its marker.
3. **Never delete a note to make the scan pass.** Removing a marker without doing the work is the one thing you must not do.
4. When you are done and notes still remain (the user deferred them, you are blocked, or you could not address them), **stop and report them explicitly** — list each with its `file:line` and why it is unresolved. Do not quietly delete them to clean up the scan.
5. Run `uv run lup-devtools dev check`. If you intentionally left notes for the user, its `claude comments` check will fail — that is expected, and is not a reason to delete the notes.

## Guidelines

- **The note is the spec** — do exactly what it asks, nothing more.
- **Clarity is structural, not a comment** — if a note flags confusion, fix the code's shape (naming, flow, decomposition) so it reads on its own. Explaining unclear code with a comment is the wrong fix.
- **A file should read like a workflow** — comments are usually patches; prefer to make the code self-evident, and delete code that isn't needed rather than leaving it dead.
- **One concern per edit** — do not fold unrelated fixes together.
- **When in doubt, ask** — a wrong "fix" is worse than a question.
- **Never delete a note you did not address** — if you cannot resolve it, report it to the user with its `file:line`; removing the marker without doing the work defeats the entire purpose.
- **A note may be wrong** — if acting on it would break something or contradicts the code, surface that instead of blindly complying.
