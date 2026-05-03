# Plan: Devtools & Slash Command Ontology Refactor

## Context

The `lup-devtools` CLI grew organically and had structural issues: session/trace/feedback were conflated, version-related commands were scattered across `agent`, git operations mixed with pre-flight checks, and slash commands referenced stale devtools paths or underused devtools.

## Completed Work

### Phase 1: Split `session/` into `trace/` + `feedback/`

- [x] Created `src/lup/devtools/trace/` sub-package (`__init__.py` + `traces.py`)
- [x] Created `src/lup/devtools/feedback/` sub-package (`__init__.py` + `state.py`)
- [x] Deleted `src/lup/devtools/session/` entirely
- [x] Updated `main.py` to register `trace_app` and `feedback_app`

### Phase 2: Rename `git/` → `dev/`

- [x] Renamed sub-package from `git/` to `dev/`
- [x] Fixed internal import in `dev/branches.py` (`from lup.devtools.dev.worktree`)
- [x] `check.py` stays inside `dev/`

### Phase 3: Create `version` sub-app

- [x] Created `src/lup/devtools/version.py` with `show` (default), `changelog`, and `bump`
- [x] Removed `version_cmd` and `VersionInfo` from `agent.py`
- [x] Registered `version_app` in `main.py`

### Phase 4: Update all slash commands

- [x] Rewired 17+ commands: `session` → `trace`/`feedback`, `git` → `dev`, `agent version` → `version`
- [x] Deleted periodic section from `fb-reflect.md` (lines 46-51)
- [x] Renamed `meta-principle.md` → `principle.md`
- [x] Updated `install.md` stale file listing

### Phase 5: Update CLAUDE.md and supporting files

- [x] Directory tree, sub-apps list, example commands, feedback loop section
- [x] Updated `__init__.py` docstring
- [x] Fixed stale references in `version-reviewer.md`, `trace-explorer.md`, `TEMPLATE_CLAUDE.md`

### Verification

- [x] `uv run pyright` — 0 errors
- [x] `uv run ruff check . && uv run ruff format --check .` — clean
- [x] `uv run pytest` — 10 passed
- [x] Smoke tests: all sub-apps (`trace`, `feedback`, `dev`, `version`) working
- [x] `grep -r "lup-devtools session\|commit-results"` — no stale references

---

## Phase 6: New devtools commands (COMPLETED)

Three new commands that replace manual work currently done inline by slash commands.

### 6a. `feedback analyze` — structured analysis report

**Location:** `src/lup/devtools/feedback/analyze.py` (new module), registered in `feedback/__init__.py`.

**What it replaces:** `/fb-analyze` currently runs 3 separate devtools commands (`feedback tools`, `feedback errors`, `trace capabilities`) and holds all their output in context. The `analyze` command consolidates these into a single structured report.

**Behavior:**

Produces a JSON report combining:
- **Tool health**: per-tool call counts, error counts, error rate — from existing `tools()` logic in `state.py`
- **Error patterns**: sessions with high error rates, grouped by error type — from existing `errors()` logic in `state.py`
- **Capability gaps**: agent capability requests extracted from traces — from existing `capabilities()` logic in `traces.py`

**Interface:**

```
lup-devtools feedback analyze [--version VERSION] [--all-versions] [--output FILE]
```

- Default output: JSON to stdout
- `--output FILE`: write JSON to a file instead
- Version filtering: same `--version` / `--all-versions` options as other feedback commands

**Output schema** (TypedDict):

```python
class ToolHealth(TypedDict):
    name: str
    calls: int
    errors: int
    error_rate: float

class ErrorPattern(TypedDict):
    session_id: str
    error_count: int
    total_calls: int
    error_rate: float
    top_errors: list[str]

class CapabilityGap(TypedDict):
    request: str
    count: int
    session_ids: list[str]

class AnalysisReport(TypedDict):
    version: str | None
    tool_health: list[ToolHealth]
    error_patterns: list[ErrorPattern]
    capability_gaps: list[CapabilityGap]
```

**Implementation notes:**
- Reuse the data-loading and computation logic already in `state.py` and `traces.py` — call the functions that `tools()`, `errors()`, and `capabilities()` use internally, but collect results into the TypedDict instead of printing
- If the existing functions are tightly coupled to printing (typer.echo), extract the data-gathering portions into separate functions that return typed data, and have both the existing CLI commands and `analyze` call those

**Slash command update:** `/fb-analyze` replaces its 3 separate devtools calls with:
```bash
uv run lup-devtools feedback analyze --json
```

**Files modified:**
- `src/lup/devtools/feedback/analyze.py` (new)
- `src/lup/devtools/feedback/__init__.py` (register `analyze` command)
- `src/lup/devtools/feedback/state.py` (extract data-returning helpers if needed)
- `src/lup/devtools/trace/traces.py` (extract data-returning helper for capabilities if needed)
- `.claude/plugins/lup/commands/fb-analyze.md` (wire new command)

---

### 6b. `dev conflicts` — conflict scope classification

