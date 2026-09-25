"""How a skill outside the git loop points at the commit skill.

Several skills commit before or after their own work, and the skill that
writes a commit well is git-workflow's. A project that declined the loop still
commits — by hand, the way it always does — so the step stays and only the
pointer goes: each of these renders as ``, with `/lup:commit``` where the loop
is taken and as nothing where it is not, after a sentence that reads whole
either way.
"""

import lup.harness.models as models


def with_commit_skill() -> models.WhereTaken:
    """``, with `/lup:commit``` where git-workflow is taken, and nothing elsewhere."""
    return models.WhereTaken(
        module="git-workflow",
        parts=[
            models.TextPart(text=", with `"),
            models.SkillInvocation(plugin="lup", skill="commit"),
            models.TextPart(text="`"),
        ],
    )
