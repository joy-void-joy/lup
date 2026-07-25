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
        ModelTier,
        PluginLocation,
        PromptDocument,
        QualifiedAgentName,
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


class NativeSpellings(SkillInvocationRenderer):
    """Own one native runtime's spelling of everything portable prose names.

    Every native word a prompt can reach arrives through one of these, so a
    declaration states intent and never a platform. A new prompt part adds an
    abstract method here, which no runtime can be constructed without
    answering — the rendering seam is closed by construction rather than by a
    reminder to edit two renderers.
    """

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

    @abstractmethod
    def invocation_pattern(self, plugin: str, placeholder: str) -> str:
        """Spell an invocation whose skill the reader supplies."""

    @abstractmethod
    def ask_user(self, question: str) -> str:
        """Instruct the runtime to put one material question to the user."""

    @abstractmethod
    def delegate(self, subagent_type: QualifiedAgentName, prompt: str) -> str:
        """Instruct the runtime to hand one task to one of its agents."""

    @abstractmethod
    def request_approval(self, action: str, reason: str) -> str:
        """Instruct the runtime to obtain explicit approval before acting."""

    @abstractmethod
    def relocate_session(self, path: str) -> str:
        """Spell the move into an already-created worktree this runtime allows."""

    @abstractmethod
    def resolver_entry(self) -> str:
        """Spell how this runtime enters the shared resolver."""

    @abstractmethod
    def arguments_ref(self) -> str:
        """Spell how this runtime reaches the arguments of an invocation."""

    @abstractmethod
    def runtime_docs(self) -> str:
        """Name this runtime's own documentation, wherever it lives."""

    @abstractmethod
    def model_alias(self, tier: ModelTier) -> str | None:
        """Spell one portable tier, or decline where none is proven."""


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
