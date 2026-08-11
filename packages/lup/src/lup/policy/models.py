"""Shared policy vocabulary: semantic events in, allow/ask/deny decisions out.

The native decoders in ``lup.adapters.<provider>.native`` translate wire
payloads into these events (shell command, fetch URL, edit batch, unknown
tool); the policies in :mod:`lup.policy.rules` and :mod:`lup.policy.chain`
consume them and return a :class:`Decision`.
"""

from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
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


class ToolIdentity(BaseModel):
    """Opaque source identity retained only for diagnostics."""

    model_config = ConfigDict(frozen=True)

    original_name: str
    source_evidence: JsonValue = None


class EditChange(BaseModel):
    """One named file change within an edit operation."""

    model_config = ConfigDict(frozen=True)

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


class SemanticToolBase(BaseModel):
    """One native call as policy understands it, judging itself.

    Each kind knows which declared family judges it, so routing is the tool
    answering rather than a walk naming the kinds. Pydantic's metaclass is an
    ``ABCMeta``, so a kind that does not answer :meth:`decide_under` cannot be
    built at all — a new tool cannot slip past the router by omission.
    """

    model_config = ConfigDict(frozen=True)

    @abstractmethod
    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        """The verdict this call's own family policy reaches."""

    def as_documents(self) -> Self:
        """This call with fragment evidence resolved into whole documents.

        Most tools already carry everything a policy reads. An edit stated
        as a preimage and its replacement is the exception, and answers for
        itself — a judge fed the fragment loses the source context the
        kernel's reading depends on.
        """
        return self


class EditBatch(SemanticToolBase):
    """The complete set of file changes in one native edit operation."""

    changes: list[EditChange] = Field(min_length=1)

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        if policies.edit is None:
            return undeclared("edit")
        return policies.edit.decide(self)

    def as_documents(self) -> Self:
        return self.model_copy(
            update={"changes": [change.as_documents() for change in self.changes]}
        )


class ShellCommand(SemanticToolBase):
    """A semantic command execution request."""

    command: str
    cwd: Path | None = None
    unsandboxed: bool = False

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        if policies.shell is None:
            return undeclared("shell")
        return policies.shell.decide(self)


class FetchUrl(SemanticToolBase):
    """Retrieval of one known URL."""

    url: AnyHttpUrl

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        if policies.fetch is None:
            return undeclared("fetch")
        return policies.fetch.decide(self)


class SearchWeb(SemanticToolBase):
    """A web search query, distinct from fetching a known URL."""

    query: str

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        """Search has no rule surface at all, so it always asks."""
        return Decision(
            effect="ask",
            reason=f"web search {self.query!r} is not covered by policy",
        )


class UnknownTool(SemanticToolBase):
    """An unclassified native tool invocation retained for audit."""

    identity: ToolIdentity
    input: JsonObject = Field(default_factory=dict)

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        return policies.unknown.decide(self)


type SemanticTool = EditBatch | ShellCommand | FetchUrl | SearchWeb | UnknownTool


class SessionStarted(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str


class InputSubmitted(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str


class BeforeTool(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: SemanticTool
    identity: ToolIdentity


class ApprovalRequested(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: SemanticTool
    reason: str


class AfterTool(BaseModel):
    model_config = ConfigDict(frozen=True)

    identity: ToolIdentity
    succeeded: bool
    output: str = ""


class SubagentStarted(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str


class SubagentStopped(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    succeeded: bool


class CompletionRequested(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str = ""


class BeforeCompaction(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str = ""


class AfterCompaction(BaseModel):
    model_config = ConfigDict(frozen=True)

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


class Decision(BaseModel):
    """One conservative policy verdict, and where the call it judges runs.

    The two fields are separate axes: :attr:`effect` answers who decides,
    :attr:`sandbox` answers where it runs. :data:`SandboxPlacement` carries
    what each pair means and :meth:`placed` renders one for a given runtime.
    """

    model_config = ConfigDict(frozen=True)

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

    def placed(self, escapable: bool) -> "Decision":
        """This verdict as a runtime that can, or cannot, place a call sees it."""
        kernel = KernelDecision(self.effect, self.reason, self.sandbox).placed(
            escapable
        )
        return Decision(
            effect=kernel.effect, reason=kernel.reason, sandbox=kernel.sandbox
        )


class ObservationFailure(BaseModel):
    """One observer failure that cannot change the policy verdict."""

    model_config = ConfigDict(frozen=True)

    observer: str
    message: str


class PolicyEvaluation(BaseModel):
    """Computed decision plus separately surfaced observer failures."""

    model_config = ConfigDict(frozen=True)

    decision: Decision
    observation_failures: list[ObservationFailure] = Field(default_factory=list)
