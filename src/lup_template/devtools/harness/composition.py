"""Native composition roots wiring concrete Claude and Codex capabilities.

The one place the harness CLI touches adapter implementations: each root
bundles a generation recipe, a runtime-readiness probe set, and a skill
invocation renderer, and ``harness_compositions`` maps the CLI target
selector onto those already concrete roots.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

import typer
from pydantic import BaseModel, ConfigDict

from lup.adapters.claude.harness import ClaudeSpellings
from lup.adapters.claude.harness_runtime import (
    ClaudeCliEvidence,
    claude_capability_probes,
)
from lup.adapters.codex.harness import CodexSpellings
from lup.adapters.codex.harness_runtime import (
    CodexCliEvidence,
    codex_capability_probes,
)
from lup.codescan.boundaries import ApplicationRoots, generated_tree_paths
from lup.harness.contracts import NativeSpellings, SkillInvocationRenderer
from lup.harness.models import CapabilityEvidence
from lup.workspace.paths import project_root
from lup_template.devtools.harness.catalog import portable_harness
from lup_template.devtools.harness.generate import (
    GenerationRecipe,
    claude_generation_recipe,
    codex_generation_recipe,
)

type NativeCapabilityEvidence = (
    CapabilityEvidence[ClaudeCliEvidence] | CapabilityEvidence[CodexCliEvidence]
)
type RuntimeReadiness = Callable[[], Sequence[NativeCapabilityEvidence]]


class NativeHarnessComposition(BaseModel):
    """Concrete capabilities supplied to one CLI composition root."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    recipe: GenerationRecipe
    readiness: RuntimeReadiness
    invocation_renderer: SkillInvocationRenderer


def claude_composition(root: Path) -> NativeHarnessComposition:
    """Construct the Claude capabilities directly."""

    def readiness() -> Sequence[NativeCapabilityEvidence]:
        return [
            probe.probe()
            for probe in claude_capability_probes(root / ".claude" / "plugins" / "lup")
        ]

    return NativeHarnessComposition(
        recipe=claude_generation_recipe(root),
        readiness=readiness,
        invocation_renderer=ClaudeSpellings(),
    )


def codex_composition(root: Path) -> NativeHarnessComposition:
    """Construct the Codex capabilities directly."""

    def readiness() -> Sequence[NativeCapabilityEvidence]:
        return [probe.probe() for probe in codex_capability_probes()]

    return NativeHarnessComposition(
        recipe=codex_generation_recipe(root),
        readiness=readiness,
        invocation_renderer=CodexSpellings(),
    )


NATIVE_RUNTIMES: list[NativeSpellings] = [ClaudeSpellings(), CodexSpellings()]
"""Every runtime this project generates a tree for."""


def application_roots() -> ApplicationRoots:
    """Where this project composes concrete native implementations.

    The generated trees are asked of the runtimes rather than written down, so
    a location a runtime learns sanctions its own tree. The rest are this
    project's own homes, derived from where this package actually sits, so
    renaming it during initialization moves them instead of leaving the rule
    pointing at a package that is gone.
    """
    package = Path(__file__).resolve().parents[2].relative_to(project_root()).as_posix()
    harness = f"{package}/devtools/harness/"
    plugins = [plugin.name for plugin in portable_harness().plugins]
    return ApplicationRoots(
        composition=[
            *generated_tree_paths(NATIVE_RUNTIMES, plugins),
            "tests/",
            "packages/lup/tests/",
            "examples/",
            f"{package}/agent/core.py",
            harness,
            f"{package}/devtools/setup.py",
            f"{package}/devtools/usage/app.py",
        ],
        portable_prose=[f"{harness}content/"],
    )


EVERY_TARGET = "all"
"""The selector that reaches every native tree, and the repository-wide
artifacts that belong to no single one of them."""


def harness_compositions(value: str) -> list[NativeHarnessComposition]:
    """Parse a generic CLI selector into already concrete compositions."""
    constructors: dict[str, Callable[[Path], NativeHarnessComposition]] = {
        "claude": claude_composition,
        "codex": codex_composition,
    }
    root = project_root()
    if value == EVERY_TARGET:
        return [constructor(root) for constructor in constructors.values()]
    constructor = constructors.get(value)  # lup: ignore[dict-get]
    if constructor is not None:
        return [constructor(root)]
    raise typer.BadParameter("target must be claude, codex, or all")
