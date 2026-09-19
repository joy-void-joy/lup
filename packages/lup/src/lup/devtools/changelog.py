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
from collections.abc import Iterator
from itertools import dropwhile
from pathlib import Path

from markdown_it import MarkdownIt
from pydantic import BaseModel

from lup.workspace.history import parse_semver

parser = MarkdownIt()

PREAMBLE = """# Changelog

Agent version history. Each version tracks a behavioral change in the agent.

"""
"""What a changelog opens with when a bump is the one that creates it."""


def release_heading(version: str, date: dt.date) -> str:
    """The one line every release in a changelog is found by.

    One writer, because two of them is how a file ends up holding both
    spellings of the same thing: a release closing an open section and a bump
    writing a note are the same heading, and which one a document gets should
    not depend on which command wrote it.

    The version is bare and the date follows a dash, which is what this
    repository's changelog was already written in — a format that predates
    the module and was, until the reader was widened, one this module could
    not read at all. `ReleaseHeading.read` still accepts the parenthesised
    ``v`` spelling, so a document written before this stays readable and only
    its new entries are written the one way.
    """
    return f"## {version} — {date.isoformat()}"


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
        return release_heading(self.version, self.date)

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

        Read more widely than it is written, because in every repository that
        kept a changelog before this module the document is older than it: the
        ``v`` is optional and the date may be parenthesised or introduced by a
        dash, which is how a hand-written entry usually spells it. Reading only
        what this module writes is not a stricter reading but a blinder one --
        a file whose every heading fails to parse comes back as a document with
        no releases in it, and the next note written lands beneath the whole of
        it. Whatever introduces the date, it is the last word on the line, so
        that is what is read and `date.fromisoformat` remains its only judge.
        """
        # lup: ignore[string-split] — the heading is one line of a grammar this
        # module writes and reads; the split only finds where the version ends
        # and the date begins, and parse_semver and fromisoformat judge both
        name, _, remainder = content.strip().partition(" ")
        version = name.removeprefix("v")
        words = remainder.split()
        stamp = words[-1].removeprefix("(").removesuffix(")") if words else ""
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


# lup: ignore[constant-declaration] — the heading Keep a Changelog names, which
# is a convention outside this repository rather than a choice made here
UNRELEASED = "Unreleased"
"""The heading a changelog gathers the next release's entries under.

Not a version, so :class:`ReleaseHeading` reads it as prose and it stays with
the preamble, which is the right answer for every reader but the one closing
it. That reader is :meth:`Changelog.released_as`.
"""


class Changelog(BaseModel, frozen=True):
    """A changelog document: what opens it, and the releases beneath."""

    preamble: str = PREAMBLE
    unreleased: str = ""
    """What stands under ``## Unreleased``, that heading included, or empty.

    Held apart from the preamble because a release does not *write* its
    section so much as close this one: the entries were accumulated as they
    landed, by whoever landed them, and a release names the version they
    turned out to be. Rendering puts it back exactly where it was, so a
    document nobody is releasing round-trips unchanged.
    """

    sections: list[ReleaseSection] = []

    @classmethod
    def parse(cls, text: str) -> "Changelog":
        """Read a document into its preamble, its open section, and the releases."""
        lines = text.splitlines(keepends=True)
        headings = release_headings(text)
        opening = unreleased_heading(text)
        first = headings[0].line if headings else len(lines)
        if opening is None or opening > first:
            return cls(
                preamble="".join(lines[:first]),
                sections=list(sectioned(lines, headings)),
            )
        return cls(
            preamble="".join(lines[:opening]),
            unreleased="".join(lines[opening:first]),
            sections=list(sectioned(lines, headings)),
        )

    def released_as(
        self, version: str, date: dt.date, additions: str = ""
    ) -> "Changelog":
        """This document with its open section closed as ``version``.

        The entries stay as their authors wrote them and the heading above
        them is replaced, because that is what a release is: the same list,
        named. ``additions`` is folded in beneath them for what only the
        release knows -- the migrations pending at the moment it is cut.

        A document with nothing open gets an empty section rather than a
        refusal, so a release that happens to carry no entries still records
        that it happened, on the date it happened.
        """
        body = without_heading(self.unreleased)
        text = f"{release_heading(version, date)}\n\n{body}{additions}"
        return self.model_copy(
            update={
                "unreleased": "",
                "sections": [
                    ReleaseSection(version=version, date=date, text=text),
                    *self.sections,
                ],
            }
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
        """The whole document, ready to write back.

        The open section sits where it was read, above every release and below
        the preamble, so a document nobody is releasing comes back unchanged.
        """
        return (
            self.preamble
            + self.unreleased
            + "".join(section.text for section in self.sections)
        )


class DocumentHeading(BaseModel, frozen=True):
    """One second-level heading: where it sits, and what it says.

    Both readings below want the same two facts and judge them differently —
    one asks whether the text names a version, the other whether it is the
    open section — so the pair is read once and named rather than returned
    positionally to two callers who would each have to remember the order.
    """

    line: int
    content: str


def second_level_headings(text: str) -> Iterator[DocumentHeading]:
    """Each ``##`` heading's line and its own text, in document order.

    Through the parser rather than by scanning for ``## ``, for the reason
    this module opens with: an entry may quote a fenced block containing one,
    and a scanner would split the document inside somebody's example.
    """
    tokens = parser.parse(text)
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2" and token.map is not None:
            yield DocumentHeading(line=token.map[0], content=tokens[index + 1].content)


def unreleased_heading(text: str) -> int | None:
    """Where the open section starts, or ``None`` where nothing is open.

    Matched without regard to case, because the heading is written by hand by
    whoever adds the first entry after a release, and ``## unreleased`` is the
    same intention.
    """
    return next(
        (
            heading.line
            for heading in second_level_headings(text)
            if heading.content.strip().casefold() == UNRELEASED.casefold()
        ),
        None,
    )


def without_heading(block: str) -> str:
    """A section's entries, with the heading line above them dropped.

    What a release keeps when it renames the section: the entries are their
    authors', and the heading is the release's to replace. The blank line that
    separated the two goes with the heading rather than with the entries, so
    the replacement supplies its own and the spacing does not depend on how
    whoever opened the section happened to type it.
    """
    lines = block.splitlines(keepends=True)
    entries = "".join(dropwhile(lambda line: not line.strip(), lines[1:]))
    return entries if not entries or entries.endswith("\n") else f"{entries}\n"


def sectioned(
    lines: list[str], headings: list[ReleaseHeading]
) -> Iterator[ReleaseSection]:
    """Each release heading paired with the lines beneath it, up to the next."""
    bounds = [*(heading.line for heading in headings[1:]), len(lines)]
    for heading, end in zip(headings, bounds):
        yield ReleaseSection(
            version=heading.version,
            date=heading.date,
            text="".join(lines[heading.line : end]),
        )


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
