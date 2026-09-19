
### Examples

```
feat(agent): add retry logic for API calls
fix(tools): handle empty response from search
refactor(config): extract settings validation
meta(harness): add new workflow command
```

## Phase 4: Verify

After creating commits:

1. Run `git log --oneline -5` to show what was created
2. Run `uv run lup-devtools dev pending` to confirm the working directory is clean

## Guidelines

- **Never amend** unless explicitly requested
- **Never force push** to dev/main/master
- **Don't skip hooks** unless explicitly requested
- **Don't commit secrets** (.env.local, credentials, API keys)
- **Don't commit large binaries** unless necessary
- **Session data** (notes/traces/) is not committed here: the feedback loop's own page says how one session becomes one `data(sessions):` commit

## If Pre-commit Hooks Fail

1. Fix the issue (formatting, linting, etc.)
2. Re-stage the fixed files
3. Create a **new** commit (don't amend - the previous commit didn't happen)
