---
description: "Resolve inline feedback through isolated work"
---

Deferred notes — `# lup: defer: <text>` — are parked work, not open feedback, and the resolver entry excludes them from its inventory, so an editor can never be assigned one. That bare spelling is the default: nothing evaluates a wake condition mechanically, so `defer[<gate>]: <text>` is reserved for a real, externally-checkable gate ("until the v2 API ships") and never restates that this code might change again. Triage them before launching the resolver: read each note against the current state of the repository — its gate where it stated one, its own text where it did not — and when the work reads as due, propose waking it to the user. Waking is an explicit edit that removes the `defer` head so the note re-enters open feedback on the next run; anything still parked carries forward untouched, never re-litigated.

Run `uv run lup-devtools harness resolve --adapter claude`. The command accepts optional flags: `--run-id <id>` resumes a persisted run and `--accept`/`--reject` records the human decision on its review branch. It waits zero seconds by default and parks on material questions, printing each one beside the `# lup:` notes it was raised from, the concern's spec, and its acceptance criteria; rerun with the repeatable `--answer <question-id>=<value>` flag to answer them. `--admit <text>` admits work discovered mid-run in the human's own words and `--admit-note <file>:<line>` admits a note you wrote in the tree, both repeatable. Never pass `--wait` or `--supervise`; both hold a run open for a human instead of parking — `--wait` at the mailbox, `--supervise` at the page it opens. Launch it with `dangerouslyDisableSandbox: true`. Every session the run opens is a child of this call, and a session spawned inside the sandbox cannot create its own `~/.claude/session-env/<id>` — so each of its shell calls dies on `EROFS: read-only file system, mkdir`, leaving planners and workers unable to run a single command while still appearing to work.

## Relaying a parked question

The run parks rather than guessing, so every material question is a decision that belongs to the human. Never answer one yourself — and never merely transcribe one either. A prompt and a choice list, handed over as printed, reads as a decision with no stakes and cannot be judged.

**Measure before you relay.** The planner writes from notes, not from the tree, so every question's framing is a hypothesis you can check: read the code it concerns and measure what it asserts. A type probe shows whether the "redundant" overload is load-bearing or whether removing it widens every call site. A grep bounds how many sites a proposed rule would actually catch, and how many of those are correct by design. A count of the thing a note named as the worst case can demote it to a false positive outright. Measurement changes the answer often enough that relaying from the planner's prose alone is guessing with extra steps.

**Relay what it takes to judge cold.** For each option: what it means concretely, what it costs, what it collides with elsewhere in this same run, and which of the concern's acceptance criteria it satisfies or fails. Explain the underlying problem from scratch when the question is unfamiliar rather than building on context the human does not have, and put it in the terms they reason in rather than the planner's vocabulary.

**Give your own recommendation, marked as yours.** It is allowed to differ from the planner's, and it should when your investigation says so. When the option set mis-carves the problem, say that and offer the corrected option instead of defending the list — a wrong framing costs a whole extra round even when every detail in it is accurate. The choices are suggestions, not a menu: say so, and pass an answer in the user's own words whenever they give one.

**Relay the whole batch at once.** A run parks with all of its open questions together; asking them one at a time makes the human re-establish the same context for each.

## Work discovered while a run is parked

A parked run is when the most is known about what else needs doing. Admit that work into the run that found it: hand the run the new evidence and only that evidence is planned, so the run keeps its id, every answer already recorded, and every concern already completed. The admitted concern then passes the same approval and material-question gates as one from intake, and may depend on a concern this run has already finished.

The evidence is a `# lup:` note you write in the file it concerns, which keeps the concern traceable to code; an open issue by number, which keeps it traceable to what was filed; or the human's own words when neither carries them. The run records which, so a statement-grounded concern is distinguishable in review. Admission is accepted at any phase before integration — past that the review branch is assembled, and a fresh run is the honest answer.

So a concern discovered mid-run is never dropped and never a reason to restart. Restarting re-derives the inventory from scratch and discards every material answer already collected, which is the most expensive thing you can do at exactly the moment the run holds the most of them.

## Friction you hit during a run is an issue, not just an admission

A run exercises the resolver harder than anything else does, so it is where the harness's own defects surface. **File each one as an issue against this repository at the moment you meet it**, with the exact command, the exact error, the state it left behind, and what the recovery cost — observation rather than conclusion.

File it *and then* decide whether to admit it. The two do different work: an admission dies with the run, while an issue survives it and is picked up by the next intake, which is what closes the loop — friction becomes an issue, an issue becomes evidence, evidence becomes a concern, and the concern becomes the fix. Friction only admitted is friction that has to be rediscovered.

Intake takes every open issue except those labelled `resolver-skip`, so a filed issue needs no further wiring to reach the next run. `uv run lup-devtools dev issues` prints exactly what a run would take, without starting one. When a concern derived from an issue lands, the run comments on the issue naming the review branch — and never closes it, because a reviewer passing is not a human having read the code.
