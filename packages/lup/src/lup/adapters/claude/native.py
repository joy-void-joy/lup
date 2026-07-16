"""Claude-private native event parsing and decision rendering."""

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError

from lup.policy.models import (
    BeforeTool,
    Decision,
    EditBatch,
    EditChange,
    FetchUrl,
    SearchWeb,
    ShellCommand,
    ToolIdentity,
    UnknownTool,
)
from lup.policy.native import NativeDecisionRenderer, NativeEventDecoder
from lup.types import JsonObject


class ClaudeEditOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["edit"] = "edit"
    path: Path
    before: str
    after: str


class ClaudeWriteOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["write"] = "write"
    path: Path
    content: str


class ClaudeEditBatchOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["edit_batch"] = "edit_batch"
    changes: list[EditChange] = Field(min_length=1)


class ClaudeShellOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["shell"] = "shell"
    command: str
    cwd: Path | None = None


class ClaudeFetchOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["fetch"] = "fetch"
    url: str


class ClaudeSearchOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["search"] = "search"
    query: str


class ClaudeUnknownOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["unknown"] = "unknown"
    name: str
    input: JsonObject = Field(default_factory=dict)


type ClaudeOperation = (
    ClaudeEditOperation
    | ClaudeWriteOperation
    | ClaudeEditBatchOperation
    | ClaudeShellOperation
    | ClaudeFetchOperation
    | ClaudeSearchOperation
    | ClaudeUnknownOperation
)


class ClaudeBeforeToolEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: ClaudeOperation


class ClaudeHookPayload(BaseModel):
    """Validated external hook input before operation-specific parsing."""

    model_config = ConfigDict(frozen=True)

    tool_name: str
    tool_input: JsonObject = Field(default_factory=dict)


def parse_claude_before_tool(payload: ClaudeHookPayload) -> ClaudeBeforeToolEvent:
    """Decode Claude names and payload fields at the adapter boundary."""
    match payload.tool_name, payload.tool_input:
        case "Edit", {
            "file_path": str(path),
            "old_string": str(before),
            "new_string": str(after),
        }:
            operation: ClaudeOperation = ClaudeEditOperation(
                path=Path(path), before=before, after=after
            )
        case "Write", {"file_path": str(path), "content": str(content)}:
            operation = ClaudeWriteOperation(path=Path(path), content=content)
        case "Bash", {"command": str(command)}:
            operation = ClaudeShellOperation(command=command)
        case "WebFetch", {"url": str(url)}:
            operation = ClaudeFetchOperation(url=url)
        case "WebSearch", {"query": str(query)}:
            operation = ClaudeSearchOperation(query=query)
        case _:
            operation = ClaudeUnknownOperation(
                name=payload.tool_name, input=payload.tool_input
            )
    return ClaudeBeforeToolEvent(operation=operation)


class ClaudeEventDecoder(NativeEventDecoder[ClaudeBeforeToolEvent]):
    """Decode validated Claude operations into the shared vocabulary."""

    def decode(self, event: ClaudeBeforeToolEvent) -> BeforeTool:
        operation = event.operation
        match operation:
            case ClaudeEditOperation(path=path, before=before, after=after):
                tool = EditBatch(
                    changes=[EditChange(path=path, before=before, after=after)]
                )
                name = "Edit"
            case ClaudeWriteOperation(path=path, content=content):
                tool = EditBatch(changes=[EditChange(path=path, after=content)])
                name = "Write"
            case ClaudeEditBatchOperation(changes=changes):
                tool = EditBatch(changes=changes)
                name = "Edit"
            case ClaudeShellOperation(command=command, cwd=cwd):
                tool = ShellCommand(command=command, cwd=cwd)
                name = "Bash"
            case ClaudeFetchOperation(url=url):
                name = "WebFetch"
                try:
                    tool = FetchUrl(url=AnyHttpUrl(url))
                except ValidationError:
                    identity = ToolIdentity(original_name=name)
                    return BeforeTool(
                        tool=UnknownTool(identity=identity, input={"url": url}),
                        identity=identity,
                    )
            case ClaudeSearchOperation(query=query):
                tool = SearchWeb(query=query)
                name = "WebSearch"
            case ClaudeUnknownOperation(name=name, input=input_data):
                identity = ToolIdentity(original_name=name)
                return BeforeTool(
                    tool=UnknownTool(identity=identity, input=input_data),
                    identity=identity,
                )
        identity = ToolIdentity(original_name=name)
        return BeforeTool(tool=tool, identity=identity)


class ClaudeDecisionOutput(BaseModel):
    """Claude PreToolUse hook-specific decision payload."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    hook_event_name: Literal["PreToolUse"] = Field(
        default="PreToolUse", alias="hookEventName"
    )
    permission_decision: Literal["allow", "ask", "deny"] = Field(
        alias="permissionDecision"
    )
    reason: str = Field(default="", alias="permissionDecisionReason")


class ClaudeDecisionRenderer(NativeDecisionRenderer[ClaudeDecisionOutput]):
    """Render all semantic effects through Claude's native approval result."""

    def render(self, decision: Decision) -> ClaudeDecisionOutput:
        return ClaudeDecisionOutput(
            permissionDecision=decision.effect,
            permissionDecisionReason=decision.reason,
        )
