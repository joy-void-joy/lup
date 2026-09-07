"""Changing the machinery rather than the product.

Two subjects that looked separate until they were listed side by side: the
harness a session runs under, and the walks that move code without losing it.
Both answer the same question — the thing being edited is the apparatus, not
the thing it was built to make — and a project doing one of them is doing the
other within the week.

So adding a command, changing one, standing an investigator up, the refactor
walk, the principle pass, and the tools that resolve a name rather than match
text are one module. The two pages here are the reference behind the harness
half: what generation produces and how to change it, and every intended
difference between the runtimes it produces for.

Both of those pages describe the *composed* roster rather than this module's
own, which is why they read it off the document context. A page whose subject
is the composition cannot be a value this module holds, because this module is
part of what it describes.
"""

from lup.harness.content.application import ApplicationLayout
from lup.harness.content.docs import harness, platform_differentiation
from lup.harness.content.docs.catalog import LIBRARY_DOCS_ROOT, published
from lup.harness.content.modules.specs import META
from lup.harness.content.skills.add_command import skill as build_add_command
from lup.harness.content.skills.create_investigator import (
    skill as build_create_investigator,
)
from lup.harness.content.skills.modify_command import skill as build_modify_command
from lup.harness.content.skills.principle import skill as build_principle
from lup.harness.content.skills.refactor import SKILL as SKILL_REFACTOR
from lup.harness.content.skills.refactor_tools import skill as build_refactor_tools
from lup.harness.models import ContentRoster
from lup.harness.modules import DocumentEntry, Module


def module(layout: ApplicationLayout) -> Module:
    """Harness authoring and refactoring as one value, against the layout."""
    return Module(
        spec=META,
        content=ContentRoster(
            skills=[
                build_add_command(layout),
                build_create_investigator(layout),
                build_modify_command(layout),
                build_principle(layout),
                SKILL_REFACTOR,
                build_refactor_tools(layout),
            ]
        ),
        documents=[
            DocumentEntry(
                semantic_id="docs.harness",
                build=lambda context: published(
                    "harness",
                    "harness.md",
                    harness.document(
                        context.skills,
                        context.agents,
                        context.plugin,
                        context.layout,
                    ),
                    LIBRARY_DOCS_ROOT,
                ),
            ),
            DocumentEntry(
                semantic_id="docs.platform-differentiation",
                build=lambda context: published(
                    "platform_differentiation",
                    "platform-differentiation.md",
                    platform_differentiation.document(
                        context.skills,
                        context.agents,
                        context.claude_decodes,
                        context.codex_decodes,
                        context.layout,
                    ),
                    LIBRARY_DOCS_ROOT,
                ),
            ),
        ],
        subapps=["harness"],
    )
