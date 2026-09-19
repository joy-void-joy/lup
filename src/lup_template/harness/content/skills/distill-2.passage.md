
Then the questions only a restart has: {{ ask }}.

## Phase 2: Archaeology

Now read the old repository — to sharpen the interview and draft the brief,
never to inventory code for carrying:

- `git -C <old-path> log --oneline --reverse` — the story: what was tried, in
  what order, what got reverted or abandoned
- Its `DESIGN.md`, `README`, and guidance — what it thought it was
- `# lup: defer:` markers and open `# lup:` feedback — what it knew was
  unfinished
- `notes/`, `tmp/` briefings, and feedback-loop state — what its sessions
  learned

You are extracting three things: decisions and their reasons, dead ends and
why they died, and domain facts that were expensive to learn. When something
in the old code answers a design question, read it, state the answer in your
own words in the brief, and close the file. Findings worth reacting to go back
to the user as questions, not as an inventory.

## Phase 3: The Distillation Brief

Write `DESIGN.md` at the project root, in the same structure `{{ brainstorm_skill }}` uses — Purpose, Architecture, Tools, Delegation,
Output Model, Session Behavior, Reflection, Success & Feedback, Environment,
Open Questions, only the sections actually discussed — plus the two sections a
restart owes to its history:

```markdown
## Graveyard
What the exploration tried and this project deliberately leaves behind — one
line each, with the reason. This is what stops a future session from
re-exploring a dead end.

## Field Notes
Domain facts that were expensive to learn and are free to carry: API quirks,
constants, format discoveries, rate limits, auth shapes. Knowledge, never
code.
```

When one exploration splits into several successors, the Graveyard and Field
Notes are shared history — write them the same in each successor's brief — and
a `## Scope` section states what *this* successor takes and what its siblings
take, so neither drifts into the other's ground.

Show the user the brief and fold in their corrections before handing off.

## Phase 4: Hand Off

Summarize what was decided and what remains open, then point the user to `{{ init_skill }}`, which reads `DESIGN.md` and skips every interview
question the brief already answers.

## Principles

- **Rewrite, don't carry.** The brief is the only conduit from old to new. If
  a design question tempts you to copy, the brief is missing a sentence —
  write the sentence.
- **The graveyard is a deliverable.** What was deliberately left behind, with
  reasons, is worth as much as what survives: it is the record that keeps the
  restart from sprawling the same way.
- **Ask, then read.** The user's narrative outranks the repository's evidence;
  archaeology sharpens questions rather than replacing them.
- **Scope at agent speed.** The restart is not a chance to shrink the vision —
  implementation runs at agent pace, and the clean slate is for clarity, not
  for a cut-down POC.
