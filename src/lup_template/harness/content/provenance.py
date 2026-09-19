"""What a project settles about where its lup came from.

Standing a project up on the template and installing the plugin into a
repository that already exists ask the same three questions — which branch of
the library the project builds on, how it obtains the distribution, and which
commit its upstream checkpoint records. The answers are the same answers, so
they are written once here and composed by both skills. Two skills restating
them is a pair that drifts, and for these the drift is not hypothetical: the
repository mode is the only mode that resolves while nothing is published, so
a copy that omits it leaves an agent to discover the constraint by failing.

Only the checkouts differ. Installing runs in the library's checkout and writes
to a different repository, so it spells both; initializing runs in the checkout
it is turning into a project, where the two are one directory and naming it
would be noise. That difference is a :class:`Provenance`, and it is the whole
of what a caller supplies.

Everything that is not this question stays with the skill that asks it.
Installing reads a repository it did not write and must leave its own checkout
untouched; initializing knows its checkout is a fresh template clone, renames
the package before anything is allowed to un-vendor it, and interviews a
domain. Framing sentences stay with their skill too, placed before the shared
block rather than folded into it: an addition cannot drift from what it adds
to, while a restatement can.
"""

from pydantic import BaseModel

import lup.harness.models as models

from lup.formats.markdown import contained


class Provenance(BaseModel, frozen=True):
    """How one skill spells the checkouts a provenance answer is about."""

    library_git: str
    """Git run against the checkout the library comes from."""

    project_devtools: str
    """The devtools CLI run against the repository being written to."""

    library_checkout: str
    """That library checkout, as ``sync setup`` is handed it."""


def branch_probes(spelling: Provenance) -> list[models.PromptPart]:
    """The two refs that settle which library this is, and the ask between them."""
    return [
        models.Passage(
            module=__name__,
            values={
                "ask": models.AskUser(
                    question="whether to proceed from the checkout's current branch, which carries work the stable branch has not reviewed, or from the stable branch instead"
                ),
                "library_git": models.plain(spelling.library_git),
            },
        ),
    ]


def acquisition(spelling: Provenance) -> list[models.PromptPart]:
    """The look-up that settles which mode the project resolves ``lup`` through."""
    # A row is split on `|` before its cells are parsed, so the one value that
    # flows into this table is contained where it lands in one. The fence and
    # the prose below take it as it reads: nothing there ends a row.
    celled = contained(spelling.project_devtools)
    return [
        models.Passage(
            module=__name__,
            name="library-as-a-package",
            values={
                "project_devtools": models.plain(spelling.project_devtools),
                "celled": models.plain(celled),
                "library_git": models.plain(spelling.library_git),
            },
        ),
    ]


def sync_baseline(spelling: Provenance) -> list[models.PromptPart]:
    """Where the upstream checkpoint is taken, and why the short way misses it."""
    return [
        models.Passage(
            module=__name__,
            name="upstream-checkpoint",
            values={
                "update_skill": models.SkillInvocation(plugin="lup", skill="update"),
                "project_devtools": models.plain(spelling.project_devtools),
                "library_checkout": models.plain(spelling.library_checkout),
            },
        ),
    ]
