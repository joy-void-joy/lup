"""Canonical declaration for the clean-gone skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.clean-gone",
    name="clean-gone",
    description="Sweep every branch to one disposition — land unlanded work, clear merged ones",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=[
        "Bash(uv run lup-devtools:*)",
        "AskUserQuestion",
        "EnterWorktree",
        "Skill(lup:commit)",
        "Skill(lup:rebase)",
        "Skill(lup:merge)",
    ],
    argument_hint="[branch-name]",
    prompt=models.PromptDocument(
        parts=[
            models.TextPart(
                text=r"""# Branch Disposition Sweep

Resolve every local branch to exactly one disposition and act on it. Unlanded work and merged leftovers surface in the same pass, so no branch sits in a silent bucket waiting to go stale.

## Arguments

- **branch-name** (optional): a single branch to dispose of. If provided, runs in targeted mode. If omitted, sweeps every branch.

Raw arguments: `"""
            ),
            models.ArgumentsRef(),
            models.TextPart(
                text=r"""`

Parse the raw arguments: if non-empty, the first word is the **branch name**. Ignore remaining words.

## Process

### 1. Commit pending changes

Invoke `"""
            ),
            models.SkillInvocation(plugin="lup", skill="commit"),
            models.TextPart(
                text=r"""` to commit any uncommitted work before the sweep.

## Targeted Mode (branch name provided)

1. Run `uv run lup-devtools dev survey --json`.
2. Find the named branch. If it is absent, report and stop.
3. Show its `disposition` and `reason`, and confirm the matching action via AskUserQuestion.
4. Carry out that disposition's action from the table below.

## Full Sweep Mode (no argument)

### 2. Collect data

```bash
uv run lup-devtools dev survey --json
```

Every branch arrives with a `disposition` and a `reason` already computed. **Do not re-derive them** — the classifier is shared with `dev status`, so a judgement made here would drift from the one made there.

### 3. Present the sweep

One table covering every branch, ordered `LAND` first (that is the work at risk), then `DELETE`/`STALE`, then `KEEP`/`CURRENT`:

| Branch | Disposition | Unique | Diff | PR | Proposed action |

### 4. Act on each disposition

| Disposition | Meaning | Action |
| --- | --- | --- |
| `LAND` | Holds commits the integration branch lacks, with no PR driving it | Land it — step 5 |
| `DELETE` | Reached the integration branch, or its PR merged | `uv run lup-devtools dev delete <branch>` |
| `STALE` | Every commit already cherry-picked into the integration branch | Confirm, then delete |
| `KEEP` | Protected, or an open PR is already driving it | Leave alone |
| `CURRENT` | The branch checked out here | Never delete; warn if it would otherwise qualify |

### 5. Landing a LAND branch

Ask the user, per branch, which route to take:

- **Open a PR** — relocate into that branch's worktree: """
            ),
            models.RelocateSession(path="the survey's worktree field"),
            models.TextPart(
                text=r""". Create one first via `uv run lup-devtools dev worktree create <branch>` when `worktree` is null. Then run `"""
            ),
            models.SkillInvocation(plugin="lup", skill="rebase"),
            models.TextPart(
                text=r"""`.
- **Merge directly** — from the integration checkout, `"""
            ),
            models.SkillInvocation(plugin="lup", skill="merge"),
            models.TextPart(
                text=r""" <branch>`. Suits small, uncontroversial work that needs no review.
- **Drop it** — the work is not worth landing. Requires explicit confirmation, then delete.

Never choose a route on the user's behalf: a `LAND` branch by definition carries no PR expressing intent, so the intent has to come from them.

Land the oldest divergence first. Every branch that lands moves the integration branch, so the ones behind it re-diverge and their conflict surface grows.

### 6. Confirm and execute

Use AskUserQuestion before anything that deletes or pushes. Then carry out the approved actions.

### 7. Report results

What landed, what was deleted, and what was deliberately left alone.

## Guidelines

- Never force-delete without explicit user approval for that specific branch
- **Never delete a `LAND` branch unless the user explicitly chose to drop it** — it holds the only copy of that work
- Skip the current branch — warn the user instead
- Containment counts as landed only against the integration branch; riding inside a sibling that has not landed either is no reason to drop work
- For rebased branches, content may have reached the integration branch via a rebase PR even though `--is-ancestor` is false — the `DELETE` disposition already accounts for merged PRs
"""
            ),
        ]
    ),
)
