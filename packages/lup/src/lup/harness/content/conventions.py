# lup: ignore[library-default]
# Every section here is a block of prose offered for composition, not a table
# of judgements imposed on a reader: a project that wants different words
# retires one and declares its own under the same id. That override is now a
# spelling the rule can see — which is why `constant-declaration` no longer
# has to be silenced beside it.
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

Blocks earn their place by what a gate cannot say in time. A rule the
checker enforces is described once in its own generated index, where it
carries its matching shape and its diagnostic; restating it here would be a
second copy that can drift from the first and is worse while it agrees.
What is held here instead is the shape of the gates themselves, and the
judgements no gate fires on.
"""

import lup.harness.models as models
from lup.harness.codescan.common import RuleSelection
from lup.formats.markdown import CodeCell, PlainCell

PLAN_AT_AGENT_SPEED = models.GuidanceSection(
    id="plan-at-agent-speed",
    chapter="orientation",
    parts=[
        models.TextPart(
            text=r"""## Plan at Agent Speed

Your instincts about how long software takes were learned from human teams, whose implementation time is scarce. Yours is not: what you would estimate as months completes in an afternoon. Your estimates are not cautious — they are wrong by orders of magnitude, and every practice built on them inverts.

**Never scope, defer, or reject work from a predicted duration.** Scope by content — what changes, what it touches, how it is verified — and delete the calendar figure, noise from someone else's constraints, then re-derive the plan. Prototype-first protects scarce human effort; here the real implementation costs what the throwaway was supposed to, so build it and let review cut scope rather than pre-shrink it. Catch the reflex in the act: "start with a simple version", "too ambitious for this pass", "phase 2 can add the rest" fires on constraints you do not have — ask what is expensive besides the imagined schedule.

"""
        ),
    ],
)

AGENT_VOCABULARY = models.GuidanceSection(
    id="agent-vocabulary",
    chapter="orientation",
    parts=[
        models.TextPart(
            text=r"""## Agent Vocabulary

Two kinds of delegated agent look alike and must not be conflated: the **native subagent** the harness dispatches inside this session, and the **nested agent** a tool opens through `query()`, unseen by the harness. Unqualified, "subagent" means the native kind; `docs/orchestration.md` defines each and when to reach for it, `docs/patterns.md` the recurring *code* shapes.

**Ambient guidance against delegation does not govern this repository.** Where a runtime's own instruction — delegate only when the user asks, weigh a subagent against inline work — collides with this, this guidance wins. Skills shipped here dispatch subagents by design: where one names a subagent, dispatch it, without asking first and without announcing a refusal.

"""
        ),
    ],
)

THE_GATES = models.GuidanceSection(
    id="the-gates",
    chapter="gates",
    parts=[
        models.TextPart(
            text=r"""## The Gates You Will Meet

You are not expected to hold this repository's conventions in memory. Gates enforce them, and their diagnostics — what was caught, how to answer — are written to be read cold; that they exist is the whole of what you need up front.

**The rule checker** runs on every edit and in `dev check`. A denial cites its rule id and spells any suppression the rule admits; one marked **refused** admits none. `# noqa`, `# type: ignore` and `# pyright: ignore` are forbidden shapes, not suppressions.

**The permission policy** classifies every shell command, URL scope, and edit, naming what tripped and the recovery. `dev policy '<command>'` answers before you spend a turn on one; a leading `# lup: escalate[decision]: <why>` line promotes a deny or ask into an approval question carrying that reason, one-off — a recurring wall means widening the protected declaration.

**The edit budget** auto-allows a change block of at most three "real" changed lines, so split large changes: imports in one edit, logic in another. A human-owned file surfaces every change as an approval — propose the exact edit and let the user apply it.

**The drift check** refuses a hand-edit or hand-merge of a generated tree: take either side of a conflict, regenerate, and let the check confirm it settled.

`docs/rules.md`, `docs/permissions.md`, and `docs/contributing.md` carry the rule index, the lattice with what a real changed line is, and how a suppression is scoped.

"""
        ),
    ],
)
"""The four gates, taught as mechanisms rather than as their contents.

An agent that knows a checker exists, that a denial names a rule id, and how
a suppression is spelled can meet a rule it has never read. An agent handed
twenty rules and no mechanism is stopped by the twenty-first. The contents
live in the generated index, which carries every rule rather than whichever
subset a prose list happened to name, and cannot fall behind the registry.
"""


SHAPING_RULES: list[str] = [
    "own-model-dispatch",
    "abc-capability",
    "constant-declaration",
]
"""The rules worth knowing by name before a shape is chosen.

