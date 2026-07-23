---
description: "Resolve inline feedback through isolated work"
---

Deferred notes — `# lup: defer[<wake condition>]: <text>` — are parked work, not open feedback. Triage them instead of re-litigating them: read each note's wake condition against the current state of the repository. When a condition reads as met, plan a dedicated concern that proposes waking the note and leave the wake decision to the user; otherwise carry the note forward untouched. An editor strips a deferred note only when its assigned concern explicitly wakes it.

Invoke Workflow(scriptPath=".claude/workflows/commands/resolve.js", args={}). The workflow accepts optional args: {"run_id": "<id>"} resumes a persisted run and {"accept": true} or {"accept": false} records the human decision on its review branch.
