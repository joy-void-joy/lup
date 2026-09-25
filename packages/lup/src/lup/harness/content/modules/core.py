"""The module every project has: what an agent is, and what will stop it.

Core is the one subject with no alternative, and its spec says so: it is
*essential*, so no selection may decline it and every other module may name
what it holds without listing it in ``requires``. A project may decline the git
loop, the resolver, or the feedback loop and still be a lup project; declining
what tells a session how this repository judges an edit would leave a harness
that generates but cannot be worked in.

Its skills are the ones whose subject is the work itself rather than any
workflow over it: shaping a change before it is built, saying what is left,
finding out why something broke, and asking the policy what it decides. Its
pages are the reference behind that — why the seams are where they are, how a
permission decision is reached, which library answers which need, how to
contribute, and what the generated trees are and how they are regenerated.

Three command trees are here for the reason the module is essential. `dev` is
the gate, `harness` generates and launches every tree, and `git` holds the
worktrees, the merge driver and the hooks the gate reads — every module ends at
one of the three, so a module owning one of them would make every other module
depend on it without saying so.

What it needs from elsewhere is one tree, named in ``requires``: the debug
skill reads a session's trace, which is the observability module's.
"""

import lup.harness.content.conventions as conventions
from lup.harness.codescan.common import RuleSelection
from lup.harness.content.agents.tdd_implementer import AGENT as AGENT_TDD_IMPLEMENTER
from lup.harness.content.application import ApplicationLayout
from lup.harness.content.docs import (
    architecture,
    contributing,
    conventions as conventions_page,
    harness,
    library,
    native_capabilities,
    orchestration,
    patterns,
    permissions,
    platform_differentiation,
    quality_pipeline,
)
from lup.harness.content.docs.catalog import page
from lup.harness.content.modules.specs import CORE
from lup.harness.content.skills.brainstorm import skill as build_brainstorm
from lup.harness.content.skills.debug import skill as build_debug
from lup.harness.content.skills.hooks import skill as build_hooks
from lup.harness.content.skills.report import SKILL as SKILL_REPORT
from lup.harness.content.skills.verify_solved import SKILL as SKILL_VERIFY_SOLVED
from lup.harness.models import ContentRoster
from lup.harness.modules import DocumentEntry, Module


def documents() -> list[DocumentEntry]:
    """The pages describing machinery every project runs on.

    Each is about the library rather than about a workflow over it, which is
    what puts them here: a project declining the resolver stops publishing the
    resolver's page, and no project stops publishing how an edit is judged —
    nor which of the gate's three layers catches what, since the hook
    installer and the gate are both core's command trees.
    Two describe the composition rather than a subject — the harness page
    lists the roster every generated banner points a reader at, and the parity
    audit maps what that roster renders differently per runtime — which is why
    they read the document context. What the rest point at in other modules
    they point at through a :class:`~lup.harness.models.WhereTaken`.
    """
    return [
        page("library", "library.md", lambda context: library.document(context.layout)),
        page("architecture", "architecture.md", lambda _: architecture.DOCUMENT),
        page("permissions", "permissions.md", lambda _: permissions.DOCUMENT),
        page(
            "native_capabilities",
            "native-capabilities.md",
            lambda context: native_capabilities.document(context.library_checkout),
        ),
        page("conventions", "conventions.md", lambda _: conventions_page.DOCUMENT),
        page("patterns", "patterns.md", lambda _: patterns.DOCUMENT),
        page(
            "orchestration",
            "orchestration.md",
            lambda context: orchestration.document(context.layout),
        ),
        page(
            "harness",
            "harness.md",
            lambda context: harness.document(
                context.skills, context.agents, context.plugin, context.layout
            ),
        ),
        page(
            "contributing",
            "contributing.md",
            lambda context: contributing.document(context.layout),
        ),
        page(
            "quality_pipeline",
            "quality-pipeline.md",
            lambda _: quality_pipeline.DOCUMENT,
        ),
        page(
            "platform_differentiation",
            "platform-differentiation.md",
            lambda context: platform_differentiation.document(
                context.skills,
                context.agents,
                context.claude_decodes,
                context.codex_decodes,
                context.layout,
            ),
        ),
    ]


def module(layout: ApplicationLayout, rules: RuleSelection) -> Module:
    """Core as one value, against the project's layout and rule selection.

    The rule selection reaches the design principles because that section
    renders one line per shaping rule the project actually holds itself to, so
    a retired rule stops being taught in the edit that stops it firing. The
    layout reaches the skills that show a reader this project's own sources.
    """
    return Module(
        spec=CORE,
        content=ContentRoster(
            skills=[
                build_brainstorm(layout),
                build_debug(layout),
                build_hooks(layout),
                SKILL_REPORT,
                SKILL_VERIFY_SOLVED,
            ],
            agents=[AGENT_TDD_IMPLEMENTER],
        ),
        guidance=[
            conventions.PLAN_AT_AGENT_SPEED,
            conventions.AGENT_VOCABULARY,
            conventions.THE_GATES,
            conventions.design_principles(rules),
            conventions.SANCTIONED_EXCEPTIONS,
            conventions.DEFECT_DISPOSITION,
        ],
        documents=documents(),
    )
