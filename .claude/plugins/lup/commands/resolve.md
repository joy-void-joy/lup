---
allowed-tools: Bash(uv run lup-devtools:*), Bash(git:*), Read, Edit, Write, Glob, Grep, AskUserQuestion, Agent, Workflow, Skill
description: Cluster inline review notes into concerns, fan out isolated fixes, verify each, and merge
---

# Resolve Inline Feedback

Turn every `# claude:` / `// claude:` note in the codebase into a fix, verify each one independently, and clear only the notes that are genuinely resolved.

These notes are how the user queues feedback: they read through files and drop `# claude: <note>` anywhere (any language — `ignore` is reserved for the anti-pattern escape hatch, everything else is for you). At scale, working note-by-note is both slow and **myopic**: many notes are the *same* concern seen from different files, and a note about one line ("why is this an `int`?") usually implies a codebase-wide change ("give domain primitives named type aliases"). So this command works at the level of **concerns**, not comments: it clusters the notes, fans the editing out to isolated worktrees in parallel, verifies each diff independently, surfaces them for your review, and integrates only what you approve — onto a dedicated branch you merge when it's ready.

The human-judgment steps stay in this conversation; the parallel editing runs in a background **workflow** that cannot pause to ask questions. So the shape is:

**snapshot → triage → decide with you → execute (workflow) → review with you → approve & integrate → clean up → report.**

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

Get the raw notes — each entry carries a `context` field with the surrounding source, so you rarely need to open the files yourself:

```
uv run lup-devtools dev comments --json
```

Dispatch a single **triage `Agent`** (the planner). It reads each note's `context` window and returns a **plan**: a list of concerns. For each concern:

- `id` — short slug (becomes branch `resolve/<id>`)
- `title` — one line
- `spec` — the **generalized, marker-free** task: the *underlying* issue stated at the ontology level, not the literal note. (A note questioning one `int` → "give domain primitives named type aliases wherever a raw built-in stands in for a concept.")
- `files` — the blast radius (starting points, not a fence)
- `notes` — every `{file, line, text}` this concern subsumes
- `needs_user` — true when resolving it needs a decision only the user can make (taste, architecture direction, ambiguous intent)

The one rule for the planner, because it is what keeps the work coherent:

- **Generalize, don't transcribe.** One concern may subsume many notes across many files. The dominant theme in this repo — *"backend concerns belong behind an ABC in `lup`, not matched or leaked into `core` and the template"* — is **one** concern spanning ~10 files, not eighteen separate ones. Cluster notes by the *underlying issue*, not by the file they sit in.

Concerns may freely **overlap in files**. Worktree isolation exists precisely so two editors can touch the same file and have the changes reconciled at merge — so never split or shrink a concern just to keep file sets disjoint. A cross-cutting refactor is *one* concern; two notes that are the same issue are *one* concern.

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

It runs one **worktree-isolated editor per concern** as the `resolve-editor` subagent. The editor works **autonomously** — the permission hooks auto-allow its Edits/Writes and its git/test/lup-devtools commands so it never prompts you, while keeping anti-pattern denials and the `Edit(tmp/…)` prompt in force. It can fix notes that live in protected files (`CLAUDE.md`, `pyproject.toml`, `.claude/`); your Phase-6 review is where you sign off. Each editor's **first step strips its own concern's markers** from its worktree (via `dev comments --clear`), so it fixes the generalized spec — never the literal note — and cannot "resolve" anything by deleting a marker. Then an **independent verifier** per concern judges the diff against the *original* notes and records, for each note, **how it was addressed** — that mapping feeds your review.

It merges nothing — it returns a **manifest**, one entry per concern: `{ id, title, spec, branch, committed, accepted, generalized, reason, residual, summary, files_changed, swept_beyond_scope, note_findings, notes }`. Watch it with `/workflows`; you are notified when it finishes.

## Phase 5 — Review with you

The verifier is **advisory — you are the gate.** Build one **HTML review** so you can see every concern's implementation before anything merges.

For each manifest entry that `committed`, gather its diff against the snapshot base:

```
git diff --stat <base>...resolve/<id>
git diff <base>...resolve/<id>
```

