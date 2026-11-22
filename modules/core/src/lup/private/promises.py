"""`private`'s promises: what the operator can count on of what never leaves under their name.

Checked through the harness, lup's parts started in one process: `Withholding`
builds its list there, no project the machine runs among it, so the operator's
home, user name and machine name are withheld, and the values a promise's
machine layer gives (`README.md` here, *Promises*).
"""

import tempfile
from pathlib import Path
from typing import Literal

import lup
from lup import Agent, Codebase, Model, Part
from lup.testing import (
    Accepted,
    Answering,
    RealGit,
    Refused,
    Repository,
    Scripted,
    Testing,
)

DEFAULT = """
from lup import Modules, Project

project = Project(modules=Modules.default())
"""
"""A project on lup's defaults."""

KESTREL = """
from lup import Modules, Project
from lup.private.module import Private, Values

project = Project(modules=Modules().edit(Private(values=Values().add("Kestrel Labs"))))
"""
"""The operator's machine layer, withholding a value of their own."""


class Said(Model):
    """A line a check reads: holding the operator's value or not, in prose or in a file, written as is or in code."""

    word: Literal["Kestrel Labs", "kestrel labs", "Kestrel Labsworth", "nothing"]


def checking(text: str, *, prose: bool = False) -> lup.JsonObject:
    """Return a check of `text`, one line, as `Guard` asks one."""
    return {
        "texts": [
            {
                "within": "the body",
                "lines": [{"number": 1, "text": text}],
                "prose": prose,
            }
        ]
    }


class Found(Model):
    """A place a check found something, as the caller reads it."""

    within: str
    what: str
    steer: str


class Founds(Model):
    """Every place a check found something."""

    places: list[Found]


def places(answered: Accepted) -> list[Found]:
    """Return each place a check found something."""
    return Founds.model_validate_json(answered.answer()).places


STANDING = {
    "git": RealGit(),
    "ssh": Scripted(answers=[Answering(when=["-G"], output="hostname github.com\n")]),
}
"""git run for real and ssh stood in for, which `Withholding` runs to read a
project's remotes."""


class PrivatePromises(Part):
    """What the operator can count on of what never leaves under their name."""

    @lup.promise
    async def a_value_withheld_is_found_by_its_kind_never_said(
        self, by: Testing
    ) -> None:
        """A value of the operator's own, given in their machine's layer, is found in a text however it's cased, never inside a longer word, and named by its kind: what's said of it never holds it."""
        word = by.any(Said).word
        started = await by.started(
            Repository(declaration=DEFAULT, machine=KESTREL), programs=STANDING
        )
        checked = await started.serve(
            "checked", checking(f"made by {word} today"), Codebase(repository="harmon")
        )
        assert isinstance(checked, Accepted), checked
        found = places(checked)
        held = word in ["Kestrel Labs", "kestrel labs"]
        assert bool(found) == held
        assert all("kestrel" not in each.model_dump_json().casefold() for each in found)

    @lup.promise
    async def an_item_number_is_found_in_prose_never_in_code(self, by: Testing) -> None:
        """An inbox item's number is found where Markdown reads prose, a commit's message or a post's part, never in code, after a backslash, nor in a file."""
        written = by.any(Cited).written
        prose = by.any(bool)
        started = await by.started(
            lup.Project(modules=lup.Modules.default()), programs=STANDING
        )
        checked = await started.serve(
            "checked", checking(written, prose=prose), Codebase(repository="harmon")
        )
        assert isinstance(checked, Accepted), checked
        assert bool(places(checked)) == (prose and written == "see @1505")

    @lup.promise
    async def a_post_holding_a_value_withheld_isnt_posted(self, by: Testing) -> None:
        """A post holding a value withheld is refused at `Publishing`, saying where, and nothing reaches GitHub."""
        held = by.any(bool)
        git = RealGit()
        with tempfile.TemporaryDirectory(prefix="lup-private-") as directory:
            work = git.made(Path(directory) / "work")
            git.git(
                "config", "remote.origin.url", "git@github.com:a/harmon.git", cwd=work
            )
            started = await by.started(
                Repository(declaration=DEFAULT, machine=KESTREL),
                programs={
                    "git": git,
                    "ssh": Scripted(
                        answers=[Answering(when=["-G"], output="hostname github.com\n")]
                    ),
                    "gh": Scripted(
                        answers=[
                            Answering(
                                when=["issue", "create"],
                                output="https://github.com/a/harmon/issues/1\n",
                            )
                        ]
                    ),
                },
                git=work / ".git",
            )
            filed = await started.call(
                "file_issue",
                {"title": "a bug", "body": "at Kestrel Labs" if held else "at home"},
                by.any(Agent),
            )
        assert isinstance(filed, Refused) == held
        created = [
            each for each in started.ran("gh") if "issue" in each and "create" in each
        ]
        assert bool(created) != held


class Cited(Model):
    """A line citing an inbox item's number, in prose or not."""

    written: Literal["see @1505", "see `@1505`", "see \\@1505", "mail me@1505.x"]
