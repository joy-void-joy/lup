"""Spec-driven subagent delegation tool.

Claude runs subagents natively (``AgentDefinition`` from a
``SubagentSpec``). Backends without native subagents get this served
MCP tool instead: the agent calls ``run_subagent(name, task)`` and the
tool dispatches a one-shot :func:`lup.adapters.common.query` to the
backend that serves the spec's model. The same spec list drives both
paths, so the available roles never diverge between backends.

Specs that require tools can only run on the Claude backend (one-shot
queries on other backends have no tool support); the tool fails loudly
rather than silently dropping the tools.
"""

import logging

from pydantic import BaseModel, Field

from lup.adapters.common import query
from lup.mcp import LupMcpTool, ToolError, lup_tool
from lup.types import SubagentSpec, model_backend

logger = logging.getLogger(__name__)


class RunSubagentInput(BaseModel):
    """Input for the run_subagent tool."""

    name: str = Field(description="Name of the subagent role to run")
    task: str = Field(description="The task or question for the subagent")


class RunSubagentOutput(BaseModel):
    """Result returned from a delegated subagent run."""

    subagent: str = Field(description="Name of the subagent that ran")
    result: str = Field(description="The subagent's final text output")


def create_run_subagent_tool(specs: list[SubagentSpec]) -> LupMcpTool:
    """Create the run_subagent tool from the shared spec list.

    Args:
        specs: SDK-agnostic subagent definitions (the same list the
            Claude adapter converts to native ``AgentDefinition``).

    Returns:
        A LupMcpTool for backends without native subagent support.
    """
    by_name = {spec.name: spec for spec in specs}
    roles = "; ".join(f"{spec.name}: {spec.description}" for spec in specs)

    @lup_tool(
        "Delegate a focused task to a specialized subagent and return its "
        "result. Use this when part of the work benefits from an "
        "independent, focused worker instead of doing everything inline. "
        f"Available roles — {roles}",
        name="run_subagent",
    )
    async def run_subagent(validated: RunSubagentInput) -> RunSubagentOutput:
        spec = by_name.get(validated.name)
        if spec is None:
            raise ToolError(
                f"Unknown subagent {validated.name!r}. Available: {sorted(by_name)}"
            )

        backend = model_backend(spec.model)
        if spec.tools and backend != "anthropic":
            raise ToolError(
                f"Subagent {spec.name!r} requires tools {spec.tools}, which "
                f"one-shot queries on the {backend} backend cannot provide. "
                "Give the spec a Claude model, or drop its tools."
            )

        logger.info(
            "Delegating to subagent %r (model=%s, backend=%s)",
            spec.name,
            spec.model,
            backend,
        )
        response = await query(
            validated.task,
            model=spec.model,
            system_prompt=spec.prompt,
            tools=spec.tools or None,
            max_turns=spec.max_turns,
        )
        return RunSubagentOutput(subagent=spec.name, result=response.text or "")

    return run_subagent
