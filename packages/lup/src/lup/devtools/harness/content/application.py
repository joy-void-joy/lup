"""Where a project's own code sits, for library prose that has to name it.

A skill that tells its reader to open the system prompt has to say where the
system prompt is, and that is one of the few facts about a repository the
library cannot know: initialization renames the package, so a path written
down here would name a directory that is gone. Every author who needed one
reached for ``src/lup_template/`` — the template's own package — which reads
correctly in exactly one repository and misdirects every project built on it.

The rename is not what makes this necessary. A project resolving ``lup`` from
the package index, from git, or from a linked checkout receives this library
as a distribution that no rename ever touches, so a literal baked in here
would misdirect that project forever, however it spells its own package.

Held as a value the composition root supplies rather than as a part the
renderer spells, because the axis is a project rather than a runtime: a
:class:`~lup.harness.models.NativePath` differs between Claude and Codex and
belongs to whichever adapter is rendering, while this differs between
repositories and is identical in every tree one of them generates. That is the
shape :class:`~lup.harness.codescan.common.RuleSelection` already has — declared once
by the project and handed down to the content that renders it.
"""

from pydantic import BaseModel, Field


class ApplicationLayout(BaseModel, frozen=True):
    """The import root a project publishes, and the paths that follow from it.

    One field, because one fact is all the library is missing: the rest of a
    path is this template's layout, which every project built on it inherits
    and which the library may therefore state.
    """

    package: str = Field(min_length=1)
    """The import root, as ``DevProject.package`` reports it."""

    def path(self, *members: str) -> str:
        """One file inside the application, as prose names it."""
        return "/".join(["src", self.package, *members])

    def directory(self, *members: str) -> str:
        """One directory inside the application, trailing separator included.

        Spelled here rather than left to each caller because prose naming a
        directory says so with the separator, and a caller appending it to
        :meth:`path` is a caller reassembling a path the value already knows
        how to give it.
        """
        return f"{self.path(*members)}/"
