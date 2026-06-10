"""System prompts for the agent.

This is a TEMPLATE. Customize for your domain.

Key patterns:
1. Named sections composed at render time — add, remove, or reorder
2. Use {date} placeholder for current date
3. Tools self-document via their descriptions — listing them here
   creates a second source of truth that drifts as tools change
   (see Tool Design Philosophy in CLAUDE.md)
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any  # claude: ignore — SdkMcpTool's input type param

from claude_agent_sdk import SdkMcpTool


# ---------------------------------------------------------------------------
# Prompt sections — customize for your domain
# ---------------------------------------------------------------------------

INTRO = """\
You are an AI agent. Today's date is {date}."""

PURPOSE = """\
## Your Task

[Describe what the agent does]"""

OUTPUT_FORMAT = """\
## Output Format

Provide your output as structured JSON with:
- **summary**: Brief summary of your decision/output
- **factors**: Key factors that influenced your reasoning
- **confidence**: Your confidence level (0.0-1.0)"""

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
    OUTPUT_FORMAT,
    GUIDELINES,
]


def get_system_prompt(
    *,
    date: datetime | None = None,
    server_tools: dict[str, Sequence[SdkMcpTool[Any]]] | None = None,  # claude: ignore
    extra_sections: list[str] | None = None,
) -> str:
    """Generate the system prompt by composing sections.

    Args:
        date: Date to use as "today". If None, uses current date.
        server_tools: Tool definitions per server name to auto-generate
            tool docs, e.g. ``{"example": extract_sdk_tools(EXAMPLE_TOOLS)}``.
        extra_sections: Additional prompt sections appended after SECTIONS.

    Returns:
        The formatted system prompt.
    """
    effective_date = date or datetime.now()
    all_sections = list(SECTIONS)
    if extra_sections:
        all_sections.extend(extra_sections)

    prompt = "\n\n".join(all_sections)
    prompt = prompt.format(date=effective_date.strftime("%Y-%m-%d"))

    if server_tools:
        tool_docs = generate_tool_docs(server_tools)
        prompt += f"\n\n{tool_docs}"

    return prompt + "\n"


def generate_tool_docs(
    server_tools: dict[str, Sequence[SdkMcpTool[Any]]],  # claude: ignore
) -> str:
    """Generate tool documentation from MCP tool descriptions.

    Tool descriptions are the single source of truth for what each tool does,
    when to use it, and why it exists. This function passes them through
    untruncated — comprehensive descriptions are intentional.
    """
    lines = ["## Auto-Generated Tool Reference\n"]

    for server_name, tools in server_tools.items():
        if not tools:
            continue

        lines.append(f"### {server_name.title()}\n")

        for tool in tools:
            if tool.description:
                lines.append(f"- **{tool.name}**: {tool.description}")
            else:
                lines.append(f"- **{tool.name}**")

        lines.append("")

    return "\n".join(lines)
