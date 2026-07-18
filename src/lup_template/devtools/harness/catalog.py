"""Root of the project-owned harness declaration graph.

The declaration leaves — skills, agents, prompt documents, settings, and
assets — live under ``content/``, aggregated by ``content.catalog``. This
module assembles those leaves with the hook policy and the resolver spec
into the portable ``Harness`` that ``generate`` compiles into both native
trees. Generated guidance and the adopter docs point here as the file that
owns URL scopes and protected edit roots, so its path is part of the
documented surface.
"""

from pathlib import Path

from pydantic import AnyHttpUrl

from lup.harness.models import (
    Harness,
    HookSet,
    HookUrlScope,
    Plugin,
    ResolveSpec,
    SkillInvocation,
)
from lup_template.devtools.harness.content.catalog import AGENTS, SKILLS
from lup_template.devtools.harness.content.guidance import DOCUMENT as GUIDANCE


def portable_harness(version: str = "0.2.0", root: Path | None = None) -> Harness:
    """Build the canonical declaration graph consumed by every adapter.

    Deliberately one declaration, not one per platform: every intended
    Claude/Codex difference is a rendering decision in the adapters
    (``compile_claude`` / ``compile_codex``) or a support artifact in the
    generation recipes, mapped in ``docs/platform-differentiation.md``.
    Per-platform declarations overriding a shared default were rejected
    because they would let semantic content fork silently.
    """
    del root
    plugin = Plugin(
        id="plugin.lup",
        name="lup",
        version=version,
        description=(
            "Self-improvement harness with feedback, review, and safe resolution flows"
        ),
        skills=SKILLS,
        agents=AGENTS,
        hooks=HookSet(
            id="hooks.lup-policy",
            policy_ids=["fetch", "shell", "edit", "unknown-tool"],
            allowed_fetch=[
                HookUrlScope(origin=AnyHttpUrl("https://docs.claude.com")),
                HookUrlScope(origin=AnyHttpUrl("http://docs.claude.com")),
                HookUrlScope(origin=AnyHttpUrl("https://ai.pydantic.dev")),
                HookUrlScope(origin=AnyHttpUrl("http://ai.pydantic.dev")),
            ],
            protected_edit_roots=[
                Path(".claude"),
                Path("tmp"),
                Path("pyproject.toml"),
                Path("sync.json"),
                Path("downstream.json"),
            ],
            human_owned_files=[Path("README.md")],
        ),
    )
    return Harness(
        generator_version=version,
        source_evidence={"content": "typed-python"},
        plugins=[plugin],
        guidance=GUIDANCE,
        resolver=ResolveSpec(
            id="resolver.lup",
            worker_skill=SkillInvocation(plugin="lup", skill="implementer"),
            review_skill=SkillInvocation(plugin="lup", skill="resolve-reviewer"),
            merge_skill=SkillInvocation(plugin="lup", skill="merge"),
        ),
    )
