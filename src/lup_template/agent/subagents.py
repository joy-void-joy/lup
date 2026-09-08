# lup: ignore[constant-declaration]
# The prompts here are each subagent's own standing prose and the roster is
# which subagents this application declares — both are what this module is for,
# and a project wanting others writes them here.
"""Subagent definitions.

This is a TEMPLATE. Define subagents for specialized tasks in your domain.

Subagents are spawned by the main agent to perform focused work.
Each subagent has:
- A specialized prompt (focused on one job)
- Runtime capabilities and optional exact tool grants
- A portable model tier, resolved by the selected provider

Definitions use ``SubagentSpec`` as portable data. The application injects a
typed factory recipe into :func:`lup.orchestration.subagents.create_run_subagent_tool`; the
tool then performs a one-shot query without selecting a provider itself.

A spec without a ``model`` inherits the session's main model. These roles
request the strongest tier; each adapter supplies its native model.
Capabilities express runtime facilities; exact ``tools`` grants retain
Lup's canonical vocabulary and must never be widened by an adapter.

Subagents are one of several agent shapes — ``docs/orchestration.md`` is
the full catalog. Where the siblings live:

- Nested agents: a one-shot :meth:`lup.sessions.client.Client.query` inside a
  tool handler; the reviewer in ``agent/tools/reflect.py`` is the
  exemplar
- Background agents: :class:`lup.orchestration.background.BackgroundAgent`, with
  the observer example in ``agent/tools/realtime.py``
- Persistent agents: ``lup.orchestration.realtime.scheduler`` and ``lup.orchestration.realtime.relay``,
  with example tools in ``agent/tools/realtime.py``
- Data augmentation: ``agent/tools/example.py`` (domain dispatch,
  null-filling, extraction)
"""

from lup.types import SubagentSpec

# =============================================================================
# lup: template: capabilities — grant each subagent only the facilities its job needs
# =============================================================================


# =============================================================================
# lup: template: subagent definitions — replace researcher/analyzer with your
# domain's specialists (each spec: prompt, capabilities, exact grants, model tier)
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
    capabilities=["workspace-read", "web-search"],
    model="strongest",
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
    capabilities=["workspace-read"],
    model="strongest",
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
