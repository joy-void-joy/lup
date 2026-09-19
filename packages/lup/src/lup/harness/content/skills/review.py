"""Canonical declaration for the review skill.

A trace is reviewed against what the session had available, and what the
library can promise every project has is the harness: the always-loaded
guidance, the plugin's roster, the tool groups it declares, and the policy
that judged the session's calls. A project whose sessions run an agent of its
own has more — a system prompt, a toolset registry, a tool policy — and adds
those sources by declaring this skill under its id with that step written for
its own layout, which is what the scaffold does.
"""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def skill(layout: ApplicationLayout) -> models.Skill:
    """Review a trace against the harness the session actually ran under."""
    return models.Skill(
        id="skill.review",
        name="review",
        description="Review a session trace for workflow quality, tool usage, and improvement opportunities",
        arguments=[
            models.Argument(
                name="arguments",
                description="Optional arguments supplied with the skill invocation",
                required=False,
            ),
        ],
        tools=[
            "Read",
            "Grep",
            "Glob",
            "Bash(ls:*, wc:*, sort:*, tail:*, stat:*, uv run lup-devtools:*)",
            "Agent",
        ],
        argument_hint="[session ID, file path, or pasted trace]",
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "arguments": models.ArgumentsRef(),
                        "harness_content_guidance_py": models.code(
                            layout.path("harness", "content", "guidance.py")
                        ),
                        "harness_content_skills_directory": models.code(
                            layout.directory("harness", "content", "skills")
                        ),
                        "harness_catalog_py": models.code(
                            layout.path("harness", "catalog.py")
                        ),
                    },
                ),
            ],
        ),
    )
