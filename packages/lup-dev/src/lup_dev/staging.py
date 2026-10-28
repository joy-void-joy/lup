"""Staging chosen hunks of a file without a terminal: what `lup-dev stage` does.

`git add -p` asks at a terminal, hunk after hunk, and an answer given ahead
goes by position, so a miscount stages the wrong hunk without a word. Here a
file's hunks are listed numbered, each with where it lies and its first lines
(`Changed.listed`); those named are staged, by number or by a range of the
file's lines, and what was staged is said (`Staged.said`). It only stages:
the commit stays the agent's.

**The hunks** are the file's changes against what the index holds for it, each
a run of lines changed together, found with `difflib` as the judge finds the
lines a write changed (`policy/judge.py`): between the index's blob and the
file as `git add` would store it, which git makes through the repository's
attributes (`git hash-object --path`). No diff text is read, so none is
parsed. They can differ from `git diff`'s, which joins changes a few lines
apart into one hunk and lines up repeated lines its own way.

**Staging** builds the content the chosen hunks make of the index's, writes it
as a blob, and points the index's entry at it (`git update-index --cacheinfo`),
keeping the entry's mode: git's own plumbing, which `git add -p` ends in too.
Where the entry changed since it was read, nothing is staged.

**A range of lines** names the file's lines as it stands, numbered from 1 as an
editor numbers them, which staging doesn't move: a range is still right after
another staging, where the hunks are numbered afresh. It takes the lines added
within it, the lines those replace, and the lines removed between two of its
lines. A removed line is replaced by the added line most like it, the pairs
found as `difflib`'s `ndiff` finds them, in order; one like none of them, by
the first added line after it (`Hunk.slots`). So a range taking an edited
line takes the line it was, and one taking only lines inserted beside edited
ones takes nothing removed.
"""

import stat
from difflib import SequenceMatcher
from itertools import batched
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from lup.blocks import counted
from lup.types import Model
from lup_dev.errors import LupDevError
from lup_dev.git import Git, nul_separated

if TYPE_CHECKING:
    from collections.abc import Iterator

ENTRY = "%(objectmode)%x00%(objectname)%x00%(stage)%x00%(path)"
"""How `git ls-files` writes each entry of the index for `Changed.of`: its
fields, each ended by a NUL byte, as `Entry` names them."""


class StagingError(LupDevError):
    """A file whose hunks can't be listed or staged here, or a choice naming none of them."""


class Lines(Model):
    """A range of a file's lines as it stands, numbered from 1, both ends taken."""

    first: int
    last: int


class Slot(Model):
    """What a hunk stages as one piece: one of its added lines with the removed lines it replaces, or, in a hunk adding none, its removed lines."""

    removed: list[bytes] = []
    added: bytes | None = None


class Pair(Model):
    """A removed line and the added line most like it, by their places in a hunk."""

    removed: int
    added: int


def paired(
    removed: list[bytes],
    added: list[bytes],
    *,
    cutoff: float = 0.75,
    most: int = 10_000,
) -> list[Pair]:
    r"""Pair each removed line with the added line most like it, in order, as `difflib`'s `ndiff` does: the likest pair first, then the likest on either side of it.

    Lines are compared without the whitespace around them, so indentation alone
    doesn't make two lines alike, and a pair is at least `cutoff` alike. Where
    the hunk holds more than `most` pairs of lines to compare, none is paired:
    comparing every pair grows as their product.

    >>> paired([b"a = 1\n", b"return a\n"], [b"a = 10\n", b"c = 3\n", b"return a + c\n"])
    [Pair(removed=0, added=0), Pair(removed=1, added=2)]
    """
    if len(removed) * len(added) > most:
        return []
    matcher = SequenceMatcher(a=b"", b=b"", autojunk=False)

    def found(below: Pair, above: Pair) -> list[Pair]:
        best: Pair | None = None
        likeness = cutoff
        for at in range(below.added + 1, above.added):
            matcher.set_seq2(added[at].strip())
            for place in range(below.removed + 1, above.removed):
                matcher.set_seq1(removed[place].strip())
                if (
                    matcher.real_quick_ratio() >= likeness
                    and matcher.quick_ratio() >= likeness
                    and matcher.ratio() >= likeness
                ):
                    best, likeness = Pair(removed=place, added=at), matcher.ratio()
        if best is None:
            return []
        return [*found(below, best), best, *found(best, above)]

    return found(
        Pair(removed=-1, added=-1), Pair(removed=len(removed), added=len(added))
    )


