---
description: "Land every branch that has not reached the integration branch, and clear the ones that have"
allowed-tools: Bash(uv run lup-devtools:*), AskUserQuestion, EnterWorktree, Skill(lup:commit), Skill(lup:rebase), Skill(lup:merge)
argument-hint: "[branch-name]"
---

# Land Every Branch

Drive every local branch to its terminal state. Each one is classified by whether its commits have reached the integration branch — the ones that have not get landed, the ones that have get cleared — so no branch sits in a silent bucket waiting to go stale.

## Arguments

- **branch-name** (optional): a single branch to dispose of. If provided, runs in targeted mode. If omitted, sweeps every branch.

Raw arguments: `$ARGUMENTS`

Parse the raw arguments: if non-empty, the first word is the **branch name**. Ignore remaining words.

## Process

### 1. Commit pending changes

Invoke `/lup:commit` to commit any uncommitted work before the sweep.

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

- **Open a PR** — relocate into that branch's worktree with `EnterWorktree(path=<the survey's worktree field>)`, or create one first via `uv run lup-devtools dev worktree create <branch>` when `worktree` is null. Then run `/lup:rebase`.
- **Merge directly** — from the integration checkout, `/lup:merge <branch>`. Suits small, uncontroversial work that needs no review.
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
