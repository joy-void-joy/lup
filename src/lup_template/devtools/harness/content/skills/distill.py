"""Canonical declaration for the distill skill."""

import lup.harness.models as models
from lup_template.devtools.harness.content.skills.discovery import discovery_parts

SKILL = models.Skill(
    id="skill.distill",
    name="distill",
    description="Restart from an explored repo — distill its direction into a fresh design",
    arguments=[
        models.Argument(
            name="arguments",
            description="Old repository path(s) and the narrative of the direction found",
            required=False,
        ),
    ],
    tools=[
        "Bash(git:*, ls:*, find:*, uv run lup-devtools:*)",
        "Read",
        "Grep",
        "Glob",
        "Write",
        "Edit",
        "Agent",
        "AskUserQuestion",
        "Skill(lup:import)",
    ],
    argument_hint="<old-repo-path> [more-paths] <narrative of the direction found>",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.TextPart(
                text=r"""# Distill: Restart a Project from Its Exploration

The user explored a domain in a previous lup-based repository until the
direction became clear — and the exploration sprawled in finding it. This
fresh template is the restart: it carries the direction without the sediment.
You are the pendant of `"""
            ),
            models.SkillInvocation(plugin="lup", skill="brainstorm"),
            models.TextPart(
                text=r"""` for that situation — the design conversation starts
from an exploration instead of an idea. Your deliverable is the
**distillation brief**: a `DESIGN.md` distilled from the user's narrative and
the old repository's evidence, handed to `"""
            ),
            models.SkillInvocation(plugin="lup", skill="init"),
            models.TextPart(
                text=r"""`.

**The core stance: nothing is copied.** The whole point of restarting is to
*not* carry the old architecture. The old repository is read-only evidence you
consult to answer design questions — never a template to walk, never a source
tree to transplant. Everything in this project is rewritten from the brief. A
verbatim carry — even one file, even a test — happens only when the user
explicitly asks for it, and then it routes through `"""
            ),
            models.SkillInvocation(plugin="lup", skill="import"),
            models.TextPart(
                text=r"""` so every carried piece gets a ledger row and a
completeness audit rather than a quiet paste.

## User's Starting Point

"""
            ),
            models.ArgumentsRef(),
            models.TextPart(
                text=r"""

### Parse Arguments

Each leading path-like word names an **old repository** (there may be more
than one); everything after is the **narrative** — the direction found, the
concepts that earned their place, where the new project should go. The
narrative is the primary input, and the repository is evidence for sharpening
it. If the arguments come through empty, """
            ),
            models.AskUser(
                question="which repository this restart distills from, and "
                "their narrative of the direction it found"
            ),
            models.TextPart(
                text=r""".

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
reachable by name, so a month from now one genuinely needed piece is `"""
            ),
            models.SkillInvocation(plugin="lup", skill="import"),
            models.TextPart(
                text=r""" <name> <scope>` away — nothing is lost by leaving
everything behind today.

## Phase 1: Interview First

Read nothing yet. The user watched this exploration sprawl and knows why they
are restarting; that knowledge is the input the old repository cannot give
you.
"""
            ),
            *discovery_parts(),
            models.TextPart(
                text=r"""
Then the questions only a restart has: """
            ),
            models.AskUser(
                question="which of the old project's concepts survive into the "
                "restart and which die with it, with the reason for each — and "
                "whether this restart is the only successor or one of several "
                "splitting the exploration"
            ),
            models.TextPart(
                text=r""".

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

Write `DESIGN.md` at the project root, in the same structure `"""
            ),
            models.SkillInvocation(plugin="lup", skill="brainstorm"),
            models.TextPart(
                text=r"""` uses — Purpose, Architecture, Tools, Delegation,
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

Summarize what was decided and what remains open, then point the user to `"""
            ),
            models.SkillInvocation(plugin="lup", skill="init"),
            models.TextPart(
                text=r"""`, which reads `DESIGN.md` and skips every interview
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
"""
            ),
        ],
    ),
)
