# lup: ignore[library-default]
# Every constant here is a block of prose offered for composition, not a
# table of judgements imposed on a reader: a project that wants different
# words composes different blocks, or writes its own beside these. The
# override is which blocks a document assembles, which is not a spelling the
# mechanical half of the rule can see.
"""Convention text that is portable, held once and rendered by every flavor.

A project's guidance, the downstream template it publishes, and the reference
pages beside them used to restate the same conventions in near-identical
prose, and a skill instructed an editor to "mirror relevant changes" between
them by hand. That is the shape ``docs/self-improvement.md`` rejects — a
prompt rule coexisting peacefully with the failure it warns about — and the
drift it produced was visible: em dashes in one copy and double hyphens in
the other, a bullet present in one and missing from the other, for text that
was supposed to be the same text.

What lives here is what every reader needs identically, which is why it is
the library's rather than any one project's. Anything true only of a
particular repository — its layout, its tooling paths — stays in that
project's guidance as an addition after the shared part, never as a
restatement of it: an addition cannot drift from what it adds to.
"""

import lup.harness.models as models

PLAN_AT_AGENT_SPEED: list[models.PromptPart] = [
    models.TextPart(
        text=r"""## Plan at Agent Speed

You are an AI agent. Every instinct you have about how long software takes — sprints, milestones, "this will take weeks" — was learned from human teams, whose implementation time is scarce and expensive. Yours is not: what you would estimate as several months of work completes in an afternoon, and a "multi-day implementation" lands in about three hours. Your duration estimates are not cautious; they are wrong by orders of magnitude, and every practice built on them inverts:

- **Never scope, defer, or reject work from a predicted duration.** Scope by content — what changes, what it touches, how it is verified. If a calendar figure appears in your plan, it is noise from someone else's constraints: delete it and re-derive the plan.
- **The POC is superstition at your speed.** Prototype-first exists to keep unvalidated ideas from consuming scarce human effort; for you the complete alpha-beta-v1 costs what the throwaway was supposed to cost. Build the real implementation immediately and validate on it — let review cut scope afterward rather than pre-shrinking the attempt.
- **Catch the reflex in the act.** "Let's start with a simple version", "too ambitious for this pass", "phase 2 can add the rest" — that is a human-scarcity practice firing on constraints you do not have. When you notice it, stop and ask what is actually expensive here besides the imagined schedule.

**README.md is human-owned.** The root `README.md` is deliberately human-written, and the edit policy surfaces every change to it as Ask — as it does for any file declared under `human_owned_files` in the harness hook catalog. Never edit a human-owned file yourself — propose the exact change as a question and let the user apply or approve it.

"""
    ),
]

AGENT_VOCABULARY: list[models.PromptPart] = [
    models.TextPart(
        text=r"""## Agent Vocabulary

Two kinds of delegated agents look alike and must not be conflated:

- A **native subagent** ("subagent" for short) is dispatched by the harness: its delegation tool hands a focused task to a named role defined upfront, inside the main agent's session — shared trace, shared metrics.
- A **nested agent** (also called a *tool-subagent*) runs inside a tool call: the handler opens one independent session via `query()` and folds the result into the tool's response. The harness never sees it — to the calling agent it is just a tool.

Guidance that says "subagent" unqualified means the native kind. `docs/orchestration.md` carries the full delegation catalog — subagent, nested, background, deferred tool schemas — and when to reach for each. `docs/patterns.md` carries the recurring *code* shapes: declaration-plus-renderer, closed-by-construction, the typed-matcher router, and the engine-versus-surface split.

"""
    ),
]

TYPE_SAFETY: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### Type Safety

- **Never silently swallow exceptions** — no `except ...: pass`, no `contextlib.suppress`; log with `logger.exception()`, handle meaningfully, or re-raise. Catch-all `except Exception` is fine at boundaries (task loops, subagent delegation) that do so; bare `except:` and `except BaseException` are never fine
- **Every function must specify input and output types**
- **Never use `Any`, `dict[str, Any]`, or `dict[str, object]`** — Use `TypedDict` for dict-like data, `BaseModel` for validated models, or specific types
  - `docs/conventions.md` maps each origin of dict-shaped data to its typed stand-in, and lists the SDK types to prefer
