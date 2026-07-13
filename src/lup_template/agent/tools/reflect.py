"""Reflection tool — forced self-assessment before output finalization.

This is a TEMPLATE. Customize the input model and reviewer prompt
for your domain.

Pattern: A tool the agent calls to record its self-assessment before
producing final output. A :class:`~lup.reflect.ReviewGate` enforces
this — submit_output (or sleep, in persistent mode) is rejected until
the reviewer passes: approve and warn open the gate, fail keeps it
closed so the agent revises and reviews again, and after 3 consecutive
fails the gate opens anyway (escape hatch).

Runs a reviewer sub-agent (an independent one-shot query) that
critiques the main agent's reasoning with sandboxed file access to
past outputs (Read/Glob/Grep) and WebFetch for known URLs, returning a
structured :class:`~lup.reflect.ReviewResult` verdict. Skipping the
reviewer, or a reviewer failure, records an approval — availability
must not deadlock the session.

Usage in core.py:
    1. Call ``create_reflect_tools(session_dir=..., outputs_dir=...)``
    2. Register the tools as an MCP server
    3. Wire ``create_reflection_gate(gate=kit["gate"], ...)`` into hooks

Tool naming convention:
    After registration: ``mcp__{server_name}__review``
    Example: ``mcp__notes__review``
"""

import json
import logging
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, Field

