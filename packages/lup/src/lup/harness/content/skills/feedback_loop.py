"""Canonical declaration for the feedback-loop skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.feedback-loop",
    name="feedback-loop",
    description="Full feedback loop \u2014 orchestrates status, investigation, analysis, reflection, and implementation",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=[
        "Bash(git:*, uv run lup-devtools:*, uv run lup:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "Agent",
        "WebSearch",
        "WebFetch",
        "AskUserQuestion",
        "Skill(lup:fb-status)",
        "Skill(lup:fb-investigate)",
        "Skill(lup:fb-analyze)",
        "Skill(lup:fb-reflect)",
        "Skill(lup:fb-implement)",
    ],
    argument_hint="[optional: paste a trace, reflection, or output for single-trace analysis]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "arguments": models.ArgumentsRef(),
                    "fb_investigate_skill": models.SkillInvocation(
                        plugin="lup", skill="fb-investigate"
                    ),
                    "fb_status_skill": models.SkillInvocation(
                        plugin="lup", skill="fb-status"
                    ),
                    "fb_analyze_skill": models.SkillInvocation(
                        plugin="lup", skill="fb-analyze"
                    ),
                    "fb_reflect_skill": models.SkillInvocation(
                        plugin="lup", skill="fb-reflect"
                    ),
                    "fb_implement_skill": models.SkillInvocation(
                        plugin="lup", skill="fb-implement"
                    ),
                },
            ),
        ],
    ),
)
