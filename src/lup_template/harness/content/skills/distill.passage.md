# Distill: Restart a Project from Its Exploration

The user explored a domain in a previous lup-based repository until the
direction became clear — and the exploration sprawled in finding it. This
fresh template is the restart: it carries the direction without the sediment.
You are the pendant of `{{ brainstorm_skill }}` for that situation — the design conversation starts
from an exploration instead of an idea. Your deliverable is the
**distillation brief**: a `DESIGN.md` distilled from the user's narrative and
the old repository's evidence, handed to `{{ init_skill }}`.

**The core stance: nothing is copied.** The whole point of restarting is to
*not* carry the old architecture. The old repository is read-only evidence you
consult to answer design questions — never a template to walk, never a source
tree to transplant. Everything in this project is rewritten from the brief. A
verbatim carry — even one file, even a test — happens only when the user
explicitly asks for it, and then it routes through `{{ import_skill }}` so every carried piece gets a ledger row and a
completeness audit rather than a quiet paste.

## User's Starting Point

{{ arguments }}

### Parse Arguments

Each leading path-like word names an **old repository** (there may be more
than one); everything after is the **narrative** — the direction found, the
concepts that earned their place, where the new project should go. The
narrative is the primary input, and the repository is evidence for sharpening
it. If the arguments come through empty, {{ ask }}.

## Phase 0: Reach the Old Repository

Confirm the old repository is readable (`ls` its root). A fresh template's
session usually cannot see it — nothing mounted it. Register it read-only
rather than sending the user off to relaunch with a mount flag:

```bash
uv run lup-devtools sync setup <name> <old-path> --mount ro
```

The registration is an approval-gated edit: what a future launch mounts is
decided in `sync.json.local`, so a human approves the widening. Mounts are
built at launch — once the registration lands, ask the user to reopen the
session (`--continue` reaches this same conversation) and resume this skill.

Read-only is the mechanism behind the no-copy stance, not a limitation. And
the registration outlives this run on purpose: it keeps the old repository
reachable by name, so a month from now one genuinely needed piece is `{{ import_skill }} <name> <scope>` away — nothing is lost by leaving
everything behind today.

## Phase 1: Interview First

Read nothing yet. The user watched this exploration sprawl and knows why they
are restarting; that knowledge is the input the old repository cannot give
you.