from lup.adapters.wiring import query
from lup.adapters.tools.names import GLOB, GREP, READ, WEB_FETCH
from lup.mcp import LupMcpTool, lup_tool
from lup.reflect import ReviewGate, ReviewResult, ReviewVerdict
from lup_template.agent.config import (
    compat_api_key,
    compat_base_url,
    engine_for_settings,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TEMPLATE: reviewer system prompt — target your domain's failure modes
# ---------------------------------------------------------------------------

REVIEWER_SYSTEM_PROMPT = """\
You review the main agent's output before it is finalized. Your job is \
to catch errors in reasoning, gaps in research, and miscalibrated confidence.

## What to flag

**Overconfidence:**
- Conclusions not supported by the evidence gathered
- Important counterarguments or alternative explanations ignored
- Small sample size or weak sources treated as definitive

**Underconfidence:**
- Strong evidence hedged unnecessarily
- Clear patterns dismissed as uncertain
- Excessive caveats when the data is consistent

**Research gaps:**
- Evidence from a single source or angle when multiple exist
- Obvious avenues not explored (check the trace)
- Key data sources overlooked for this domain

**Logic errors:**
- Contradictions between stated reasoning and conclusions
- Factors pulling in opposite directions without resolution
- Missing steps in the argument chain

If you don't find real issues, say so briefly and stop. Don't fabricate \
concerns to appear thorough.

## Verdict

Alongside your critique, return a verdict:

- **fail** — a concrete error that would change the output: a conclusion \
the evidence does not support, a contradiction in the argument chain, or \
fabricated evidence. A fail sends the agent back to revise and re-review.
- **warn** — real but non-blocking issues; the conclusion stands.
- **approve** — no errors found, or only trivial issues.

Do not fail for style, or for concerns you cannot ground in the material.

## Historical data

You have Read, Glob, and Grep access to past outputs at:

  {outputs_dir}/

Use these to check calibration patterns: how accurate were past outputs \
in similar situations?

## Format

Your final response is the structured verdict + assessment. Be direct \
and specific in the assessment — cite the exact claim, factor, or \
number you're questioning.
"""


# ---------------------------------------------------------------------------
# TEMPLATE: reflection input — add your domain's self-assessment fields
# ---------------------------------------------------------------------------


class ReflectInput(BaseModel):
    """Input for the reflection tool. Customize fields for your domain.

    Add domain-specific fields here (e.g., factors with logits for
    forecasting, move evaluation for game playing).
    """

    assessment: str = Field(
        description=(
            "Freeform narrative assessment of the work so far. "
            "Structure however feels natural for this particular task."
        ),
    )
    confidence: float = Field(
        description="Your confidence in the current output (0.0-1.0).",
    )
    key_uncertainties: str | None = Field(
        default=None,
        description="What you're most uncertain about and what would change your mind.",
    )
    tool_audit: str = Field(
        description=(
            "Which tools provided useful information, which returned "
            "empty results, and which had actual failures."
        ),
    )
    process_reflection: str = Field(
        description=(
            "How did the system feel to use — not what you did, but how the "
            "scaffolding supported you. What felt rigid or lacking, what felt "
            "smooth? Where did you hit friction — a tool returning unhelpful "
            "output, a forced workaround, a missing capability?"
        ),
    )
    skip_reviewer: bool = Field(
        default=False,
        description=(
            "Skip the reviewer sub-agent and record an approval "
            "(e.g., for speed or when trivial)."
        ),
    )


class ReviewOutput(BaseModel):
    """Output from the reflection tool."""

    status: str = Field(
        description="'reviewed' when the gate opened, 'revise' on a fail verdict"
    )
    assessment_saved: str = Field(description="Path where assessment was saved")
    process_reflection: str = Field(description="Agent's process reflection")
    tool_audit: str = Field(description="Agent's tool usage audit")
    reviewer_verdict: str = Field(
        description="Reviewer verdict: approve, warn, or fail (approve when skipped)"
    )
    gate_open: bool = Field(
        description=(
            "Whether output is now unblocked; if False, address the "
            "critique and call review again"
        )
    )
    reviewer_critique: str = Field(description="Reviewer critique or skip reason")


# ---------------------------------------------------------------------------
# Reviewer sub-agent
# ---------------------------------------------------------------------------


REVIEWER_TOOLS: list[str] = [READ, GLOB, GREP, WEB_FETCH]
"""What the reviewer may call: file tools over past outputs (Read/Glob/Grep)
plus WebFetch for known URLs. The reviewer reads and verifies; it does not act."""

REVIEWER_THINKING_BUDGET = 8000
"""Thinking-token budget for the reviewer's critique — enough to weigh the
evidence without matching the main agent's full budget."""

REVIEWER_MAX_TURNS = 5
"""Turn cap for the reviewer: a bounded read-and-critique pass, not an
open-ended investigation."""


async def run_reviewer(
    validated: ReflectInput,
    outputs_dir: Path | None,
    *,
    model: str = "claude-opus-4-6",
) -> ReviewResult | None:
    """Run the reviewer sub-agent and return its structured verdict.

    The tool never inspects the backend: it asks for the full reviewer setup —
    file tools over past outputs, a thinking budget, a turn cap — and ``query``
    keeps what the chosen backend can honor, dropping the rest with a log line.
    The engine and endpoint come from the same settings helpers the session
    uses (``engine_for_settings``/``compat_base_url``), and the template wires
    ``reviewer_model=aux_model()`` (config.py), so the reviewer follows the
    session's backend — including OpenRouter routing — without Anthropic
    credentials on ``AGENT_SDK=codex``/``openai``. Where the backend cannot
    honor structured output, the text critique is wrapped as an approve
    verdict — degraded review must not block the session.

    Args:
        validated: The reflection input from the main agent.
        outputs_dir: Path to past outputs for historical calibration.
        model: Model to use for the reviewer (default: claude-opus-4-6).
    """
    prompt_sections = [
        "## Agent Assessment\n\n" + validated.assessment,
        f"## Confidence: {validated.confidence:.0%}",
    ]
    if validated.key_uncertainties:
        prompt_sections.append("## Key Uncertainties\n\n" + validated.key_uncertainties)

    reviewer_prompt = "\n\n".join(prompt_sections)

    response = await query(
        reviewer_prompt,
        prefix="  ↳ [reviewer] ",
        model=model,
        engine=engine_for_settings(),
        base_url=compat_base_url(),
        api_key=compat_api_key(),
        system_prompt=REVIEWER_SYSTEM_PROMPT.format(outputs_dir=outputs_dir or "N/A"),
        output_type=ReviewResult,
        max_thinking_tokens=REVIEWER_THINKING_BUDGET,
        permission_mode="bypassPermissions",
        tools=REVIEWER_TOOLS,
        max_turns=REVIEWER_MAX_TURNS,
    )

    result = response.output(ReviewResult)
    if result is not None:
        return result
    if response.text:
        return ReviewResult(verdict=ReviewVerdict.approve, assessment=response.text)
    return None


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


class ReflectToolKit(TypedDict):
    """Return type for :func:`create_reflect_tools`."""

    tools: list[LupMcpTool]
    gate: ReviewGate


def create_reflect_tools(
    *,
    session_dir: Path,
    outputs_dir: Path | None = None,
    gate: ReviewGate | None = None,
    reviewer_model: str = "claude-opus-4-6",
) -> ReflectToolKit:
    """Create the reflection tool(s) and their gate state.

    Returns both the tools (for MCP server registration) and the
    gate (for wiring into :func:`~lup.reflect.create_reflection_gate`).

    Args:
        session_dir: Where to save the review output (JSON).
        outputs_dir: Path to past outputs for the reviewer to Read.
            If None, the reviewer won't have historical data access.
        gate: External gate instance to use. Creates a new one if None.
        reviewer_model: Model for the reviewer sub-agent. The template
            passes ``aux_model()`` so the reviewer follows the backend.
    """
    gate = gate or ReviewGate()

    @lup_tool(
        "Structured self-review before finalizing output. Call this tool "
        "after completing your research and analysis but before producing "
        "your final structured output. Runs an independent reviewer that "
        "critiques your reasoning and returns a verdict: approve or warn "
        "opens the output gate; fail means address the critique and call "
        "review again (after 3 consecutive fails the gate opens anyway). "
        "You must get a passing review before submitting output."
    )
    async def review(validated: ReflectInput) -> ReviewOutput:
        # Save the review input
        session_dir.mkdir(parents=True, exist_ok=True)
        review_path = session_dir / "review.json"
        review_path.write_text(
            json.dumps(validated.model_dump(), indent=2), encoding="utf-8"
        )

        result = ReviewResult(
            verdict=ReviewVerdict.approve, assessment="(reviewer skipped)"
        )
        if not validated.skip_reviewer:
            try:
                result = await run_reviewer(
                    validated, outputs_dir, model=reviewer_model
                ) or ReviewResult(
                    verdict=ReviewVerdict.approve,
                    assessment="(reviewer unavailable — see logs)",
                )
            except (RuntimeError, OSError, TimeoutError, ValueError):
                logger.exception("Reviewer sub-agent failed")
                result = ReviewResult(
                    verdict=ReviewVerdict.approve,
                    assessment="(reviewer error — see logs)",
                )

        gate.record(result)

        return ReviewOutput(
            status="reviewed" if gate.reflected else "revise",
            assessment_saved=str(review_path),
            process_reflection=validated.process_reflection,
            tool_audit=validated.tool_audit,
            reviewer_verdict=result.verdict.value,
            gate_open=gate.reflected,
            reviewer_critique=result.assessment,
        )

    return ReflectToolKit(tools=[review], gate=gate)