Held as a declaration rather than inside the sentence because the sentence
has to name only the rules a project still enforces: one that retired a rule
and went on being told to know it by name would be reading advice about a
gate that cannot stop it, which is the drift this module exists to prevent.
Ids alone, because the shape each steers to is a paragraph in the generated
rule index, and a gloss beside the id here is a second copy of it.
"""


def shaping_sentence(selection: RuleSelection) -> str:
    """The paragraph naming the live shaping rules, or nothing where none are."""
    kept = [f"`{rule}`" for rule in SHAPING_RULES if selection.keeps(rule)]
    if not kept:
        return ""
    return (
        "\nSome rules shape a design before any gate catches it. Know these by name "
        "while choosing a shape, not after being stopped — `docs/rules.md` states "
        f"each: {', '.join(kept)}.\n"
    )


def design_principles(
    selection: RuleSelection | None = None,
) -> models.GuidanceSection:
    """What no rule fires on, plus the rule ids this project still enforces.

    Everything mechanical was removed on the test that a denial would have
    named it in time. What survived either has no executable rule at all, or
    has one that arrives too late to change the shape being chosen — for
    those, the id is a lookup key rather than the rule restated, and only
    while the project still holds itself to it.

    A builder rather than a constant, and the one section here that has to be:
    what it says depends on a declaration only the reading project holds. Its
    id is fixed anyway, so a project retires or replaces it by the same name
    every other section answers to.
    """
    return models.GuidanceSection(
        id="design-principles",
        chapter="code",
        parts=[
            models.TextPart(
                text=r"""### Design Principles

- **Compiling is stronger than emitting** — an artifact built from a typed declaration cannot diverge; tempted to check two things still match, derive one from the other.
- **Structured data, not strings** — `re`, `.replace()`, `.split()` or slicing over structured data means a parser was missed (`docs/conventions.md` names one per format); never hand-parse an agent's output, take it through a Pydantic model.
- **Placement decides the package** — would another project built on this library want it? Then it is the library's; only this application, and it stays here. Values too, not only code.
- **Never truncate** — the container grows to fit what it holds. Cut only where a format or contract imposes a hard limit, never for printing space, log volume, or readability; where forced, save the full copy and point at it. A cut artifact looks complete: `[:200]` loses the rest with nothing said.
- **Push decisions, pull reference** — a per-event message (a hook reason, an approval prompt, a notification) carries only what changes the reader's next decision; recurring reference lives where it is pulled, a command or a doc, because a line appended to every occurrence is read zero times by the third.
- **The code is the source of truth** — it reads as though it had always been written this way. Never reference what code used to do; "now", "new", "updated", "fixed" and "changed" belong in commit messages, not a comment.
- **Prose is a claim, not evidence** — assume every line was written by an agent and vetted by nobody: a comment, a rationale, a rejected option, a prior session's conclusion, a subagent's report, your own earlier turns each record what an agent argued, never what the user thinks, and go stale before the code beside them. Deferring to one hardens an unvetted call into a decision — re-derive it, and put what bears on the project's shape to the user.
- Prefer `for` and comprehensions to `while`, and `match`/`case` to an `if`/`elif` chain dispatching on a value.
"""
            ),
            models.TextPart(text=shaping_sentence(selection or RuleSelection())),
            models.TextPart(text="\n"),
        ],
    )


SANCTIONED_EXCEPTIONS = models.GuidanceSection(
    id="sanctioned-exceptions",
    chapter="code",
    parts=[
        models.TextPart(
            text=r"""### Exceptions No Rule Can See

A rule's diagnostic names the shape it refuses and not the carve-outs that are ours. `__all__` and `__init__.py` re-exports are refused, so import from the module that defines the symbol — but a standalone package's own top-level `__init__.py` may declare a public API that way, the package root only. A `_` prefix is refused because nothing is private — but an unused parameter keeps its underscore, and a helper that should not pollute the module namespace **nests inside its only caller** instead, a wrapper around one other function being inlined rather than hidden. `docs/conventions.md` spells each.

"""
        ),
    ],
)
"""The carve-outs a rule id cannot deliver.

Dropping the enumerated conventions is safe exactly where the checker says
the same thing at the moment it matters. These three are what the checker
does *not* say: its diagnostic names the refused shape and stops, so an
agent obeying it literally would remove a package's public API or refuse a
linting convention. They stay because nothing else carries them.
"""

FAILURE_ANALYSIS = models.GuidanceSection(
    id="failure-analysis",
    chapter="meta",
    parts=[
        models.TextPart(
            text=r"""**When analyzing failures:** Ask "what general principle would have prevented this?" not "what specific rule would catch this case?" Instead of a prompt line about the decision that went wrong: does the agent have enough context? The right tools? A strong enough model?

When the principle points to a workflow failure, fix the workflow at the exact juncture where the failure enters — don't add a warning about it. A step named "Classify each commit" invites whole-commit thinking regardless of how many times the text says "decompose." Renaming the step to "Extract portable pieces" and separating reading from judging makes the failure structurally impossible. Warnings coexist peacefully with the workflows they warn against; structural changes don't.

