<!-- Generated from src/lup_template/devtools/harness/content/guidance.py via `uv run lup-devtools harness generate all`; deliberately rendered as both .claude/CLAUDE.md and AGENTS.md — edit the source, not this file. See docs/generated-artifacts.md. -->

# Lup repository guidance

Lup is a reusable framework and template for autonomous, tool-using agents. Keep library code provider-neutral and keep provider syntax in generated adapter artifacts.

## Plan at Agent Speed

You are an AI agent. Every instinct you have about how long software takes — sprints, milestones, "this will take weeks" — was learned from human teams, whose implementation time is scarce and expensive. Yours is not: what you would estimate as several months of work completes in an afternoon, and a "multi-day implementation" lands in about three hours. Your duration estimates are not cautious; they are wrong by orders of magnitude, and every practice built on them inverts:

- **Never scope, defer, or reject work from a predicted duration.** Scope by content — what changes, what it touches, how it is verified. If a calendar figure appears in your plan, it is noise from someone else's constraints: delete it and re-derive the plan.
- **The POC is superstition at your speed.** Prototype-first exists to keep unvalidated ideas from consuming scarce human effort; for you the complete alpha-beta-v1 costs what the throwaway was supposed to cost. Build the real implementation immediately and validate on it — let review cut scope afterward rather than pre-shrinking the attempt.
- **Catch the reflex in the act.** "Let's start with a simple version", "too ambitious for this pass", "phase 2 can add the rest" — that is a human-scarcity practice firing on constraints you do not have. When you notice it, stop and ask what is actually expensive here besides the imagined schedule.

**README.md is human-owned.** The root `README.md` is deliberately human-written, and the edit policy surfaces every change to it as Ask — as it does for any file declared under `human_owned_files` in the harness hook catalog. Never edit a human-owned file yourself — propose the exact change via AskUserQuestion and let the user apply or approve it.

## Agent Vocabulary

Two kinds of delegated agents look alike and must not be conflated:

- A **native subagent** ("subagent" for short) is dispatched by the harness: Claude Code's `Agent`/`Task` tool hands a focused task to a named role defined upfront, inside the main agent's session — shared trace, shared metrics.
- A **nested agent** (also called a *tool-subagent*) runs inside a tool call: the handler opens one independent session via `query()` and folds the result into the tool's response. The harness never sees it — to the calling agent it is just a tool.

Guidance that says "subagent" unqualified means the native kind. `.claude/PATTERNS.md` carries the full pattern catalog — subagent, nested, background, deferred tool schemas — and when to reach for each.

## Development Workflow

### Git Workflow

This project uses **git worktrees** (not regular branches) to develop multiple features in parallel.

**IMPORTANT:** Never commit _code_ directly to `dev`. Always work in a worktree for code changes.

**Exception:** Data commits (`data(outputs):`) can go directly to `dev` — generated outputs don't need review. In this repo session data under `notes/` is gitignored (traces stay local), so such commits arise only for repos that opted into the commit-loop pattern via $lup:init.

### Two-Tier Branch Model

- **`dev`** = integration branch. Feature PRs merge here. Day-to-day development target.
- **`main`** = stable branch. Only receives PRs from `dev`. Branch-protected on GitHub.

Worktrees typically branch from `dev`, but can also branch from other feature branches. Feature PRs target `dev` (or the branch they diverged from). Periodically, `dev` is merged into `main` via a reviewed PR.

**Worktrees vs branches:**

- `git checkout -b` — Creates a branch, stays in same directory. Switching changes all files in place.
- `git worktree add` — Creates a new directory with its own working copy. Multiple branches simultaneously.

**If already in a worktree:** Check with `git worktree list`. If you're in a feature worktree, just work directly — no need to create another.

**Feature workflow:**

1. `uv run lup-devtools dev worktree create feat-name`
   This creates the worktree as a sibling under `tree/` (e.g., `tree/feat-name` alongside `tree/dev`) and syncs dependencies. Generate and launch the native plugin with `lup-devtools harness claude` or `harness codex`. **Never** use `git worktree add ./worktrees/...` — worktrees must be siblings, not nested inside another checkout.
