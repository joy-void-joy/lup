"""Canonical declaration for the land skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.land",
    name="land",
    description="Land every branch that has not reached the integration branch, and clear the ones that have",
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
    argument_hint="[branch-name ...]",
    prompt=models.PromptDocument(
        parts=[
            models.TextPart(
                text=r"""# Land Every Branch

Drive every local branch to its terminal state. Each one is classified by whether its commits have reached the integration branch — the ones that have not get landed, the ones that have get cleared — so no branch sits in a silent bucket waiting to go stale.

## Arguments

- **branch-name ...** (optional): one or more branches to dispose of. If any are provided, runs in targeted mode over all of them. If omitted, sweeps every branch.

Raw arguments: `"""
            ),
            models.ArgumentsRef(),
            models.TextPart(
                text=r"""`

Parse the raw arguments into a list of **branch names**: split on whitespace and commas, dropping bare connectors (`and`, `&`, `+`). Every remaining token names a branch. An empty list means full sweep mode; otherwise targeted mode runs over the whole list.

## Process

### 1. Commit pending changes

Invoke `"""
            ),
            models.SkillInvocation(plugin="lup", skill="commit"),
            models.TextPart(
                text=r"""` to commit any uncommitted work before the sweep.

## Targeted Mode (branch names provided)

1. Run `uv run lup-devtools dev survey --json`.
2. Resolve every named branch against the survey. Report each name that matches nothing; stop only when none of them resolve.
3. Show every resolved branch's `disposition` and `reason` in one table, then """
            ),
            models.RequestApproval(
                action="carrying out the actions those dispositions imply",
                reason="the branches may hold work the user has not looked at",
            ),
            models.TextPart(
                text=r"""
4. Carry out each disposition's action from the table below, taking every `LAND` branch through step 6.

## Full Sweep Mode (no argument)

### 2. Collect data

```bash
uv run lup-devtools dev survey --json
```

Every branch arrives with a `disposition` and a `reason` already computed. **Do not re-derive them** — the classifier is shared with `dev status`, so a judgement made here would drift from the one made there.

### 3. Reconcile against the runs holding branches

Read `runs` before you read `branches`. Each entry is a resolver run holding branches out of the sweep, and `alive` says whether anything is still answerable for them.

A run with `alive: false` holds work that no verb here reaches: it is not landing on its own, and nothing will retire its leases. Report it before the table — the run id, how many branches, and `uv run lup-devtools harness resolve status --run-id <id>` for what it was doing when it stopped — and ask what should happen to the run before offering any per-branch action. Landing its branches by hand bypasses the join machinery the run never ran, which is the whole reason the lease holds them.

Do not present a dead run's branches as a to-do list. One decision about the run is the honest question; twenty-six decisions about its branches is the same question asked in a form that hides what it is.

### 4. Present the sweep

One table covering every branch, ordered `LAND` first (that is the work at risk), then `DELETE`/`STALE`, then `KEEP`/`CURRENT`:

| Branch | Disposition | Unique | Diff | PR | Proposed action |

**Group the `LAND` rows by the run holding them**, where `runs` gives one, and label the group with the run rather than repeating it per row. Branches from one run are one situation; listed flat they read as unrelated work that happens to share a prefix.

**Report each group's union, not the sum of its rows.** Branches from a run are stacked, so a branch's `unique_commits` counts commits its siblings also carry — summing them multiplies the same work by how many branches contain it. `git rev-list --count ^<integration> <branch>...` over the group is the real figure, and the two can differ by more than a factor of two.

**Offer only the branches no sibling contains.** A branch listed in another's `contained_in` lands when that one does, so proposing both asks for a decision that has already been made. Name the ones riding along under the branch that carries them, so nothing looks dropped.

## Acting on Dispositions (both modes)

### 5. Act on each disposition

| Disposition | Meaning | Action |
| --- | --- | --- |
| `LAND` | Holds commits the integration branch lacks, with no PR driving it | Land it — step 6 |
| `DELETE` | Reached the integration branch, or its PR merged | `uv run lup-devtools dev delete <branch>` |
| `STALE` | Every commit already cherry-picked into the integration branch | Confirm, then delete |
| `KEEP` | Protected, an open PR is already driving it, or a resolver run holds its lease | Leave alone — but a run with `alive: false` holds it forever, which step 3 is for |
| `CURRENT` | The branch checked out here | Never delete; warn if it would otherwise qualify |

### 6. Landing a LAND branch

Land one branch at a time, oldest divergence first — rebase, merge, and push before the next branch is touched. Every branch that lands moves the integration branch, so a rebase run ahead of a sibling's merge carries a base that no longer exists.

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
- **Merge directly** — take the same route into the worktree and through `"""
            ),
            models.SkillInvocation(plugin="lup", skill="rebase"),
            models.TextPart(
                text=r"""`, then merge from the integration checkout with `"""
            ),
            models.SkillInvocation(plugin="lup", skill="merge"),
            models.TextPart(
                text=r""" <branch>`. `sync-base` has already pulled the integration branch in, so the merge is a fast-forward, and pushing it closes the PR the rebase opened. Suits small, uncontroversial work that needs no review.
- **Drop it** — the work is not worth landing. Requires explicit confirmation, then delete.

Never choose a route on the user's behalf: a `LAND` branch by definition carries no PR expressing intent, so the intent has to come from them.

### 7. Confirm and execute

"""
            ),
            models.RequestApproval(
                action="deleting a branch or pushing to a remote",
                reason="a LAND branch carries no PR expressing intent, so the intent "
                "has to come from the user",
            ),
            models.TextPart(
                text=r""" Then carry out the approved actions.

### 8. Report results

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
