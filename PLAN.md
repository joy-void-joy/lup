# Plan: Devtools + Slash Command Ontology Refactor

## Context

The `lup-devtools` CLI was organized by data format — trace files, metric JSON, feedback state, git. The mental model should be organized by **what you're operating on**: the agent, a session, the repo. Meanwhile, many slash commands shell out to raw git/grep instead of using devtools, and 12 use overly broad `Bash` permissions.

## Current State (after checkpoint commit)

The prior refactor session already:
- [x] Merged metrics.py commands (tools, errors, trends, history) into feedback.py
- [x] Created dev.py: worktree management, branch analysis (branch-status, base-branch, pr-status), session commits
- [x] Deleted standalone git.py, metrics.py, worktree.py
- [x] Stripped charts.py CLI commands (kept library functions)
- [x] Rewired main.py to 7 sub-apps: agent, api, dev, feedback, sync, trace, usage
- [x] Partially updated slash commands (allowed-tools, some path rewiring)
- [x] Partially updated CLAUDE.md

## Remaining Work: Rename to Final Ontology

The checkpoint uses `dev` + `feedback` + `trace`. The target uses `session` + `git`:

| Checkpoint | Target | What changes |
|------------|--------|-------------|
| `feedback` (681 lines) | `session/state.py` | Rename sub-app, split into sub-package |
| `trace` (modified) | `session/traces.py` | Merge into session sub-package |
| `dev` (671 lines) | `git/` sub-package | Rename sub-app, split into worktree.py + branches.py |
| (missing) | `session/analysis.py` | New: `compare` command, merged `errors` |
| (missing) | `git/check.py` | New: unified pyright + ruff + pytest |
| `feedback version` | `agent version` | Move version command to agent sub-app |

### Target CLI Surface

```
lup-devtools
├── agent                         # existing + version command
│   ├── inspect
│   ├── chat
│   ├── repl
│   ├── serve-tools
│   └── version                   # moved from feedback, expanded
├── session                       # NEW sub-package (trace + feedback + dev.commit)
│   ├── list                      # from trace.list
│   ├── show                      # from trace.show
│   ├── search                    # from trace.search
│   ├── errors                    # from feedback.errors (already merged)
│   ├── capabilities              # from trace.capabilities
│   ├── commit                    # from dev.commit-results
│   ├── collect                   # from feedback.collect
│   ├── mark / unmark             # from feedback.mark/unmark
│   ├── status                    # from feedback.status (already merged)
│   ├── unanalyzed                # from feedback.unanalyzed
│   ├── summary                   # (NEW — was dropped in checkpoint, restore from metrics.py)
│   ├── tools                     # from feedback.tools
│   ├── trends                    # from feedback.trends
│   ├── history                   # from feedback.history
│   ├── prompt-health             # from feedback.prompt-health
│   └── compare                   # NEW — cross-version metrics comparison
├── git                           # renamed from dev, split into sub-package
│   ├── worktree create           # from dev.worktree-create
│   ├── worktree list             # NEW
│   ├── worktree remove           # NEW
│   ��── branches                  # from dev.branch-status
│   ├── base-branch               # from dev.base-branch
│   ├── pr-status                 # from dev.pr-status
│   └── check                     # NEW — unified pyright + ruff + pytest
├── sync                          # unchanged
├── usage                         # unchanged
└── api                           # unchanged
```

## Phase 1: Create `session/` sub-package

Split existing `feedback.py` (681 lines) + `trace.py` into sub-package:

### `src/lup/devtools/session/__init__.py`
- Create Typer app
- Import and register all commands from sub-modules

### `src/lup/devtools/session/traces.py`
- Move from current `trace.py`: `find_trace`, `load_trace`, `show`, `search`, `list_traces`, `capabilities`

### `src/lup/devtools/session/state.py`
- Move from current `feedback.py`: models, load/save/match/compute functions, `collect`, `status`, `mark`, `unmark`, `unanalyzed`, `prompt_health`, `tools`, `errors`, `trends`, `history`
- Move from current `dev.py`: `get_uncommitted_session_ids`, `get_session_summary`, `commit_session`, `commit_results`
- Fix: move `ANALYZED_FILE` from module-level to function-level

### `src/lup/devtools/session/analysis.py`
- Restore `summary` command (load all sessions, show aggregate stats — was in deleted metrics.py)
- New `compare` command: cross-version metrics/tool-usage comparison with `--json` flag

## Phase 2: Create `git/` sub-package

Split existing `dev.py` (671 lines) into sub-package:

### `src/lup/devtools/git/__init__.py`
- Create Typer app with nested `worktree` sub-app