2. Commit regularly and atomically
3. Push when complete (or periodically for backup)
4. `$lup:rebase` — Push, open PR, clean up history with `git reset --soft main` and force-push
5. Review — Fix issues, re-run `$lup:rebase` to rebuild history
6. `$lup:close` — Merge approved PR and clean up

**Note:** The `worktrees/` and `refs/` directories are gitignored. `refs/` contains symlinks to downstream projects.

### Merge Conflict Resolution

**Never silently drop code during conflict resolution.** The bias is toward inclusion — keeping both sides is always safer than losing features. A rename on one side must not swallow an addition on the other.

Before completing any merge, **audit for deletions**: compare the result against both parents and verify that every removed function, parameter, or command was intentionally removed, not lost as a side effect of choosing one conflict side.

Use `$lup:merge` (with no argument) for guided conflict resolution. See the command for the full decision tree.

### Commit Guidelines

- **Commit before responding** — Don't accumulate changes across responses
- **Commit early, commit often** — Frequent commits provide checkpoints
- **Keep commits atomic** — If you need "and" in your message, it should be two commits
- **History will be rebased** — Don't worry about perfect messages during development

**Format:** `type(scope): description`

| Type       | Use                                                                  |
| ---------- | -------------------------------------------------------------------- |
| `feat`     | New feature or capability                                            |
| `fix`      | Bug fix                                                              |
| `refactor` | Code change that neither fixes a bug nor adds a feature              |
| `docs`     | Documentation only (README, standalone docs)                         |
| `test`     | Adding or updating tests                                             |
| `chore`    | Maintenance (dependencies, build config)                             |
| `meta`     | Changes to `.claude/` files (CLAUDE.md, settings, scripts, commands) |
| `data`     | Generated data and outputs                                           |

### Editing Style

**Prefer small, atomic edits.** A PreToolUse hook counts "real" changed lines (ignoring imports, comments, whitespace, blank lines, docstrings, string literals, type annotations, and TypedDict/BaseModel bodies) and auto-allows edits with <=3 real changes per change block. Pure deletions and single-line `replace_all` renames are auto-allowed; multi-line `replace_all` falls through to the size gate. Anti-pattern detection runs before any auto-allow, and `Write` (full-file rewrites) never auto-allows. An edit that trips only the size gate is *deferred* rather than surfaced — the hook emits no decision, so auto-accept mode applies it while other modes still prompt; protected paths, anti-patterns, marker changes, and full-file writes stay explicit approvals in every mode.

- Split large changes into multiple small edits (<=3 real lines per Edit call)
- Separate concerns — imports in one edit, logic in another
- Use `rename-symbol` for identifier renames instead of `Edit` with `replace_all`

---

## Code Conventions

### Primary Libraries

- **claude-agent-sdk**: Primary framework for building agents (use `query()` for one-shot LLM calls with structured output)
- **pydantic**: For data validation and settings
- **pydantic-settings**: For configuration (not dotenv)

### Model Selection

Default to **Opus 4.6** (`claude-opus-4-6`) — or **Fable** (`claude-fable-5`) — for the main agent, every subagent, reviewer, and background agent. This runs on a subscription where the best model is the point: reach for Sonnet only when latency or cost provably dominates and quality is non-critical, and for Haiku almost never. A role that genuinely warrants a cheaper model declares it explicitly with a reason; otherwise it inherits the Opus-class default.

### Type Safety

