# lup: ignore[constant-declaration]
# Each constant here is one section of a single document, not a judgement a
# caller could hold differently: the sections compose into this repository's
# guidance and nothing else reads them. The same reasoning as `conventions`
# next door, which states it the same way.
"""Canonical repository guidance.

The portable conventions are composed from ``lup.devtools.harness.content
.conventions`` rather than restated here, so this document holds only what is
true of *this* repository: its two-package layout, its tooling paths, and the
placement rule that follows from having both halves in one tree.

What earns space here is what an agent needs before it knows to look: a norm
no gate fires on, or a mechanism it must recognise the first time one stops
it. Anything a denial names at the moment it matters is left to the denial
and to the generated reference behind it — a second copy in always-loaded
prose can only fall behind the registry that actually runs, and is redundant
for as long as it agrees.

One constant per section, spliced in reading order by ``guidance_parts``.
The document is held to a byte ceiling it sits close to, and a single
returned list gave nobody a place to see which section was spending it —
``dev guidance`` reports per heading, and these are the pieces that answer.
"""

import lup.devtools.harness.content.conventions as conventions
import lup.harness.models as models
from lup.codescan.common import RuleSelection

HEADER: list[models.PromptPart] = [
    models.TextPart(
        text=r"""# Lup repository guidance

Lup is a reusable framework and template for autonomous, tool-using agents. Keep library code provider-neutral and keep provider syntax in generated adapter artifacts.

"""
    ),
]

CHANGING_THE_POLICY: list[models.PromptPart] = [
    models.TextPart(text=r"""Change the policy those gates enforce with """),
    models.SkillInvocation(plugin="lup", skill="hooks"),
    models.TextPart(
        text=r""", which edits the canonical inputs in `lup.policy` and the `HookSet` in `devtools/harness/catalog.py`, regenerates both native plugins, and runs the shared fixture suite. Harness generation compiles one hermetic dispatcher and runtime per plugin, so never edit a generated dispatcher or runtime.

Harness settings stay project-level, in the tree the harness owns ("""
    ),
    models.NativePath(location="project_settings"),
    models.TextPart(
        text=r"""), which holds only the native settings outside that semantic policy boundary — never user-level.

"""
    ),
]

MARKER_VOCABULARY: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### The `# lup:` Marker Vocabulary

A `# lup:` (or `// lup:`) comment is **actionable review feedback** left in the code for the agent to address — anything whose subject is the code and belongs at the site it concerns. Three flavors carry feedback, and **deleting one is denied**: bare `# lup: <text>` is open, `# lup: solved: <text>` claims you addressed it, `# lup: defer: <text>` parks it. Two more share the namespace without being feedback and go when what they annotate does — `# lup: ignore[<rule>]` is the suppression above, and `# lup: template: <decision>` marks a customization point the scaffold leaves to whoever adopts it.

Resolve open feedback by fixing what it points at, or, for a question, by answering it definitively in the code, the docs, or a recorded user decision. Then rewrite the marker as **`# lup: solved: <the note's original words>`**, text unchanged, so the claim sits beside what it claims to fix and can be checked against what was asked; only the verify-solved pass retires one. `docs/contributing.md` carries the lifecycle, and how a customization marker reads differently in a scaffold and in a repository that adopted it (`"""
    ),
    models.SkillInvocation(plugin="lup", skill="resolve"),
    models.TextPart(
        text=r"""`), and `dev todos` walks the customization points still standing.

"""
    ),
]

DEFERRED_WORK: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### Deferred Work

**Never create tracking files.** A `TODO.md`, backlog, or roadmap parks a decision where no workflow will surface it again — deferral by tracking file is delegation to nobody. Work not being done now lives in one of three places, chosen by what it attaches to:

- **A `# lup: defer: <text>` note**, when the work belongs to a site in this code, where `dev check` keeps it visible until somebody wakes it. A bracketed `defer[gone:<path>]` or `defer[branch:<name>]` states a gate `dev check` resolves rather than reads, failing the run the answer turns yes; any other gate stays prose, and prose stays advisory.
- **A GitHub issue**, when the tooling is misbehaving rather than the code and the repair is not one this session can make — nothing in the tree owns that, so a note would have nowhere to sit.
- **A question to the user**, when whether to defer at all is itself the open question.

`docs/contributing.md` carries what each gate wakes on, and the one exception to all three — a `tmp/` briefing, which starts a fresh session on a situation this one cannot finish, rewritten whole rather than appended to.

---

"""
    ),
]

