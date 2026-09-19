"""Canonical declaration for the update skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.update",
    name="update",
    description="Move every carrier of lup to one upstream commit, and resolve what it leaves",
    tools=[
        "Bash(git:*, uv run lup-devtools:*, uv sync:*, uv lock:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "AskUserQuestion",
        "Skill(lup:commit)",
    ],
    argument_hint="[commit]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.TextPart(
                text=r"""# Update from Upstream

Three things in this project came from lup and each used to move on its own:
the library by a pin, the native trees by a regeneration, and the copied half —
`src/` and `tests/`, stamped out at initialization — only when somebody read
upstream's commits and retyped them. Separately is how they came apart, and a
commit that changed the library *and* its caller arrived as a breakage rather
than as work anybody chose.

One command moves all three to one commit. What is left for a person is what
no command can decide: a merge conflict in a file both sides changed, and a
migration whose instruction is a sentence.

## 1. Commit what is pending

Invoke `"""
            ),
            models.SkillInvocation(plugin="lup", skill="commit"),
            models.TextPart(
                text=r"""` first. The update merges a branch into this one, and a
merge cannot start over uncommitted work — nor could you tell afterwards which
changes were yours.

## 2. Run the update

```bash
uv run lup-devtools dev update
```

Optionally `--commit <sha>` to pin every carrier at one named commit rather
than at the tip of the branch this project follows.

What it does, in this order, and the order is the whole point:

1. **Resolves the pin** and reads back the commit `uv.lock` got. Everything
   after this is compiled at *that* commit, so the three carriers cannot land
   at three different places.
2. **Syncs the environment**, so the library on disk is the one just pinned.
3. **Compiles upstream's copied half** at that commit onto the `lup-scaffold`
   branch and merges it. The merge base is the commit this project last took,
   which is what makes this an ordinary merge rather than a diff against
   nothing.
4. **Regenerates the native trees**, under the library that just landed.

A conflicted merge stops it before the regeneration, deliberately: the trees
are compiled from declarations the merge has not finished writing.

**If this project has never adopted a scaffold branch**, the update says so.
Root one once, at the commit the project was stamped from:

```bash
uv run lup-devtools dev scaffold adopt --base <commit>
```

## 3. Resolve the conflicts it lists

Every conflict is a file upstream changed that this project also changed. Read
both sides and keep both intents — the bias is inclusion, and a rename on one
side must not swallow an addition on the other. `"""
            ),
            models.SkillInvocation(plugin="lup", skill="merge"),
            models.TextPart(
                text=r"""` carries the decision tree.

Two things are worth knowing before starting:

- **A declaration is where a conflict belongs.** The harness catalog and the
  tool-group list are files this project is *supposed* to have edited, so a
  conflict there is the mechanism working. A conflict anywhere else is worth a
  second look: it usually means something was copied that could have been
  imported.
- **Never resolve a generated tree by hand.** Take either side, run
  `uv run lup-devtools harness generate all`, and let `harness check all`
  confirm it settled.

Commit the merge, then run `dev update` again so the regeneration it skipped
happens under the merged declarations.

## 4. Apply the migrations it lists

A migration is a break two trees cannot describe between them — a signature
that gained required parameters, a refusal that split. The update prints each
one with the reason it was taken and the steps that answer it. A step carrying
a command can be run; a step that is a sentence is a decision about this
project's code, so make it here rather than looking for a command.

Module moves are not in that list and need no decision, being derived. Where
this project holds imports from before a reorganisation, the exact invocation
that repoints them is

```bash
uv run lup-devtools dev migrate map <the-commit-you-came-from>..
```

## 5. Verify, then commit

"""
            ),
            models.WatchOutput(command="uv run lup-devtools dev check"),
            models.TextPart(
                text=r"""

The `carrier drift` row is the one to read: it names the commit the library is
pinned at and the commit the copied half was merged at, and says nothing at all
when they agree.

Then `"""
            ),
            models.SkillInvocation(plugin="lup", skill="commit"),
            models.TextPart(
                text=r"""`, keeping the merge and any migration work as separate
commits — they are separate claims, and a reader bisecting a regression needs
to know which one carried it.

## Guidelines

- **Nothing here reads upstream's commits.** Reviewing another repository's
  history for what is worth having is the other direction, and it has its own
  skill: `"""
            ),
            models.SkillInvocation(plugin="lup", skill="import"),
            models.TextPart(
                text=r"""` with no arguments sweeps every tracked project.
- **A defect in lup is fixed in lup.** Working around one in the copied half
  moves this project further from upstream, which is what makes the next update
  expensive. `"""
            ),
            models.SkillInvocation(plugin="lup", skill="upstream"),
            models.TextPart(
                text=r"""` cuts the fix in a worktree of lup itself.
- **The copied half is merged, never retyped.** If something upstream changed
  is missing here, the scaffold branch did not carry it — say so rather than
  hand-porting it, because a hand-port diverges from upstream permanently and
  silently.
"""
            ),
        ],
    ),
)