- **Python 3.12+ generics**: `class A[T]`, not `Generic[T]`
- Use `TypedDict` and Pydantic models for structured data
- Never manually parse agent output — use structured outputs via Pydantic
- **Never use `# type: ignore`** — Ask the user how to properly fix type errors
- **`# lup: ignore` escape hatch** — when `Any` or another anti-pattern is genuinely needed at an untyped boundary, an inline ignore requests user approval instead of silencing the check; prefer the typed `# lup: ignore[rule-id]` over the bare form (`docs/contributing.md`), and `docs/rules.md` indexes every rule id a denial can cite
- **Use Pydantic BaseModel instead of dataclasses**
- **Use `match`/`case` instead of `if`/`elif` chains** for dispatching on values or ranges
- **Never dispatch on the type of our own models** — no `isinstance` over a union we declare, no `case ClassName()` arms, no `assert_never` net. The union's base declares the operation and each subtype answers or declines it, so a new variant is one class instead of an edit to every walk that would have to notice it, and a filter cannot go stale by omission. Narrowing untyped data at a boundary — a vendor payload, a `JsonValue` — is the different case where `isinstance` is right, because those alternatives are not ours to give a method to. The `own-model-dispatch` rule enforces exactly this line: it fires only on classes we define that inherit `BaseModel`
- **Compiling is stronger than emitting** — build an artifact from a typed declaration and it cannot diverge; transport checked source and a checker can only warn once it already has. When tempted to add a check that two things still match, ask whether one can be derived from the other instead (`docs/patterns.md`)
- **A constant should probably be an overridable default** — a canonical value (a native tool's real name, a vendor's field) is fine hardcoded; a non-canonical one (an allowlist, a ceiling, a retry count) is our judgement, so give it a default a caller can override rather than a constant they must fork to change (`docs/patterns.md`)
- **A capability ABC is an engine, not a surface** — a consumer never holds or calls one directly; it holds a concrete plain class that composes the seam and is parametrized by which implementation fills it. `ModelRouter` over `ModelMatcher` is the shape, `SessionFactory` over a `SessionOpener` the surface. The test is behaviour: a frozen value that only carries capabilities is a transparent carrier, and a seam that is only ever injected says so in its own docstring (`docs/patterns.md`)
- **Use `for`/comprehensions over `while`** — reach for structured iteration whenever the iteration space is expressible (a range, a sequence, an iterator, `enumerate`/`zip`); reserve `while` for genuinely unbounded, condition-driven loops

"""
    ),
]

NO_BARREL_FILES: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### Imports: No Barrel Files

**Never use `__init__.py` re-exports or `__all__` in internal packages.** Import directly from the module that defines the symbol.

- `from lup.mcp import lup_tool` — not `from lup import lup_tool`
- `__init__.py` files should contain only the module docstring (no imports, no `__all__`)
- Barrel files drift out of sync and hide real dependencies

**Exception:** Standalone library packages under `packages/` may use re-exports with `__all__` in their top-level `__init__.py` to declare a public API. Only the package root — not subpackages.

"""
    ),
]

NO_PRIVATE_PREFIXES: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### Naming: No Private Prefixes

**Never use `_` prefixes** on functions, methods, classes, or constants. Nothing is private.

This holds for module-level functions, class methods, constants, and classes alike; `docs/conventions.md` shows each form beside the prefixed name it replaces.

**If a helper truly shouldn't pollute the module namespace**, nest it inside its only caller rather than marking it private.

**Avoid useless mini-wrappers.** If a function's only purpose is to call another function with no additional logic, inline it.

**Exceptions:** `_` prefix is fine for unused parameters (`_context`, `_exc_type`) — that's a linting convention, not a privacy convention.

"""
    ),
]

FAILURE_ANALYSIS: list[models.PromptPart] = [
    models.TextPart(
        text=r"""**When analyzing failures:** Ask "what general principle would have prevented this?" not "what specific rule would catch this case?" The fix is almost never a prompt line about a specific decision. Instead: does the agent have enough context? The right tools? A strong enough model?

When the principle points to a workflow failure, fix the workflow at the exact juncture where the failure enters — don't add a warning about it. A step named "Classify each commit" invites whole-commit thinking regardless of how many times the text says "decompose." Renaming the step to "Extract portable pieces" and separating reading from judging makes the failure structurally impossible. Warnings coexist peacefully with the workflows they warn against; structural changes don't.

"""
    ),
]
"""The two paragraphs every self-improvement reader needs identically.

Authored in three places before this — the repository guidance, the
downstream template, and the reference page — and already visibly drifted:
one copy still asked "Is the model strong enough?" in the older, longer
phrasing. Nothing but holding them once keeps three copies in step.
"""

MERGE_CONFLICT_RESOLUTION: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### Merge Conflict Resolution

**Never silently drop code during conflict resolution.** The bias is toward inclusion — keeping both sides is always safer than losing features. A rename on one side must not swallow an addition on the other.

Before completing any merge, **audit for deletions**: compare the result against both parents and verify that every removed function, parameter, or command was intentionally removed, not lost as a side effect of choosing one conflict side.

Use `"""
    ),
    models.SkillInvocation(plugin="lup", skill="merge"),
    models.TextPart(
        text=r"""` (with no argument) for guided conflict resolution. See the command for the full decision tree.

"""
    ),
]

COMMIT_GUIDELINES: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### Commit Guidelines

- **Commit before responding** — Don't accumulate changes across responses
- **Commit early, commit often** — Frequent commits provide checkpoints
- **Keep commits atomic** — If you need "and" in your message, it should be two commits
- **History will be rebased** — Don't worry about perfect messages during development
- **Meaningful final commits** — After rebasing, each commit should tell what changed and why

**Format:** `type(scope): description`

"""
    ),
]
