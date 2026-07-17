"""Shared policy vocabulary: semantic events in, allow/ask/deny decisions out.

The native decoders in ``lup.adapters.<provider>.native`` translate wire
payloads into these events (shell command, fetch URL, edit batch, unknown
tool); the policies in :mod:`lup.policy.rules` and :mod:`lup.policy.chain`
consume them and return a :class:`Decision`.
"""

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from lup.types import JsonObject, JsonValue


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


class EditBatch(BaseModel):
    """The complete set of file changes in one native edit operation."""

    model_config = ConfigDict(frozen=True)

    changes: list[EditChange] = Field(min_length=1)


class ShellCommand(BaseModel):
    """A semantic command execution request."""

    model_config = ConfigDict(frozen=True)

    command: str
    cwd: Path | None = None


class FetchUrl(BaseModel):
    """Retrieval of one known URL."""

    model_config = ConfigDict(frozen=True)

    url: AnyHttpUrl


class SearchWeb(BaseModel):
    """A web search query, distinct from fetching a known URL."""

    model_config = ConfigDict(frozen=True)

    query: str


class UnknownTool(BaseModel):
    """An unclassified native tool invocation retained for audit."""

    model_config = ConfigDict(frozen=True)

    identity: ToolIdentity
    input: JsonObject = Field(default_factory=dict)


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

    effect: Literal["allow", "ask", "deny"]
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
