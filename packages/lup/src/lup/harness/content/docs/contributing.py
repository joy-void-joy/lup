"""How to contribute to this repository, whichever component you land in."""

import lup.harness.content.conventions as conventions
import lup.harness.models as models
from lup.devtools.subapps import SubAppSpec
from lup.harness.content.application import ApplicationLayout


def document(
    layout: ApplicationLayout, subapps: list[SubAppSpec]
) -> models.PromptDocument:
    """The contribution guide, naming this project's own half by its own name.

    Takes the served sub-apps because its first fenced block instructs the
    setup wizard, whose module a project may decline: the line renders only
    where ``setup`` is among what the CLI serves, so the block never tells a
    reader to run a command their checkout does not have.
    """
    setup = (
        "uv run lup-devtools setup                  # interactive: keys, integrations\n"
        if any(spec.name == "setup" for spec in subapps)
        else ""
    )
    return models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "setup": models.TextPart(text=setup),
                    "project_directory": models.code(layout.directory()),
                    "harness_content_directory": models.code(
                        layout.directory("harness", "content")
                    ),
                },
            ),
            *conventions.COMMIT_TYPES.parts,
            models.Passage(
                module=__name__,
                name="contributing-2",
                values={
                    "rebase_skill": models.SkillInvocation(
                        plugin="lup", skill="rebase"
                    ),
                    "close_skill": models.SkillInvocation(plugin="lup", skill="close"),
                    "merge_skill": models.SkillInvocation(plugin="lup", skill="merge"),
                    "resolve_skill": models.SkillInvocation(
                        plugin="lup", skill="resolve"
                    ),
                },
            ),
        ],
    )
