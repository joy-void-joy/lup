"""Canonical declaration for the commit skill."""

import lup.harness.content.conventions as conventions
import lup.harness.models as models

SKILL = models.Skill(
    id="skill.commit",
    name="commit",
    description="Review all diffs and create atomic commits",
    tools=["Bash(uv run lup-devtools:*, git:*)", "Read", "Glob", "Grep"],
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(module=__name__),
            *conventions.COMMIT_TYPES.parts,
            models.Passage(module=__name__, name="examples"),
        ],
    ),
)
