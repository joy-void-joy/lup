"""Native composition roots wiring concrete Claude and Codex capabilities.

The one place the harness CLI touches adapter implementations: each builder
bundles a generation recipe, a runtime-readiness probe set, and a skill
invocation renderer, and :class:`NativeTargets` maps the CLI target selector
onto those already concrete roots. What a project publishes through them is
its own ``ProjectContent``, so the builders decide nothing about content.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

import typer
from pydantic import BaseModel

from lup.providers.claude.harness import ClaudeSpellings
from lup.providers.claude.harness_runtime import (
    ClaudeCliEvidence,
    claude_capability_probes,
)
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.harness.codescan.common import RuleSelection
from lup.providers.codex.harness import CodexSpellings
from lup.providers.codex.home import CodexWorktreeHomeStore
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.codex.trust import HOOKS_LIST, hook_wire_fields
from lup.providers.codex.harness_runtime import (
    CodexCliEvidence,
    codex_capability_probes,
)
from lup.devtools.harness.drift import refuse_generation
from lup.harness.generate import (
    NativeHarnessComposition,
    ProjectContent,
    claude_generation_recipe,
    codex_generation_recipe,
    obstruction_at,
)
from lup.harness.evidence import WireContract
from lup.harness.models import CapabilityEvidence, PromptDocument
from lup.providers.profile_tree import profile_directory
from lup.providers.profiles import ProfileDirectory


def claude_profile_directory() -> ProfileDirectory:
    """The Claude side of the accounts this person keeps, as a directory to curate.

    What a project falls back to when it names no origin of its own: this
    checkout's own profiles, then the global ones every checkout shares, so
    an account signed in once opens in every repository.
    """
    return profile_directory(CLAUDE_LOGIN)


def codex_profile_directory() -> ProfileDirectory:
    """The Codex side of the same accounts, one name meaning one person on both."""
    return profile_directory(CODEX_LOGIN)


type NativeCapabilityEvidence = (
    CapabilityEvidence[ClaudeCliEvidence] | CapabilityEvidence[CodexCliEvidence]
)


class NativeComposer(ABC):
    """How one runtime assembles a project's content into what a CLI opens.

    One declared seam rather than a free function per runtime, and the
    difference is not style. A function is reached by name, so adding a
    runtime means finding every caller that names one and remembering the new
    one — and a caller that forgets leaves that runtime silently absent
    rather than failing. A seam is reached by the object a project declared,
    so what ``NativeTargets`` holds is the whole of what exists.

    Deliberately one method. What a runtime answers here is a composition,
    and every part of it — the recipe, the readiness probes, the invocation
    renderer — is that same runtime's answer, so splitting them into three
    seams would hand a caller three objects that never vary independently.
    The composition is the unit that varies.
    """

    @abstractmethod
    def compose(
        self,
        root: Path,
        content: ProjectContent,
        guidance: PromptDocument | None = None,
    ) -> NativeHarnessComposition:
        """This runtime's composition over one project's content."""


class ClaudeComposer(NativeComposer):
    """Construct the Claude capabilities directly."""

    def compose(
        self,
        root: Path,
        content: ProjectContent,
        guidance: PromptDocument | None = None,
    ) -> NativeHarnessComposition:
        plugin = root / ".claude" / "plugins" / content.harness.plugins[0].name

        def readiness() -> Sequence[NativeCapabilityEvidence]:
            return [probe.probe() for probe in claude_capability_probes(plugin)]

        return NativeHarnessComposition(
            recipe=claude_generation_recipe(root, content, guidance),
            readiness=readiness,
            invocation_renderer=ClaudeSpellings(),
            login=CLAUDE_LOGIN,
            default_config_home=CLAUDE_LOGIN.ambient_home,
            clipboard_transport="commands",
        )


class CodexComposer(NativeComposer):
    """Construct the Codex capabilities directly."""

    def compose(
        self,
        root: Path,
        content: ProjectContent,
        guidance: PromptDocument | None = None,
    ) -> NativeHarnessComposition:
        def readiness() -> Sequence[NativeCapabilityEvidence]:
            return [probe.probe() for probe in codex_capability_probes()]

        return NativeHarnessComposition(
            recipe=codex_generation_recipe(root, content, guidance),
            readiness=readiness,
            invocation_renderer=CodexSpellings(),
            login=CODEX_LOGIN,
            default_config_home=CodexWorktreeHomeStore().home_for(root),
            clipboard_transport="x11",
            # The one reply whose field names Lup depends on outside a typed
            # schema: hook trust is seeded from what `hooks/list` reports, and
            # a rename there fails open rather than loudly.
            wire_contracts=[WireContract(method=HOOKS_LIST, fields=hook_wire_fields())],
        )


@runtime_checkable
class TargetBuilder(Protocol):
    """How one project turns a root into one runtime's whole composition.

    Takes an optional rule selection because the one caller with a reason to
    compile a tree against a different one is a launch — a session opened
    where the conventions are not the point. Declared on the seam rather than
    reached for through a global, so a project that wants no such launch
    simply ignores the argument, and one that does cannot be handed it
    through a channel nothing types.
    """

    def __call__(
        self, root: Path, rules: RuleSelection | None = None
    ) -> NativeHarnessComposition: ...


class NativeTargets(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """Every native adapter a CLI selector can name, and how to build each.

    A project declares which runtimes it generates a tree for; the commands
    take already concrete compositions and never learn a target's name. The
    builders are keyed rather than listed because the selector a human types
    is the key, and the launch commands are the adapter's own surface.

    Arbitrary types because a builder is a callable seam rather than data:
    what pydantic would validate here is a signature, which is pyright's
    question and already answered there.
    """

    builders: dict[str, "TargetBuilder"]

    every: str = "all"
    """The selector reaching every declared tree at once, which is also what
    reaches the generated artifacts belonging to no single one of them."""

    def builder(self, name: str) -> "TargetBuilder | None":
        """How to build one named target, or nothing when it is not declared."""
        return self.builders.get(name)

    def resolve(self, value: str, root: Path) -> list[NativeHarnessComposition]:
        """Parse a generic CLI selector into already concrete compositions.

        The one boundary every command reaches a declaration through, so a
        declaration that will not compile is refused here, in the words it
        refused with, rather than travelling out as whatever its reader
        happened to raise: a missing passage file as an interpreter traceback,
        an invocation naming no skill as a hundred lines of pydantic field
        context. Both are declaration errors with a fix in the declaration,
        and this is where they are turned back into one.
        """

        def compiled(name: str, build: "TargetBuilder") -> NativeHarnessComposition:
            """One target's whole composition, or a refusal naming what stopped it."""
            try:
                return build(root)
            except Exception as refusal:
                refuse_generation(obstruction_at(name, refusal))

        if value == self.every:
            return [compiled(name, build) for name, build in self.builders.items()]
        build = self.builder(value)
        if build is not None:
            return [compiled(value, build)]
        named = ", ".join([*self.builders, self.every])
        raise typer.BadParameter(f"target must be one of: {named}")
