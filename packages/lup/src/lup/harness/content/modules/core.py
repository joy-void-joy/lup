"""The module every project has: what an agent is, and what will stop it.

Core is the one subject with no alternative. A project may decline the git
loop, the resolver, or the feedback loop and still be a lup project; declining
what tells a session how this repository judges an edit would leave a harness
that generates but cannot be worked in.

Its skills are the ones whose subject is the work itself rather than any
workflow over it: reading a codebase, saying what is left, finding out why
something broke, and asking the policy what it decides. Its pages are the
reference behind that — why the seams are where they are, how a permission
decision is reached, which library answers which need.
"""

import lup.harness.content.conventions as conventions
from lup.harness.codescan.common import RuleSelection
from lup.harness.content.agents.tdd_implementer import AGENT as AGENT_TDD_IMPLEMENTER
from lup.harness.content.application import ApplicationLayout
from lup.harness.content.docs import (
    architecture,
    conventions as conventions_page,
    library,
    native_capabilities,
    orchestration,
    patterns,
    permissions,
    quality_pipeline,
)
from lup.harness.content.docs.catalog import page
from lup.harness.content.modules.specs import CORE
from lup.harness.content.skills.analyze import SKILL as SKILL_ANALYZE
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
    resolver's page, and no project stops publishing how an edit is judged.
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
        page(
            "quality_pipeline",
            "quality-pipeline.md",
            lambda _: quality_pipeline.DOCUMENT,
        ),
        page("patterns", "patterns.md", lambda _: patterns.DOCUMENT),
        page(
            "orchestration",
            "orchestration.md",
            lambda context: orchestration.document(context.layout),
        ),
    ]


def module(layout: ApplicationLayout, rules: RuleSelection) -> Module:
    """Core as one value, against the project's layout and rule selection.

    The rule selection reaches the design principles because that section
    renders one line per shaping rule the project actually holds itself to, so
    a retired rule stops being taught in the edit that stops it firing.
    """
    return Module(
        spec=CORE,
        content=ContentRoster(
            skills=[
                SKILL_ANALYZE,
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
