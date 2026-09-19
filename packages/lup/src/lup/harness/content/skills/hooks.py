"""Canonical declaration for the hooks skill."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def skill(layout: ApplicationLayout) -> models.Skill:
    """Edit the policy, naming the catalog this project keeps its HookSet in."""
    return models.Skill(
        id="skill.hooks",
        name="hooks",
        description="Inspect and modify the canonical semantic permission policy",
        arguments=[
            models.Argument(
                name="arguments",
                description="Optional arguments supplied with the skill invocation",
                required=False,
            ),
        ],
        tools=["Read", "Edit", "Grep", "Glob", "AskUserQuestion", "Bash"],
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "arguments": models.ArgumentsRef(),
                        "hooks_path": models.PluginPath(
                            plugin="lup", location="hooks", scope="every_tree"
                        ),
                        "approval": models.RequestApproval(
                            action="changing policy behavior",
                            reason="a policy change alters what every later session may do",
                        ),
                        "command": models.CommandInvocation(
                            path=["dev", "hooks", "sweep"], arguments="<file>"
                        ),
                        "harness_catalog_py": models.code(
                            layout.path("harness", "catalog.py")
                        ),
                    },
                ),
            ],
        ),
    )
