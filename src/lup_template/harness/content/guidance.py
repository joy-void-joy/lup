"""Canonical repository guidance.

The portable conventions are composed from ``lup.harness.content
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

import lup.harness.content.conventions as conventions
import lup.harness.models as models
from lup.harness.codescan.common import RuleSelection

HEADER = models.GuidanceSection(
    id="header",
    parts=[
        models.TextPart(
            text=r"""# Lup repository guidance

Lup is a reusable framework and template for autonomous, tool-using agents: keep library code provider-neutral, and provider syntax in generated adapter artifacts.

"""
        ),
    ],
)

CHANGING_THE_POLICY = models.GuidanceSection(
    id="changing-the-policy",
    parts=[
        models.TextPart(text=r"""Change the policy those gates enforce with """),
        models.SkillInvocation(plugin="lup", skill="hooks"),
        models.TextPart(
            text=r""", which edits `lup.policy` and the catalog's `HookSet`, regenerates both plugins, and runs the fixture suite; generation compiles one hermetic dispatcher and runtime per plugin, so never edit a generated one. Harness settings stay project-level, in """
        ),
        models.NativePath(location="project_settings"),
        models.TextPart(
            text=r""", which holds only native settings outside that policy boundary — never user-level.

"""
        ),
    ],
)

MARKER_VOCABULARY = models.GuidanceSection(
    id="marker-vocabulary",
    parts=[
        models.TextPart(
            text=r"""### The `# lup:` Marker Vocabulary

A `# lup:` (or `// lup:`) comment is **actionable review feedback** about the code, at the site it concerns: bare is open, `solved:` claims you addressed it, `defer:` parks it, and **deleting any of the three is denied**. Resolve one by fixing what it points at, or answering a question definitively, then rewriting it as **`# lup: solved: <the note's original words>`**, text unchanged, so the claim can be checked against what was asked; only the verify-solved pass retires one. `ignore[<rule>]` and `template: <decision>` share the namespace without being feedback, and go when what they annotate does. `docs/contributing.md` carries the lifecycle, the bracketed `defer[<gate>]` spellings `dev check` resolves rather than reads, and what a `template:` marker asks of a repository that adopted the scaffold (`"""
        ),
        models.SkillInvocation(plugin="lup", skill="resolve"),
        models.TextPart(
            text=r"""`); `dev todos` walks those standing.

"""
        ),
    ],
)

DEFERRED_WORK = models.GuidanceSection(
    id="deferred-work",
    parts=[
        models.TextPart(
            text=r"""### Deferred Work

**Never create tracking files, and never write to the harness's persistent memory** — a file per profile, unversioned, unreviewed. A `TODO.md`, backlog, roadmap, or memory file parks a decision where no workflow will surface it again: delegation to nobody. What outlives this session goes to a `# lup: defer:` note at the site it concerns, which `dev check` keeps visible until somebody wakes it; a GitHub issue, milestone, or plan when the tooling rather than the code misbehaves, or the repository is deciding what comes next; this guidance's source, regenerated, for a rule every future session should carry; a `tmp/` briefing, rewritten whole and never appended, for what a fresh session picks up; or a question to the user, when whether to defer at all is itself the open question. `docs/contributing.md` carries which is which.

---

"""
        ),
    ],
)

DEVELOPMENT_WORKFLOW = models.GuidanceSection(
    id="development-workflow",
    parts=[
        models.TextPart(
            text=r"""## Development Workflow

Use a **git worktree**; never commit code to `dev`. Run `uv run lup-devtools dev worktree create feat-name`, then """
        ),
        models.RelocateSession(path="the path it prints"),
        models.TextPart(
            text=r""" — creation does not move the session, so old-checkout edits miss the branch. `docs/contributing.md` carries the branch model, the refused words a late relocation meets, and the merge loop.

"""
        ),
    ],
)

COMMIT_TYPE_POINTER = models.GuidanceSection(
    id="commit-type-pointer",
    parts=[
        models.TextPart(
            text=r"""The type comes from `docs/contributing.md`'s table, which the commit skill renders when one is chosen.

"""
        ),
    ],
)

