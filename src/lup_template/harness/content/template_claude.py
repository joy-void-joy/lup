"""Canonical downstream template guidance in its Claude flavor."""

import lup.harness.models as models
from lup_template.harness.content.template_sections import (
    CLAUDE_POLICY_SCOPE,
    CODEINTEL_TOOL_ROSTER,
    DIRECTORY_STRUCTURE_THROUGH_TOOLS,
    INNER_AGENT_BULLET,
    PATTERN_MENU_TAIL_THROUGH_WORKTREE_STEP,
    PRINCIPLES_THROUGH_PATTERN_MENU,
    SELF_IMPROVEMENT_THROUGH_END,
    SETUP_THROUGH_NAMING,
    TOOLING_INTRO,
    WORKFLOW_THROUGH_COMMIT_FORMAT,
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
        models.Passage(module=__name__, name="template_claude-2"),
        *INNER_AGENT_BULLET,
        models.Passage(module=__name__, name="template_claude-3"),
        *PRINCIPLES_THROUGH_PATTERN_MENU,
        models.Passage(module=__name__, name="template_claude-4"),
        *PATTERN_MENU_TAIL_THROUGH_WORKTREE_STEP,
        models.Passage(module=__name__, name="template_claude-5"),
        *WORKFLOW_THROUGH_COMMIT_FORMAT,
        models.Passage(module=__name__, name="template_claude-6"),
        *DIRECTORY_STRUCTURE_THROUGH_TOOLS,
        models.Passage(module=__name__, name="template_claude-7"),
        *CODEINTEL_TOOL_ROSTER,
        models.Passage(module=__name__, name="template_claude-8"),
        *TOOLING_INTRO,
        models.Passage(
            module=__name__,
            name="template_claude-9",
            values={
                "skill_pattern": models.SkillPattern(plugin="lup", placeholder="*"),
                "init_skill": models.SkillInvocation(plugin="lup", skill="init"),
                "install_skill": models.SkillInvocation(plugin="lup", skill="install"),
            },
        ),
        *permission_hooks(CLAUDE_POLICY_SCOPE),
        models.Passage(module=__name__, name="template_claude-10"),
        *SELF_IMPROVEMENT_THROUGH_END,
    ],
)
