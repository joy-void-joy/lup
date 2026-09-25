"""Committing, rebasing, merging, and landing a branch.

The subject is the change loop rather than the change: what a commit message
has to say, how a conflict is resolved without losing a side, and what has to
be green before a branch lands. A project whose history is somebody else's to
write declines this and keeps everything else.

It is the module most reached into. The resolver names ``skill.merge`` from
here, which is why the resolver declares it in ``requires`` — the reference
resolves either way, but an operator who declined this is owed the answer in
the vocabulary they decided in. Everything else pointing here points through a
:class:`~lup.harness.models.WhereTaken`, so a project without the loop reads no
sentence sending it to a skill it does not have.

What it does not hold is the git machinery those skills drive. Worktrees, the
merge driver, the hook installer and the conflict walks are the `git` command
tree, which core's gate reads and every session's workflow starts from — so it
is core's, and a project declining the loop keeps it, along with the pages
saying how to get set up and which check catches what before a branch lands.
"""

import lup.harness.content.conventions as conventions
from lup.harness.content.modules.specs import GIT_WORKFLOW
from lup.harness.content.skills.close import SKILL as SKILL_CLOSE
from lup.harness.content.skills.commit import SKILL as SKILL_COMMIT
from lup.harness.content.skills.land import SKILL as SKILL_LAND
from lup.harness.content.skills.merge import SKILL as SKILL_MERGE
from lup.harness.content.skills.rebase import SKILL as SKILL_REBASE
from lup.harness.models import ContentRoster
from lup.harness.modules import Module


def module() -> Module:
    """The git loop as one value.

    Nothing here needs the project's layout: every skill is a constant, none
    of their prose naming a path inside the reading project's package.
    """
    return Module(
        spec=GIT_WORKFLOW,
        content=ContentRoster(
            skills=[
                SKILL_CLOSE,
                SKILL_COMMIT,
                SKILL_LAND,
                SKILL_MERGE,
                SKILL_REBASE,
            ]
        ),
        guidance=[
            conventions.MERGE_CONFLICT_RESOLUTION,
            conventions.COMMIT_GUIDELINES,
        ],
    )