class Hunk(Model):
    """A run of lines a file changes together, against what the index holds for it.

    A file's hunks are numbered from 1 in its order, as `lup-dev stage <path>
    <number>` names them.
    """

    start: int
    """Where it lies in the index's lines, counted from 0: its first removed line,
    or the line its added ones go before."""
    removed: list[bytes]
    """The index's lines it removes, each with its line ending."""
    at: int
    """Where it lies in the file's lines, counted from 0: its first added line, or
    the line its removed ones stood before."""
    added: list[bytes]
    """The file's lines it adds, each with its line ending."""

    def slots(self) -> list[Slot]:
        r"""Return its pieces, in order: each added line with the removed lines it replaces.

        A removed line is replaced by the added line most like it (`paired`);
        one like none, by the first added line after the pair before it, or
        the last added line where none comes after.

        >>> hunk = Hunk(start=0, removed=[b"a = 1\n", b"gone\n"], at=0,
        ...     added=[b"a = 10\n", b"b = 2\n"])
        >>> [(slot.removed, slot.added) for slot in hunk.slots()]
        [([b'a = 1\n'], b'a = 10\n'), ([b'gone\n'], b'b = 2\n')]
        """
        if not self.added:
            return [Slot(removed=self.removed)]
        partners = {
            pair.removed: pair.added for pair in paired(self.removed, self.added)
        }

        def replacing(place: int) -> int:
            if place in partners:
                return partners[place]
            before = max(
                (partners[each] for each in partners if each < place), default=-1
            )
            return min(before + 1, len(self.added) - 1)

        replaced = [replacing(place) for place in range(len(self.removed))]
        return [
            Slot(
                removed=[
                    line
                    for line, by in zip(self.removed, replaced, strict=True)
                    if by == at
                ],
                added=line,
            )
            for at, line in enumerate(self.added)
        ]

    def made(self, *, whole: bool, taken: list[bool] | None) -> list[bytes]:
        """Return the lines it leaves in the index: its added lines where it's staged `whole`; its removed lines where nothing of it is `taken`; else, for each of its slots, its added line where `taken` says so, its removed lines where not."""
        if whole:
            return self.added
        if taken is None:
            return self.removed
        return [
            line
            for slot, staged in zip(self.slots(), taken, strict=True)
            for line in (
                ([] if slot.added is None else [slot.added]) if staged else slot.removed
            )
        ]

    def within(self, lines: Lines, length: int) -> list[bool]:
        """Say, for each of its slots, whether `lines` takes it, in a file `length` lines long: where its added line is in the range; in a hunk adding none, where the range holds the lines on both sides of it."""
        if self.added:
            return [
                lines.first <= self.at + at + 1 <= lines.last
                for at in range(len(self.added))
            ]
        return [0 < self.at < length and lines.first <= self.at < lines.last]

    def where(self) -> str:
        """Say where it lies in the file it's taken from, and how many lines it adds and removes: `lines 40-51 · +12 -3`."""
        match len(self.added), self.at:
            case 0, 0:
                place = "before line 1"
            case 0, _:
                place = f"after line {self.at}"
            case 1, _:
                place = f"line {self.at + 1}"
            case _:
                place = f"lines {self.at + 1}-{self.at + len(self.added)}"
        sizes = [
            *([f"+{len(self.added)}"] if self.added else []),
            *([f"-{len(self.removed)}"] if self.removed else []),
        ]
        return f"{place} · {' '.join(sizes)}"

    def rows(self, shown: int | None, width: int) -> list[str]:
        """Return its lines as listed: the removed ones, then the added ones, each numbered where it lies in the file; the first `shown` of each, or all where none is given."""

        def first(rows: list[str]) -> list[str]:
            if shown is None or len(rows) <= shown:
                return rows
            return [*rows[:shown], f"    {'':>{width}}   … {len(rows) - shown} more"]

        removed = [f"    {'':>{width}} - {text(line)}" for line in self.removed]
        added = [
            f"    {self.at + at + 1:>{width}} + {text(line)}"
            for at, line in enumerate(self.added)
        ]
        return [*first(removed), *first(added)]


def text(line: bytes) -> str:
    r"""Return a line as it reads, without its line ending; said where it has none, at a file's end.

    >>> text(b"a = 1\r\n"), text(b"b")
    ('a = 1', 'b  (no newline at the end)')
    """
    content = next(iter(line.splitlines()), b"")
    read = content.decode(errors="replace")
    return f"{read}  (no newline at the end)" if content == line else read