Write a single self-contained `tmp/resolve-review.html`, then tell the user the path and offer to open it. Give each concern a section showing:

- the **title** and the generalized **spec**
- the **original notes** it subsumes, each paired with the verifier's matching **`note_findings.how`** — *this* is "how each comment was addressed"
- the editor's **summary**, **files_changed**, and any **swept_beyond_scope**
- the **diffstat** and the full **diff** (in a `<pre>`, lightly colored by leading `+`/`-`)
- the verifier's verdict: **accepted**, **generalized**, **reason**, and **residual**

Order verifier-accepted concerns first, then the doubtful ones, then any concern that did not commit. Keep it static (inline CSS, no external assets) so it opens straight from disk.

## Phase 6 — Approve & integrate (per-concern gate)

Nothing merges until you approve it, and your approval is what clears a concern's notes — never a silent side effect.

**Resolve the integration branch** — the work lands here, *not* on your working branch:

- If `HEAD` is already a `review/resolve-*` branch, **reuse it** (a refining re-run accumulates onto it).
- Otherwise create one from the snapshot base: `git checkout -b review/resolve-<base-shortsha> <base>`.

Then, with the review open, walk the committed concerns and ask in **batches** via `AskUserQuestion` — for each: **Approve** (merge it) or **Skip** (leave its notes). Surface the verifier's verdict and residual so the choice is informed; a concern the verifier doubted is still yours to approve or skip.

For each **approved** concern, merge its branch **into the integration branch**:

```
git merge --no-ff resolve/<id>
```

Concerns overlap, so **expect conflicts** — resolve them with the `/lup:merge` decision tree and **audit for dropped code** (see CLAUDE.md § Merge Conflict Resolution). The merge carries in that concern's marker removals, so **its notes clear as the consequence of your approval**. **Skipped** concerns are never merged — their notes stay.

## Phase 7 — Clean up

The editor worktrees committed, so they are *not* auto-removed. For every concern you **merged** or **skipped**, drop its worktree and branch:

```
git worktree remove <path>      # path from `git worktree list`
git branch -D resolve/<id>
```

Keep the branches of any concern you **deferred** (so its work survives), and **never** delete the integration branch. If a branch holds work you might still want, confirm before deleting.

## Phase 8 — Report

Tell the user where the work landed and how to finish:

- the **integration branch** name, and the command to merge it into your working branch when it's good:
  `git checkout <your-branch> && /lup:merge review/resolve-<base-shortsha>`
- everything still unresolved, with its `file:line` and *why*: **skipped** by you, **deferred**, doubted by the verifier (quote its `residual`), or never committed.

```
uv run lup-devtools dev comments
uv run lup-devtools dev check
```

Your working branch is untouched apart from the Phase-1 snapshot commit, so you can keep adding `# claude:` notes and re-run (point at the integration branch — Phase 6 reuses it). `dev check`'s `claude comments` gate will list the still-open notes; that is expected, not a reason to delete them.

## Guidelines

- **Concern, not comment, is the unit.** Generalizing up front is what prevents myopic one-line fixes; the planner does it once, before any editing.
- **The editor never sees its own notes.** Markers are stripped from its worktree at fork, and it is handed only the generalized spec — so it fixes the issue, not the wording, and cannot clear a note by deleting it. Notes clear only when **you approve** a concern and its branch merges into the integration branch. The strip tool (`dev comments --clear`) refuses to run outside a `resolve/*` branch, so notes can never be silently cleared from a real checkout. **Never delete a note to make the scan pass** — that is the one thing you must not do.
- **You are the gate, not the verifier.** The verifier's verdict and per-note `how` populate the review; the merge decision is yours, per concern. A concern the verifier doubted is still yours to approve, and one it accepted is still yours to skip.
- **Clarity notes are structural.** "unclear why this is here" is fixed by reshaping the code (rename, inline, split, delete) so it reads on its own — not by adding an explanatory comment. Bake that into the concern's `spec`.
- **A note may be wrong.** If acting on it would break something or contradicts the code, surface that instead of complying.
- **Small runs use the same flow.** A handful of notes simply yields a handful of concerns; the workflow fans out fewer agents. A single trivial instruction you can also just do inline.
- **When in doubt, ask** — a wrong fix is worse than a question.
