"""Shared policy vocabulary: semantic events in, allow/ask/deny decisions out.

The native decoders in ``lup.adapters.<provider>.native`` translate wire
payloads into these events (shell command, fetch URL, edit batch, unknown
tool); the policies in :mod:`lup.policy.rules` and :mod:`lup.policy.chain`
consume them and return a :class:`Decision`.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from lup.policy.kernel.decision import (
    DecisionEffect,
    KernelDecision,
    SandboxPlacement,
)
from lup.types import JsonObject, JsonValue

if TYPE_CHECKING:
    from lup.policy.contracts import DeclaredPolicies

type PolicyId = Literal["fetch", "shell", "edit", "unknown-tool"]
"""One semantic decision family a generated hook set enforces.

Each id names the policy for one semantic tool: ``fetch`` for
:class:`FetchUrl`, ``shell`` for :class:`ShellCommand`, ``edit`` for
:class:`EditBatch`, and ``unknown-tool`` for the conservative
:class:`UnknownTool` fallback."""

type UrlPathPrefix = Annotated[str, StringConstraints(pattern=r"^/")]
"""An absolute URL path prefix scoping a fetch rule beneath an origin."""


class ToolIdentity(BaseModel, frozen=True):
    """Opaque source identity retained only for diagnostics."""

    original_name: str
    source_evidence: JsonValue = None


class EditChange(BaseModel, frozen=True):
    """One named file change within an edit operation."""

    path: Path
    before: str | None = None
    after: str | None = None

    def as_documents(self) -> "EditChange":
        """The whole before and after documents this change would produce.

        A change carrying a preimage fragment is spliced into the file it
        names, the way the edit tool itself would apply it, because the
        kernel's source-aware reading — comment positions, string literals,
        docstrings — only holds for a document that parses as one. A
        creation, a deletion, a file this process cannot read, or a preimage
        the file does not hold exactly once stays as declared and is judged
        conservatively on its own evidence.
        """
        if self.before is None or self.after is None:
            return self
        try:
            current = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return self
        if current.count(self.before) != 1:
            return self
        position = current.find(self.before)
        updated = (
            current[:position] + self.after + current[position + len(self.before) :]
        )
        return self.model_copy(update={"before": current, "after": updated})


def undeclared(family: str) -> "Decision":
    """The verdict for a family this composition never declared a policy for."""
    return Decision(
        effect="ask",
        reason=f"no {family} policy is declared, so this call needs approval",
    )


class SemanticToolBase(ABC):
    """One native call as policy understands it, judging itself.

    Each kind knows which declared family judges it, so routing is the tool
    answering rather than a walk naming the kinds, and a kind that does not
    answer :meth:`decide_under` cannot be built — a new tool cannot slip past
    the router by omission.

    A kind that constrains what it may hold enforces that in its own
    constructor. Pydantic declared those constraints while these were models;
    the guarantee is the same and the place it is written is not, which is why
    each one says so where it is checked.
    """

    @abstractmethod
    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        """The verdict this call's own family policy reaches."""

    @abstractmethod
    def as_documents(self) -> Self:
        """This call with fragment evidence resolved into whole documents.

        Most tools already carry everything a policy reads and answer with
        themselves. An edit stated as a preimage and its replacement is the
        exception — a judge fed the fragment loses the source context the
        kernel's reading depends on.
        """


class EditBatch(SemanticToolBase):
    """The complete set of file changes in one native edit operation."""

    def __init__(self, changes: list[EditChange]) -> None:
        if not changes:
            raise ValueError("an edit batch states at least one change")
        self.changes = changes

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        if policies.edit is None:
            return undeclared("edit")
        return policies.edit.decide(self)

    def as_documents(self) -> Self:
        return type(self)([change.as_documents() for change in self.changes])


