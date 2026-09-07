"""Reviewed feedback becoming concerns, worktrees, workers, and a branch.

The richest module in the roster, and so the one that says most about whether
the shape is right: it fills content, documents, and a nested command tree,
and it is the only one that reaches into another module by name.

That reach is ``skill.merge``, which git-workflow owns and the resolver's
``ResolveSpec`` names, so this declares ``requires=["git-workflow"]``. The
composition would refuse either way — every ``SkillInvocation`` is resolved
against the composed set — but it would refuse naming a skill, and somebody
who declined a module is owed the answer naming the module.

Its thirteen commands sit *inside* the ``harness`` sub-app rather than beside
it, and ``subapps`` claims top-level names only, so this module claims none of
them. Expressing a nested claim is a shape of its own and does not gate this.
"""

from lup.harness.content.docs import resolver, supervisor
from lup.harness.content.docs.catalog import LIBRARY_DOCS_ROOT, published
from lup.harness.content.modules.specs import RESOLVER
from lup.harness.content.skills.implementer import SKILL as SKILL_IMPLEMENTER
from lup.harness.content.skills.resolve import SKILL as SKILL_RESOLVE
from lup.harness.content.skills.resolve_reviewer import (
    SKILL as SKILL_RESOLVE_REVIEWER,
)
from lup.harness.models import ContentRoster
from lup.harness.modules import DocumentEntry, Module


def module() -> Module:
    """The resolver as one value."""
    return Module(
        spec=RESOLVER,
        content=ContentRoster(
            skills=[SKILL_IMPLEMENTER, SKILL_RESOLVE, SKILL_RESOLVE_REVIEWER]
        ),
        documents=[
            DocumentEntry(
                semantic_id="docs.resolver",
                build=lambda _: published(
                    "resolver", "resolver.md", resolver.DOCUMENT, LIBRARY_DOCS_ROOT
                ),
            ),
            DocumentEntry(
                semantic_id="docs.supervisor",
                build=lambda _: published(
                    "supervisor",
                    "supervisor.md",
                    supervisor.DOCUMENT,
                    LIBRARY_DOCS_ROOT,
                ),
            ),
        ],
    )
