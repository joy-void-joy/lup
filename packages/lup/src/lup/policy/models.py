"""Shared policy vocabulary: semantic events in, allow/ask/deny decisions out.

The native decoders in ``lup.adapters.<provider>.native`` translate wire
payloads into these events (shell command, fetch URL, edit batch, unknown
tool); the policies in :mod:`lup.policy.rules` and :mod:`lup.policy.chain`
consume them and return a :class:`Decision`.
"""

from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints

from lup.policy.kernel.decision import DecisionEffect
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


class EditBatch(SemanticToolBase):
    """The complete set of file changes in one native edit operation."""

    changes: list[EditChange] = Field(min_length=1)

    def decide_under(self, policies: "DeclaredPolicies") -> "Decision":
        if policies.edit is None:
            return undeclared("edit")
        return policies.edit.decide(self)


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
    """One conservative policy verdict."""

    model_config = ConfigDict(frozen=True)

    effect: DecisionEffect
    reason: str = ""


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