def changes(before: list[bytes], after: list[bytes]) -> list[Hunk]:
    r"""Return the hunks that make `after` of `before`, in order.

    >>> [hunk.where() for hunk in changes([b"a\n", b"b\n", b"c\n"], [b"a\n", b"B\n", b"c\n", b"d\n"])]
    ['line 2 · +1 -1', 'line 4 · +1']
    """
    matcher = SequenceMatcher(a=before, b=after, autojunk=False)
    return [
        Hunk(start=start, removed=before[start:end], at=at, added=after[at:until])
        for tag, start, end, at, until in matcher.get_opcodes()
        if tag != "equal"
    ]


def listing(hunks: list[Hunk], shown: int | None, *, numbered: bool) -> list[str]:
    """Return the lines listing `hunks`, each under where it lies, after its number where `numbered`: the first `shown` lines of each side, or all where none is given."""
    if not hunks:
        return []
    width = len(str(max(hunk.at + len(hunk.added) for hunk in hunks)))
    return [
        line
        for number, hunk in enumerate(hunks, start=1)
        for line in [
            f"{number}  {hunk.where()}" if numbered else hunk.where(),
            *hunk.rows(shown, width),
        ]
    ]


class Entry(Model):
    """A file's entry in the index, as `git ls-files` lists it."""

    mode: str
    object: str
    stage: str
    """`0`, or the side of a conflict: `1` to `3`."""
    path: PurePosixPath


class Staged(Model):
    """What a staging changed in the index for one file."""

    path: PurePosixPath
    hunks: list[Hunk]
    """Its change to the index, as hunks against what it held."""
    left: int
    """How many hunks the file still holds that the index doesn't."""

    def said(self, *, whole: bool = False, shown: int = 3) -> str:
        """Say what was staged, numbered where it lies in what the index holds, and how many hunks are left: the first `shown` lines of each side of each hunk, or every line where `whole`."""
        left = (
            f"{counted(self.left, 'hunk')} left, numbered afresh."
            if self.left
            else "Nothing left to stage in it."
        )
        return "\n".join(
            [
                f"Staged in {self.path}, numbered as in the index:",
                *listing(self.hunks, None if whole else shown, numbered=False),
                left,
            ]
        )


