"""Spec-driven subagent delegation tool.

Engines with native subagents run them directly (from a
``SubagentSpec``). Engines without get this served MCP tool instead: the
agent calls ``run_subagent(name, task)`` and the tool dispatches a
one-shot client to the engine that serves the spec's model. The same
spec list drives both paths, so the available roles never diverge
between engines.

A spec may pin knobs (tools, a turn cap) that a one-shot delegation on
the target model's engine cannot honor. Rather than name which engines
those are, the tool builds the client with ``on_unsupported="raise"`` and
surfaces the engine's own refusal, so it fails loudly instead of silently
dropping the knobs.
"""

import logging

from pydantic import BaseModel, Field

from lup.adapters.errors import UnsupportedOptionsError
from lup.adapters.wiring import create_client
from lup.mcp import LupMcpTool, ToolError, lup_tool
from lup.types import SubagentSpec

logger = logging.getLogger(__name__)


class RunSubagentInput(BaseModel):
    """Input for the run_subagent tool."""

    name: str = Field(description="Name of the subagent role to run")
    task: str = Field(description="The task or question for the subagent")


class RunSubagentOutput(BaseModel):
    """Result returned from a delegated subagent run."""

    subagent: str = Field(description="Name of the subagent that ran")
    result: str = Field(description="The subagent's final text output")


def create_run_subagent_tool(
    specs: list[SubagentSpec],
    *,
    default_model: str,
) -> LupMcpTool:
    """Create the run_subagent tool from the shared spec list.

    Args:
        specs: SDK-agnostic subagent definitions (the same list an
            engine with native subagents converts to its own primitive).
        default_model: Resolves specs that pin no model
            (``SubagentSpec.model is None`` means "inherit the session's
            model"); the caller supplies it so this module reads no
            application config.

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
        spec = by_name.get(validated.name)  # lup: ignore[dict-get] — role registry
        if spec is None:
            raise ToolError(
                f"Unknown subagent {validated.name!r}. Available: {sorted(by_name)}"
            )

        model = spec.model or default_model
        try:
            client = create_client(
                model=model,
                system_prompt=spec.prompt,
                tools=spec.tools or None,
                max_turns=spec.max_turns,
                on_unsupported="raise",
            )
        except UnsupportedOptionsError as exc:
            fields = ", ".join(exc.fields)
            raise ToolError(
                f"Subagent {spec.name!r} sets fields ({fields}) that a one-shot "
                f"delegation on the engine for model {model!r} cannot honor. "
                "Give the spec a model whose engine supports them, or drop "
                "these fields."
            ) from exc

        logger.info("Delegating to subagent %r (model=%s)", spec.name, model)
        response = await client.query(validated.task)
        return RunSubagentOutput(subagent=spec.name, result=response.text or "")

    return run_subagent