### `src/lup/devtools/git/worktree.py`
- Move from `dev.py`: `branch_exists`, `worktree_is_registered`, `get_tree_dir`, `copy_to_clipboard`, `worktree_create_cmd`
- New `list_cmd`: parse `git worktree list --porcelain`
- New `remove_cmd`: `git worktree remove <path>` with `--force`
- Fix: move module-level `sh.Command()` calls inside functions

### `src/lup/devtools/git/branches.py`
- Move from `dev.py`: `detect_base_branch`, `base_branch_cmd`, `get_integration_branch`, `is_ancestor`, `get_branch_worktree`, `get_pr_info`, `classify_branch`, `branch_status_cmd`, `pr_status_cmd`

### `src/lup/devtools/git/check.py`
- New: run ruff format + ruff check + pyright + pytest
- Flags: `--fix` (auto-fix ruff), `--no-test` (skip pytest)
- Report pass/fail summary per tool, exit code reflects worst result

## Phase 3: Move `version` to agent, rewire main.py, delete old files

### `src/lup/devtools/agent.py`
- Move `version` command from feedback.py, expand: AGENT_VERSION, latest v* tag, commits since, prompt health. `--json` flag.

### `src/lup/devtools/main.py`
- 6 sub-apps: agent, api, session, git, sync, usage

### Delete
- `src/lup/devtools/trace.py`
- `src/lup/devtools/feedback.py`
- `src/lup/devtools/dev.py`

## Phase 4: Update slash commands

### allowed-tools tightening

| Command | New allowed-tools |
|---------|-------------------|
| commit | `Bash(git:*)` |
| rebase | `Bash(git:*, gh:*, uv run lup-devtools:*)` |
| fb-implement | `Bash(git:*, uv run lup-devtools:*, uv run python -m lup:*)` |
| feedback-loop | `Bash(git:*, uv run lup-devtools:*, uv run python -m lup:*)` |
| import | `Bash(git:*, uv run lup-devtools:*)` |
| meta | `Bash(ls:*, uv run lup-devtools:*)` |
| meta-principle | `Bash(uv run lup-devtools:*)` |
| refactor | `Bash(git:*, uv run lup-devtools:*)` |
| update | `Bash(git:*, uv run lup-devtools:*)` |
| bump | `Bash(git:*, uv run lup-devtools:*)` |
| init | keep bare Bash (one-time wizard) |
| install | keep bare Bash (external repo installer) |

### Devtools path rewiring

All old paths updated to new session/git paths:

| Old | New |
|-----|-----|
| `lup-devtools trace *` | `lup-devtools session *` |
| `lup-devtools feedback *` | `lup-devtools session *` |
| `lup-devtools dev worktree-create` | `lup-devtools git worktree create` |
| `lup-devtools dev branch-status` | `lup-devtools git branches` |
| `lup-devtools dev base-branch` | `lup-devtools git base-branch` |
| `lup-devtools dev pr-status` | `lup-devtools git pr-status` |
| `lup-devtools dev commit-results` | `lup-devtools session commit` |

### Specific command fixes

1. **fb-analyze.md**: Add `Agent` to allowed-tools (blocks version-explorer spawn)
2. **debug.md**: Add `Bash(uv run lup-devtools:*)`, use `lup-devtools session search` instead of raw Grep
3. **clean-gone.md**: Use `lup-devtools git branches --json` for analysis
4. **bump.md**: Wire `lup-devtools agent version` for step 1 context
5. **meta.md**: Replace hardcoded command list with `ls .claude/plugins/lup/commands/`
6. **fb-reflect.md**: Wire `lup-devtools agent version` for prompt health
7. **close.md**: Wire `lup-devtools git pr-status` and `lup-devtools git worktree remove`
8. **rebase.md**: Replace inline pyright/ruff/pytest with `lup-devtools git check`
9. **refactor.md**: Same as rebase
10. **fb-implement.md**: Same as rebase
11. **fb-investigate.md**: Slim down to reference `/lup:review` per session + gate

## Phase 5: Update CLAUDE.md

- Directory tree (Architecture section)
- Command tree (Tooling section)
- Example commands (Getting Started, Feedback Loop Scripts)

## Phase 6: Verify

1. `uv run pyright`
2. `uv run ruff check . && uv run ruff format --check .`
3. `uv run pytest`
4. Smoke test: `lup-devtools --help`, `session --help`, `git --help`, `session list`, `agent version`, `git branches`, `git check --no-test`, `git worktree list`
5. `grep -r "from lup.devtools.trace\|from lup.devtools.feedback\|from lup.devtools.dev\b" src/` — no dangling imports
