"""Neutral capability seams composed by neutral harness code.

Each ABC names one narrow operation of the harness domain: the generation
pipeline stages from rendering canonical declarations through materializing
files on disk. Neutral orchestration composes these seams; provider-specific
implementations live in adapter packages, while complete process and
validation boundaries live beside their deterministic implementations.
Parameter and result models live with their owning concern, so imports here
are type-only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from lup.harness.materialization import MaterializationResult
    from lup.harness.models import (
        ArtifactTree,
        CapabilityEvidence,
        PluginLocation,
        PromptDocument,
        SkillInvocation,
        TreeLocation,
    )
    from lup.harness.reconciliation import CurrentTree, ReconciliationProposal


class ArtifactRenderer[S](ABC):
    """Render one cohesive artifact family."""

    @abstractmethod
    def render(self, source: S) -> ArtifactTree:
        """Render source into a complete in-memory artifact tree."""


class SkillInvocationRenderer(ABC):
    """Own one native runtime's complete skill invocation spelling."""

    @abstractmethod
    def render(self, invocation: SkillInvocation) -> str:
        """Render qualification, escaping, and arguments together."""


class NativePathSpelling(ABC):
    """Own one native runtime's spelling of every harness-owned location."""

    @property
    @abstractmethod
    def runtime_name(self) -> str:
        """Name the runtime the way prose addresses it."""

    @abstractmethod
    def tree(self, location: TreeLocation) -> str:
        """Spell one harness-tree location."""

    @abstractmethod
    def plugin(self, plugin: str, location: PluginLocation, member: str | None) -> str:
        """Spell one plugin-owned location, with or without a leaf."""


class PromptRenderer(ABC):
    """Own one native runtime's complete prompt-document spelling."""

    @abstractmethod
    def render(self, prompt: PromptDocument) -> str:
        """Render every semantic prompt part into native prompt text."""


class CurrentTreeReader(ABC):
    """Read and classify current artifact ownership."""

    @abstractmethod
    def read(self, root: Path) -> CurrentTree:
        """Read current files without mutating the root."""


class Reconciler(ABC):
    """Compare current and desired trees."""

    @abstractmethod
    def propose(
        self, current: CurrentTree, desired: ArtifactTree
    ) -> ReconciliationProposal:
        """Return writes, proven deletions, and explicit conflicts."""


class Materializer(ABC):
    """Apply one validated reconciliation proposal."""

    @abstractmethod
    def apply(self, proposal: ReconciliationProposal) -> MaterializationResult:
        """Atomically update only proven generator-owned paths."""


class CapabilityProbe[C](ABC):
    """Probe one named capability contract."""

    @abstractmethod
    def probe(self) -> CapabilityEvidence[C]:
        """Return evidence without invoking an unsupported operation."""