class Changed(Model):
    """A file's content as the index holds it and as `git add` would store it, whose hunks are listed and staged."""

    git: Git
    """git at the root of the worktree holding the file."""
    path: PurePosixPath
    """From the worktree's root."""
    mode: str
    """The index entry's, which staging keeps; the file's, for a file the index
    doesn't hold."""
    object: str | None
    """The index's blob for it; none for a file the index doesn't hold."""
    before: list[bytes]
    """The index's lines, each with its line ending."""
    after: list[bytes]
    """The file's lines as `git add` would store them."""
    told: list[str] = []
    """What staging hunks leaves out and the listing says: a change of mode."""

    @classmethod
    def of(cls, given: Path) -> Changed:
        """Read the file at `given`, from wherever it's given, against its worktree's index; raise `StagingError` where its hunks can't be staged here, saying what stages it."""
        located = given.absolute().parent.resolve() / given.name
        here = next(
            each for each in [located.parent, *located.parent.parents] if each.is_dir()
        )
        root = Path(Git(cwd=here).text("rev-parse", "--show-toplevel"))
        if not located.is_relative_to(root):
            message = f"{given} lies outside the worktree at {root}"
            raise StagingError(message)
        path = PurePosixPath(located.relative_to(root).as_posix())
        git = Git(cwd=root)
        entries = indexed(git, path)
        if any(entry.stage != "0" for entry in entries):
            message = f"{path} is in conflict: resolve it, then `git add {path}`"
            raise StagingError(message)
        if located.is_symlink() or any(entry.mode == "120000" for entry in entries):
            message = f"{path} is a link: `git add {path}` stages it"
            raise StagingError(message)
        if any(entry.mode == "160000" for entry in entries):
            message = f"{path} is a submodule: `git add {path}` stages its commit"
            raise StagingError(message)
        if located.is_dir():
            message = f"{path} is a directory: name one of its files"
            raise StagingError(message)
        if not located.exists():
            message = (
                f"{path} is gone from the worktree: `git rm --cached {path}` "
                "stages its removal"
                if entries
                else f"{path} is in neither the worktree nor the index"
            )
            raise StagingError(message)
        if not entries and git.ignored(Path(path)):
            message = f"{path} is ignored, and the index doesn't hold it"
            raise StagingError(message)
        cleaned = git.text("hash-object", "-w", f"--path={path}", "--", str(located))
        entry = next(iter(entries), None)
        [*held, after] = git.contents(
            [*([] if entry is None else [entry.object]), cleaned]
        )
        before = next(iter(held), b"")
        if b"\0" in before or b"\0" in after:
            message = f"{path} is binary: `git add {path}` stages it whole"
            raise StagingError(message)
        executable = bool(located.stat().st_mode & stat.S_IXUSR)
        mode = "100755" if executable else "100644"
        chmod = f"`git update-index --chmod={'+' if executable else '-'}x {path}`"
        told = (
            [f"Its mode changes to {mode}, which {chmod} stages."]
            if entry is not None and entry.mode != mode
            else []
        )
        return cls(
            git=git,
            path=path,
            mode=mode if entry is None else entry.mode,
            object=None if entry is None else entry.object,
            before=before.splitlines(keepends=True),
            after=after.splitlines(keepends=True),
            told=told,
        )

    def hunks(self) -> list[Hunk]:
        """Return the hunks that make the file of what the index holds."""
        return changes(self.before, self.after)

    def listed(self, *, whole: bool = False, shown: int = 3) -> str:
        """Say its hunks, numbered, each with where it lies and the first `shown` lines of each side, or every line where `whole`."""
        hunks = self.hunks()
        heading = (
            f"{self.path}: {counted(len(hunks), 'hunk')} to stage."
            if hunks
            else f"{self.path}: nothing to stage, the index holds it as it is."
        )
        return "\n".join(
            [
                heading,
                *self.told,
                *listing(hunks, None if whole else shown, numbered=True),
            ]
        )

    def stage(self, numbers: list[int], lines: Lines | None = None) -> Staged:
        """Stage the hunks `numbers` names, whole, and what `lines` takes, into the index; raise `StagingError`, staging nothing, where either names nothing to stage or the index's entry changed since it was read."""
        hunks = self.hunks()
        missing = [
            number for number in dict.fromkeys(numbers) if not 0 < number <= len(hunks)
        ]
        if missing:
            named = ", ".join(str(number) for number in missing)
            message = (
                f"{self.path} has {counted(len(hunks), 'hunk')}, so no hunk {named}"
            )
            raise StagingError(message)
        ranged = [None] * len(hunks) if lines is None else self.ranged(hunks, lines)

        def made() -> Iterator[bytes]:
            kept = 0
            for number, (hunk, within) in enumerate(
                zip(hunks, ranged, strict=True), start=1
            ):
                yield from self.before[kept : hunk.start]
                yield from hunk.made(whole=number in numbers, taken=within)
                kept = hunk.start + len(hunk.removed)
            yield from self.before[kept:]

        staged = list(made())
        current = indexed(self.git, self.path)
        if [entry.object for entry in current] != (
            [] if self.object is None else [self.object]
        ):
            message = (
                f"The index's entry for {self.path} changed since it was read, so "
                "nothing was staged: list its hunks again"
            )
            raise StagingError(message)
        blob = (
            self.git.run(
                "hash-object", "-w", "--stdin", "--no-filters", stdin=b"".join(staged)
            )
            .output.decode()
            .strip()
        )
        self.git.run(
            "update-index", "--add", "--cacheinfo", self.mode, blob, str(self.path)
        )
        return Staged(
            path=self.path,
            hunks=changes(self.before, staged),
            left=len(changes(staged, self.after)),
        )

    def ranged(self, hunks: list[Hunk], lines: Lines) -> list[list[bool] | None]:
        """Say, for each of `hunks`, which of its slots `lines` takes, none for one it takes nothing of; raise `StagingError` where the range lies outside the file or takes nothing."""
        if not 0 < lines.first <= lines.last <= len(self.after):
            message = (
                f"Lines {lines.first}-{lines.last} aren't a range of {self.path}, "
                f"which has {counted(len(self.after), 'line')}"
            )
            raise StagingError(message)
        taken = [
            within if any(within := hunk.within(lines, len(self.after))) else None
            for hunk in hunks
        ]
        if not any(taken):
            message = (
                f"Lines {lines.first}-{lines.last} of {self.path} hold nothing to stage"
            )
            raise StagingError(message)
        return taken


def indexed(git: Git, path: PurePosixPath) -> list[Entry]:
    """Return the index's entries for `path`: none for a file it doesn't hold, one for a file it does, one for each side of a conflict."""
    listed = git.run("ls-files", "-z", f"--format={ENTRY}", "--", f":(literal){path}")
    return [
        entry
        for mode, blob, side, named in batched(
            nul_separated(listed.output), 4, strict=True
        )
        if (
            entry := Entry(
                mode=mode, object=blob, stage=side, path=PurePosixPath(named)
            )
        ).path
        == path
    ]
