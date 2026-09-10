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


class DocsRoot(BaseModel, frozen=True):
    """Where one half's page modules live: the directory, and the import root.

    Both, because a page is named twice and neither naming is spare. The
    directory is what a generated banner points a reader at; the dotted package
    is what the coverage sweep matches a claim against, beside the prompts that
    carry their own ``__name__``. A root holding one of them would leave the
    other to be reconstructed by string surgery over a path, which is a parser
    nobody wrote.
    """

    path: str
    package: str


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

    def docs(self) -> DocsRoot:
        """Where this application's own page modules live, both ways round.

        A page names its directory for the reader a banner sends there and its
        package for the sweep that asks which module claims it. Assembling both
        is the layout's business rather than each declaring module's, because
        the layout is the one value that knows the name they are built from.
        """
        return DocsRoot(
            path=self.path("harness", "content", "docs"),
            package=f"{self.package}.harness.content.docs",
        )

    def directory(self, *members: str) -> str:
        """One directory inside the application, trailing separator included.

        Spelled here rather than left to each caller because prose naming a
        directory says so with the separator, and a caller appending it to
        :meth:`path` is a caller reassembling a path the value already knows
        how to give it.
        """
        return f"{self.path(*members)}/"
