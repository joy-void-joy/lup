"""Neutral capability seams composed by neutral harness code.

Each ABC names one narrow operation of the harness domain: the generation
pipeline stages from rendering canonical declarations through materializing
files on disk, and the native-CLI probing and launching around them. Neutral
orchestration — the devtools generation flows and the resolver — composes
these seams; concrete implementations live in the named adapter packages when
they are provider-specific and beside the matching concern module in this
package when they are deterministic. Parameter and result models live with
their owning concern, which is why every import here is type-only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from lup.harness.materialization import MaterializationResult
    from lup.harness.models import ArtifactTree, CapabilityEvidence, SkillInvocation
    from lup.harness.process import ExitStatus, LaunchRequest
    from lup.harness.reconciliation import CurrentTree, ReconciliationProposal
    from lup.harness.validation import ValidationResult


class ArtifactRenderer[S](ABC):
    """Render one cohesive artifact family."""

    @abstractmethod
    def render(self, source: S) -> ArtifactTree:
        """Render source into a complete in-memory artifact tree."""


class ArtifactValidator(ABC):
    """Validate a complete in-memory artifact tree."""

    @abstractmethod
    def validate(self, tree: ArtifactTree) -> ValidationResult:
        """Return every deterministic validation issue."""


class SkillInvocationRenderer(ABC):
    """Own one native runtime's complete skill invocation spelling."""

    @abstractmethod
    def render(self, invocation: SkillInvocation) -> str:
        """Render qualification, escaping, and arguments together."""


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


class ProcessLauncher(ABC):
    """Launch one concrete process boundary."""

    @abstractmethod
    def launch(self, request: LaunchRequest) -> ExitStatus:
        """Launch with typed arguments and environment."""