CODE_CONVENTIONS = models.GuidanceSection(
    id="code-conventions",
    parts=[
        models.TextPart(
            text=r"""---

## Code Conventions

Build on `lup` and pydantic; prefer an existing PyPI library to raw HTTP or a rebuilt wheel. The runtime an application composes against is provider-neutral: no module under `src/lup_template/` imports a provider SDK, each being one adapter's dependency behind an extra, and `seam-boundary` holds adapter imports to the composition roots naming them. `docs/conventions.md` names each library and its typed forms.

**Model selection.** Default to the **strongest** tier everywhere — main agent, subagents, reviewers, background agents — on a subscription where the best model is the point. Reach for **balanced** only where latency or cost provably dominates quality, **fast** almost never; a role warranting less declares its tier with a reason, naming a tier rather than a model id.

**Error handling.** Raise for unrecoverable errors, wrap transient ones in `with_retry`, validate inputs early, never swallow one silently. A `@lup_tool` handler takes a validated model and returns one, raising `ToolError` to send a recoverable failure back as an MCP error saying what to do about it; the `is_error` envelope and input-validation reply are the decorator's. A catch-all `except Exception` is fine at a boundary that logs, handles, or re-raises — a task loop, a subagent delegation — which is why no rule refuses one.

**Placement, in this repository.** Reusable utilities belong in `packages/lup/`, what only this application needs in `src/lup_template/`, and logic already in `lup` is imported rather than copied. Deciding a module belongs on the other side is one line of judgement and a hundred of consequence, which is where the judgement gets abandoned — so the consequence is a command: `dev relocate old.module=new.module` repoints every import and reports the mentions it left.

"""
        ),
    ],
)

TOOLING = models.GuidanceSection(
    id="tooling",
    parts=[
        models.TextPart(
            text=r"""---

## Tooling

`uv` is the package manager — `uv add <package>`, never edit pyproject.toml directly. Lint and format with ruff, type-check with pyright; `docs/contributing.md` carries the commands that have to be green. `lup` itself is the one dependency not added that way: `dev library` reads and rewrites the mode a project obtains it through, and that mode decides what upgrading means — ask `dev library status` before assuming lup's source is on disk to edit, since in three of four modes it is not.

An operation that genuinely needs the launcher's host is resubmitted with a leading `# lup: escalate[sandbox]: <why>` line rather than run from an unconfined session; the crossing is reviewed and dispatched once, so try inside first, since a missing path usually means the host was not needed.

### lup-devtools

`lup-devtools` is the development CLI, composed from `packages/lup/` and this repository's `src/lup_template/`. **Use it instead of ad-hoc commands**, and running the same one repeatedly means **add a command** to the half that would reuse it. Inline Python (`-c`, `-m`, a REPL, or bare `python`) is denied; `uv run python <script.py>` is allowed because a file can be reviewed. Sandbox-masked dotfiles can look untracked to Git — read the real tree with `dev pending`, and a persisted result is read rather than `cat`-ed, which re-persists it.

To **read** code use the `py` group or `codeintel`, which resolves a name through a language server rather than matching text: **prefer either for anything about a name**, `rename_symbol` over `replace_all`, which cannot tell one scope from another, `py text` for literal text in scoped Python source, and grep for characters in non-Python files. To **compute once**, write a script under gitignored `tmp/` and run it; to reuse it, add a command. `docs/contributing.md` carries the rest of that reviewability ladder, `docs/commands.md` every command the CLI serves — walked from the wired app, so read it to find one you did not know to look for, and `--help` for its options.

### Generated Trees

`harness generate all` regenerates every native plugin; `harness <runtime>` regenerates one and launches it. Skills and agents render from typed catalogs, one per half, composing both — change the catalog that owns the subject, then regenerate.

**Every runtime, same change.** State and build each answer to every policy, flag, hook, or artifact; name substitutes for unsupported concepts. One runtime's verdicts place no call, so it renders the plain effect. Done means `harness generate all` reconciles both; `docs/permissions.md` maps gaps.

"""
        ),
    ],
)

CONFIGURATION = models.GuidanceSection(
    id="configuration",
    parts=[
        models.TextPart(
            text=r"""---

## Configuration

Configuration loads through pydantic-settings in `src/lup_template/agent/config.py`, the only module that reads the environment. `docs/template.md` lists the variables and how gitignored `.env.local` overrides `.env`.

"""
        ),
    ],
)

