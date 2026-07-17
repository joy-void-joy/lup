# lup: Both plans said that we needed to have differences between Claude and Codex file generation. e.g. lup:resolve is different under claude (using claude's native workflow) and under codex (that doessn't have anything similar? Please check this) . Or the fact that .md compilation should happen differently between claude and codex. I don't see where this platform differenciation is
# lup: On that note, can you check whether we have good claude/codex parity, while respecting theiir native format? That all is reflected between claude and codex
"""Project-owned typed declarations for the portable Lup harness."""

from pathlib import Path

from lup.harness.models import (
    Harness,
    HookSet,
    HookUrlScope,
    Plugin,
    ResolveSpec,
    SkillInvocation,
)
from lup_template.devtools.harness.content.catalog import (
    AGENTS,
    SKILLS,
)  # lup: Like see, why is this in a content subfolder but this file is top-level? Can you review the full file hierarchy? It seems quite janky
from lup_template.devtools.harness.content.guidance import DOCUMENT as GUIDANCE


# lup: Sounds weird? Should be declared per platform instead? Unless you mean something like default harness that the other two overrides?
def portable_harness(version: str = "0.2.0", root: Path | None = None) -> Harness:
    """Build the canonical declaration graph consumed by every adapter."""
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
            policy_ids=[
                "fetch",
                "shell",
                "edit",
                "unknown-tool",
            ],  # lup: Wait what's that? It's really not understandable just like that. Sounds like the BaseModel doesn't have legible fields
            allowed_fetch=[
                HookUrlScope.model_validate({"origin": "https://docs.claude.com"}),
                HookUrlScope.model_validate({"origin": "http://docs.claude.com"}),
                HookUrlScope.model_validate({"origin": "https://ai.pydantic.dev"}),
                HookUrlScope.model_validate(
                    {"origin": "http://ai.pydantic.dev"}
                ),  # lup: Why use model_validate instead of the constructor directly?
            ],
            protected_edit_roots=[
                Path(".claude"),
                Path("tmp"),
                Path("pyproject.toml"),
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
