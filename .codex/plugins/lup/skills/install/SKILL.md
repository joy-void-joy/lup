---
name: install
description: "Install lup plugin and scaffolding into a target repo"
---

# Install Lup into Target Repo

Install the lup plugin, hooks, and useful scaffolding into an existing repository. Unlike `$lup:init` (which customizes the template for a new domain), this command ports lup capabilities into a repo that already has its own structure and conventions.

## Your Task

**Arguments provided**: the arguments supplied with this skill invocation

### Parse Arguments

- **target-repo**: Path to the target repository (default: `..`). Resolve relative paths from the current working directory.
- **--interactive**: If present, use AskUserQuestion to offer choices for each porting decision. If absent, be conservative — modify as few files as possible.

If `the arguments supplied with this skill invocation` is empty, use defaults: target=`..`, non-interactive.

## Phase 1: Analyze Source Repo (Lup Template)

Inventory what the lup plugin offers. Read these key files in the **current** repo (`.`):

### Plugin Structure

- `.claude/plugins/lup/.claude-plugin/plugin.json` — plugin identity
- `.claude/plugins/lup/hooks/hooks.json` — hook definitions
- `.claude/plugins/lup/hooks/` — generated dispatcher and hermetic semantic policy runtime
- `.claude/plugins/lup/commands/*.md` — slash commands
- `.claude/plugins/lup/agents/*.md` — agent definitions
- `.claude/plugins/lup/TEMPLATE_CLAUDE.md` — CLAUDE.md template
- `.codex/plugins/lup/TEMPLATE_AGENTS.md` — AGENTS.md template (Codex flavor of the same sections)

### Reusable Library Code

- `packages/lup/src/lup/` — utilities (trace, hooks, metrics, mcp, retry, notes, history, paths)
- `lup.workspace.paths.agent_version()` — version tracking pattern (reads `[tool.lup] agent_version` from pyproject.toml)

### DevTools CLI

The `lup-devtools` CLI (`src/lup_template/devtools/`) gives Claude Code structured commands for development tasks that would otherwise require ad-hoc bash one-liners. Without it, Claude resorts to `python -c "..."` snippets or manual shell pipelines for trace analysis, feedback collection, and session management — which are fragile and unrepeatable. The devtools encode these workflows as proper CLI commands with argument parsing, output formatting, and error handling.

- `src/lup_template/devtools/main.py` — root typer app composing sub-apps (entry point: `lup-devtools`)
  - `trace/` — trace display, search, and analysis
  - `feedback/` — feedback state, metrics, and commits
  - `dev/` — worktree management, branch analysis, pre-flight checks
  - `version.py` — version, changelog, and bump operations
  - `sync.py` — upstream sync tracking

### Configuration Patterns

- `.claude/settings.json` — settings structure
- `downstream.json` — upstream sync tracking

Build a mental inventory of **portable capabilities** organized by category:

1. **Plugin infrastructure**: hooks.json, hook scripts, plugin.json structure
2. **Permission hooks**: auto-allow patterns for Bash, Edit, WebFetch; pre-push quality gates; test protection
3. **Slash commands**: which ones are generic (commit, rebase, close, clean-gone, meta, merge, debug, refactor) vs lup-specific (init, feedback-loop, bump, update)
4. **Library utilities**: print_block, TraceLogger, version tracking, retry decorator, cache, hook composition
5. **CLAUDE.md patterns**: coding standards, git workflow, editing style, debugging philosophy
6. **DevTools patterns**: CLI structure, sync tracking

## Phase 2: Analyze Target Repo

Read the target repo to understand its structure:

1. **Top-level layout**: `ls` the root, look for `src/`, `lib/`, `tests/`, `.claude/`, `package.json`, `pyproject.toml`, `Cargo.toml`, etc.
2. **Language and ecosystem**: Python/Node/Rust/Go/etc? Package manager? Build tools?
3. **Existing `.claude/` setup**: Does it have CLAUDE.md? settings.json? Any plugins already?
4. **Existing hooks**: Any PreToolUse hooks? Permission patterns?
5. **Existing commands**: Any slash commands already defined?
6. **Git workflow**: How does the repo handle branches, PRs, commits?
7. **Code conventions**: What patterns does the repo follow? Type checking? Linting?

**Key questions to answer:**

- What language/ecosystem is the target? (This determines which library utilities are portable)
- Does it already have a `.claude/` setup that we'd be extending vs. creating from scratch?
- What existing conventions must be respected?

## Phase 3: Find the Overlap

Based on the analysis, classify each lup capability as:

### Always Portable (language-agnostic)

These work in any repo:

- **Plugin infrastructure**: The `.claude/plugins/lup/` directory structure itself
- **Permission policy**: configure URL scopes and protected roots in the canonical `HookSet`; change semantic decisions in `lup.policy`, then regenerate
- **Pre-push quality gates**: Adapt to target's linter/type-checker/test runner
- **Generic commands**: commit, rebase, close, clean-gone, meta, debug, refactor, add-command, modify-command, merge, principle, review, create-investigator
- **CLAUDE.md patterns**: Git workflow, editing style, asking questions, debugging philosophy
- **Settings patterns**: permission structure in settings.json

