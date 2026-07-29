---
name: resolve
description: "Resolve inline feedback through isolated work"
---

Deferred notes — `# lup: defer[<wake condition>]: <text>` — are parked work, not open feedback, and the resolver entry excludes them from its inventory, so an editor can never be assigned one. Triage them before launching the resolver: read each note's wake condition against the current state of the repository, and when one reads as met, propose waking it to the user. Waking is an explicit edit that removes the `defer[...]` head so the note re-enters open feedback on the next run; an unmet condition carries forward untouched, never re-litigated.

Run `uv run lup-devtools harness resolve --adapter codex`. The command accepts optional flags: `--run-id <id>` resumes a persisted run and `--accept`/`--reject` records the human decision on its review branch. It waits zero seconds by default and parks on material questions — relay them to the user verbatim, never answer them yourself, then rerun with the repeatable `--answer <question-id>=<value>` flag. Relay each question with everything printed alongside it — the `# lup:` notes it was raised from, the concern's spec, and its acceptance criteria — because a bare prompt reads as a decision with no stakes and cannot be judged. Choices are the planner's suggestions, not a menu: say so, and pass an answer in the user's own words when they give one. Never pass `--wait` or `--supervise`; both hold a run open for a human instead of parking — `--wait` at the mailbox, `--supervise` at the page it opens.
