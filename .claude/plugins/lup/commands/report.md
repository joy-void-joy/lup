---
description: "Write the report of everything left to implement, rewritten whole under tmp/, after a long session or after implementing a plan"
allowed-tools: Bash(uv run lup-devtools:*), Read, Write
---

# Report what is left

Write down everything there still is to implement, in a file under `tmp/`
named for the work it covers.

Two occasions, one output. After a long session, the report is written from
scratch: what the session opened, what it left half-done, and what the
surfaces can still see outstanding. After "please implement
tmp/plan_something.md", the same report is written again from scratch, saying
what remains of that plan — **rewritten whole, never appended to**, so a line
that is no longer true cannot survive by being further down the file.

## 1. Name the file

`tmp/<the work it covers>.md`. What is left of `tmp/plan_relocated_notes.md`
is `tmp/relocated_notes_remaining.md`; a session spent on the report surface
leaves `tmp/report_surface_remaining.md`. The name is what the next session
reads first — from a directory listing, before opening anything — so it says
what the report is about rather than that it is a report.

Two things follow from naming it. Reporting the same work again reuses its
name, so the new reading replaces the old one instead of standing beside it
disagreeing. And where the invocation names a file — an existing briefing, a
report an earlier session left — that file is the target, rewritten in place,
because it is the one somebody is already reading.

## 2. Ask the surfaces

```bash
uv run lup-devtools report --write tmp/<name>.md --force
```

`--force` because a report already standing at that name carries the *last*
session's prose, and rewriting whole is the whole point of this step. Without
it the command refuses, naming the sections it did not write: the walked half
rebuilds from the tree in a second, and the other half is what one session
knew, in a directory nothing versions. That refusal is for whoever reaches for
`--write` outside this skill; here you are about to write section 4 back on
top, so say so.

The path has to sit under `tmp/` or the command refuses it: that is where a
report is gitignored, and one written anywhere else lands in the next commit
as a tracking file.

This is the half no session can see from memory, reading every surface that
already answers for one topic:

- **Open notes** — Review feedback still asking for something, at the site it concerns.
- **Deferred work** — Work parked at its own site, with the gate that would wake it.
- **Unverified claims** — Notes claimed solved, awaiting the pass that retires one.
- **Stale artifacts** — Generated trees the typed source has moved out from under.
- **Unlanded branches** — Work committed where the integration branch has not taken it.
- **Resolver leases** — Concerns a run is holding, which nothing else should pick up.

It reports what this tree can act on: a note inside a generated artifact is
the same note twice, so only the source one counts.

## 3. Read what it wrote

Read the file you just named. Those sections are the ground truth about the
repository — do not re-derive them, contradict them, or drop one because it
was empty. An empty topic is an answer.

## 4. Rewrite the file whole

Write that same file again, in full, with every section from step 2 intact and
one more added at the end:

```markdown
## From this session

- What was implemented, and what of it is unfinished.
- What was decided and has not been written down anywhere a scan can see.
- What the next session has to do first, and what it needs to know to do it.
```

Where a plan was being implemented, that section is what is left of the plan:
each item still open, and for each, where the work stopped. An item that is
done does not appear — the report says what is left, not what happened.

Use `Write`, not `Edit`. Rewriting whole is what keeps the file honest, and
an edit to one line of a stale report leaves the rest of it stale.

## Guidelines

- **One report per piece of work, named for it.** Under `tmp/`, which is
  scratch: gitignored, so it reaches no diff, no reviewer, and no commit. A
  second file about work a standing report already covers is two reports
  disagreeing, and a `TODO.md`, a backlog, or a roadmap is the same thing
  under another name — a tracking file parks work where no workflow will
  surface it again.
- **Never append.** A report that grew is a report nobody can trust the top
  of. Every invocation replaces the whole file.
- **Work that belongs in the code goes in the code.** A request about one
  site is a `# lup:` note there, and work deliberately parked is a
  `# lup: defer:` note there. Step 2 then finds it every time, where a line
  in this file would be found only by whoever opens it.
- **Say what is left, not what was done.** A summary of the session belongs
  in the reply; this file is read by whoever picks the work up next.
