# TODO

// lup: purge notes/feedback_loop from dev history once in-flight branches merge (deferred by user decision, 2026-07-10)

## Purge dev's notes history (deferred)

The 2026-07-10 scrub removed session data from every local feature branch
(481 commits rewritten across 11 refs; backups under `refs/original/`). One
remnant remains: `2d40f7c` on `dev` tracks 4 `notes/feedback_loop/*.json`
files and is reachable from `origin/dev` and the pushed feature branches.
`main` is clean. Once the in-flight worktree branches have merged into dev:

1. Find every branch still carrying the commit: `git branch -a --contains 2d40f7c`
2. Rewrite them in one run (keeps `notes/.gitkeep`; `main` stays untouched as the range base):

   ```bash
   FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -d /tmp/rewrite --prune-empty \
     --index-filter 'git rm -r --cached -q --ignore-unmatch notes/feedback_loop notes/traces' \
     -- ^main dev <every-other-local-branch-from-step-1>
   ```

3. Resync any worktree whose checked-out branch was rewritten: `git -C tree/<name> reset -q`
   (if the current worktree's tracked notes files vanish from disk, restore them:
   `git restore --source=<old-sha> --worktree -- notes/`)
4. Force-push the rewritten shared branches: `git push --force-with-lease origin dev ...`
5. Verify: `git log --branches -- notes/` shows only `0a07641` (the `.gitkeep` commit)
6. Drop all backup refs (this purge's and the 2026-07-10 scrub's) once satisfied:

   ```bash
   git for-each-ref refs/original --format='%(refname)' | xargs -n1 git update-ref -d
   ```

// lup: Why do we need a TODO.md ? Why was it created? I don't like this, the main agent should have asked me instead of delegating for later without saying this