### Portable if Python

These port well to other Python projects:

- **Library utilities**: hook composition, version tracking, retry, cache
- **DevTools CLI**: The `lup-devtools` typer app structure — `main.py` composing sub-apps, `pyproject.toml` entry point. Even if the target doesn't need every subcommand, the skeleton (dev, py, sync, usage, version) gives Claude Code reliable tooling instead of ad-hoc scripts.
- **Upstream sync**: downstream.json + sync commands (`lup-devtools sync`)

### Portable if Agent SDK

If the target repo uses (or will use) the Claude Agent SDK, the **self-improvement loop scaffolding** is the core value of lup — these are high-priority to port:

- **Agent scaffolding**: core.py pattern (orchestration), subagents.py, models.py (structured output), prompts.py, tool_policy.py, config.py (pydantic-settings)
- **Feedback loop**: feedback collection, trace analysis, metrics aggregation, scoring CSV
- **Session management**: CLI with `run` + `loop` commands, auto-commit, session storage
- **DevTools**: The full `lup-devtools` CLI (trace, feedback, dev, version, usage)
- **Version tracking**: `[tool.lup] agent_version` in pyproject.toml + `lup-devtools version bump` for tracking agent behavior changes
- **Commands**: `init`, `feedback-loop`, `bump`, `update` — the self-improvement workflow
- **Template guidance**: Section-level merge into the target's existing guidance file — CLAUDE.md from TEMPLATE_CLAUDE.md, AGENTS.md from TEMPLATE_AGENTS.md (add missing sections, leave existing ones)

When the target has Agent SDK code, adapt the scaffolding to wrap their existing agent — don't replace it. The lup patterns (trace logging, scoring, feedback collection) layer on top of whatever agent they already have.

These patterns are **opt-in, not a bundle**: reflection, realtime/persistent mode, the feedback loop, and the commit loop each port only if the target actually needs them (see CLAUDE.md § Scaffolding Is a Menu, Not a Mandate). Don't install a pattern the target won't use — dead scaffolding is worse than a capability you can add later.

### Skip (never port)

- Domain-specific tool implementations (example.py contents)
- Domain-specific prompt content
- Domain-specific model fields (but port the pattern/structure)

## Phase 4: Decide Plugin Strategy

Before deciding what to install, determine **where** it goes. Two options:

### Option A: Install lup as its own plugin (preferred)

Create `.claude/plugins/lup/` as a standalone local plugin in the target repo. This requires:

