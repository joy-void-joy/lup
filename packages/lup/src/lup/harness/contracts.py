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
        LocatedPart,
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


class Atom(str):
    """One native name spelled whole: a path, a product name, a reference.

    Portable prose may not contain one, because whatever names it should have
    been a prompt part. Every character is the runtime's own, so the whole
    string is vocabulary.
    """


class Instruction(str):
    """One native sentence carrying the caller's own words inside it.

    Only the runtime's identifiers are its own here — the interpolated text
    belongs to whoever declared it — so vocabulary is the identifier-shaped
    tokens rather than the whole sentence.
    """


class NativeSpellings(SkillInvocationRenderer):  # lup: ignore[abc-capability]
    """Own one native runtime's spelling of everything portable prose names.

    Deliberately wider than the three-method shape the capability rule wants: a
    runtime's vocabulary is one concept with many words, and splitting it into
    a handful of ABCs would make a caller compose several objects that never
    vary independently. It extends the invocation renderer rather than being
    implemented alongside it, so a single object satisfies both seams and no
    implementation inherits two capabilities.

    Every native word a prompt can reach arrives through one of these, so a
    declaration states intent and never a platform. A new prompt part adds an
    abstract method here, which no runtime can be constructed without
    answering — the rendering seam is closed by construction rather than by a
    reminder to edit two renderers.

    The return type says what kind of spelling a method produces, and that is
    also the answer the portable-content rule reads: an :class:`Atom` is the
    runtime's own word end to end, an :class:`Instruction` wraps words the
    caller supplied. A method returning a bare ``str`` spells into an artifact
    rather than into prose, and no prose is judged against it.
    """

    @property
    @abstractmethod
    def runtime_name(self) -> Atom:
        """Name the runtime the way prose addresses it."""

    @property
    @abstractmethod
    def native_identifiers(self) -> list[Atom]:
        """This runtime's own words that appear inside its instructions.

        An instruction frames text its caller supplied, so the sentence as a
        whole says nothing about prose — but the runtime's own words within it
        are exactly what prose must not reach for. Each one has to occur in
        something this runtime actually spells, which is checked, so the list
        cannot drift away from the sentences it describes.
        """

    @abstractmethod
    def tree(self, location: TreeLocation) -> Atom:
        """Spell one harness-tree location."""

    @abstractmethod
    def plugin(self, plugin: str, location: PluginLocation, member: str | None) -> Atom:
        """Spell one plugin-owned location, with or without a leaf."""

    @abstractmethod
    def invocation_pattern(self, plugin: str, placeholder: str) -> Atom:
        """Spell an invocation whose skill the reader supplies."""

    @abstractmethod
    def arguments_ref(self) -> Atom:
        """Spell how this runtime reaches the arguments of an invocation."""

    @abstractmethod
    def ask_user(self, question: str) -> Instruction:
        """Instruct the runtime to put one material question to the user."""

    @abstractmethod
    def delegate(self, subagent_type: QualifiedAgentName, prompt: str) -> Instruction:
        """Instruct the runtime to hand one task to one of its agents."""

    @abstractmethod
    def request_approval(self, action: str, reason: str) -> Instruction:
        """Instruct the runtime to obtain explicit approval before acting."""

    @abstractmethod
    def relocate_session(self, path: str) -> Instruction:
        """Spell the move into an already-created worktree this runtime allows."""

    @abstractmethod
    def resolver_entry(self) -> Instruction:
        """Spell how this runtime enters the shared resolver."""

    @abstractmethod
    def runtime_docs(self) -> Instruction:
        """Name this runtime's own documentation, wherever it lives."""

    @abstractmethod
    def project_root(self) -> str:
        """Spell how a process this runtime spawns names the repository root.

        A tool server started from a native tree has to find the project whose
        tools it serves, and no runtime lets it ask the same way: one
        substitutes the root into the command it spawns, another only
        guarantees to spawn it there. Like :meth:`model_alias` this reaches a
        generated artifact rather than prose, so it spells a bare string.
        """

    @abstractmethod
    def model_alias(self, tier: ModelTier) -> str | None:
        """Spell one portable tier into agent metadata, or decline it.

        Neither an atom nor an instruction: this reaches a generated artifact,
        never a prompt, so tier words like ``inherit`` stay ordinary English
        everywhere prose is judged.
        """


class PromptRenderer(ABC):
    """Own one native runtime's complete prompt-document spelling.

    A part spells itself against this, so what a renderer offers is the whole
    of what a part may reach for: the reader's vocabulary, and the one question
    — scope — that no single vocabulary can answer alone.
    """

    own: NativeSpellings
    """The vocabulary of the runtime that will read what this renders."""

    @abstractmethod
    def render(self, prompt: PromptDocument) -> str:
        """Render every semantic prompt part into native prompt text."""

    @abstractmethod
    def location(self, part: LocatedPart) -> str:
        """Spell one location for the reader, or for every runtime at once."""


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
