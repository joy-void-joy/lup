"""Canonical downstream template guidance in its Claude flavor."""

import lup.harness.models as models
from lup_template.harness.content.template_sections import (
    CLAUDE_POLICY_SCOPE,
    CODEINTEL_TOOL_ROSTER,
    DIRECTORY_STRUCTURE_THROUGH_TOOLS,
    INNER_AGENT_BULLET,
    PATTERN_MENU_TAIL_THROUGH_WORKFLOW_HEADING,
    PRINCIPLES_THROUGH_PATTERN_MENU,
    SELF_IMPROVEMENT_THROUGH_END,
    SETUP_THROUGH_NAMING,
    TOOLING_INTRO,
    git_workflow,
    permission_hooks,
)

DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.Passage(
            module=__name__,
            values={
                "init_skill": models.SkillInvocation(plugin="lup", skill="init"),
                "install_skill": models.SkillInvocation(plugin="lup", skill="install"),
            },
        ),
        *SETUP_THROUGH_NAMING,
        models.Passage(module=__name__, name="agent-vocabulary"),
        *INNER_AGENT_BULLET,
        models.Passage(module=__name__, name="naming"),
        *PRINCIPLES_THROUGH_PATTERN_MENU,
        models.Passage(module=__name__, name="orchestration-pointer"),
        *PATTERN_MENU_TAIL_THROUGH_WORKFLOW_HEADING,
        git_workflow(models.Passage(module=__name__, name="regeneration-pointer")),
        models.Passage(module=__name__, name="editing-style"),
        *DIRECTORY_STRUCTURE_THROUGH_TOOLS,
        models.Passage(module=__name__, name="diagnostics"),
        *CODEINTEL_TOOL_ROSTER,
        models.Passage(module=__name__, name="relative-paths"),
        *TOOLING_INTRO,
        models.Passage(
            module=__name__,
            name="launching",
            values={
                "skill_pattern": models.SkillPattern(plugin="lup", placeholder="*"),
                "init_skill": models.SkillInvocation(plugin="lup", skill="init"),
                "install_skill": models.SkillInvocation(plugin="lup", skill="install"),
                # The launcher's own tree curates profiles in every composition;
                # the setup wizard's is a second door where it is served.
                "profile_commands": models.WhereShipped(
                    parts=[
                        models.TextPart(
                            text=" either\n`lup-devtools harness profile` or "
                            "`lup-devtools setup profile` — the same\nroster "
                            "through both"
                        )
                    ],
                    commands=["setup"],
                    otherwise=[
                        models.TextPart(text="\n`lup-devtools harness profile`")
                    ],
                ),
            },
        ),
        *permission_hooks(CLAUDE_POLICY_SCOPE),
        models.Passage(module=__name__, name="settings"),
        *SELF_IMPROVEMENT_THROUGH_END,
    ],
)
