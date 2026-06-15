---
allowed-tools: Bash(uv run lup-devtools:*), Bash(git:*), Read, Edit, Write, Glob, Grep, AskUserQuestion, Agent, Workflow, Skill
description: Cluster inline review notes into concerns, fan out isolated fixes, verify each, and merge
---

# Resolve Inline Feedback

Turn every `# claude:` / `// claude:` note in the codebase into a fix, verify each one independently, and clear only the notes that are genuinely resolved.

These notes are how the user queues feedback: they read through files and drop `# claude: <note>` anywhere (any language — `ignore` is reserved for the anti-pattern escape hatch, everything else is for you). At scale, working note-by-note is both slow and **myopic**: many notes are the *same* concern seen from different files, and a note about one line ("why is this an `int`?") usually implies a codebase-wide change ("give domain primitives named type aliases"). So this command works at the level of **concerns**, not comments: it clusters the notes, fans the editing out to isolated worktrees in parallel, verifies each diff independently, and merges only what's confirmed.

The human-judgment steps stay in this conversation; the parallel editing runs in a background **workflow** that cannot pause to ask questions. So the shape is:

**snapshot → triage → decide with you → execute (workflow) → merge & clear → report.**

## Phase 1 — Snapshot

```
uv run lup-devtools dev comments --commit
```

Records every note in one commit so the fan-out worktrees branch from a clean, shared base. If the working tree has unrelated uncommitted changes you do not want swept into that snapshot, **stop and tell the user first**. Then capture the base ref the workflow will branch from and diff against:

```
git rev-parse HEAD
```

If the scan is empty, report that and stop.

## Phase 2 — Triage into concerns

Get the raw notes:

```
uv run lup-devtools dev comments --json
```

Dispatch a single **triage `Agent`** (the planner). It reads each note's `read_start`–`read_end` window and returns a **plan**: a list of concerns. For each concern:

- `id` — short slug (becomes branch `resolve/<id>`)
- `title` — one line
- `spec` — the **generalized, marker-free** task: the *underlying* issue stated at the ontology level, not the literal note. (A note questioning one `int` → "give domain primitives named type aliases wherever a raw built-in stands in for a concept.")
- `files` — the blast radius (starting points, not a fence)
- `notes` — every `{file, line, text}` this concern subsumes
- `needs_user` — true when resolving it needs a decision only the user can make (taste, architecture direction, ambiguous intent)

Two rules for the planner, because they are what keep the later merge safe:

- **Generalize, don't transcribe.** One concern may subsume many notes across many files. The dominant theme in this repo — *"backend concerns belong behind an ABC in `lup`, not matched or leaked into `core` and the template"* — is **one** concern spanning ~10 files, not eighteen separate ones.
- **Union overlapping concerns.** Any two concerns whose `files` overlap must be merged into one. Parallel worktrees that touch the same file would collide at merge — so a cross-cutting refactor is *one* concern fixed in *one* worktree, and the concerns that run in parallel have **disjoint file sets**.

Write the plan to `tmp/resolve-plan.json` and read it back, so the rest of the run works from a concrete, inspectable artifact.

## Phase 3 — Decide with the user

Before anything is edited, settle every `needs_user` concern **in one batch** — do not drip dozens of questions mid-fix. For each, use `AskUserQuestion` to surface the concern, your reading of it, and a recommendation. Fold the answer into that concern's `spec` (so the editor receives a self-contained, already-decided task) and mark it ready.

- A concern that produces **no code change** (a pure brainstorm or explanation) is handled here in the conversation; its note is cleared only once the outcome lands somewhere real (code, docs, or a recorded decision) — never just deleted.
- If the user defers a concern, drop it from the ready set and report it later — leave its notes in place.

## Phase 4 — Execute (background workflow)

Hand the ready, autonomous concerns to the execute workflow:

```
Workflow(
  scriptPath=".claude/workflows/commands/resolve.js",
  args={ "base": "<HEAD from Phase 1>", "concerns": [ ...ready concerns... ] },
)
```

It runs one **worktree-isolated editor per concern** (each fixes the whole pattern and is told to leave `# claude:` markers untouched), then an **independent verifier** per concern that judges the diff against the *original* notes. It merges nothing — it returns a **manifest**, one entry per concern: `{ id, title, branch, accepted, generalized, reason, residual, notes }`. Watch it with `/workflows`; you are notified when it finishes.

## Phase 5 — Merge accepted branches & clear their markers

For each manifest entry with `accepted: true`, **in this conversation** (so the edits run under the permission hooks):

1. Merge its branch: `git merge --no-ff resolve/<id>`. Branches are disjoint by design, so this is clean. If a conflict does arise, resolve it with the `/lup:merge` guidance and **audit for dropped code** — never let a merge silently lose a feature (see CLAUDE.md § Merge Conflict Resolution).
2. Clear that concern's notes: `Edit` out each marker line listed in its `notes`. Removing a marker trips the marker-count hook — that prompt is the final review checkpoint, and you only reach it for work an independent verifier already accepted.

Do **not** touch markers for concerns that were not accepted.

## Phase 6 — Report

```
uv run lup-devtools dev comments
uv run lup-devtools dev check
```

List everything still unresolved with its `file:line` and *why*: rejected by the verifier (quote its `residual`), deferred by the user, or never committed. If you intentionally left notes, `dev check`'s `claude comments` gate will fail — that is expected, not a reason to delete them.

## Guidelines

- **Concern, not comment, is the unit.** Generalizing up front is what prevents myopic one-line fixes; the planner does it once, before any editing.
- **Resolution is decoupled from the marker.** Editors never resolve a note by deleting it — they are told hands-off and run on throwaway worktrees. A note is cleared only after an independent verifier accepts the work and you merge it. **Never delete a note to make the scan pass** — that is the one thing you must not do.
- **Clarity notes are structural.** "unclear why this is here" is fixed by reshaping the code (rename, inline, split, delete) so it reads on its own — not by adding an explanatory comment. Bake that into the concern's `spec`.
- **A note may be wrong.** If acting on it would break something or contradicts the code, surface that instead of complying.
- **Small runs use the same flow.** A handful of notes simply yields a handful of concerns; the workflow fans out fewer agents. A single trivial instruction you can also just do inline.
- **When in doubt, ask** — a wrong fix is worse than a question.
