"""Canonical declaration for the install skill."""

import lup.harness.models as models
import lup_template.harness.content.provenance as provenance

from lup.devtools.roster import LIBRARY_SPECS
from lup.devtools.subapps import subapp_bullets, subapp_summary

INSTALLABLE = LIBRARY_SPECS
"""Every sub-app lup ships, whichever of them this checkout happens to serve.

This skill installs lup's scaffolding into somebody else's repository, so what
it lists is what is there to be ported. A target is not owed a narrower CLI
because the project installing from declined a module — and the sub-apps only
*this* project has are its domain's, which a target has no use for either way.
"""

SPELLING = provenance.Provenance(
    library_git="git -C <source>",
    project_devtools="uv run --directory <target> lup-devtools",
    library_checkout="<source>",
)
"""Both checkouts spelled out, because this skill stands in one and writes the other."""

SKILL = models.Skill(
    id="skill.install",
    name="install",
    description="Install lup plugin and scaffolding into a target repo",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "AskUserQuestion"],
    argument_hint="[target-repo] [--interactive]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "init_skill": models.SkillInvocation(plugin="lup", skill="init"),
                    "arguments": models.ArgumentsRef(),
                },
            ),
            *provenance.branch_probes(SPELLING),
            models.Passage(
                module=__name__,
                name="analyze-the-source",
                values={
                    "arguments": models.ArgumentsRef(),
                    "manifest_path": models.PluginPath(
                        plugin="lup", location="manifest", scope="every_tree"
                    ),
                    "hooks_path": models.PluginPath(
                        plugin="lup", location="hooks", scope="every_tree"
                    ),
                    "skills_path": models.PluginPath(
                        plugin="lup", location="skills", member="*", scope="every_tree"
                    ),
                    "agents_path": models.PluginPath(
                        plugin="lup", location="agents", member="*", scope="every_tree"
                    ),
                    "guidance_template_path": models.PluginPath(
                        plugin="lup", location="guidance_template", scope="every_tree"
                    ),
                },
            ),
            *provenance.acquisition(SPELLING),
            models.Passage(
                module=__name__,
                name="skill.install",
                values={
                    "subapp_bullets": models.TextPart(
                        text=subapp_bullets(INSTALLABLE, indent="  ")
                    ),
                    "project_settings": models.NativePath(
                        location="project_settings", scope="every_tree"
                    ),
                    "update_route": models.WhereShipped(
                        parts=[
                            models.TextPart(text=" — "),
                            models.SkillInvocation(plugin="lup", skill="update"),
                            models.TextPart(text=" walks them that way"),
                        ]
                    ),
                    "skill_pattern": models.SkillPattern(plugin="lup", placeholder="*"),
                    "root_plugin_path": models.PluginPath(
                        plugin="lup", location="root", scope="every_tree"
                    ),
                    "subapp_summary": models.TextPart(text=subapp_summary(INSTALLABLE)),
                    "ask_user": models.AskUser(
                        question="which harness trees the target should carry — one runtime's, "
                        "or every runtime it uses"
                    ),
                    "root_plugin_path_2": models.PluginPath(
                        plugin="lup", location="root", scope="every_tree"
                    ),
                    "manifest_plugin_path": models.PluginPath(
                        plugin="lup", location="manifest", scope="every_tree"
                    ),
                    "marketplace": models.NativePath(
                        location="marketplace", scope="every_tree"
                    ),
                    "project_settings_2": models.NativePath(
                        location="project_settings", scope="every_tree"
                    ),
                    "guidance_template_plugin_path": models.PluginPath(
                        plugin="lup", location="guidance_template", scope="every_tree"
                    ),
                    "guidance_file": models.NativePath(
                        location="guidance_file", scope="every_tree"
                    ),
                    "skill_pattern_2": models.SkillPattern(
                        plugin="lup", placeholder="*"
                    ),
                    "manifest_plugin_path_2": models.PluginPath(
                        plugin="lup", location="manifest", scope="every_tree"
                    ),
                    "hooks_plugin_path": models.PluginPath(
                        plugin="lup", location="hooks", scope="every_tree"
                    ),
                    "marketplace_2": models.NativePath(
                        location="marketplace", scope="every_tree"
                    ),
                    "skills_plugin_path": models.PluginPath(
                        plugin="lup", location="skills", scope="every_tree"
                    ),
                    "project_settings_3": models.NativePath(
                        location="project_settings", scope="every_tree"
                    ),
                    "guidance_file_2": models.NativePath(
                        location="guidance_file", scope="every_tree"
                    ),
                },
            ),
            *provenance.sync_baseline(SPELLING),
            models.Passage(
                module=__name__,
                name="seams",
                values={
                    # Suggestions, each holding only where the plugin being
                    # installed ships the skill it suggests.
                    "meta_step": models.WhereShipped(
                        parts=[
                            models.TextPart(text="\n   - Try `"),
                            models.SkillInvocation(plugin="lup", skill="meta"),
                            models.TextPart(
                                text="` to review the generated harness trees"
                            ),
                        ]
                    ),
                    "commit_step": models.WhereShipped(
                        parts=[
                            models.TextPart(text="\n   - Run `"),
                            models.SkillInvocation(plugin="lup", skill="commit"),
                            models.TextPart(text="` to test the commit workflow"),
                        ]
                    ),
                    "update_step": models.WhereShipped(
                        parts=[
                            models.TextPart(text="\n   - Consider `"),
                            models.SkillInvocation(plugin="lup", skill="update"),
                            models.TextPart(text="` later for ongoing sync"),
                        ]
                    ),
                },
            ),
        ],
    ),
)