- **Never silently swallow exceptions** — no `except ...: pass`, no `contextlib.suppress`; log with `logger.exception()`, handle meaningfully, or re-raise. Catch-all `except Exception` is fine at boundaries (task loops, subagent delegation) that do so; bare `except:` and `except BaseException` are never fine
- **Every function must specify input and output types**
- **Never use `Any`, `dict[str, Any]`, or `dict[str, object]`** — Use `TypedDict` for dict-like data, `BaseModel` for validated models, or specific types
  - **JSON-shaped data**: use `JsonValue` / `JsonObject` from `lup.types` for data whose schema lives elsewhere (tool arguments, JSON Schemas, structured outputs, vendor payloads)
  - **MCP tool inputs**: `BaseModel.model_validate(args)` immediately — don't pass around raw dicts
  - **MCP tool outputs**: Define a `TypedDict` for the return dict
  - **SDK hooks**: Return `SyncHookJSONOutput` from `claude_agent_sdk.types`. Use typed hook inputs (`PreToolUseHookInput`, etc.) and specific output types (`PreToolUseHookSpecificOutput`, etc.)
  - **SDK types to prefer**: `HookMatcher`, `AgentDefinition`, `ClaudeAgentOptions`, `McpServerConfig`, `PermissionResultAllow`/`Deny`, `ContentBlock`, `Message`, `TextBlock`, `ToolUseBlock`, `ToolResultBlock`. Import from top-level `claude_agent_sdk` when available; `SyncHookJSONOutput`, `HookEvent`, and hook-specific types require `claude_agent_sdk.types`.
- **Python 3.12+ generics**: `class A[T]`, not `Generic[T]`
- Use `TypedDict` and Pydantic models for structured data
- Never manually parse agent output — use structured outputs via Pydantic
- **Never use `# type: ignore`** — Ask the user how to properly fix type errors
- **`# lup: ignore` escape hatch** — When `Any` or another anti-pattern is genuinely needed (untyped library boundaries, MCP), add an inline ignore to request user approval. Prefer the typed, pyright-style `# lup: ignore[rule-id]` (comma-separate a list — `# lup: ignore[dict-get, tuple-shape]`) so a site silences exactly the rule it needs and still trips the others; the bare `# lup: ignore` stays valid but the auditor flags it as untyped to nudge migration. A standalone `# lup: ignore` in the first 10 lines disables anti-pattern checks for the whole file, while `# lup: ignore[rule-id]` there disables only that rule file-wide (like `# pyright: ignore` for files). Each rule's id is shown in its deny message; the generated `docs/rules.md` (regenerated by `uv run lup-devtools dev rules`) indexes every rule family — anti-pattern, boundary, spelling, architecture — with the `lup.codescan` module that defines it.
- **Use Pydantic BaseModel instead of dataclasses**
- **Use `match`/`case` instead of `if`/`elif` chains** for dispatching on values or ranges
- **Use `for`/comprehensions over `while`** — reach for structured iteration whenever the iteration space is expressible (a range, a sequence, an iterator, `enumerate`/`zip`); reserve `while` for genuinely unbounded, condition-driven loops

### Tool Input Schemas

Define tool inputs as BaseModel classes with `Field(description=...)`:

| Do This                                                               | Not This                       |
| --------------------------------------------------------------------- | ------------------------------ |
| `class SearchInput(BaseModel): query: str = Field(description="...")` | `{"query": str, "limit": int}` |
| `SearchInput.model_json_schema()` for `@tool` schema                  | Hand-written dict schemas      |
| `SearchInput.model_validate(args)` then `params.query`                | `args.get("query", "")`        |

### Error Handling

**MCP tools:** Return `{"content": [...], "is_error": True}` for recoverable errors. Log with `logger.exception()`. Include actionable messages.

**Agent code:** Raise exceptions for unrecoverable errors. Use `with_retry` for transient failures. Validate inputs early with Pydantic.

**Never silently swallow errors** — handle them meaningfully or let them propagate.

### Structured Data, Not Strings

If you're reaching for `re`, `.replace()`, `.split()`, or string slicing to process structured data, something is wrong:

- **Web pages**: `trafilatura` for text extraction, `beautifulsoup4` for DOM
- **XML**: `xml.etree.ElementTree` or `lxml`
- **JSON**: `json.loads()`, not regex
- **SDK objects**: Filter `ContentBlock` lists by type and attribute
- **Dates**: Parse to `datetime`, don't compare strings
- **URLs**: `urllib.parse`, not splitting
- **Paths**: `pathlib.Path`, not concatenation

`import re` is a code smell — look for the structured API first.

### Standard Libraries

Use existing Python libraries from PyPI before writing raw HTTP requests. Don't rebuild the wheel.

### Code as Documentation

The codebase should read as a **monolithic source of truth** — understandable without knowledge of its history.

**The test:** "Would this comment exist if the code had always been written this way?" If no — don't add it.

