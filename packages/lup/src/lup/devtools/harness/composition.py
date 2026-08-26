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

from lup.adapters.claude.harness import ClaudeSpellings
from lup.adapters.claude.harness_runtime import (
    ClaudeCliEvidence,
    claude_capability_probes,
)
from lup.adapters.claude.login import CLAUDE_LOGIN
from lup.adapters.claude.profile_store import (
    AccountFile,
    ClaudeProfileNames,
    ClaudeProfileRegistrar,
)
from lup.codescan.common import RuleSelection
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
from lup.runtime.login import ProviderLogin
from lup.runtime.profile_tree import (
    ProfileFolders,
    TreeProfileNames,
    TreeProfileRegistrar,
    TreeProfileStateLocations,
)
from lup.runtime.profiles import ProfileDirectory

PROFILE_ROOT = Path(".lup") / "profiles"
"""Default place a project keeps its own profiles, relative to its root.

Under ``.lup`` because that is already where a checkout's personal state
lives — reconciliation proposals, resolver runs — and is already ignored, so
a login cannot be committed by a rule nobody remembered to write.
"""


def claude_profile_directory() -> ProfileDirectory:
    """The personal Claude account registry, as a directory to curate.

    What a project falls back to when it keeps no accounts of its own: names
    registered by hand, resolved against the login Claude Code itself writes.
    """
    accounts = AccountFile()
    return ProfileDirectory(
        ClaudeProfileNames(accounts), ClaudeProfileRegistrar(accounts), CLAUDE_LOGIN
    )


def local_profile_directory(
    root: Path,
    login: ProviderLogin,
    profile_root: Path = PROFILE_ROOT,
) -> ProfileDirectory:
    """The accounts a project keeps itself, as directories under it.

    What a project supplies instead of falling back to a personal registry:
    one name means one directory in this checkout, so an account reaches a
    launch without anything under the operator's home deciding which. A
    checkout that has started no profiles resolves nothing, which leaves a
    launch on whatever account its environment already selected.

    Which runtime's homes those directories hold is the ``login``'s to say —
    the subdirectory each takes is one of the words it carries — so a project
    on one runtime keeps that runtime's accounts and a project on two keeps
    both under one name, without this naming either.
    """
    folders = ProfileFolders(root / profile_root, login.home_subdir)
    return ProfileDirectory(
        TreeProfileNames(folders),
        TreeProfileRegistrar(folders),
        login,
        TreeProfileStateLocations(folders),
    )


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
        """Parse a generic CLI selector into already concrete compositions."""
        if value == self.every:
            return [build(root) for build in self.builders.values()]
        build = self.builder(value)
        if build is not None:
            return [build(root)]
        named = ", ".join([*self.builders, self.every])
        raise typer.BadParameter(f"target must be one of: {named}")