DEVELOPMENT_WORKFLOW: list[models.PromptPart] = [
    models.TextPart(
        text=r"""## Development Workflow

Use a **git worktree**; never commit code to `dev`. Run `uv run lup-devtools dev worktree create feat-name`, then """
    ),
    models.RelocateSession(path="the path it prints"),
    models.TextPart(
        text=r""" — creation does not move the session, so old-checkout edits miss the branch. Late relocation may persistently reject ordinary shell words anywhere in argv. `docs/contributing.md` carries the branch model, refused-word set, and merge loop.

"""
    ),
]

COMMIT_TYPE_POINTER: list[models.PromptPart] = [
    models.TextPart(
        text=r"""The type comes from the table in `docs/contributing.md`, which the commit skill renders at the moment one is being chosen.

"""
    ),
]

CODE_CONVENTIONS: list[models.PromptPart] = [
    models.TextPart(
        text=r"""---

## Code Conventions

Build on `lup` and pydantic. The runtime an application composes against is provider-neutral, and each provider's SDK is one adapter's dependency behind an extra rather than a framework the application talks to: no module under `src/lup_template/` imports one, and `seam-boundary` keeps adapter imports to the composition roots that name them. `docs/conventions.md` names each library and puts each typed form beside the raw dict it replaces. Prefer an existing PyPI library to raw HTTP or a rebuilt wheel.

**Model selection.** Default to the **strongest** tier everywhere — main agent, subagents, reviewers, background agents. This runs on a subscription where the best model is the point: reach for **balanced** only when latency or cost provably dominates quality, and **fast** almost never. A role that warrants less declares that tier with a reason, and declarations state a tier, not a model id.

**Error handling.** A `@lup_tool` handler takes a validated model and returns one; raise `ToolError` to send a recoverable failure back as an MCP error saying what to do about it — the `is_error` envelope and the input-validation reply are the decorator's. Elsewhere raise for unrecoverable errors, wrap transient ones in `with_retry`, validate inputs early, and never swallow one silently. A catch-all `except Exception` is fine at a boundary that logs, handles, or re-raises — a task loop, a subagent delegation — which is why no rule refuses one.

**Placement, in this repository.** Reusable utilities belong in `packages/lup/`; what only this application needs belongs in `src/lup_template/`. If logic already exists in `lup`, import it rather than copying it. Deciding a module belongs on the other side is one line of judgement and a hundred of consequence, which is where the judgement usually gets abandoned — so the consequence is a command: `dev relocate old.module=new.module` repoints every import and reports the mentions it left for you.

"""
    ),
]

TOOLING: list[models.PromptPart] = [
    models.TextPart(
        text=r"""---

## Tooling

`uv` is the package manager — `uv add <package>`, never edit pyproject.toml directly. Lint and format with ruff, type-check with pyright; `docs/contributing.md` carries the commands that have to be green.

`lup` itself is the one dependency not added that way: how a project obtains it is a mode `dev library` reads and rewrites, and the mode decides what upgrading means. Ask `dev library status` before assuming lup's source is on disk to edit — in three of the four modes it is not.

When a command genuinely has to run outside the sandbox, put it through the runtime's native per-call escalation on its first attempt rather than replacing the whole session with an unsandboxed one; the policy still judges the escalated call, so an allowed command can be approved at that narrower boundary.

### lup-devtools

Development tooling is the `lup-devtools` CLI, composed from the reusable commands under `packages/lup/` and this repository's under `src/lup_template/`. **Use it instead of ad-hoc commands.** Inline Python (`-c`, `-m`, a REPL, or bare `python`) is denied; `uv run python <script.py>` is allowed because a file can be reviewed. Running the same command repeatedly means **add a command** to the half that would reuse it.
`tmp/` is gitignored scratch. To **read** code, use `py info`/`py source`/`py search`/`py text`/`py imports` or codeintel; to **compute once**, write a script under `tmp/` and run it; to reuse the computation, add a devtools command. `docs/contributing.md` carries the rest of this reviewability ladder.

The `codeintel` group answers questions about code by *resolving* it, through a language server. **Prefer it or `py search` for anything about a name**, and `rename_symbol` over an edit with `replace_all`, which cannot tell one scope from another. Use `py text` for literal text in explicitly scoped Python source, and grep for characters in non-Python files.
`docs/commands.md` carries every command the CLI serves, walked from the wired app at generation time rather than listed by hand — so a command exists there by existing, and reading it is how you find one you did not know to look for. `--help` gives its options.

### Generated Trees

`harness generate all` regenerates every native plugin; `harness <runtime>` regenerates one and launches it. Skills and agents render from typed catalogs — one under `packages/lup/` for what is about agent work, one under `src/lup_template/` for what is about being a template, composing both. Change the catalog that owns the subject, then regenerate.

**Every runtime, same change.** State and build each answer to every policy, flag, hook, or artifact; name substitutes for unsupported concepts. One runtime drops `sandbox="outside"` for lack of a per-call escape. Done means `harness generate all` reconciles both; `docs/permissions.md` maps gaps.

"""
    ),
]

