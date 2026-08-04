"""Root of the project-owned harness declaration graph.

The declaration leaves — skills, agents, prompt documents, settings, and
assets — live under ``content/``, aggregated by ``content.catalog``. This
module assembles those leaves with the hook policy and the resolver spec
into the portable ``Harness`` that ``generate`` compiles into both native
trees. Generated guidance and the adopter docs point here as the file that
owns URL scopes, protected edit roots, and the shell vocabulary declared in
``content.shell_vocabulary``, so its path is part of the documented surface.
"""

from pathlib import Path

from pydantic import AnyHttpUrl

from lup.harness.models import (
    Harness,
    HookPathRole,
    HookSandbox,
    HookSet,
    HookUrlScope,
    Plugin,
    ResolveSpec,
    SkillInvocation,
)
from lup.workspace.paths import project_root, read_project_name
from lup_template.devtools.harness.content.catalog import AGENTS, SKILLS
from lup_template.devtools.harness.content.guidance import DOCUMENT as GUIDANCE
from lup_template.devtools.harness.content.shell_vocabulary import SHELL_RULES


def declared_hook_set() -> HookSet:
    """The hook set this project declares, for a session composed in process.

    Generated plugins read it off the harness they are compiled from. A
    session this program builds itself has to reach the same declaration, or
    it enforces something the generated tree does not.
    """
    return next(
        plugin.hooks
        for plugin in portable_harness().plugins
        if plugin.hooks is not None
    )


def portable_harness(version: str = "0.2.0", root: Path | None = None) -> Harness:
    """Build the canonical declaration graph consumed by every adapter.

    Deliberately one declaration, not one per platform: every intended
    Claude/Codex difference is a rendering decision in the adapters
    (``compile_claude`` / ``compile_codex``) or a support artifact in the
    generation recipes, mapped in ``docs/platform-differentiation.md``.
    Per-platform declarations overriding a shared default were rejected
    because they would let semantic content fork silently.
    """
    plugin = Plugin(
        id="plugin.lup",
        name="lup",
        marketplace=f"{read_project_name(root or project_root())}-repository",
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
                HookUrlScope(origin=AnyHttpUrl("https://code.claude.com")),
                HookUrlScope(origin=AnyHttpUrl("http://code.claude.com")),
                HookUrlScope(origin=AnyHttpUrl("https://ai.pydantic.dev")),
                HookUrlScope(origin=AnyHttpUrl("http://ai.pydantic.dev")),
                HookUrlScope(origin=AnyHttpUrl("https://learn.chatgpt.com")),
                HookUrlScope(origin=AnyHttpUrl("http://learn.chatgpt.com")),
                HookUrlScope(origin=AnyHttpUrl("https://developers.openai.com")),
                HookUrlScope(origin=AnyHttpUrl("http://developers.openai.com")),
                HookUrlScope(origin=AnyHttpUrl("https://github.com")),
                HookUrlScope(origin=AnyHttpUrl("https://api.github.com")),
                HookUrlScope(
                    origin=AnyHttpUrl("https://githubusercontent.com"),
                    include_subdomains=True,
                ),
                HookUrlScope(origin=AnyHttpUrl("https://pypi.org")),
                HookUrlScope(origin=AnyHttpUrl("https://files.pythonhosted.org")),
            ],
            protected_edit_roots=[
                Path(".claude"),
                Path("pyproject.toml"),
                Path("sync.json"),
                Path("downstream.json"),
            ],
            path_roles=[
                HookPathRole(root=Path("tests"), role="test"),
                HookPathRole(root=Path("tmp"), role="scratch"),
            ],
            human_owned_files=[Path("README.md")],
            shell_rules=SHELL_RULES,
            sandbox=HookSandbox(
                extra_domains=["api.anthropic.com"],
                credential_paths=["~/.ssh", "~/.aws/credentials"],
                # Every command in this project reaches its toolchain through
                # `uv`, which locks its cache whenever it resolves dependencies
                # — which a changed pyproject.toml forces, and an integration
                # merge is what changes pyproject.toml.
                writable_paths=["~/.cache/uv"],
            ),
        ),
    )
    return Harness(
        generator_version=version,
        source_evidence={"content": "typed-python"},
        plugins=[plugin],
        guidance=GUIDANCE,
        resolver=ResolveSpec(
            id="resolver.lup",
            worker_identity="resolver-worker",
            worker_skill=SkillInvocation(plugin="lup", skill="implementer"),
            review_skill=SkillInvocation(plugin="lup", skill="resolve-reviewer"),
            merge_skill=SkillInvocation(plugin="lup", skill="merge"),
        ),
    )
