"""Subagent definitions.

This is a TEMPLATE. Define subagents for specialized tasks in your domain.

Subagents are spawned by the main agent to perform focused work.
Each subagent has:
- A specialized prompt (focused on one job)
- A subset of tools (only what it needs)
- Its own model (cheaper models for simpler tasks)

Definitions use SubagentSpec (SDK-agnostic). Each adapter converts
these into its native subagent primitive at build time.
"""

from typing import Literal, cast

from claude_agent_sdk import AgentDefinition

from lup.lib.types import SubagentSpec

# =============================================================================
# TOOL LISTS (customize for your domain)
# =============================================================================


def research_tools() -> list[str]:
    """Tools for research subagents."""
    return [
        "WebSearch",
        "WebFetch",
        "Read",
        "Glob",
    ]


def analysis_tools() -> list[str]:
    """Tools for analysis subagents."""
    return [
        "Read",
        "Glob",
    ]


# =============================================================================
# SUBAGENT DEFINITIONS (customize for your domain)
# =============================================================================


RESEARCHER_PROMPT = """\
You are a research assistant gathering information on a topic.

## Your Task
Research the topic/question given to you. Your output should be thorough and factual.

## Approach
1. Search for relevant information
2. Verify facts across multiple sources
3. Note any uncertainties or contradictions
4. Organize findings clearly

## Output Format (JSON)
```json
{
  "key_facts": ["Fact 1 with source", "Fact 2 with source"],
  "uncertainties": ["What we don't know"],
  "sources": [{"title": "...", "url": "..."}],
  "summary": "Brief synthesis of findings"
}
```
"""

researcher = SubagentSpec(
    name="researcher",
    description=(
        "Research agent for gathering information. Searches multiple sources, "
        "verifies facts, and returns organized findings."
    ),
    prompt=RESEARCHER_PROMPT,
    tools=research_tools(),
    model="haiku",
)


ANALYZER_PROMPT = """\
You are an analysis assistant examining data or content.

## Your Task
Analyze the given data/content and extract insights.

## Approach
1. Understand what you're analyzing
2. Identify patterns and anomalies
3. Draw conclusions
4. Note confidence levels

## Output Format (JSON)
```json
{
  "insights": ["Insight 1", "Insight 2"],
  "patterns": ["Pattern observed"],
  "anomalies": ["Unusual finding"],
  "confidence": 0.8,
  "summary": "Brief analysis summary"
}
```
"""

analyzer = SubagentSpec(
    name="analyzer",
    description=(
        "Analysis agent for examining data and extracting insights. "
        "Identifies patterns, anomalies, and draws conclusions."
    ),
    prompt=ANALYZER_PROMPT,
    tools=analysis_tools(),
    model="haiku",
)


# =============================================================================
# ADAPTER CONVERSIONS
# =============================================================================


CLAUDE_MODEL_LITERALS = {"sonnet", "opus", "haiku", "inherit"}

type ClaudeModelLiteral = Literal["sonnet", "opus", "haiku", "inherit"]


def spec_to_claude(spec: SubagentSpec) -> AgentDefinition:
    """Convert a SubagentSpec to a Claude AgentDefinition."""
    model: ClaudeModelLiteral | None = None
    if spec.model in CLAUDE_MODEL_LITERALS:
        model = cast(ClaudeModelLiteral, spec.model)

    return AgentDefinition(
        description=spec.description,
        prompt=spec.prompt,
        tools=spec.tools,
        model=model,
    )


# =============================================================================
# EXPORTED SUBAGENTS
# =============================================================================

ALL_SPECS: list[SubagentSpec] = [researcher, analyzer]


def get_subagents() -> dict[str, AgentDefinition]:
    """Build Claude AgentDefinitions at runtime.

    Using a factory function (not a module constant) allows:
    - Tool lists computed from current settings/API keys
    - Context-dependent subagent configuration
    - Runtime reconfiguration between sessions
    """
    return {spec.name: spec_to_claude(spec) for spec in ALL_SPECS}


def get_subagent_specs() -> list[SubagentSpec]:
    """Return all subagent specs (SDK-agnostic)."""
    return list(ALL_SPECS)