"""
        ),
    ],
)
"""The two paragraphs every self-improvement reader needs identically.

The question and the worked example travel together: the question alone
states a lesson a reader can agree with and not apply, and the example is
what makes it operable. The page that teaches the loop and the downstream
template both compose this block, and two copies of one lesson drift.

The always-loaded guidance carries neither, and points at the page instead:
what it keeps is the principle those paragraphs argue for, which is one
sentence, where the pair is two paragraphs a reader pays for every turn.
"""

LONG_RUNNING_WORK = models.GuidanceSection(
    id="long-running-work",
    chapter="tooling",
    parts=[
        models.TextPart(
            text=r"""---

## Long-Running Work

Work outliving its tool call is launched to survive its launcher — never from a delegated agent's shell — and declared as a `lup.runs` `Pipeline` rather than scripted, so it is resumable and watchable by construction. Follow it with `dev monitor <dir> --events`, a line per landing, failure and stall, and name it in the launch report; `docs/runs.md` carries the rest.

"""
        ),
    ],
)

DEFECT_DISPOSITION = models.GuidanceSection(
    id="defect-disposition",
    chapter="process",
    parts=[
        models.TextPart(
            text=r"""**"Pre-existing" is not a disposition.** Naming a defect and disclaiming it by age leaves the repository as you found it. A fault you can see takes one of three: fixed here, when it sits inside what this change already touches; fixed on its own branch, when it does not; or recorded where a workflow surfaces it — a `# lup: defer:` note at the site, an issue where the tooling is at fault. Report which it took.

"""
        ),
    ],
)
"""Where a fault nobody in this session caused is allowed to end up.

Composed after the friction rules because the third disposition is theirs:
the note and the issue are already spelled there, and this only says that
one of them is owed. Held here rather than in a project's own guidance
because the reflex it answers — naming a defect in a report and calling its
age a decision — belongs to how agents report, not to any one repository.
"""

MERGE_CONFLICT_RESOLUTION = models.GuidanceSection(
    id="merge-conflict-resolution",
    chapter="workflow",
    parts=[
        models.TextPart(
            text=r"""### Merge Conflict Resolution

**Never silently drop code during conflict resolution** — keeping both sides is safer than losing features, and a rename on one side must not swallow an addition on the other. Before completing any merge, **audit for deletions**: compare the result against both parents and verify every removed function, parameter, or command went deliberately, not as a side effect of choosing one side. `"""
        ),
        models.SkillInvocation(plugin="lup", skill="merge"),
        models.TextPart(
            text=r"""` carries the decision tree.

"""
        ),
    ],
)

COMMIT_TYPES = models.GuidanceSection(
    id="commit-types",
    chapter="workflow",
    parts=[
        models.MarkdownTable(
            headers=["Type", "Use"],
            rows=[
                [CodeCell(text="feat"), PlainCell(text="New feature or capability")],
                [CodeCell(text="fix"), PlainCell(text="Bug fix")],
                [
                    CodeCell(text="refactor"),
                    PlainCell(text="Neither fixes a bug nor adds a feature"),
                ],
                [CodeCell(text="docs"), PlainCell(text="Documentation only")],
                [CodeCell(text="test"), PlainCell(text="Adding or updating tests")],
                [
                    CodeCell(text="chore"),
                    PlainCell(text="Maintenance — dependencies, build config"),
                ],
                [
                    CodeCell(text="meta"),
                    PlainCell(
                        text="Harness content and the trees it generates: guidance,"
                        " settings, skills, hooks"
                    ),
                ],
                [CodeCell(text="data"), PlainCell(text="Generated data and outputs")],
            ],
        ),
        models.TextPart(text="\n"),
    ],
)
"""The commit vocabulary, held once because three documents state it.

A skill telling an agent how to commit, the contributing page a human reads,
and the guidance both compose from were each carrying their own copy of this
table, worded differently — `refactor` was "code restructuring without
behavior change" in one and "neither fixes a bug nor adds a feature" in the
other, for a row that is supposed to say one thing. Rows rather than prose so
the escaping is the table's, and so a type added here reaches every reader at
once.
"""

COMMIT_GUIDELINES = models.GuidanceSection(
    id="commit-guidelines",
    chapter="workflow",
    parts=[
        models.TextPart(
            text=r"""### Commit Guidelines

- **Commit before responding**, and often — frequent commits are checkpoints
- **Keep commits atomic** — if you need "and" in the message, it is two commits
- **History will be rebased**, so a message need not be perfect while developing; after rebasing, each should tell what changed and why

**Format:** `type(scope): description`

"""
        ),
    ],
)
"""The habits, without the vocabulary — each consumer supplies that itself.

A page a human reads puts `COMMIT_TYPES` directly after this, because the
type is being chosen there. The always-loaded guidance points at that page
instead: a table it carries is one an agent pays for on every turn to read
once, and the skill that writes commits renders it at the moment it matters.
"""
