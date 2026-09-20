# Close PR

Check the review status of the feature branch's PR, merge it if approved, and clean up.

## Process

### 1. Commit pending changes

Invoke `{{ commit_skill }}` to commit any uncommitted work before proceeding.

### 2. Get PR status

```bash
uv run lup-devtools git pr status --json
```

If no PR is found, check if the user passed a PR number as an argument. If still nothing, report the error and stop.

### 2b. Prepare against the PR target

Read `<target>` from the status result's `base_ref`, then fetch `origin` before
running `uv run lup-devtools git pr prepare --base origin/<target> --json` in
its clean feature checkout. The command merges the exact fetched target,
regenerates every runtime tree, and commits without pushing. If it commits,
review and check those changes, publish through `git pr push`, then read status
again and wait for checks and reviews on that head. The forge runs no custom
merge driver, so this preparation lets it merge generated ownership proofs.

### 3. Evaluate reviews

**If there are unresolved review comments or requested changes:**

1. Display all review comments clearly formatted
2. Show which reviews requested changes vs approved
3. **Stop here.** Tell the user to fix the issues and re-run `{{ rebase_skill }}`.

### 3b. Read where the checks stand

`checks_state` answers `passing`, `failing`, or `running`, and the third is not the first. **If it is `running`, stop and say so** — the checks have not finished, so nothing yet says whether they pass, and a merge decided here is decided on an answer the forge has not given. Name the checks whose `status` is not `COMPLETED` and let the user re-run once they settle. **If it is `failing`, stop** and report the failing checks, the same as a review requesting changes.

**If all reviews are approved (or there are none) and `checks_state` is `passing`:**

1. Show the PR summary
2. {{ approval }}

### 4. Merge the PR

```bash
uv run lup-devtools git pr merge <PR_NUMBER>
```

### 5. Clean up

Delete the merged branch:

```bash
uv run lup-devtools git delete <BRANCH_NAME>
```

### 6. Report

Summarize what was done: PR merged (with link), cleanup results.

## Guidelines

- Always show review comments before merging -- never skip review feedback
- The user approves the merge before it happens -- never merge unprompted
