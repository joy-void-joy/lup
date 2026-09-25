"""How to contribute to this repository, whichever component you land in."""

import lup.harness.content.conventions as conventions
import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def document(layout: ApplicationLayout) -> models.PromptDocument:
    """The contribution guide, naming this project's own half by its own name.

    Core's page, so every project has it, and four of the things it points at
    are other modules': the setup wizard its first fenced block runs, the git
    loop's skills that land and merge a branch, and the resolver that answers
    review notes. Each of those is a
    :class:`~lup.harness.models.WhereTaken`, so the guide never tells a reader
    to run a command or a skill their checkout does not have.
    """
    return models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "setup": models.WhereTaken(
                        module="setup",
                        parts=[
                            models.TextPart(
                                text="uv run lup-devtools setup                  "
                                "# interactive: keys, integrations\n"
                            )
                        ],
                    ),
                    "land_does_it": models.WhereTaken(
                        module="git-workflow",
                        parts=[
                            models.TextPart(text=", which is what `"),
                            models.SkillInvocation(plugin="lup", skill="land"),
                            models.TextPart(text="` does"),
                        ],
                    ),
                    "project_directory": models.code(layout.directory()),
                    "harness_content_directory": models.code(
                        layout.directory("harness", "content")
                    ),
                },
            ),
            *conventions.COMMIT_TYPES.parts,
            models.Passage(
                module=__name__,
                name="what-has-to-be-green",
                values={
                    "loop_skills": models.WhereTaken(
                        module="git-workflow",
                        parts=[
                            models.Passage(
                                module=__name__,
                                name="loop-skills",
                                values={
                                    "rebase_skill": models.SkillInvocation(
                                        plugin="lup", skill="rebase"
                                    ),
                                    "close_skill": models.SkillInvocation(
                                        plugin="lup", skill="close"
                                    ),
                                    "merge_skill": models.SkillInvocation(
                                        plugin="lup", skill="merge"
                                    ),
                                },
                            )
                        ],
                    ),
                    "resolve_pass": models.WhereTaken(
                        module="resolver",
                        parts=[
                            models.TextPart(text=" "),
                            models.SkillInvocation(plugin="lup", skill="resolve"),
                            models.TextPart(
                                text=" runs that pass;\n[resolver.md](resolver.md) "
                                "describes what it does."
                            ),
                        ],
                    ),
                },
            ),
        ],
    )
