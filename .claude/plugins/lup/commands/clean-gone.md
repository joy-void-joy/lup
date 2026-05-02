---
allowed-tools: Bash(git:*, gh:*, uv run lup-devtools:*), AskUserQuestion
argument-hint: [branch-name]
description: Review branches/worktrees and clean up merged ones
---

# Clean Merged Branches

Review all local branches and worktrees. Identify branches that are fully merged into the integration branch, have completed PRs, or are stale. Present the results and ask before deleting.

## Arguments

- **branch-name** (optional): Name of a specific branch to remove. If provided, runs in targeted mode. If omitted, runs a full scan of all branches.

Raw arguments: `$ARGUMENTS`

Parse the raw arguments as follows: if non-empty, the first word is the **branch name** (not a natural-language instruction). Ignore any remaining words.

## Process

### 1. Get branch status

```bash
# Targeted mode (specific branch)
uv run lup-devtools dev branch-status <branch-name> --json

# Full scan (all branches)
uv run lup-devtools dev branch-status --json
```

The devtool handles: fetch/prune, containment analysis, PR status, cherry-pick detection, and worktree info. It classifies each branch as DELETE, STALE, KEEP, or CURRENT.

### 2. Present results

Display the branch status table to the user. For each DELETE/STALE branch, show:
- Branch name and classification reason
- Whether it has a worktree
- PR status (if any)

### 3. Confirm with user

Use AskUserQuestion before deleting anything. Show the list of branches to be cleaned up.

### 4. Clean up

For each confirmed branch:

1. **Remove worktree** (if any):
   ```bash
   git worktree remove <path>
   ```

2. **Delete local branch**:
   ```bash
   git branch -d <branch-name>
   ```
   Use `-d` (not `-D`). If `-d` fails (branch not recognized as merged due to rebase), report to user and ask if `-D` is acceptable.

3. **Delete remote branch** (if it exists):
   ```bash
   git push origin --delete <branch-name>
   ```

### 5. Report results

List what was cleaned up.

## Guidelines

- Never force-delete (`-D`) without explicit user approval for that specific branch
- Always confirm before deleting anything
- Skip the current branch — warn the user instead
- For rebased branches: the original feature branch content is in main via the rebase PR, even though `--is-ancestor` returns false (commits were rewritten)
