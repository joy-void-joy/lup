"""Narrow harness, artifact, diagnostic, and process capabilities."""

from abc import ABC, abstractmethod
from pathlib import Path

from lup.harness.models import (
    ArtifactTree,
    CapabilityEvidence,
    CurrentTree,
    ExitStatus,
    LaunchRequest,
    MaterializationResult,
    ReconciliationProposal,
    SkillInvocation,
    ValidationResult,
)

# lup: Isn't that mainly for resolve? Shouldn't it go there? Or what are we using those ABC for? It's not clear from code+file position

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