1. **Plugin directory**: `.claude/plugins/lup/.claude-plugin/plugin.json` — the plugin entry's `name` stays `lup` (so commands keep the `lup:` prefix everywhere).
2. **Marketplace**: `.claude/plugins/.claude-plugin/marketplace.json` with a **project-unique** `name` (use the target's package/repo name, e.g. `myproject`), listing the `lup` plugin:
   ```json
   { "name": "myproject", "plugins": [{ "name": "lup", "source": "./lup" }] }
   ```
3. **Register + enable** in settings.json under that same unique name:
   ```json
   "extraKnownMarketplaces": { "myproject": { "source": { "source": "directory", "path": "./.claude/plugins" } } },
   "enabledPlugins": { "lup@myproject": true }
   ```
   On a Python target where `lup-devtools` is installed, `lup-devtools dev plugin name` does steps 2–3 automatically (default name: the target's `[project].name`).

**Never name the marketplace `lup` or `local`.** Marketplace names share one global namespace (`~/.claude/plugins/known_marketplaces.json`), so a shared name collides across every repo that registers it — an install from one repo silently shadows the others. The plugin entry stays `lup`; only the *marketplace* is named per-project.

### Option B: Merge into an existing plugin

If the target already has a local plugin (e.g., `.claude/plugins/myproject/`), offer to merge lup's hooks and commands into it. This avoids a second plugin but mixes namespaces. Only do this in interactive mode when the user explicitly chooses it.

**In non-interactive mode, always use Option A.**

When the target already has other local plugins, lup installs alongside them under its own project-named marketplace — no conflict.

## Phase 5: Decide What to Install

Use your judgment based on what you found in Phases 1-3. The analysis should drive the decisions — don't follow a fixed checklist.

### Non-Interactive Mode (default)

Be conservative — only install what clearly adds value. Typical candidates (but decide based on the actual target):

- **Plugin infrastructure**: plugin.json, hooks.json, settings.json (project-named marketplace + plugin enablement)
- **Permission hooks** adapted to the target's ecosystem (its build tool, test runner, linter, doc URLs)
- **Generic commands** that work in any repo (git workflow, CLAUDE.md maintenance, meta, refactor, etc.)
- **Guidance file**: Perform a **section-level merge** using the platform template — `TEMPLATE_CLAUDE.md` (`.claude/plugins/lup/TEMPLATE_CLAUDE.md`) into the target's CLAUDE.md, or `TEMPLATE_AGENTS.md` (`.codex/plugins/lup/TEMPLATE_AGENTS.md`) into its AGENTS.md. Read the template, use the `<!-- section: ... -->` markers to identify independent merge units, adapt for the target's project name and ecosystem, then compare marked sections against the target's existing guidance file. Add sections that are missing; leave existing sections untouched. If no guidance file exists, create one from the adapted template.
- **If Agent SDK detected**: Also install the self-improvement scaffolding — this is lup's core value. The feedback loop commands, lib utilities (trace, scoring, metrics, hooks, version), devtools CLI pattern, session/trace directory structure, downstream.json for sync. Adapt to layer on top of the target's existing agent, not replace it.

**Constraints** in non-interactive mode:

- Don't rewrite existing CLAUDE.md content or change existing hooks/commands
- Don't install anything requiring new dependencies (suggest them in the report)
- Don't modify existing source code files (only create new files)

### Interactive Mode

Use AskUserQuestion at decision points where the user's input matters — don't ask about things you can decide confidently from the analysis, and don't enumerate every file individually.

Group decisions at meaningful levels. Examples of the _kinds_ of things to surface:

- Plugin strategy (own plugin vs merge) when the target already has plugins
- Which capability categories to install when the target could use some but not all
- How to handle CLAUDE.md when the target has one with different conventions
- Whether/how to port Agent SDK scaffolding when the target has existing agent code
- Whether to restructure existing code to fit lup patterns or layer on top
- Offering rewrites or retemplating of existing files when they'd benefit from lup patterns

What questions to ask — and how many — depends entirely on what you found. A bare repo with no `.claude/` needs fewer questions than one with an established plugin ecosystem.

## Phase 6: Execute Installation

For each item being installed:

1. **Read the source file** from the current repo
2. **Adapt it** for the target:
   - Replace `uv run` with target's equivalent (npm run, cargo, make, etc.) in hooks and commands
   - Adjust file path patterns in hooks for target's directory structure
   - Keep command markdown structure but update tool references and examples
   - Walk the `TEMPLATE:` markers in ported scaffolding files — each marks a domain decision with a one-line description. Adapt the code a marker points at to the target (and remove the marker), or leave it in place as an open decision the target gathers later with `uv run lup-devtools dev todos`
3. **Write to the target repo** — create directories as needed
4. **Never overwrite** existing files without asking (even in non-interactive mode, warn and skip)

### Renaming Rules

**Only Python import paths change** to match the target's package name. All framework vocabulary stays as `lup`:

| Changes (adapt to target package) | Stays as `lup` (framework identity) |
|---|---|
| `from lup_template.*` → `from <target>.*` imports | `lup-devtools` CLI entry point name |
| `src/lup_template/` → `src/<target>/` paths | `@lup_tool(...)`, `LupMcpTool` |
| `pyproject.toml` package name | `.claude/plugins/lup/` directory |
| marketplace `name` (marketplace.json) → `<target>` | plugin entry `name`: `lup` (so `the corresponding Lup skill` is stable) |
| Main CLI entry point name | `.lup/` state directory |
| Logger module paths | `lup-tools`, `lup-sandbox-*`, `lup-mcp-*` |
| | Naming convention ("Lup" = inner agent) |

### Installation Order

1. `.claude/plugins/lup/.claude-plugin/plugin.json`
2. `.claude/plugins/lup/hooks/hooks.json` (only reference hooks being installed)
3. `.claude/plugins/lup/hooks/scripts/` — adapted hook scripts
4. `.claude/plugins/lup/commands/` — selected commands
5. `src/<project>/devtools/` — devtools CLI skeleton (if Python target, adapt import paths but keep `lup-devtools` as the CLI entry point name)
6. `.claude/settings.json` — create or merge
7. The guidance file — section-level merge from its platform template: `.claude/CLAUDE.md` from TEMPLATE_CLAUDE.md, or `AGENTS.md` from TEMPLATE_AGENTS.md (read template → use `<!-- section: ... -->` markers to identify merge units → adapt for target → compare sections → add missing ones → leave existing untouched)
8. **Initialize upstream sync**: Run `uv run lup-devtools sync mark-synced lup` to baseline the sync state so `$lup:update` only shows commits after installation

## Phase 7: Verify & Report

After installation:

1. **List all files created/modified** in the target repo
2. **Show a summary** of what was installed and why
3. **Note what was skipped** and why (especially in non-interactive mode)
4. **Suggest next steps**:
   - Review the installed hooks and adjust patterns
   - Try `$lup:meta` to review the .claude structure
   - Run `$lup:commit` to test the commit workflow
   - Consider `$lup:update` later for ongoing sync

## Guidelines

- **Respect the target**: Don't impose lup conventions where the target has its own. Adapt to them.
- **Minimal footprint**: In non-interactive mode, prefer doing less. The user can always run with `--interactive` later to add more.
- **No new dependencies**: Don't install anything that requires `pip install` or `npm install` unless explicitly approved in interactive mode.
- **Adapt, don't copy**: Every file needs to be reviewed and adapted for the target's ecosystem.
- **Preserve existing work**: Never overwrite existing `.claude/` files. Merge or extend.
- **Explain decisions**: For each installed item, briefly explain what it does and why it helps.
