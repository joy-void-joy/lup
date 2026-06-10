"""Final-output tool — SDK-agnostic finalization mechanism.

The agent submits its structured output through an MCP tool instead of a
native SDK output mechanism (Claude ``output_format`` / Codex
``output_schema``). One mechanism on every backend means one gate, one
test surface, and one artifact:

- Validation happens in the handler — invalid payloads return
  ``is_error`` with the validation message, so the agent fixes and
  resubmits.
- The reflection gate is enforced in the handler — submitting before
  reflecting returns ``is_error`` directing the agent to the reflection
  tool first. This works on backends whose hooks are unavailable or
  experimental; PreToolUse hooks remain optional hardening.
- The validated output is written to ``session_dir/output.json``, which
  the orchestration layer reads after the run via :func:`read_output`.

Tool naming convention: registered on the ``notes`` server, the tool is
``mcp__notes__submit_output`` on every backend.

Examples:
    Create the tool and register it alongside the reflection tools::

        >>> kit = create_output_tool(
        ...     AgentOutput,
        ...     session_dir=notes.session,
        ...     gate=reflect_kit["gate"],
        ...     reflection_tool_name="mcp__notes__review",
        ... )
        >>> server = create_mcp_server("notes", tools=[*reflect_tools, *kit["tools"]])

    After the run, read the result::

        >>> output = read_output(notes.session, AgentOutput)
"""

import json
import logging
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, Field, ValidationError

from lup.mcp import LupMcpTool, ToolError, lup_tool
from lup.reflect import ReflectionGate

logger = logging.getLogger(__name__)

OUTPUT_FILENAME = "output.json"


class SubmitOutputResult(BaseModel):
    """Confirmation returned by the submit_output tool."""

    status: str = Field(description="'accepted' when the output was saved")
    saved_to: str = Field(description="Path where the output was written")


class OutputToolKit(TypedDict):
    """Return type for :func:`create_output_tool`."""

    tools: list[LupMcpTool]
    output_path: Path


def output_path(session_dir: Path) -> Path:
    """Return the canonical path of the submitted output for a session."""
    return session_dir / OUTPUT_FILENAME


def read_output[T: BaseModel](session_dir: Path, output_model: type[T]) -> T | None:
    """Read and validate the submitted output, or None if absent or invalid."""
    path = output_path(session_dir)
    if not path.exists():
        return None
    try:
        return output_model.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError, OSError:
        logger.exception("Submitted output at %s is unreadable or invalid", path)
        return None


def create_output_tool(
    output_model: type[BaseModel],
    *,
    session_dir: Path,
    gate: ReflectionGate | None = None,
    reflection_tool_name: str = "review",
) -> OutputToolKit:
    """Create the ``submit_output`` tool bound to a session directory.

    Args:
        output_model: Pydantic model the submission must validate against.
        session_dir: Where ``output.json`` is written.
        gate: Reflection gate enforced in-handler. None disables gating.
        reflection_tool_name: Name shown in the gate denial message.

    Returns:
        The tool (for MCP server registration) and the output path
        (for completion checks and result reading).
    """
    path = output_path(session_dir)

    @lup_tool(
        "Submit your final structured output. This is how the session's "
        "result is recorded — call it exactly once, after your analysis is "
        "complete. If the payload is invalid you get the validation errors "
        "back: fix them and resubmit. Submission is rejected until you have "
        f"reflected via {reflection_tool_name}.",
        input_model=output_model,
        name="submit_output",
        output_model=SubmitOutputResult,
    )
    async def submit_output(validated: BaseModel) -> SubmitOutputResult:
        if gate is not None and not gate.reflected:
            raise ToolError(
                f"You must call {reflection_tool_name}() with your "
                "self-assessment before submitting output. Reflect first, "
                "then resubmit."
            )
        session_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(validated.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )
        return SubmitOutputResult(status="accepted", saved_to=str(path))

    return OutputToolKit(tools=[submit_output], output_path=path)
