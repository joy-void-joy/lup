# lup: ignore[native-spelling]
# This portable guide discusses native hook vocabulary as its subject matter.
"""Canonical repository guidance."""

import lup.harness.models as models

import lup_template.devtools.harness.content.conventions as conventions

from lup_template.devtools.harness.content.catalog import (
    agent_roster_text,
    skill_roster_parts,
)
from lup_template.devtools.subapps import subapp_summary

# lup: state that a consumer never holds or calls an implemented ABC directly.
# The ABC is the swappable engine; the surface a caller touches is a concrete
# plain class that composes it and can be parametrized. `ModelRouter.resolve` over the
# `ModelMatcher` ABC in lup/runtime/routing.py is the shape, and `SessionFactory`
# in lup/runtime/contracts.py is the violation being corrected under the
# object-bound-entry-points concern. Belongs beside the compile-over-emit and
# overridable-default principles, not as a standalone bullet.
DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.TextPart(
            text=r"""# Lup repository guidance

Lup is a reusable framework and template for autonomous, tool-using agents. Keep library code provider-neutral and keep provider syntax in generated adapter artifacts.

## Plan at Agent Speed

You are an AI agent. Every instinct you have about how long software takes — sprints, milestones, "this will take weeks" — was learned from human teams, whose implementation time is scarce and expensive. Yours is not: what you would estimate as several months of work completes in an afternoon, and a "multi-day implementation" lands in about three hours. Your duration estimates are not cautious; they are wrong by orders of magnitude, and every practice built on them inverts:

- **Never scope, defer, or reject work from a predicted duration.** Scope by content — what changes, what it touches, how it is verified. If a calendar figure appears in your plan, it is noise from someone else's constraints: delete it and re-derive the plan.
- **The POC is superstition at your speed.** Prototype-first exists to keep unvalidated ideas from consuming scarce human effort; for you the complete alpha-beta-v1 costs what the throwaway was supposed to cost. Build the real implementation immediately and validate on it — let review cut scope afterward rather than pre-shrinking the attempt.
- **Catch the reflex in the act.** "Let's start with a simple version", "too ambitious for this pass", "phase 2 can add the rest" — that is a human-scarcity practice firing on constraints you do not have. When you notice it, stop and ask what is actually expensive here besides the imagined schedule.

**README.md is human-owned.** The root `README.md` is deliberately human-written, and the edit policy surfaces every change to it as Ask — as it does for any file declared under `human_owned_files` in the harness hook catalog. Never edit a human-owned file yourself — propose the exact change as a question and let the user apply or approve it.

## Agent Vocabulary

Two kinds of delegated agents look alike and must not be conflated:

- A **native subagent** ("subagent" for short) is dispatched by the harness: its delegation tool hands a focused task to a named role defined upfront, inside the main agent's session — shared trace, shared metrics.
- A **nested agent** (also called a *tool-subagent*) runs inside a tool call: the handler opens one independent session via `query()` and folds the result into the tool's response. The harness never sees it — to the calling agent it is just a tool.

Guidance that says "subagent" unqualified means the native kind. `docs/orchestration.md` carries the full delegation catalog — subagent, nested, background, deferred tool schemas — and when to reach for each. `docs/patterns.md` carries the recurring *code* shapes: declaration-plus-renderer, closed-by-construction, and the typed-matcher router.

## Development Workflow

### Git Workflow

This project uses **git worktrees** (not regular branches) to develop multiple features in parallel.

**IMPORTANT:** Never commit _code_ directly to `dev`. Always work in a worktree for code changes.

**Exception:** Data commits (`data(outputs):`) can go directly to `dev` — generated outputs don't need review. In this repo session data under `notes/` is gitignored (traces stay local), so such commits arise only for repos that opted into the commit-loop pattern via """
        ),
        models.SkillInvocation(plugin="lup", skill="init"),
        models.TextPart(
            text=r""".

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
2. """
        ),
        models.RelocateSession(path="the path step 1 prints"),
        models.TextPart(
            text=r""" — creating a worktree does not move the session, and edits left in the old checkout never reach the branch.
3. Commit regularly and atomically
4. Push when complete (or periodically for backup)
5. `"""
        ),
        models.SkillInvocation(plugin="lup", skill="rebase"),
        models.TextPart(
            text=r"""` — Push, open PR, clean up history with `git reset --soft main` and force-push
6. Review — Fix issues, re-run `"""
        ),
        models.SkillInvocation(plugin="lup", skill="rebase"),
        models.TextPart(
            text=r"""` to rebuild history
7. `"""
        ),
        models.SkillInvocation(plugin="lup", skill="close"),
        models.TextPart(
            text=r"""` — Merge approved PR and clean up

**Note:** The `worktrees/` and `refs/` directories are gitignored. `refs/` contains symlinks to downstream projects.

"""
        ),
        *conventions.MERGE_CONFLICT_RESOLUTION,
        models.TextPart(
            text=r"""**Generated artifacts are regenerated, never hand-merged.** A digest manifest (`.lup-ownership.json`) conflicts on every parallel branch because each field is derived, so `.gitattributes` gives it a driver that keeps one side; `lup-devtools dev merge-driver` registers it in a clone that has not run `worktree create`. Reconciling such a file hunk by hunk produces a proof that matches neither tree — take either side, then `lup-devtools harness generate all` and let `harness check all` confirm it settled.

"""
        ),
        *conventions.COMMIT_GUIDELINES,
        models.TextPart(
            text=r"""| Type       | Use                                                                  |
| ---------- | -------------------------------------------------------------------- |
| `feat`     | New feature or capability                                            |
| `fix`      | Bug fix                                                              |
| `refactor` | Code change that neither fixes a bug nor adds a feature              |
| `docs`     | Documentation only (README, standalone docs)                         |
| `test`     | Adding or updating tests                                             |
| `chore`    | Maintenance (dependencies, build config)                             |
| `meta`     | Changes to harness content and the trees it generates (guidance, settings, skills, hooks) |
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

Default to the **strongest** tier for the main agent, every subagent, reviewer, and background agent. This runs on a subscription where the best model is the point: reach for a **balanced** tier only when latency or cost provably dominates and quality is non-critical, and for the **fast** tier almost never. A role that genuinely warrants a cheaper model declares that tier explicitly with a reason; otherwise it inherits the strongest default. Agent declarations state the tier, not a model id — each runtime spells the tier in its own lineup.

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
- **`# lup: ignore` escape hatch** — When `Any` or another anti-pattern is genuinely needed (untyped library boundaries, MCP), add an inline ignore to request user approval. Prefer the typed, pyright-style `# lup: ignore[rule-id]` (comma-separate a list — `# lup: ignore[dict-get, tuple-shape]`) so a site silences exactly the rule it needs and still trips the others; the bare `# lup: ignore` stays valid but the auditor flags it as untyped to nudge migration. A standalone `# lup: ignore` in the first 10 lines disables anti-pattern checks for the whole file, while `# lup: ignore[rule-id]` there disables only that rule file-wide (like `# pyright: ignore` for files). Each rule's id is shown in its deny message; the generated `docs/rules.md` indexes every rule family with the `lup.codescan` module that defines it.
- **Use Pydantic BaseModel instead of dataclasses**
- **Use `match`/`case` instead of `if`/`elif` chains** for dispatching on values or ranges
- **Never dispatch on the type of our own models** — no `isinstance` over a union we declare, no `case ClassName()` arms, no `assert_never` net. The union's base declares the operation and each subtype answers or declines it, so a new variant is one class instead of an edit to every walk that would have to notice it, and a filter cannot go stale by omission. Narrowing untyped data at a boundary — a vendor payload, a `JsonValue` — is the different case where `isinstance` is right, because those alternatives are not ours to give a method to. The `own-model-dispatch` rule enforces exactly this line: it fires only on classes we define that inherit `BaseModel`
- **Compiling is stronger than emitting** — build an artifact from a typed declaration and it cannot diverge; transport checked source and a checker can only warn once it already has. When tempted to add a check that two things still match, ask whether one can be derived from the other instead (`docs/patterns.md`)
- **A constant should probably be an overridable default** — a canonical value (a native tool's real name, a vendor's field) is fine hardcoded; a non-canonical one (an allowlist, a ceiling, a retry count) is our judgement, so give it a default a caller can override rather than a constant they must fork to change (`docs/patterns.md`)
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

A `# lup:` (or `// lup:`) comment is **actionable review feedback** left in the code for the agent to address. Four flavors, and only the removal rules differ:

| Marker | Removing it |
|---|---|
| `# lup: <text>` — open feedback | **denied**; resolve it into a claim instead |
| `# lup: solved: <text>` — a claim you addressed it | **denied**; only the verify-solved review pass retires one |
| `# lup: defer: <text>` — parked work (§ Deferred Work) | **denied** while parked |
| `# lup: ignore[<rule>]` — an anti-pattern hatch (§ Type Safety), not feedback | fine once the violation is gone |

Resolve open feedback by fixing what it points at, or, for a question, by answering it definitively in the code, the docs, or a recorded user decision. Then rewrite the marker as **`# lup: solved: <the note's original words>`**, text unchanged, so the claim sits beside what it claims to fix and can be checked against what was asked. `docs/contributing.md` carries the full lifecycle (use `"""
        ),
        models.SkillInvocation(plugin="lup", skill="resolve"),
        models.TextPart(
            text=r"""`).

### Deferred Work

**Never create tracking files.** A `TODO.md`, backlog, or roadmap file parks a decision where no workflow will surface it again — deferral by tracking file is delegation to nobody. Deferred work lives in exactly two places: a `# lup: defer: <text>` note at the site it concerns, where `dev check` keeps it visible; or a question to the user, when whether to defer is itself the open question. Default to the bare `defer:`; a bracket states a real, externally-checkable gate, never that this code might change again. `docs/contributing.md` carries both, and the one exception — a `tmp/` briefing, which starts a fresh session on a situation this one cannot finish, and is rewritten whole rather than appended to.

### DRY: Don't Repeat Yourself

- If logic exists in `lup` (the library), import it. Don't copy-paste.
- Reusable utilities belong in `packages/lup/`, not `src/lup_template/`.
- Placement test: would another project built on lup want this? Then it belongs
  in `packages/lup/`. If it only makes sense for this application, it belongs in
  `src/lup_template/`.

### A Constant Should Be an Overridable Default

The placement test applies to values, not only to code. `packages/lup` may declare a value only when it could not have chosen otherwise — a language's file suffixes, a provider's wire spelling, a closed enum the library itself defines. Ask: *could a second implementer with the same intent have written a different value?* If yes it is a judgement, and the library takes the caller's instead of making it for every adopter.

**Having defaults is fine; assuming a non-canonical choice with no parameter to replace it is the defect.** `HookSet` is the shape. The audited `library-default` rule checks the mechanical half; canonicity it cannot, so declare that at the site with `# lup: ignore[library-default]` and a reason. `docs/library.md` carries the criterion, every library table's classification, and the target layout.

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

If you find yourself running the same command repeatedly, **add a command** to `src/lup_template/devtools/`.

`tmp/` is scratch: gitignored, so nothing written there reaches a diff, a reviewer, or the human — which is why it does not execute. For one-off work, in order: `lup-devtools py eval '<expression>'` for anything that fits one expression, which auto-imports and needs no file; run it in the sandbox where the work allows; add a `lup-devtools` command, which is reviewable because `devtools/` lands in the diff; or, as a last resort, `python3 <<<EOF` behind a `# lup: escalate: <why>` marker. The argument is reviewability, not power — an agent may already edit `devtools/` and run it.

**Write scripts in Python using [typer](https://typer.tiangolo.com/)** for CLIs. Use **[sh](https://sh.readthedocs.io/)** for shell commands instead of `subprocess`.

"""
        ),
        models.TextPart(
            text="Sub-apps: "
            + subapp_summary()
            + ". Run `uv run lup-devtools --help` for the full command tree — the"
            " list above is rendered from the typed sub-app roster in"
            " `src/lup_template/devtools/subapps.py`.\n"
        ),
        models.TextPart(
            text=r"""
`lup-devtools harness generate all` regenerates and reconciles every native
plugin; `harness <runtime>` regenerates one and launches it. `lup-devtools
usage <runtime>` reports usage, and profiles — named per-runtime config homes —
are managed with `lup-devtools setup profile`.

Each repo names its plugin marketplace after the project. How a launch reaches
the plugin differs per runtime: one verifies the local directory in place, the
other seeds a persistent per-worktree home from personal authentication and
settings, installs the verified plugin there, and checks its digest first. A
runtime flag or an inherited environment variable selects an explicit home
instead. Personal cache, trust, and session state are never committed.

### Lup Skills & Agents

Both lists below are rendered from the typed declarations in
`src/lup_template/devtools/harness/content/catalog.py` — change the catalog,
then regenerate.

**Skills:**

"""
        ),
        *skill_roster_parts(),
        models.TextPart(
            text=r"""
**Agents:**

"""
            + agent_roster_text()
            + r"""
### Permission Hooks

Permissions come from the canonical semantic policies in `lup.policy` and the
application-owned `HookSet` in `devtools/harness/catalog.py`. Harness generation
compiles one hermetic dispatcher and runtime for each native
plugin. Never edit generated dispatcher or runtime files.

Every shell command, URL scope, and edit in a batch is classified. Segments
join deny > ask > defer > allow, and malformed input fails conservatively.
`docs/permissions.md` carries the full lattice — shell vocabulary, `$(...)`
recursion, write targets, fetch scopes, and edit gates. You rarely need to
read it first: a denial names what tripped and how to recover.

**Two markers change a decision, so keep them in mind before you are stopped:**

- `# lup: escalate: <why>` as the leading line of a shell command promotes a
  classified deny or ask into an approval question carrying that reason. This
  is the recovery path when work is denied as unjudged — reshape the command
  into the allowed vocabulary, or escalate with a reason.
- `# lup: ignore[<rule-id>]` on the offending line suppresses exactly that
  anti-pattern (see § Type Safety). It must sit on the line that
  trips the rule — a marker one line above is reported as spurious while the
  violation stays uncovered.

Use `"""
        ),
        models.SkillInvocation(plugin="lup", skill="hooks"),
        models.TextPart(
            text=r"""` to change the canonical policy inputs, regenerate both native
plugins, and run the shared fixture suite. `settings.json`
holds only native settings outside this semantic policy boundary.

### Code Intelligence

The `codeintel` tool group answers questions about code by *resolving* it, through a language server. **Prefer these over grep for anything about a name** — a name has a definition, a scope, and a set of references, and only a resolver knows them.

- **find_definition** — where a symbol is declared, through the import or alias that names it
- **find_references** — every use across the workspace, excluding look-alikes in other scopes
- **hover** — the type the checker actually resolved, before you assume one
- **list_symbols** — every symbol a file declares, instead of grepping for `def ` or `class `
- **rename_symbol** — plans a workspace-wide rename and reports the files it would touch, without writing. **Always prefer it over `Edit` with `replace_all`**, which cannot tell one scope from another; apply the reported edits yourself.

Grep is still right for what is genuinely characters: a string literal, a comment, a non-Python file.

---

## Configuration

### Environment Variables

The `.env` file contains template configuration. Create `.env.local` for secrets (gitignored):

```bash
# .env.local - your secrets (ANTHROPIC_API_KEY is read directly by the SDK from env)

# Optional overrides
# AGENT_MODEL=claude-opus-5
# AGENT_MAX_BUDGET_USD=5.00
# AGENT_MAX_TURNS=50
# AGENT_SANDBOX_ENABLED=false   # run without Docker (disables code execution tools)
# AGENT_NOTES_PATH=./notes      # relocate session data
# AGENT_LOGS_PATH=./logs        # relocate trace logs
```

Settings in `.env.local` override `.env`. Configuration is loaded via pydantic-settings — see `src/lup_template/agent/config.py`.

Harness settings changes stay **project-level**, in the tree the harness owns ("""
        ),
        models.NativePath(location="project_settings"),
        models.TextPart(
            text=r"""), never user-level.

---

## Process & Communication

### Asking Questions

**Always surface a question as a question**, through whatever structured question facility the harness gives you, rather than as narration the user has to notice. This applies to clarifying requirements, offering choices, confirming destructive actions, proposing changes, and any situation needing user input.

Even for open-ended questions, attach concrete options plus a free-form one. Structured answers are what downstream notification parsing reads.

**When proposing changes:** Propose (don't assume), show relevant current state, explain rationale, offer alternatives.

**When in doubt, ask.**

### Slash Commands & Skills

**After every command invocation**, reflect on how it was actually used vs. documented:

1. Compare intent vs usage
2. Notice patterns — user corrections signal the command should evolve
3. Proactively propose updates, as a question the user answers

**Evolution signals:** User provides external docs, corrects your approach, asks for something the command should cover, or ignores sections.

### External Resources

When a question is about the harness you are running under, its agent SDK, or its model API, read that runtime's own documentation rather than answering from memory:

1. Delegate to the documentation subagent your harness ships, where it has one.
2. Fetch the vendor's documentation directly — """
        ),
        models.RuntimeDocs(),
        models.TextPart(
            text=r""". The fetch scopes the permission policy admits are declared in `harness/catalog.py`.

When the user provides documentation links, incorporate that knowledge into the guidance source or the relevant skill declaration.

---

## Self-Improvement Loop

`docs/self-improvement.md` carries the full loop: how to diagnose a failure
through the pipeline, the three levels of analysis, what to track per session,
and the anti-patterns to avoid. Read it when running the feedback-loop,
review, or meta skills — each of them works from it.

**When analyzing failures:** Ask "what general principle would have prevented this?" not "what specific rule would catch this case?" The fix is almost never a prompt line about a specific decision. Instead: does the agent have enough context? The right tools? A strong enough model?

When the principle points to a workflow failure, fix the workflow at the exact juncture where the failure enters — don't add a warning about it. A step named "Classify each commit" invites whole-commit thinking regardless of how many times the text says "decompose." Renaming the step to "Extract portable pieces" and separating reading from judging makes the failure structurally impossible. Warnings coexist peacefully with the workflows they warn against; structural changes don't.

The durable fix is a capability, not a rule: trace the failure to the missing
input or the workflow step where the wrong decision entered, and change that.
A prompt rule coexists peacefully with the failure it warns about.
"""
        ),
    ],
)
