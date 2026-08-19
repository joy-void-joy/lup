"""A changelog file, as the versions it records rather than as its text.

Two readings of one document meet here. A release is *written* from a model —
a version, a date, a summary, and the details under it — so what a bump
records is decided by fields rather than by whatever a caller managed to
spell. Every release already in the file is *carried*, as the lines it
already occupies, because a changelog holds whatever its authors wrote and a
section rewritten through a model would come back as only the parts the model
has fields for.

Section boundaries come from a markdown parser rather than from scanning for
``## ``. A changelog entry may quote a fenced block, and a line inside one is
not a heading — a scanner would split the document there and write the next
release into the middle of somebody's example.

Neither half of a heading is judged here: ``parse_semver`` decides what counts
as a version and ``date.fromisoformat`` decides what counts as a date, so the
only thing this module does to the line is find where one ends and the other
begins.
"""

import datetime as dt
from pathlib import Path

from markdown_it import MarkdownIt
from pydantic import BaseModel

from lup.workspace.history import parse_semver

parser = MarkdownIt()

PREAMBLE = """# Changelog

Agent version history. Each version tracks a behavioral change in the agent.

"""
"""What a changelog opens with when a bump is the one that creates it."""


class ReleaseNote(BaseModel, frozen=True):
    """One release, as the fields a bump states rather than as markdown.

    ``details`` is a list because a bump names them one at a time. It was once
    a single string split on commas, which silently shredded any detail whose
    prose held one and kept only the last of several — a container deciding
    its own contents from their punctuation.
    """

    version: str
    date: dt.date
    summary: str
    details: list[str] = []

    def heading(self) -> str:
        """The line this release is found by, and where its date is written."""
        return f"## v{self.version} ({self.date.isoformat()})"

    def render(self) -> str:
        """This release as the markdown a changelog carries it in."""
        details = "".join(f"- {detail}\n" for detail in self.details)
        return f"{self.heading()}\n\n{self.summary}\n{details}\n"


class ReleaseHeading(BaseModel, frozen=True):
    """Where one release begins in a document, and what it names."""

    line: int
    version: str
    date: dt.date

    @classmethod
    def read(cls, line: int, content: str) -> "ReleaseHeading | None":
        """One heading's own text as a release, or None where it names none.

        The inverse of :meth:`ReleaseNote.heading`, and the reason a round-trip
        test can hold the two together rather than a convention doing it.
        """
        # lup: ignore[string-split] — the heading is one line of a grammar this
        # module writes and reads; the split only finds where the version ends
        # and the date begins, and parse_semver and fromisoformat judge both
        name, _, remainder = content.strip().partition(" ")
        version = name.removeprefix("v")
        stamp = remainder.strip().removeprefix("(").removesuffix(")")
        if parse_semver(version) is None:
            return None
        try:
            date = dt.date.fromisoformat(stamp)
        except ValueError:
            return None
        return cls(line=line, version=version, date=date)


class ReleaseSection(BaseModel, frozen=True):
    """One release already in the file, kept as the text it occupies."""

    version: str
    date: dt.date | None
    text: str


class Changelog(BaseModel, frozen=True):
    """A changelog document: what opens it, and the releases beneath."""

    preamble: str = PREAMBLE
    sections: list[ReleaseSection] = []

    @classmethod
    def parse(cls, text: str) -> "Changelog":
        """Read a document into its preamble and the releases under it."""
        lines = text.splitlines(keepends=True)
        headings = release_headings(text)
        bounds = [*(heading.line for heading in headings[1:]), len(lines)]
        return cls(
            preamble="".join(lines[: headings[0].line]) if headings else text,
            sections=[
                ReleaseSection(
                    version=heading.version,
                    date=heading.date,
                    text="".join(lines[heading.line : end]),
                )
                for heading, end in zip(headings, bounds)
            ],
        )

    @classmethod
    def read(cls, path: Path) -> "Changelog":
        """The document at ``path``, or an empty one where none exists yet."""
        return cls.parse(path.read_text()) if path.exists() else cls()

    def dates(self) -> dict[str, dt.date]:
        """When each release this document records was written."""
        return {
            section.version: section.date
            for section in self.sections
            if section.date is not None
        }

    def with_note(self, note: ReleaseNote) -> "Changelog":
        """This document with ``note`` written in, replacing any it supersedes.

        A version already present is rewritten in place rather than added
        again, so a bump repeated after an amended summary leaves one section
        rather than two claiming the same version.
        """
        written = ReleaseSection(
            version=note.version, date=note.date, text=note.render()
        )
        if any(section.version == note.version for section in self.sections):
            return self.model_copy(
                update={
                    "sections": [
                        written if section.version == note.version else section
                        for section in self.sections
                    ]
                }
            )
        return self.model_copy(update={"sections": [written, *self.sections]})

    def render(self) -> str:
        """The whole document, ready to write back."""
        return self.preamble + "".join(section.text for section in self.sections)


def release_headings(text: str) -> list[ReleaseHeading]:
    """Every release heading in document order.

    A second-level heading naming no parseable version stays with whatever it
    already belonged to, which is how a document's own prose headings survive
    a bump instead of being read as releases with peculiar names.
    """
    tokens = parser.parse(text)
    found = [
        ReleaseHeading.read(token.map[0], tokens[index + 1].content)
        for index, token in enumerate(tokens)
        if token.type == "heading_open" and token.tag == "h2" and token.map is not None
    ]
    return [heading for heading in found if heading is not None]
