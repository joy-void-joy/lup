"""Canonical downstream template guidance in its Codex AGENTS.md flavor."""

import lup.harness.models as models
from lup_template.harness.content.template_sections import (
    CODEX_POLICY_SCOPE,
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
        models.Passage(module=__name__, name="template_codex-2"),
        *INNER_AGENT_BULLET,
        models.Passage(module=__name__, name="template_codex-3"),
        *PRINCIPLES_THROUGH_PATTERN_MENU,
        *PATTERN_MENU_TAIL_THROUGH_WORKTREE_STEP,
        models.Passage(module=__name__, name="template_codex-4"),
        *WORKFLOW_THROUGH_COMMIT_FORMAT,
        models.Passage(module=__name__, name="template_codex-5"),
        *DIRECTORY_STRUCTURE_THROUGH_TOOLS,
        models.Passage(module=__name__, name="template_codex-6"),
        *CODEINTEL_TOOL_ROSTER,
        models.Passage(module=__name__, name="template_codex-7"),
        *TOOLING_INTRO,
        models.Passage(
            module=__name__,
            name="template_codex-8",
            values={
                "skill_pattern": models.SkillPattern(plugin="lup", placeholder="*"),
                "init_skill": models.SkillInvocation(plugin="lup", skill="init"),
                "install_skill": models.SkillInvocation(plugin="lup", skill="install"),
            },
        ),
        *permission_hooks(CODEX_POLICY_SCOPE),
        models.Passage(module=__name__, name="template_codex-9"),
        *SELF_IMPROVEMENT_THROUGH_END,
    ],
)