- Never reference what code used to do or explain modifications you made
- Never use "now", "new", "updated", "fixed", or "changed" in comments
- Use commit messages for change history, not code comments

### Inline `# lup:` Notes

A `# lup:` (or `// lup:`) comment is **actionable review feedback** left in the code for the agent to address — distinct from the `# lup: ignore` escape hatch under [Type Safety](#type-safety) and from the `# lup: defer[...]` parking flavor under [Deferred Work](#deferred-work). The edits hook prompts whenever an edit changes a file's `# lup:` marker count, and `lup-devtools` scans for unresolved notes.

**Never delete a `# lup:` note until its concern is actually resolved.** Making a file parse, tidying up, or editing past it does not count. Resolve a note by fixing the code or structure it points at, or — for a question — by answering it definitively and reflecting that answer in the code, the docs, or an explicit user decision. Only then does the note come out (use `$lup:resolve`).

A note in a comment-less format (e.g. JSON) is the trap: you can't keep it there, but you still can't silently drop it to satisfy the parser. Resolve its concern first, or relocate it to a file that can hold it (the code it refers to, a tracking doc). If a note raises several concerns, remove it only once every one is resolved; otherwise keep the unresolved parts.

### Deferred Work

**Never create tracking files.** A `TODO.md`, backlog, or roadmap file parks a decision where no workflow will surface it again — deferral by tracking file is delegation to nobody. Deferred work lives in exactly two places:

- **A `# lup: defer[<wake condition>]: <text>` note** at the most relevant site — the code or config the work concerns. The bracket names the condition under which the work wakes, mirroring `# lup: ignore[rule-id]`. `dev comments` lists deferred notes in their own section and `dev check` stays red while any exist, so parked work remains visible pressure instead of silent debt. Each resolve pass triages them: a note whose wake condition reads as met is proposed to the user for waking; an unmet one is carried forward untouched, never re-litigated as ordinary feedback and never stripped by an editor whose concern doesn't wake it.
- **AskUserQuestion** — when whether (or how) to defer is itself the open question, ask instead of filing.

### DRY: Don't Repeat Yourself

- If logic exists in `lup` (the library), import it. Don't copy-paste.
- Reusable utilities belong in `packages/lup/`, not `src/lup_template/`.
- See [lup vs lup_template Boundary](#lup-library-vs-lup_template-application-boundary) for the placement test.

### Imports: No Barrel Files

**Never use `__init__.py` re-exports or `__all__` in internal packages.** Import directly from the module that defines the symbol.

- `from lup.mcp import lup_tool` — not `from lup import lup_tool`
- `__init__.py` files should contain only the module docstring (no imports, no `__all__`)
- Barrel files drift out of sync and hide real dependencies

**Exception:** Standalone library packages under `packages/` may use re-exports with `__all__` in their top-level `__init__.py` to declare a public API. Only the package root — not subpackages.

### Naming: No Private Prefixes

**Never use `_` prefixes** on functions, methods, classes, or constants. Nothing is private.

- Module-level functions: just name them `build_options`, not `_build_options`
- Class methods: `remove_stale_container`, not `_remove_stale_container`
- Constants: `PACE_THRESHOLDS`, not `_PACE_THRESHOLDS`
- Classes: `PendingReminder`, not `_PendingReminder`

**If a helper truly shouldn't pollute the module namespace**, nest it inside its only caller:

```python
def build_display(usage, stats):
    def place_label(text, position, width):
        ...
    # use place_label here
```

**Avoid useless mini-wrappers.** If a function's only purpose is to call another function with no additional logic, inline it.

**Exceptions:** `_` prefix is fine for unused parameters (`_context`, `_exc_type`) — that's a linting convention, not a privacy convention.

---

## Tooling

### Package Tools

- **uv**: Package manager. Use `uv add <package>` (never edit pyproject.toml directly)
- **ruff**: Formatting and linting
- **pyright**: Type checking

### lup-devtools

All development tooling lives in `src/lup_template/devtools/` and is exposed as the `lup-devtools` CLI entry point. **Always use `lup-devtools` instead of ad-hoc commands.** Never use `uv run python -c "..."` or bare `python`/`python3` — these are denied by the Bash permission hook.

If you find yourself running the same command repeatedly, **add a command** to `src/lup_template/devtools/`. Use `tmp/*.py` for one-off scripts.

**Write scripts in Python using [typer](https://typer.tiangolo.com/)** for CLIs. Use **[sh](https://sh.readthedocs.io/)** for shell commands instead of `subprocess`.

Sub-apps: `agent`, `dashboard`, `dev`, `feedback`, `harness`, `py`, `setup`, `sync`, `trace`, `usage`, `version`. Run `uv run lup-devtools --help` for the full command tree — the list above is rendered from the typed sub-app roster in `src/lup_template/devtools/subapps.py`.

`lup-devtools harness claude` and `harness codex` regenerate, reconcile, and
launch the native plugins. `lup-devtools usage` reports Claude usage. Profiles
(named Claude config dirs) are managed with `lup-devtools setup profile`.

Each repo names its plugin marketplace after the project. Claude launches the
verified local plugin directory; Codex installs a separately cached copy and
verifies its digest before launch. Personal cache and trust state are never
committed.

### Lup Skills & Agents

Both lists below are rendered from the typed declarations in
`src/lup_template/devtools/harness/content/catalog.py` — change the catalog,
then regenerate.

**Skills:**

- $lup:add-command — Create a new slash command in the lup plugin
- $lup:brainstorm — Pre-init design exploration — brainstorm architecture, MCP tools, and agent design
- $lup:bump — Review changes since last bump and bump agent version
- $lup:clean-gone — Review branches/worktrees and clean up merged ones
- $lup:close — Check PR review status, merge if approved, and clean up branches
- $lup:commit — Review all diffs and create atomic commits
- $lup:create-investigator — Create a new diagnostic/investigator command (like /debug)
- $lup:debug — Trace an error through logs to find root cause
- $lup:fb-analyze — Aggregate tool health, capability gaps, and reasoning patterns across sessions
- $lup:fb-implement — Implement prioritized changes from feedback loop analysis
- $lup:fb-investigate — Deep trace reading and error classification for selected sessions
- $lup:fb-reflect — Meta and meta-meta reflection on the feedback loop process itself
- $lup:fb-status — Feedback loop entry point — status, targets, and previous session context
- $lup:feedback-loop — Full feedback loop — orchestrates status, investigation, analysis, reflection, and implementation
- $lup:hooks — Inspect and modify the canonical semantic permission policy
- $lup:implementer — Implement one resolver concern inside its leased worktree
- $lup:import — Import a specific pattern from a tracked downstream repo
- $lup:init — Initialize the self-improvement loop for a specific domain
- $lup:install — Install lup plugin and scaffolding into a target repo
- $lup:merge — Merge a branch or resolve existing merge conflicts
- $lup:meta — Review and modify .claude structure, brainstorm improvements interactively
- $lup:modify-command — Modify an existing slash command based on a description or delta
- $lup:principle — Propagate a general principle across the entire repo
- $lup:rebase — Clean up commit history on the feature branch and open/update a PR
- $lup:refactor — Rewrite a file or folder from scratch while respecting coding conventions
- $lup:refactor-tools — Audit SDK agent tools and subagents — find gaps, overlaps, and refactoring opportunities
- $lup:resolve — Resolve inline feedback through isolated work
- $lup:resolve-reviewer — Review one resolver concern against its acceptance criteria
- $lup:review — Review a session trace for workflow quality, tool usage, and improvement opportunities
- $lup:update — Review upstream template commits and apply improvements

**Agents:**

- `implementer` — Implement production changes against established acceptance tests
- `resolve-editor` — Resolve one concern within its leased isolated worktree
- `trace-explorer` — Investigate trace evidence without changing production files
- `version-explorer` — Inventory version-impact evidence across the repository
- `version-reviewer` — Independently review a proposed version change

### Permission Hooks

Permissions come from the canonical semantic policies in `lup.policy` and the
application-owned `HookSet` in `devtools/harness/catalog.py`. Harness generation
compiles one hermetic dispatcher and dependency-free runtime for each native
plugin. Do not edit generated dispatcher or runtime files directly.

The policy classifies each shell command against the vocabulary in
`lup.policy.shell_rules`, every URL scope, and each edit in a batch. Denial
wins over approval, malformed input fails conservatively, command substitution
and file-writing redirection are never auto-allowed (stream discards to
`/dev/null` and fd duplication are stripped as safe), and edit decisions
include protected paths, marker changes, size, and the canonical anti-pattern
audit. An edit that exceeds the size gate alone is deferred — the hook emits no
decision so auto-accept mode applies while the hard gates stay explicit. The
resolver editor receives only its declared autonomous edit exceptions;
temporary paths, human-owned files such as `README.md`, marker changes, and
anti-pattern violations retain their guardrails.

Use `$lup:hooks` to change the canonical policy inputs, regenerate both native
plugins, and run the shared canonical/bundled fixture suite. `settings.json`
contains only native settings that are outside this semantic policy boundary.

### Pyright LSP

The `pyright-lsp` plugin provides code intelligence. **Use these actively** — faster and more accurate than grep for code understanding.

**Navigation:**

- **go-to-definition** — Jump to where a symbol is defined (instead of grepping for `def foo`)
- **find-references** — Find all usages (instead of grepping for a symbol name)
- **hover-documentation** — Type info and docs at a position
- **list-symbols** — All symbols in a file (instead of grepping for `def ` or `class `)
- **find-implementations** — Implementations of an interface/abstract method
- **trace-call-hierarchy** — Understand call chains

**Refactoring:**

- **rename-symbol** — Rename across workspace. **Always prefer over `Edit` with `replace_all`** — understands scope.

| Task                             | LSP                | grep/Edit        |
| -------------------------------- | ------------------ | ---------------- |
| Find where a function is defined | `go-to-definition` |                  |
| Find all callers of a function   | `find-references`  |                  |
| Rename a variable/function/class | `rename-symbol`    |                  |
| Search for a string literal      |                    | `Grep`           |
| Search across non-Python files   |                    | `Grep`           |
| Change logic within a function   |                    | `Edit`           |
| Add new code                     |                    | `Edit` / `Write` |

---

## Configuration

### Environment Variables

The `.env` file contains template configuration. Create `.env.local` for secrets (gitignored):

```bash
# .env.local - your secrets (ANTHROPIC_API_KEY is read directly by the SDK from env)

# Optional overrides
# AGENT_MODEL=claude-opus-4-6
# AGENT_MAX_BUDGET_USD=5.00
# AGENT_MAX_TURNS=50
# AGENT_SANDBOX_ENABLED=false   # run without Docker (disables code execution tools)
# AGENT_NOTES_PATH=./notes      # relocate session data
# AGENT_LOGS_PATH=./logs        # relocate trace logs
```

Settings in `.env.local` override `.env`. Configuration is loaded via pydantic-settings — see `src/lup_template/agent/config.py`.

All Claude Code settings modifications should be **project-level** (in `.claude/settings.json`), not user-level.

---

## Process & Communication

### Asking Questions

**Always use the `AskUserQuestion` tool** instead of asking questions in plain text. This applies to clarifying requirements, offering choices, confirming destructive actions, proposing changes, and any situation needing user input.

Even for open-ended questions, use `AskUserQuestion` with options that include a custom input option. This allows structured notification parsing.

**When proposing changes:** Propose (don't assume), show relevant current state, explain rationale, offer alternatives.

**When in doubt, ask.**

### Slash Commands & Skills

**After every command invocation**, reflect on how it was actually used vs. documented:

1. Compare intent vs usage
2. Notice patterns — user corrections signal the command should evolve
3. Proactively propose updates via AskUserQuestion

**Evolution signals:** User provides external docs, corrects your approach, asks for something the command should cover, or ignores sections.

### External Resources

When questions involve Claude Code, Agent SDK, or Claude API:

1. Use the `claude-code-guide` subagent: `Agent(subagent_type="claude-code-guide", prompt="...")`
2. Fetch docs directly: `WebFetch(url="https://docs.claude.com/en/agent-sdk/<topic>")`

When the user provides documentation links, incorporate that knowledge into CLAUDE.md or relevant commands.

---

## Self-Improvement Loop

See [The Bitter Lesson](#the-bitter-lesson) and [Tool Design Philosophy](#tool-design-philosophy) — these govern all agent improvements.

**When analyzing failures:** Ask "what general principle would have prevented this?" not "what specific rule would catch this case?" The fix is almost never a prompt line about a specific decision. Instead: does the agent have enough context? The right tools? A strong enough model?

When the principle points to a workflow failure, fix the workflow at the exact juncture where the failure enters — don't add a warning about it. A step named "Classify each commit" invites whole-commit thinking regardless of how many times the text says "decompose." Renaming the step to "Extract portable pieces" and separating reading from judging makes the failure structurally impossible. Warnings coexist peacefully with the workflows they warn against; structural changes don't.

### Diagnosing Failures

When the agent fails, the instinct is to patch the prompt. Resist it. Instead, trace the failure through the pipeline:

1. **What data did the agent have?** Read the trace. What tools did it call? What did they return? Was the information sufficient for a correct decision?
2. **Where in the workflow did the wrong decision enter?** Find the exact step — not the symptom, the entry point. A bad output is a symptom; a missing tool call or a misleading tool result is the cause.
3. **What structural change prevents it?** A new tool, a better tool description, a restructured pipeline step, richer data — these are durable fixes. A prompt rule is a patch that coexists with the failure.

| Do This | Not This |
|---|---|
| Trace the failure to a missing input or structural flaw | Add "NEVER do X" or "ALWAYS do Y" to the prompt |
| Formulate general principles with fresh examples | Copy examples from the specific trace that failed |
| Ask "what data was the agent missing?" and provide it | Add a numeric threshold ("if score > 15, then...") |
| Restructure the pipeline step where the error enters | Add a warning after the error-prone step |

**Examples that look the same but aren't:**

- Agent misclassifies commits → **Do:** Restructure the step to process files individually before grouping. **Don't:** Add "CRITICAL: Always check if a commit touches multiple concerns."
- Agent produces verbose output → **Do:** Constrain via output model or add a reviewer subagent. **Don't:** Add "Keep responses under 200 words."
- Agent ignores an available tool → **Do:** Improve the tool's description (what/when/why). **Don't:** Add "Remember to use X tool" to the prompt.

### Three Levels of Analysis

1. **Object Level** — The agent itself: tools, capabilities, behavior
2. **Meta Level** — The agent's self-tracking: what it monitors about itself
3. **Meta-Meta Level** — The feedback loop process: scripts, analysis methods

### Running the Feedback Loop

1. **Collect feedback**: `uv run lup-devtools feedback collect`
2. **Read traces deeply**: Read 5-10 sessions in detail — don't skip to aggregates
3. **Extract patterns**: Tool failures, capability requests, reasoning quality
4. **Implement changes**: Fix tools → Build requested capabilities → Simplify prompts
5. **Update documentation**: This file should evolve with the agent

### What to Track Per Session

- **Sessions**: `notes/traces/<version>/sessions/<session_id>/`
- **Outputs**: `notes/traces/<version>/outputs/<task_id>/`
- **Traces**: `notes/traces/<version>/logs/<session_id>/`
- **Metrics**: Tool calls, timing, errors via metrics tracking

### Anti-Patterns

- Adding rules the agent can't act on (no access to required data)
- Adding "CRITICAL: Never do X" warnings instead of restructuring the workflow so X has no entry point
- Copying examples from a specific trace into the prompt instead of deriving general principles and writing fresh examples
- Adding numeric thresholds or absolute rules ("if more than N, do X") — these are brittle and don't survive domain shifts
- Patching for one observed symptom instead of tracing the failure through the pipeline to find the structural cause
- Listing tools by name in the system prompt (two sources of truth that drift apart)
- Skipping trace analysis to jump to aggregate statistics
- Over-engineering initial implementations
- Making changes in `lup.environment` when `lup.agent` is the right place

**Validation questions for proposed changes:**

1. Does this add a capability or just a rule?
2. Would this help if the domain changed completely?
3. Are we changing the right level (object/meta/meta-meta)?
4. What data would we need to validate this change worked?
