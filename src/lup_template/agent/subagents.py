"""Subagent definitions.

This is a TEMPLATE. Define subagents for specialized tasks in your domain.

Subagents are spawned by the main agent to perform focused work.
Each subagent has:
- A specialized prompt (focused on one job)
- A subset of tools (only what it needs)
- Its own model (cheaper models for simpler tasks)

Definitions use SubagentSpec (SDK-agnostic). Each backend interprets
the same spec list:

- Claude: converted to native ``AgentDefinition`` via
  :func:`~lup.adapters.claude.spec_to_claude`
- Codex/OpenAI: served as the ``run_subagent`` tool via
  :func:`~lup.subagents.create_run_subagent_tool`, which dispatches a
  one-shot query to the backend serving the spec's model
"""

from lup.types import SubagentSpec

# =============================================================================
# TOOL LISTS (customize for your domain)
# =============================================================================
#
# Use functions (not constants) so tool lists can be computed at runtime
# based on available API keys, session context, etc.
#
# Example with conditional inclusion:
#   def research_tools() -> list[str]:
#       from lup_template.agent.config import settings
#       tools = ["WebSearch", "WebFetch", "Read", "Glob"]
#       if settings.exa_api_key:
#           tools.append("mcp__search__search_exa")
#       return tools


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
# EXPORTED SUBAGENTS
# =============================================================================

ALL_SPECS: list[SubagentSpec] = [researcher, analyzer]


def get_subagent_specs() -> list[SubagentSpec]:
    """Return all subagent specs (SDK-agnostic).

    Each adapter converts these into its native primitive at build time.
    """
    return list(ALL_SPECS)
