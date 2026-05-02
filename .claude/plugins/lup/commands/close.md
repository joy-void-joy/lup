---
allowed-tools: Bash(git:*, gh:*, uv run lup-devtools:*), AskUserQuestion
description: Check PR review status, merge if approved, and clean up branches
---

# Close PR

Check the review status of the feature branch's PR, merge it if approved, and clean up.

## Process

### 1. Identify the PR

```bash
uv run lup-devtools dev pr-status --json
```

If the command exits non-zero (no open PR), check if the user passed a PR number as an argument. If still nothing, report the error and stop.

### 2. Check PR review status

The `pr-status` output includes review decision, checks, and merge state. For detailed review comments:

```bash
gh pr view <PR_NUMBER> --comments
```

### 3. Evaluate and act

**If there are unresolved review comments or requested changes:**

1. Display all review comments to the user, clearly formatted
2. Show which reviews requested changes vs approved
3. **Stop here.** Tell the user to fix the issues and re-run `/lup:rebase` to push updates.

**If all reviews are approved (or no reviews yet but checks pass):**

1. Show the PR summary to the user
2. Use AskUserQuestion to confirm the merge
3. If confirmed, proceed to merge and cleanup

### 4. Merge the PR

```bash
gh pr merge <PR_NUMBER> --squash --delete-branch
```

Use `--squash` to create a single merge commit. The `--delete-branch` flag removes the branch on remote automatically.

### 5. Clean up

After merge, pull the merged changes into the integration branch:

```bash
# From the integration branch worktree
cd ../dev && git pull && cd -
```

Then check the merged branch's cleanup status and clean up:

```bash
uv run lup-devtools dev branch-status "$CURRENT_BRANCH" --json
```

If the branch shows as DELETE, remove worktree (if any), delete local branch (`git branch -d`), and delete remote branch (`git push origin --delete`). Confirm with user before deleting.

### 6. Report

Summarize what was done:

- PR merged (with link)
- Cleanup results (from clean-gone)

## Guidelines

- Always show review comments before merging -- never skip review feedback
- Use `--squash` merge to keep dev history clean
- The user must confirm before merging via AskUserQuestion
