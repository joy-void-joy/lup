---
description: "Resolve inline feedback through isolated work"
---

Deferred notes — `# lup: defer[<wake condition>]: <text>` — are parked work, not open feedback, and the resolver entry excludes them from its inventory, so an editor can never be assigned one. Triage them before launching the resolver: read each note's wake condition against the current state of the repository, and when one reads as met, propose waking it to the user. Waking is an explicit edit that removes the `defer[...]` head so the note re-enters open feedback on the next run; an unmet condition carries forward untouched, never re-litigated.

Invoke Workflow(scriptPath=".claude/workflows/commands/resolve.js", args={}). The workflow accepts optional args: {"run_id": "<id>"} resumes a persisted run and {"accept": true} or {"accept": false} records the human decision on its review branch.
