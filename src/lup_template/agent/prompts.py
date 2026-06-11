"""System prompts for the agent.

This is a TEMPLATE. Customize for your domain.

Key patterns:
1. Named sections composed at render time — add, remove, or reorder
2. Use {date} placeholder in a section to get the current date; only the
   section declaring it is substituted, so literal braces (a JSON output
   example, say) in other sections are passed through verbatim
3. The output-format section is derived from the ``AgentOutput`` model, so
   customizing models.py keeps the prompt in sync — no hand-listed fields
4. Tools self-document via their descriptions — listing them here
   creates a second source of truth that drifts as tools change
   (see Tool Design Philosophy in CLAUDE.md)
"""

from datetime import datetime

from lup_template.agent.models import AgentOutput

# ---------------------------------------------------------------------------
# Prompt sections — customize for your domain
# ---------------------------------------------------------------------------

INTRO = """\
You are an AI agent. Today's date is {date}."""

PURPOSE = """\
## Your Task

[Describe what the agent does]"""


def output_format() -> str:
    """Render the output-format section from the ``AgentOutput`` schema.

    Fields and their descriptions come straight from the model, so adding
    or renaming a field in models.py updates the prompt automatically —
    avoiding the two-sources-of-truth drift CLAUDE.md warns against.
    """
    lines = [
        "## Output Format",
        "",
        "When your analysis is complete, submit your final result with the",
        "submit_output tool — the session's result is exactly what you submit",
        "there. Reflect with the review tool first; submission is rejected",
        "until you have. Your submission includes:",
    ]
    properties = AgentOutput.model_json_schema().get("properties", {})
    for name, schema in properties.items():
        description = schema.get("description", "")
        lines.append(f"- **{name}**: {description}" if description else f"- **{name}**")
    return "\n".join(lines)


GUIDELINES = """\
## Guidelines

1. Think step by step
2. Use your available tools to gather information before reasoning
3. Be explicit about uncertainty
4. Document your reasoning

[Add domain-specific guidelines here]"""


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

SECTIONS: list[str] = [
    INTRO,
    PURPOSE,
    output_format(),
    GUIDELINES,
]


def get_system_prompt(
    *,
    date: datetime | None = None,
    extra_sections: list[str] | None = None,
) -> str:
    """Generate the system prompt by composing sections.

    Only the section declaring the ``{date}`` placeholder is substituted,
    so customized sections may contain literal braces (e.g. a JSON example)
    without raising.

    Args:
        date: Date to use as "today". If None, uses current date.
        extra_sections: Additional prompt sections appended after SECTIONS.

    Returns:
        The formatted system prompt.
    """
    effective_date = (date or datetime.now()).strftime("%Y-%m-%d")
    rendered = [
        section.format(date=effective_date) if "{date}" in section else section
        for section in SECTIONS
    ]
    if extra_sections:
        rendered.extend(extra_sections)

    return "\n\n".join(rendered) + "\n"
