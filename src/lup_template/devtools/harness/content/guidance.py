"""Canonical repository guidance.

The portable conventions are composed from ``lup.devtools.harness.content
.conventions`` rather than restated here, so this document holds only what is
true of *this* repository: its two-package layout, its tooling paths, and the
placement rule that follows from having both halves in one tree.
"""

import lup.devtools.harness.content.conventions as conventions
import lup.harness.models as models

DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.TextPart(
            text=r"""# Lup repository guidance

Lup is a reusable framework and template for autonomous, tool-using agents. Keep library code provider-neutral and keep provider syntax in generated adapter artifacts.

"""
        ),
        *conventions.PLAN_AT_AGENT_SPEED,
        *conventions.AGENT_VOCABULARY,
        models.TextPart(
            text=r"""## Development Workflow

### Git Workflow

Work in a **git worktree**, not a branch switched in place, and never commit _code_ directly to `dev`. Create one with `uv run lup-devtools dev worktree create feat-name` — it lands as a sibling under `tree/`, never nested inside another checkout — and then """
        ),
        models.RelocateSession(path="the path it prints"),
        models.TextPart(
            text=r""", because creating a worktree does not move the session, and edits left in the old checkout never reach the branch.

`docs/contributing.md` carries the two-tier branch model, the commit-type table, and the loop from a fresh worktree to a merged pull request.

"""
        ),
        *conventions.MERGE_CONFLICT_RESOLUTION,
        models.TextPart(
            text=r"""**Generated artifacts are regenerated, never hand-merged.** Take either side of the conflict, regenerate, and let the drift check confirm it settled; `docs/contributing.md` carries the manifest driver and the recovery.

"""
        ),
        *conventions.COMMIT_GUIDELINES,
        models.TextPart(
            text=r"""`docs/contributing.md` carries the type vocabulary.

### Editing Style

**Prefer small, atomic edits.** The edit hook auto-allows a change block of at most three "real" changed lines. `docs/permissions.md` carries what counts as real, and which gates stay explicit approvals in every mode.

- Split large changes into multiple small edits (<=3 real lines per Edit call)
- Separate concerns — imports in one edit, logic in another
- Use `rename_symbol` for identifier renames instead of `Edit` with `replace_all`

---

## Code Conventions

### Primary Libraries

Build on claude-agent-sdk and pydantic; `docs/conventions.md` names each library and what it is for.

### Model Selection

Default to the **strongest** tier for the main agent, every subagent, reviewer, and background agent. This runs on a subscription where the best model is the point: reach for a **balanced** tier only when latency or cost provably dominates and quality is non-critical, and for the **fast** tier almost never. A role that genuinely warrants a cheaper model declares that tier explicitly with a reason; otherwise it inherits the strongest default. Agent declarations state the tier, not a model id — each runtime spells the tier in its own lineup.

"""
        ),
        *conventions.TYPE_SAFETY,
        models.TextPart(
            text=r"""### Tool Input Schemas

Define tool inputs as BaseModel classes with `Field(description=...)`, and take both the `@tool` schema and the validation from that model. `docs/conventions.md` puts each form beside the raw dict it replaces.

### Error Handling

**MCP tools:** Return `{"content": [...], "is_error": True}` for recoverable errors. Log with `logger.exception()`. Include actionable messages.

**Agent code:** Raise exceptions for unrecoverable errors. Use `with_retry` for transient failures. Validate inputs early with Pydantic.

**Never silently swallow errors** — handle them meaningfully or let them propagate.

### Structured Data, Not Strings

If you're reaching for `re`, `.replace()`, `.split()`, or string slicing to process structured data, something is wrong. `docs/conventions.md` names the parser to reach for, per format.

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

"""
        ),
        *conventions.NO_BARREL_FILES,
        *conventions.NO_PRIVATE_PREFIXES,
        models.TextPart(
            text=r"""---

## Tooling

### Package Tools

`uv` is the package manager — `uv add <package>`, never edit pyproject.toml directly. Formatting and linting are ruff, type checking is pyright; `docs/contributing.md` carries the commands that have to be green.

### lup-devtools

Development tooling is exposed as the `lup-devtools` CLI entry point, composed in `src/lup_template/devtools/main.py` from two halves: the workflow commands in `packages/lup/src/lup/devtools/`, and what only this repository has beside them. **Always use `lup-devtools` instead of ad-hoc commands.** Never use `uv run python -c "..."` or bare `python`/`python3` — these are denied by the Bash permission hook.

If you find yourself running the same command repeatedly, **add a command** — to `packages/lup/src/lup/devtools/` when another project on lup would want it, to `src/lup_template/devtools/` when only this one would.

`tmp/` is scratch: gitignored, so nothing written there reaches a diff, a reviewer, or the human — which is why it does not execute. Match the rung to the question: to **read** code, `py info`/`py source`/`py search`/`py imports` plus the codeintel tools answer without running anything; to **compute** something, `lup-devtools py eval '<expression>'` auto-imports and evaluates in the sandbox; with no sandbox available, add a devtools command. `docs/contributing.md` carries the rest of the ladder, down to a heredoc behind a `# lup: escalate: <why>` marker. The argument is reviewability, not power — an agent may already edit `devtools/` and run it.

"""
        ),
        models.TextPart(
            text=r"""Run `uv run lup-devtools --help` for the command tree;
`docs/template.md` lists the sub-apps, rendered from the same typed roster the
CLI itself wires.

`lup-devtools harness generate all` regenerates and reconciles every native
plugin; `harness <runtime>` regenerates one and launches it. `docs/harness.md`
carries the rest of the loop and how a launch reaches the plugin on each
runtime. Personal cache, trust, and session state are never committed.

### Lup Skills & Agents

`docs/harness.md` carries the roster of every skill and agent this plugin
ships, each with the one line that describes it. Both lists are rendered from
the typed declarations: the ones about agent work in
`packages/lup/src/lup/devtools/harness/content/catalog.py`, the ones about
being a template in
`src/lup_template/devtools/harness/content/catalog.py`, which composes both.
Change the catalog that owns the subject, then regenerate.

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
  classified deny or ask into an approval question carrying that reason.
- `# lup: ignore[<rule-id>]` on the offending line suppresses exactly that
  anti-pattern, and no other.

`docs/permissions.md` carries how the escalation marker scopes and the recovery
path when work is denied as unjudged; `docs/contributing.md` carries the
suppression marker's scoping.

Use `"""
        ),
        models.SkillInvocation(plugin="lup", skill="hooks"),
        models.TextPart(
            text=r"""` to change the canonical policy inputs, regenerate both native
plugins, and run the shared fixture suite. `settings.json`
holds only native settings outside this semantic policy boundary.

### Code Intelligence

The `codeintel` tool group answers questions about code by *resolving* it, through a language server. **Prefer them over grep for anything about a name.** `docs/conventions.md` lists what each tool answers.

**Always prefer `rename_symbol` over `Edit` with `replace_all`**, which cannot tell one scope from another; apply the edits it reports yourself.

`grep` through `Bash` is still right for what is genuinely characters: a string literal, a comment, a non-Python file.

---

## Configuration

`.env` holds template defaults; `.env.local` holds secrets, is gitignored, and overrides them. Configuration is loaded through pydantic-settings in `src/lup_template/agent/config.py`, which is the only module that reads the environment. `docs/template.md` lists the variables.

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

**Explain from scratch, and walk through the options.** A finding handed over as a verdict cannot be judged — only accepted or refused on trust. Explain the underlying problem as though the reader has none of your context, then the options, then your own recommendation marked as yours. Prefer being slow and complete over being brief: the reader is deciding, and a decision made without the reasoning is one they have to re-derive later.

This is what makes a claim checkable rather than plausible. Verify each one against **what was actually asked** — the note's own words, the issue's own report — not against a title, a commit subject, or your own earlier summary. A claim that survives that check is worth stating plainly; one that does not is worth correcting out loud, including when the claim was yours.

**When in doubt, ask.**

### Slash Commands & Skills

**After every command invocation**, reflect on how it was actually used vs. documented:

1. Compare intent vs usage
2. Notice patterns — user corrections signal the command should evolve
3. Proactively propose updates, as a question the user answers

**Evolution signals:** User provides external docs, corrects your approach, asks for something the command should cover, or ignores sections.

### Reporting Friction

When the tooling fights you, **open a GitHub issue against this repository** rather than only working around it and moving on. A workaround that lives in one session's narration teaches nobody; the issue is what survives the session.

File one whenever a command half-completes and leaves inconsistent state, a classifier reports a failed probe as though it were a fact, a sandbox or permission boundary blocks an operation the documented workflow prescribes, or a recovery needed steps the workflow never named.

Record what you observed rather than what you concluded: the exact command, the exact error, the state it left behind, and what the recovery cost. Name the component that owns the fix. A friction report is evidence, which is worth more than a guess at the cause — and evidence is what the self-improvement loop below consumes.

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

"""
        ),
        *conventions.FAILURE_ANALYSIS,
        models.TextPart(
            text=r"""The durable fix is a capability, not a rule: trace the failure to the missing
input or the workflow step where the wrong decision entered, and change that.
A prompt rule coexists peacefully with the failure it warns about.
"""
        ),
    ],
)
