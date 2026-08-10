"""Native composition roots wiring concrete Claude and Codex capabilities.

The one place the harness CLI touches adapter implementations: each builder
bundles a generation recipe, a runtime-readiness probe set, and a skill
invocation renderer, and :class:`NativeTargets` maps the CLI target selector
onto those already concrete roots. What a project publishes through them is
its own ``ProjectContent``, so the builders decide nothing about content.
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
from lup.devtools.harness.generate import (
    NativeHarnessComposition,
    ProjectContent,
    claude_generation_recipe,
    codex_generation_recipe,
)
from lup.harness.models import CapabilityEvidence, PromptDocument

type NativeCapabilityEvidence = (
    CapabilityEvidence[ClaudeCliEvidence] | CapabilityEvidence[CodexCliEvidence]
)


def claude_composition(
    root: Path, content: ProjectContent, guidance: PromptDocument | None = None
) -> NativeHarnessComposition:
    """Construct the Claude capabilities directly."""
    plugin = root / ".claude" / "plugins" / content.harness.plugins[0].name

    def readiness() -> Sequence[NativeCapabilityEvidence]:
        return [probe.probe() for probe in claude_capability_probes(plugin)]

    return NativeHarnessComposition(
        recipe=claude_generation_recipe(root, content, guidance),
        readiness=readiness,
        invocation_renderer=ClaudeSpellings(),
    )


def codex_composition(
    root: Path, content: ProjectContent, guidance: PromptDocument | None = None
) -> NativeHarnessComposition:
    """Construct the Codex capabilities directly."""

    def readiness() -> Sequence[NativeCapabilityEvidence]:
        return [probe.probe() for probe in codex_capability_probes()]

    return NativeHarnessComposition(
        recipe=codex_generation_recipe(root, content, guidance),
        readiness=readiness,
        invocation_renderer=CodexSpellings(),
    )


class NativeTargets(BaseModel):
    """Every native adapter a CLI selector can name, and how to build each.

    A project declares which runtimes it generates a tree for; the commands
    take already concrete compositions and never learn a target's name. The
    builders are keyed rather than listed because the selector a human types
    is the key, and the launch commands are the adapter's own surface.
    """

    model_config = ConfigDict(frozen=True)

    builders: dict[str, Callable[[Path], NativeHarnessComposition]]

    every: str = "all"
    """The selector reaching every declared tree at once, which is also what
    reaches the generated artifacts belonging to no single one of them."""

    def builder(self, name: str) -> Callable[[Path], NativeHarnessComposition] | None:
        """How to build one named target, or nothing when it is not declared."""
        return self.builders.get(name)  # lup: ignore[dict-get]

    def resolve(self, value: str, root: Path) -> list[NativeHarnessComposition]:
        """Parse a generic CLI selector into already concrete compositions."""
        if value == self.every:
            return [build(root) for build in self.builders.values()]
        build = self.builder(value)
        if build is not None:
            return [build(root)]
        named = ", ".join([*self.builders, self.every])
        raise typer.BadParameter(f"target must be one of: {named}")