CONFIGURATION: list[models.PromptPart] = [
    models.TextPart(
        text=r"""---

## Configuration

Configuration loads through pydantic-settings in `src/lup_template/agent/config.py`, the only module that reads the environment. `.env.local` holds secrets, is gitignored, and overrides the defaults in `.env`; `docs/template.md` lists the variables.

"""
    ),
]

PROCESS_AND_COMMUNICATION: list[models.PromptPart] = [
    models.TextPart(
        text=r"""---

## Process & Communication

**Wait on pushed tool output, not polls.** Keep a long-lived command's resumable call live and yield to the runtime's event-driven waiter. Repeated shell-session reads are polling, even with long timeouts.

**Surface every question through the harness's structured facility**, not narration: clarifications, choices, and destructive confirmations included. Even open-ended questions need concrete options plus free-form because downstream notifications read structured answers.

**Explain decisions from scratch:** the problem, relevant state, options, rationale, and your recommendation marked as yours. A verdict cannot be judged; prefer complete context over brevity.

Verify claims against **what was actually asked** — the note or issue itself, not a title, commit, or prior summary. State surviving claims plainly; correct failures out loud, including yours.

**After every command**, compare actual use with its docs and propose any update as a question. External docs, corrections, uncovered requests, or ignored sections signal that the command should evolve.

"""
    ),
]

REPORTING_FRICTION: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### Reporting Friction

**Fix tooling friction instead of working around it.** This repository usually owns the hook, command, or classifier that obstructed you. Repair it on its own branch so the diff stays single-purpose.

**Open an issue only when this session cannot repair it**: the owner is outside this repository, a design decision is missing, or reproduction is the work. A narrated workaround teaches nobody, so what cannot be fixed is still recorded.

Record the exact command, error, resulting state, recovery cost, and owning component — repair commit or issue — with `uv run lup-devtools dev report-friction`; the checkout selects the repository. Evidence beats conclusions.
**Read the tracker first.** `uv run lup-devtools dev issues` lists open reports; search closed ones too. Update a matching report with `--issue NUMBER`, or comment on a closed match, rather than splitting evidence across duplicates.

"""
    ),
]

EXTERNAL_RESOURCES: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### External Resources

When a question is about the harness you run under, its agent SDK, or its model API, read that runtime's own documentation rather than answering from memory — delegate to the documentation subagent your harness ships, or fetch the vendor's docs at """
    ),
    models.RuntimeDocs(),
    models.TextPart(
        text=r""". The fetch scopes the policy admits are declared in `harness/catalog.py`. When the user provides documentation links, fold what they teach into the guidance source or the relevant skill.

"""
    ),
]

SELF_IMPROVEMENT: list[models.PromptPart] = [
    models.TextPart(
        text=r"""---

## Self-Improvement Loop

`docs/self-improvement.md` carries the full loop, and the feedback-loop, review, and meta skills each work from it.

"""
    ),
    *conventions.FAILURE_ANALYSIS_BRIEF,
    models.TextPart(
        text=r"""The durable fix is a capability, not a rule: trace the failure to the missing input or the workflow step where the wrong decision entered, and change that — a prompt rule coexists peacefully with the failure it warns about.
"""
    ),
]


def guidance_parts(selection: RuleSelection) -> list[models.PromptPart]:
    """This repository's guidance, naming only the rules it still enforces."""
    return [
        *HEADER,
        *conventions.PLAN_AT_AGENT_SPEED,
        *conventions.AGENT_VOCABULARY,
        *conventions.THE_GATES,
        *CHANGING_THE_POLICY,
        *MARKER_VOCABULARY,
        *DEFERRED_WORK,
        *DEVELOPMENT_WORKFLOW,
        *conventions.MERGE_CONFLICT_RESOLUTION,
        *conventions.COMMIT_GUIDELINES,
        *COMMIT_TYPE_POINTER,
        *CODE_CONVENTIONS,
        *conventions.design_principles(selection),
        *conventions.SANCTIONED_EXCEPTIONS,
        *TOOLING,
        *CONFIGURATION,
        *PROCESS_AND_COMMUNICATION,
        *REPORTING_FRICTION,
        *EXTERNAL_RESOURCES,
        *SELF_IMPROVEMENT,
    ]


def document(selection: RuleSelection | None = None) -> models.PromptDocument:
    """The guidance as one document, built against the project's selection.

    Taking the selection rather than reading one keeps the catalog free to
    import this module: the catalog owns the declaration and hands it down,
    so nothing here reaches back up for it.
    """
    return models.PromptDocument(
        source=__name__, parts=guidance_parts(selection or RuleSelection())
    )
