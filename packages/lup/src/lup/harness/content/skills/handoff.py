"""Canonical declaration for the handoff skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.handoff",
    name="handoff",
    description="Hand a body of work to another session, with what it takes to resume it",
    tools=["Bash(uv run lup-devtools:*)", "Read", "Grep"],
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.TextPart(
                text=r"""# Handoff

Move a body of work to somebody else, recorded so they can pick it up without
asking you anything.

## What this is for

Not one task — """
            ),
            models.SkillInvocation(plugin="lup", skill="delegate"),
            models.TextPart(
                text=r""" is one task and is meant to be one line. This is the
larger thing: you are stopping, or somebody else is better placed, and what
has to cross is the work *plus* everything you learned that is not in the diff.

The failure it answers is expensive and quiet. The tasks arrive, the locks
arrive, and the receiver spends a day re-deriving three things you already
settled and re-trying two approaches you already ruled out. None of that is
visible in the code, so nothing else can carry it.

## Phase 1: See who is here

```sh
uv run lup-devtools coordination roster
```

Read `holding` on each row, not just `doing`. If the work you are handing over
overlaps what somebody else is holding, that is worth knowing before you write
the handoff rather than after.

A name nobody answers to leaves the work for whoever picks it up. That is a
real outcome and often the right one at the end of a session.

## Phase 2: Write it

```sh
uv run lup-devtools ledger handoff "<what this body of work is>" \
    --to <peer> \
    --open "<something still undecided>" \
    --result '{"statement": "...", "source": "...", "grade": "..."}' \
    --not-again "<an approach already tried and dropped>" \
    --task <task-id> \
    --path <path in scope>
```

- `--open` is **required, at least once.** A handoff with nothing open is not
  a handoff — you finished, and `ledger done` is the verb for that.
- `--result` is something you take as settled. Every one needs a **source** and
  a **grade**, because a result the receiver cannot check and cannot weigh is
  one they have to derive again. Grade it in whatever words this project uses,
  and grade it honestly — an explicit "I did not run this" is worth more than
  a confident label.
- `--not-again` is the cheapest thing here and the one that pays most. A dead
  end costs the receiver exactly what it cost you and is invisible everywhere
  else.
- `--task` is repeatable and moves that task's holder to the receiver.
- `--path` is repeatable. A path **you** hold moves with the work. A path
  **somebody else** holds is recorded as contested and reported back — it is
  not taken from them, because only a holder can release a lock.

## Phase 3: Read what it reports

- **`handed to <peer>`** — it went to somebody.
- **`transferred <id>`** — that task is now theirs.
- **`locked <path>`** — that lock moved.
- **`contested <path>`** — somebody else holds it. Both names are on the
  record now. Say so in your reply; it is not an error and not resolved.
- **`woken`** — the peer has been made to look.
- **an instruction naming `SendMessage`** — the peer runs a runtime no command
  can speak to, so carry it yourself with your own tool, to the address named.
- **a note saying it was left unheld** — nobody holds it and nobody will be
  told.

## Phase 4: Render it for whoever reads it

The record is one thing; who reads it changes only how it is written.

```sh
uv run lup-devtools ledger brief <handoff-id> --for peer
uv run lup-devtools ledger brief <handoff-id> --for detached
uv run lup-devtools ledger brief <handoff-id> --for person
```

- **`peer`** — a session in this repository. Ids stay as ids, because it can
  resolve them and they keep being true as the work moves.
- **`detached`** — an agent with no access to this repository. Everything a
  peer would look up is written out. Use this when you are briefing something
  that cannot read the tree.
- **`person`** — a file for the person to open.

If the `detached` rendering does not read as enough to work from, the record
is short something — fix the record, not the rendering.

## What not to do

**Never write a handoff file by hand.** That is what went stale in every
worked example this is derived from: a document written once while the thing
it described moved on. Record the handoff and render it.

**Do not hand over what you can finish.** A handoff is not a way to stop.
"""
            ),
        ],
    ),
)
