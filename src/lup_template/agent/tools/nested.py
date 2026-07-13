"""Nested Agent pattern (template).

A nested agent is an MCP tool that, inside its handler, spins up an
*independent* SDK client via :func:`lup.adapters.wiring.query`, runs it to
completion, and folds the scalar result back into a structured tool response.

It differs from a **subagent** (defined upfront in ``get_subagent_specs`` and
sharing the main session and trace): a nested agent is created on demand and
keeps its context fully separate, so the main agent receives only the
conclusion, not the reasoning chain. The tool handler is the context boundary —
it post-processes ("augments") the nested agent's raw output into the response.

This is a TEMPLATE. Replace the example with the quick, context-separable work
your domain needs (generation, parsing, scoring, a second opinion), and add
``NESTED_TOOLS`` to a server group in ``toolsets.py`` to serve it. See
PATTERNS.md § Nested Agent Pattern. ``query`` disables session persistence,
and the settings helpers (``aux_model``/``engine_for_settings``) keep the
nested call on the session's backend, like the reviewer in ``reflect.py``.
"""

from pydantic import BaseModel, Field

from lup.adapters.wiring import query
from lup.mcp import lup_tool
from lup_template.agent.config import (
    aux_model,
    compat_api_key,
    compat_base_url,
    engine_for_settings,
)


class CritiqueInput(BaseModel):
    """Input for the nested critique tool."""

    draft: str = Field(description="The text to get an independent second opinion on")
    focus: str = Field(
        default="clarity and correctness",
        description="What the nested reviewer should weigh most heavily",
    )


class CritiqueOutput(BaseModel):
    """The nested agent's critique, folded into structured output by the tool."""

    critique: str = Field(
        description="The nested agent's assessment, bounded by the tool"
    )
    truncated: bool = Field(
        description="Whether the tool shortened the output — the tool owns this, "
        "not the nested agent"
    )


@lup_tool(
    "Get an independent second opinion on a draft from a nested agent. Use when "
    "the main agent wants a fresh critique without spending its own context on a "
    "full review pass: the nested agent reads the draft in isolation and returns "
    "only its assessment. Exists to keep review reasoning out of the main "
    "agent's context window. Returns {critique, truncated}."
)
async def critique(params: CritiqueInput) -> CritiqueOutput:
    """Run a nested reviewer and augment its raw text into the response."""

    response = await query(
        f"Critique the following draft, focusing on {params.focus}. "
        f"Be specific and concise.\n\n{params.draft}",
        model=aux_model(),
        engine=engine_for_settings(),
        base_url=compat_base_url(),
        api_key=compat_api_key(),
        max_turns=1,
    )
    text = response.text or ""
    limit = 2000
    # Augment: the tool, not the nested agent, bounds and shapes the output.
    return CritiqueOutput(critique=text[:limit], truncated=len(text) > limit)


NESTED_TOOLS = [critique]
"""Nested-agent tools — add to a server group in ``toolsets.py`` to serve them."""