**Location:** `src/lup/devtools/dev/conflicts.py` (new module), registered in `dev/__init__.py`.

**What it replaces:** `/merge-conflict` Step A (scope classification) is currently done by reading git log manually and reasoning about which files are in-scope vs out-of-scope. The `conflicts` command automates the mechanical part.

**Behavior:**

After a failed merge/rebase, lists conflicted files with:
- **File path**
- **Conflict count** per file (number of `<<<<<<<` markers)
- **Scope classification**: in-scope / out-of-scope / mixed, based on whether this branch's commits touched that file

Scope classification logic:
1. Find the merge base: `git merge-base HEAD MERGE_HEAD` (merge) or from rebase state
2. Get files touched by this branch: `git diff --name-only <merge-base>..HEAD`
3. For each conflicted file:
   - If the file was modified by this branch's commits → **in-scope**
   - If not → **out-of-scope**
   - (Mixed is possible if a file was touched by both sides for different reasons, but the binary classification is the useful first cut)

**Interface:**

```
lup-devtools dev conflicts [--json]
```

- Default output: table with file path, conflict count, scope
- `--json`: structured JSON output
- Exits with error if not in a merge/rebase state

**Output schema** (TypedDict):

```python
class ConflictFile(TypedDict):
    path: str
    conflict_count: int
    scope: str  # "in-scope" | "out-of-scope"
    branch_touched: bool

class ConflictReport(TypedDict):
    state: str  # "merge" | "rebase" | "cherry-pick"
    base: str  # merge base SHA
    files: list[ConflictFile]
    in_scope_count: int
    out_of_scope_count: int
```

**Implementation notes:**
- Use `git diff --name-only --diff-filter=U` to list conflicted files
- Count conflict markers with `grep -c '<<<<<<<' <file>` per file
- Detect merge state from `.git/MERGE_HEAD`, `.git/rebase-merge/`, or `.git/rebase-apply/`
- Use `sh` library for git commands (not subprocess)

**Slash command update:** `/merge-conflict` Step A adds:
```bash
uv run lup-devtools dev conflicts --json
```
The scope classification from the tool informs the decision tree — in-scope files take ours, out-of-scope take theirs, per the existing resolution rules.

**Files modified:**
- `src/lup/devtools/dev/conflicts.py` (new)
- `src/lup/devtools/dev/__init__.py` (register `conflicts` command)
- `.claude/plugins/lup/commands/merge-conflict.md` (wire new command into Step A)

---

### 6c. `dev pr-body` — PR summary generation

**Location:** add to `src/lup/devtools/dev/branches.py` (already has PR-related code: `get_pr_info`, `pr_status`).

**What it replaces:** `/rebase` manually constructs the PR body by reading `git diff <base>...HEAD` and `git log --oneline <base>..HEAD`, then formatting it into the Summary/Commits/Test plan template. The `pr-body` command generates this automatically.

**Behavior:**

Reads the diff and commit log from the current branch against its base, produces a PR body in the standard format:

```markdown
## Summary
<1-3 bullet points describing the changes>

## Commits
<list of commits>

## Test plan
- [ ] ...
```

The summary bullets are derived from commit messages grouped by conventional commit type. The commits section is a verbatim `git log --oneline`. The test plan is a skeleton.

**Interface:**

```
lup-devtools dev pr-body [--base BRANCH]
```

- Default: auto-detect base branch using existing `detect_base_branch()`
- `--base`: override the base branch
- Output: markdown text to stdout (no `--json` — the output IS the artifact)

**Implementation notes:**
- Reuse `detect_base_branch()` already in `branches.py`
- Group commits by conventional commit prefix (feat/fix/refactor/etc.) for summary bullets
- Use the same classification logic as `version.py`'s `classify_commit()` — but don't import it; the grouping here is simpler (just prefix extraction for bullet formatting)
- The summary bullets are mechanical: "Added X" for feat, "Fixed Y" for fix, etc. — derived from commit messages, not from reading code
- Keep it simple — this generates a starting point that `/rebase` can edit via `gh pr edit`

**Slash command update:** `/rebase` step 2 (create PR) and step 6 (update PR body) replace the manual body construction with:
```bash
BODY=$(uv run lup-devtools dev pr-body)
gh pr create --base "<target>" --title "<title>" --body "$BODY"
# or for updates:
gh pr edit <PR_NUMBER> --body "$BODY"
```

**Files modified:**
- `src/lup/devtools/dev/branches.py` (add `pr_body` function)
- `src/lup/devtools/dev/__init__.py` (register `pr-body` command)
- `.claude/plugins/lup/commands/rebase.md` (wire new command)

---

### Verification

- [x] `uv run pyright` — 0 errors
- [x] `uv run ruff check . && uv run ruff format --check .` — clean
- [x] `uv run pytest` — 10 passed
- [x] Smoke tests: all three commands (`feedback analyze`, `dev conflicts`, `dev pr-body`) `--help` working
- [x] Integration check: `feedback --help` and `dev --help` show new commands
