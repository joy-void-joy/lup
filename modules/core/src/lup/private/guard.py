"""What refuses what never leaves under the operator's name: each project's `Guard` at `Publishing`, and the gate's `private` step, both asking the machine's `Withholding`, which alone holds the list."""

import asyncio
from pathlib import Path

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Agent, Operator
from lup.doors.parts import Part, Program
from lup.private.checking import Binary, Checked, Checking, Text
from lup.private.withholding import Withholding
from lup.programs.git.answers import tab_separated
from lup.programs.git.running import Git
from lup.publishing.events import Changed, Commit, Line, Post, Publishing, Push
from lup.types import Model


def lines_of(text: str) -> list[Line]:
    r"""Return each line of `text`, numbered from 1.

    >>> [each.number for each in lines_of("a\nb")]
    [1, 2]
    """
    return [
        Line(number=number, text=each)
        for number, each in enumerate(text.splitlines(), start=1)
    ]


def committed(commit: Commit) -> Checking:
    """Return what a commit publishes, to check: its message, as prose, each path it adds or changes, and each file's added lines, or its bytes where it isn't text."""
    short = commit.id

    def changed(each: Changed) -> list[Text]:
        return [
            Text(within=f"{short}'s path", lines=[Line(number=1, text=each.path)]),
            Text(within=f"{short} {each.path}", lines=each.added),
        ]

    return Checking(
        texts=[
            Text(
                within=f"{short}'s message", lines=lines_of(commit.message), prose=True
            ),
            *(text for each in commit.changed for text in changed(each)),
        ],
        binaries=[
            Binary(within=f"{short} {each.path}", content=each.content)
            for each in commit.changed
            if each.content is not None
        ],
    )


class Guard(Part):
    """Each project's part refusing at `Publishing` what never leaves under the operator's name, as the machine's `Withholding` finds it."""

    @lup.on(Publishing)
    async def heard(self, publishing: Publishing) -> None:
        """Refuse a push or a post holding what never leaves, saying where, never what."""
        match publishing.published:
            case Push(ref=ref, commit=commit):
                checking = Checking(
                    texts=[
                        Text(
                            within="the ref it updates",
                            lines=[Line(number=1, text=ref)],
                        )
                    ]
                )
                if commit is not None:
                    made = committed(commit)
                    checking = Checking(
                        texts=[*checking.texts, *made.texts], binaries=made.binaries
                    )
                what = f"this push to `{ref}`"
                after = (
                    "A push sends every commit the remote lacks, so rewrite the commit "
                    "that carries it (amend it, or rebase) and push again: a commit on "
                    "top leaves it in what's pushed."
                )
            case Post(what=posted, parts=parts):
                checking = Checking(
                    texts=[
                        Text(
                            within=f"the {each.name}",
                            lines=lines_of(each.text),
                            prose=True,
                        )
                        for each in parts
                    ]
                )
                what, after = posted, ""
        checked = await Withholding.checked(checking)
        if checked.places:
            raise RefusedError(
                "\n".join([checked.told(what), *([after] if after else [])])
            )


class Unchecked(Model):
    """Asking the gate's check, giving nothing: it reads the worktree it's typed in."""


class Checker(Part):
    """The gate's `private` step: the worktree's files, and the commits the remotes lack, checked as `Withholding` checks what's about to leave."""

    git: Program = Program(
        name="git",
        optional=True,
        why="lists the worktree's files and the commits its remotes lack",
        install="https://git-scm.com",
    )

    @lup.command(here=True)
    async def check(self, unchecked: Unchecked, by: Agent | Operator) -> str:
        """Check the worktree's files, and the messages of the commits its remotes lack, for what never leaves under the operator's name; refused where any holds one, saying where, never what."""
        del unchecked, by
        worktree = await Git.located(Path.cwd(), through=self.git)
        if worktree is None:
            message = "`lup private check` runs in a worktree, and this is none"
            raise RefusedError(message)
        files = await worktree.files()
        contents = [
            await asyncio.to_thread((worktree.root / each).read_bytes) for each in files
        ]
        texts: list[Text] = []
        binaries: list[Binary] = []
        for path, content in zip(files, contents, strict=True):
            try:
                text = content.decode()
            except UnicodeDecodeError:
                binaries = [*binaries, Binary(within=str(path), content=content)]
                continue
            texts = [*texts, Text(within=str(path), lines=lines_of(text))]
        unpushed = await worktree.done("rev-list", "HEAD", "--not", "--remotes")
        commits = [row[0] for row in tab_separated(unpushed.text())]
        messages = [
            Text(
                within=f"{each}'s message",
                lines=lines_of(
                    (await worktree.done("show", "-s", "--format=%B", each)).text()
                ),
                prose=True,
            )
            for each in commits
        ]
        checked: Checked = await Withholding.checked(
            Checking(
                texts=[*texts, *messages],
                binaries=binaries,
                repository=worktree.main.name,
            )
        )
        if checked.places:
            raise RefusedError(checked.told("this worktree"))
        return (
            f"Nothing that never leaves in {len(files)} files and "
            f"{len(commits)} commits the remotes lack."
        )