PROCESS_AND_COMMUNICATION = models.GuidanceSection(
    id="process-and-communication",
    parts=[
        models.TextPart(
            text=r"""---

## Process & Communication

**Wait on pushed tool output, not polls.** Keep a long-lived command's resumable call live and yield to the runtime's event-driven waiter; repeated shell-session reads are polling, even with long timeouts.

**Surface every question through the harness's structured facility**, not narration — clarifications, choices, destructive confirmations — with concrete options plus free-form even when open-ended, because downstream notifications read structured answers. **Ask what form the project should take** rather than inferring it: the shape a fix takes, how work is cut into branches or issues, what a surface looks like are the user's to settle, and picking one silently spends their decision. **A design conversation is the exception:** its decisions go numbered in plaintext in one batch, each standing alone, so the user answers by number and skips what is yours to decide.

**Explain decisions from scratch:** the problem, relevant state, options, rationale, and your recommendation marked as yours — a verdict cannot be judged, so prefer complete context to brevity. **Check a checkable claim before asking about it** — a version, a hook, a payload — and answer "did you check?" with what you read against what you ran. **Say what is, not how it came to be:** an overview carries the thing as it stands and the reasoning holding it up, not what was tried or which turn found what, your path rather than the subject.

Verify claims against **what was actually asked** — the note or issue itself, not a title, commit, or prior summary; state surviving claims plainly and correct failures out loud, including yours. **After every command**, compare actual use with its docs and propose an update as a question: external docs, corrections, uncovered requests, or ignored sections all say it should evolve.

"""
        ),
    ],
)

REPORTING_FRICTION = models.GuidanceSection(
    id="reporting-friction",
    parts=[
        models.TextPart(
            text=r"""### Reporting Friction

**Fix tooling friction instead of working around it.** This repository usually owns the hook, command, or classifier that obstructed you; repair it on its own branch so the diff stays single-purpose. **Open an issue only when this session cannot repair it** — the owner is outside this repository, a design decision is missing, or reproduction is the work — because a narrated workaround teaches nobody. **Read the tracker first:** `dev issues` lists the open reports, closed ones are worth searching, and a match is updated with `--issue NUMBER` rather than split across duplicates. Record the exact command, error, resulting state, recovery cost, and owning component with `dev report-friction`, whose checkout selects the repository; evidence beats conclusions.

"""
        ),
    ],
)

EXTERNAL_RESOURCES = models.GuidanceSection(
    id="external-resources",
    parts=[
        models.TextPart(
            text=r"""### External Resources

When a question is about the harness you run under, its agent SDK, or its model API, read that runtime's own documentation rather than answering from memory — delegate to the documentation subagent your harness ships, or fetch the vendor's docs at """
        ),
        models.RuntimeDocs(),
        models.TextPart(
            text=r""". The fetch scopes the policy admits are declared in `harness/catalog.py`. When the user provides documentation links, fold what they teach into the guidance source or the relevant skill.

"""
        ),
    ],
)

SELF_IMPROVEMENT = models.GuidanceSection(
    id="self-improvement",
    parts=[
        models.TextPart(
            text=r"""---

## Self-Improvement Loop

`docs/self-improvement.md` carries the full loop — what to ask of a failure, and what to change in answer — and the feedback-loop, review, and meta skills each work from it. The durable fix is a capability, not a rule: trace the failure to the missing input or the workflow step where the wrong decision entered, and change that — a prompt rule coexists peacefully with the failure it warns about.
"""
        ),
    ],
)


def guidance_sections(selection: RuleSelection) -> list[models.GuidanceSection]:
    """This repository's guidance, in the order a reader meets it.

    The reading order *is* this declaration, which is the whole of what the
    function does: the sections come from two packages and several subjects
    occupy more than one, so the sequence can be read off neither half. What it
    is not is an assembly — every section is a named value, and this says which
    names in what order and nothing about their contents.
    """
    return [
        HEADER,
        conventions.PLAN_AT_AGENT_SPEED,
        conventions.AGENT_VOCABULARY,
        conventions.THE_GATES,
        CHANGING_THE_POLICY,
        MARKER_VOCABULARY,
        DEFERRED_WORK,
        DEVELOPMENT_WORKFLOW,
        conventions.MERGE_CONFLICT_RESOLUTION,
        conventions.COMMIT_GUIDELINES,
        COMMIT_TYPE_POINTER,
        CODE_CONVENTIONS,
        conventions.design_principles(selection),
        conventions.SANCTIONED_EXCEPTIONS,
        TOOLING,
        conventions.LONG_RUNNING_WORK,
        CONFIGURATION,
        PROCESS_AND_COMMUNICATION,
        REPORTING_FRICTION,
        conventions.DEFECT_DISPOSITION,
        EXTERNAL_RESOURCES,
        SELF_IMPROVEMENT,
    ]


def guidance_parts(selection: RuleSelection) -> list[models.PromptPart]:
    """The same document as the flat parts a renderer walks."""
    return models.sectioned(guidance_sections(selection))


def document(selection: RuleSelection | None = None) -> models.PromptDocument:
    """The guidance as one document, built against the project's selection.

    Taking the selection rather than reading one keeps the catalog free to
    import this module: the catalog owns the declaration and hands it down,
    so nothing here reaches back up for it.
    """
    return models.PromptDocument(
        source=__name__, parts=guidance_parts(selection or RuleSelection())
    )