class ShellCommand(SemanticToolBase):
    """A semantic command execution request."""

    def __init__(
        self, command: str, cwd: Path | None = None, unsandboxed: bool = False
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.unsandboxed = unsandboxed

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        if policies.shell is None:
            return undeclared("shell")
        return policies.shell.decide(self)

    def as_documents(self) -> Self:
        return self


class FetchUrl(SemanticToolBase):
    """Retrieval of one known URL."""

    def __init__(self, url: AnyHttpUrl | str) -> None:
        self.url = AnyHttpUrl(str(url))
        """Parsed here, so a malformed URL cannot reach a policy decision."""

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        if policies.fetch is None:
            return undeclared("fetch")
        return policies.fetch.decide(self)

    def as_documents(self) -> Self:
        return self


class SearchWeb(SemanticToolBase):
    """A web search query, distinct from fetching a known URL."""

    def __init__(self, query: str) -> None:
        self.query = query

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        """Search has no rule surface at all, so it always asks."""
        return Decision(
            effect="ask",
            reason=f"web search {self.query!r} is not covered by policy",
        )

    def as_documents(self) -> Self:
        return self


class UnknownTool(SemanticToolBase):
    """An unclassified native tool invocation retained for audit."""

    def __init__(self, identity: ToolIdentity, input: JsonObject | None = None) -> None:
        self.identity = identity
        self.input: JsonObject = input or {}

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        return policies.unknown.decide(self)

    def as_documents(self) -> Self:
        return self


type SemanticTool = EditBatch | ShellCommand | FetchUrl | SearchWeb | UnknownTool


class SessionStarted(BaseModel, frozen=True):
    session_id: str


class InputSubmitted(BaseModel, frozen=True):
    text: str


class BeforeTool(BaseModel, frozen=True, arbitrary_types_allowed=True):
    tool: SemanticTool
    identity: ToolIdentity


class ApprovalRequested(BaseModel, frozen=True, arbitrary_types_allowed=True):
    tool: SemanticTool
    reason: str


class AfterTool(BaseModel, frozen=True):
    identity: ToolIdentity
    succeeded: bool
    output: str = ""


class SubagentStarted(BaseModel, frozen=True):
    name: str


class SubagentStopped(BaseModel, frozen=True):
    name: str
    succeeded: bool


class CompletionRequested(BaseModel, frozen=True):
    reason: str = ""


class BeforeCompaction(BaseModel, frozen=True):
    reason: str = ""


class AfterCompaction(BaseModel, frozen=True):
    summary: str = ""


type SemanticEvent = (
    SessionStarted
    | InputSubmitted
    | BeforeTool
    | ApprovalRequested
    | AfterTool
    | SubagentStarted
    | SubagentStopped
    | CompletionRequested
    | BeforeCompaction
    | AfterCompaction
)


class Decision(BaseModel, frozen=True):
    """One conservative policy verdict, and where the call it judges runs.

    The two fields are separate axes: :attr:`effect` answers who decides,
    :attr:`sandbox` answers where it runs. :data:`SandboxPlacement` carries
    what each pair means and :meth:`placed` renders one for a given runtime.
    """

    effect: DecisionEffect
    reason: str = ""
    sandbox: SandboxPlacement = "ambient"

    @field_validator("sandbox")
    @classmethod
    def reached(
        cls, sandbox: SandboxPlacement, info: ValidationInfo
    ) -> SandboxPlacement:
        """Hold the kernel's own invariant rather than restating it here.

        ``effect`` is declared first, so it is already validated and readable
        while this field is: a deny or a defer collapses the placement here
        exactly as it does in the kernel, from the same line of code.
        """
        return KernelDecision(info.data["effect"], sandbox=sandbox).sandbox

    def placed(self, escapable: bool, agent_escalates: bool) -> "Decision":
        """This verdict as a runtime that can, or cannot, place a call sees it."""
        kernel = KernelDecision(self.effect, self.reason, self.sandbox).placed(
            escapable, agent_escalates
        )
        return Decision(
            effect=kernel.effect, reason=kernel.reason, sandbox=kernel.sandbox
        )


class ObservationFailure(BaseModel, frozen=True):
    """One observer failure that cannot change the policy verdict."""

    observer: str
    message: str


class PolicyEvaluation(BaseModel, frozen=True):
    """Computed decision plus separately surfaced observer failures."""

    decision: Decision
    observation_failures: list[ObservationFailure] = []
