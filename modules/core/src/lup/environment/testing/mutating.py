"""A landing's mutation: the lines a branch changed that no promise runs, and the small breaks of the others that no promise notices (`lup/testing/README.md`, *Mutation*).

It never fails a landing. What it finds is told in the landing's review, so
whoever reads it judges whether the branch's promises check what it changed.
It's run as `python -m lup.environment.testing.mutating` from a worktree's
root, against `dev` unless told otherwise.

It runs the promises once, recording which runs which line (`--lup-reach`),
and lists each changed line of the repository's code that none runs. Then it
breaks a sample of the others in small ways, each in a copy of the
repository's sources apart from the worktree, so no write reaches it, and runs
against each break only the promises reaching its line, stopping at the first
that fails. A line only importing a module runs, as a class's body, is run by
no promise of its own, so its break runs against every promise.
"""

import ast
import asyncio
import difflib
import io
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from itertools import accumulate, takewhile
from pathlib import Path, PurePosixPath
from queue import Queue
from typing import TYPE_CHECKING

import typer

from lup.environment.testing.reaching import locations, reached
from lup.programs import run
from lup.programs.git import Git
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lup.programs.git import Changed


class Break(Model):
    """One small break of a changed line: where, and what its code was and becomes."""

    path: PurePosixPath
    """The file, from the worktree's root."""
    line: int
    was: str
    becomes: str
    start: int
    """Where in the file's bytes the code broken starts."""
    end: int
    """Where it ends."""
    imported: bool = False
    """Whether it runs as its module is imported, at its top or in a class's
    body, where no promise of its own runs it."""

    def ran_by(self, ran: dict[int, list[str]]) -> bool:
        """Say whether a check runs the line of this break, as `ran` says which checks run each line."""
        return bool(ran.get(self.line))

    def said(self) -> str:
        """Say the break in a line, as the review shows it.

        >>> Break(path=PurePosixPath("a.py"), line=3, was="x < 1", becomes="x <= 1", start=0, end=5).said()
        'a.py:3: `x < 1` → `x <= 1`'
        """
        return f"{self.path}:{self.line}: `{self.was}` → `{self.becomes}`"

    def applied(self, text: bytes) -> bytes:
        """Return `text`, the file's bytes, with this break made."""
        # lup: ignore("string-slice", why="the positions are the ones Python's own parser gave the code broken")
        return text[: self.start] + self.becomes.encode() + text[self.end :]


class Unreached(Model):
    """A file's changed lines that no promise runs."""

    path: PurePosixPath
    lines: list[int]


class Mutated(Model):
    """What a landing's mutation found: the changed lines no promise runs, and the breaks of the others no promise noticed, of those tried."""

    unreached: list[Unreached] = []
    unnoticed: list[Break] = []
    tried: int = 0

    def said(self) -> str:
        """Say what was found, as the landing's review shows it."""
        lines = [
            f"  {each.path}: {', '.join(str(line) for line in each.lines)}"
            for each in self.unreached
        ]
        breaks = [f"  {each.said()}" for each in self.unnoticed]
        return "\n".join(
            [
                *(
                    ["Lines this branch changed that no promise runs:", *lines]
                    if lines
                    else []
                ),
                f"Breaks of changed lines no promise noticed: {len(breaks)} of {self.tried} tried.",
                *breaks,
            ]
        )


def changed_lines(before: bytes | None, after: bytes) -> list[int]:
    r"""Return the lines of a file as it is, `after`, from 1, that differ from what it was, `before`: every line of a file new since.

    >>> changed_lines(b"a\nb\nc\n", b"a\nB\nc\nd\n"), changed_lines(None, b"a\n")
    ([2, 4], [1])
    """
    now = io.BytesIO(after).readlines()
    if before is None:
        return list(range(1, len(now) + 1))
    matcher = difflib.SequenceMatcher(
        a=io.BytesIO(before).readlines(), b=now, autojunk=False
    )
    return [
        line + 1
        for tag, _, _, first, last in matcher.get_opcodes()
        if tag in ["replace", "insert"]
        for line in range(first, last)
    ]


def code(path: PurePosixPath) -> bool:
    """Say whether `path` is the repository's code, which mutation breaks: Python, and neither a module's promises nor a test.

    >>> [code(PurePosixPath(each)) for each in ["lup/inbox/inbox.py", "lup/inbox/promises.py", "tests/test_a.py", "README.md"]]
    [True, False, False, False]
    """
    test = path.name.startswith("test_") or "tests" in path.parts
    return (
        path.suffix == ".py"
        and path.name not in ["promises.py", "conftest.py"]
        and not test
    )


def breaks(path: PurePosixPath, text: bytes, lines: list[int]) -> list[Break]:
    r"""Return each small break of the code of `text`, the file at `path`, on `lines`: a comparison flipped, `and` and `or` swapped, a `not` dropped or added to a condition, a constant or an index changed, a statement dropped.

    >>> [each.becomes for each in breaks(PurePosixPath("a.py"), b"if x < 1 and y:\n    go()\n", [1, 2])]
    ['(x <= 1)', 'not (x < 1 and y)', '(x < 1 or y)', '2', 'pass']
    """
    starts = [0, *accumulate(len(each) for each in io.BytesIO(text).readlines())]
    tree = ast.parse(text)

    def made(node: ast.expr | ast.stmt, becomes: str) -> Break:
        start = starts[node.lineno - 1] + node.col_offset
        end = starts[(node.end_lineno or node.lineno) - 1] + (node.end_col_offset or 0)
        # lup: ignore("string-slice", why="the positions are the ones Python's own parser gave the node")
        was = text[start:end].decode()
        return Break(
            path=path, line=node.lineno, was=was, becomes=becomes, start=start, end=end
        )

    def broken(node: ast.AST) -> list[Break]:
        match node:
            case ast.If(test=test) | ast.While(test=test):
                return [made(test, f"not ({ast.unparse(test)})")]
            case ast.BoolOp(op=ast.And()):
                return [
                    made(
                        node,
                        f"({ast.unparse(ast.BoolOp(op=ast.Or(), values=node.values))})",
                    )
                ]
            case ast.BoolOp(op=ast.Or()):
                return [
                    made(
                        node,
                        f"({ast.unparse(ast.BoolOp(op=ast.And(), values=node.values))})",
                    )
                ]
            case ast.UnaryOp(op=ast.Not(), operand=operand):
                return [made(node, f"({ast.unparse(operand)})")]
            case ast.Compare(left=left, ops=[op], comparators=comparators):
                flipped = flip(op)
                if flipped is None:
                    return []
                swapped = ast.Compare(left=left, ops=[flipped], comparators=comparators)
                return [made(node, f"({ast.unparse(swapped)})")]
            case ast.Constant(value=bool() as value):
                return [made(node, str(not value))]
            case ast.Constant(value=int() as value):
                return [made(node, str(value + 1))]
            case ast.Subscript(
                slice=ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=1))
            ):
                return [made(node.slice, "0")]
            case ast.Return(value=ast.expr()):
                return [made(node, "return None")]
            case ast.Expr(value=ast.Constant()):
                return []
            case ast.Expr() | ast.Assign() | ast.AugAssign() | ast.Raise():
                return [made(node, "pass")]
            case _:
                return []

    def visited(node: ast.AST, *, called: bool) -> Iterator[Break]:
        """Yield each break of `node` and what it holds on `lines`, each saying whether it runs as its module is imported: not in a function's body, which runs as `called`."""
        if getattr(node, "lineno", None) in lines:
            yield from (
                each.model_copy(update={"imported": not called})
                for each in broken(node)
            )
        match node:
            case ast.FunctionDef(body=body) | ast.AsyncFunctionDef(body=body):
                inner: list[ast.AST] = [*body]
            case ast.Lambda(body=expression):
                inner = [expression]
            case _:
                inner = []
        for child in ast.iter_child_nodes(node):
            inside = called or any(child is each for each in inner)
            yield from visited(child, called=inside)

    found = [each for each in visited(tree, called=False) if each.becomes != each.was]
    return sorted(found, key=lambda each: (each.start, each.end))


def flip(op: ast.cmpop) -> ast.cmpop | None:
    """Return the comparison `op` flips to, its boundary moved or its sense turned; none for one this doesn't flip."""
    match op:
        case ast.Lt():
            return ast.LtE()
        case ast.LtE():
            return ast.Lt()
        case ast.Gt():
            return ast.GtE()
        case ast.GtE():
            return ast.Gt()
        case ast.Eq():
            return ast.NotEq()
        case ast.NotEq():
            return ast.Eq()
        case ast.In():
            return ast.NotIn()
        case ast.NotIn():
            return ast.In()
        case ast.Is():
            return ast.IsNot()
        case ast.IsNot():
            return ast.Is()
        case _:
            return None


def sampled[T](each: list[T], most: int) -> list[T]:
    """Return at most `most` of `each`, evenly spread across it.

    >>> sampled(list(range(10)), 3), sampled([1, 2], 5)
    ([0, 3, 6], [1, 2])
    """
    if len(each) <= most:
        return each
    step = len(each) / most
    return [each[int(index * step)] for index in range(most)]


class Candidate(Model):
    """A break to try, with the checks to run against it, by pytest's names for them."""

    broken: Break
    checks: list[str]


class Reaching(Model):
    """A file the branch changed: its breaks, and which checks run each of its lines."""

    path: PurePosixPath
    breaks: list[Break]
    ran: dict[int, list[str]]
    """For each line some check runs, the checks running it."""

    @classmethod
    def of(cls, root: Path, changed: Changed, reach: Path) -> Reaching:
        """Read the file `changed` names in the worktree at `root`: its breaks on the lines changed, and which checks ran each line, from the coverage data file at `reach`."""
        text = (root / changed.path).read_bytes()
        lines = changed_lines(changed.before, text)
        return cls(
            path=changed.path,
            breaks=breaks(changed.path, text, lines),
            ran=reached(reach, root / changed.path),
        )

    def touching(self) -> list[str]:
        """Return each check that runs any line of the file, in order."""
        return list(
            dict.fromkeys(name for names in self.ran.values() for name in names)
        )

    def unreached(self) -> list[int]:
        """Return each line with a break that no check runs, in order, a line run as its module is imported aside: no check is credited with it, whichever run it."""
        return list(
            dict.fromkeys(
                each.line
                for each in self.breaks
                if each.line not in self.ran and not each.imported
            )
        )

    def candidates(
        self, most: int, written: dict[str, PurePosixPath]
    ) -> list[Candidate]:
        """Return each break to try, with at most `most` of the checks that run its line, or, for a line run as its module is imported, that run any line of the file: those written nearest the file first, as `written` says where each check is."""

        def nearest(checks: list[str]) -> list[str]:
            far = PurePosixPath()
            ranked = sorted(
                checks, key=lambda check: -nearness(self.path, written.get(check, far))
            )
            return ranked[:most]

        return [
            Candidate(
                broken=each,
                checks=nearest(
                    self.touching() if each.imported else self.ran[each.line]
                ),
            )
            for each in self.breaks
            if (each.imported and self.touching()) or each.ran_by(self.ran)
        ]


def nearness(file: PurePosixPath, other: PurePosixPath) -> int:
    """Say how many directories `file` and `other` share from the root, a module's environment side counted as its library side.

    >>> nearness(PurePosixPath("src/lup/environment/testing/plugin.py"), PurePosixPath("src/lup/testing/promises.py"))
    3
    >>> nearness(PurePosixPath("src/lup/inbox/inbox.py"), PurePosixPath("src/lup/testing/promises.py"))
    2
    """
    mine = [each for each in file.parent.parts if each != "environment"]
    theirs = [each for each in other.parent.parts if each != "environment"]
    same = (one == other for one, other in zip(mine, theirs, strict=False))
    return sum(1 for _ in takewhile(bool, same))


class Copy(Model):
    """The repository's sources, copied apart from the worktree, where a break is made and its checks run."""

    root: Path

    @classmethod
    def of(cls, worktree: Path, into: Path) -> Copy:
        """Copy every module's sources, the declaration and the project's settings from `worktree` into `into`."""
        for each in sorted((worktree / "modules").glob("*/src")):
            shutil.copytree(
                each,
                into / each.relative_to(worktree),
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        for each in [*sorted(worktree.glob("*.py")), worktree / "pyproject.toml"]:
            if each.is_file():
                shutil.copy2(each, into / each.name)
        return cls(root=into)

    def noticed(self, candidate: Candidate) -> bool:
        """Say whether a check of `candidate`'s fails with its break made in the copy, stopping at the first that does; the copy is left as it was."""
        broken = candidate.broken
        file = self.root / broken.path
        text = file.read_bytes()
        file.write_bytes(broken.applied(text))
        sources = ":".join(
            str(each) for each in sorted((self.root / "modules").glob("*/src"))
        )
        try:
            ran = run(
                "env",
                f"PYTHONPATH={sources}",
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-q",
                "-x",
                *candidate.checks,
                cwd=self.root,
                checked=False,
            )
        finally:
            file.write_bytes(text)
        return ran.status != 0


async def changed_since(root: Path, since: str) -> list[Changed]:
    """Return each file of the worktree at `root` changed since where its branch left `since`."""
    worktree = await Git.located(root)
    if worktree is None:
        message = f"{root} is in no git worktree"
        raise typer.BadParameter(message)
    return await worktree.changed(since)


class Trying(Model):
    """How much a landing's mutation tries."""

    breaks: int = 20
    """Breaks of lines checks run, at most."""
    checks: int = 16
    """Checks run against each break, at most: those running its line written
    nearest its file."""
    workers: int = 12
    """Processes at once: the checks' first run's workers, and breaks tried
    side by side, each in a copy of its own."""


def mutated(root: Path, since: str, trying: Trying) -> Mutated:
    """Find what mutation finds of the worktree at `root`, its branch against `since`, trying as much as `trying` says."""
    changed = [
        each for each in asyncio.run(changed_since(root, since)) if code(each.path)
    ]
    with tempfile.TemporaryDirectory(prefix="lup-mutation-") as scratch:
        reach = Path(scratch) / "reach" / "reach.db"
        run(
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "-n",
            str(trying.workers),
            f"--lup-reach={reach}",
            *[f"--lup-reach-only={root / each.path}" for each in changed],
            cwd=root,
            checked=False,
        )
        files = [Reaching.of(root, each, reach) for each in changed]
        written = {
            each.check: each.file
            for each in locations(reach.with_suffix(".checks.json"))
        }
        unreached = [
            Unreached(path=each.path, lines=each.unreached())
            for each in files
            if each.unreached()
        ]
        tried = sampled(
            [
                each
                for file in files
                for each in file.candidates(trying.checks, written)
            ],
            trying.breaks,
        )
        copies: Queue[Copy] = Queue()
        for index in range(min(trying.workers, len(tried))):
            copies.put(Copy.of(root, Path(scratch) / f"copy-{index}"))

        def noticed(candidate: Candidate) -> bool:
            copy = copies.get()
            try:
                return copy.noticed(candidate)
            finally:
                copies.put(copy)

        with ThreadPoolExecutor(max_workers=trying.workers) as side_by_side:
            verdicts = list(side_by_side.map(noticed, tried))
    return Mutated(
        unreached=unreached,
        unnoticed=[
            each.broken for each, seen in zip(tried, verdicts, strict=True) if not seen
        ],
        tried=len(tried),
    )


def main(
    since: str = typer.Option(
        "dev", help="The branch the worktree's branch is compared with."
    ),
    breaks: int = typer.Option(
        Trying().breaks, help="How many breaks of lines checks run to try, at most."
    ),
    checks: int = typer.Option(
        Trying().checks, help="How many checks to run against each break, at most."
    ),
    workers: int = typer.Option(
        Trying().workers, help="How many processes to run at once."
    ),
) -> None:
    """Say which lines this worktree's branch changed no promise runs, and which small breaks of the others no promise notices; it never fails."""
    trying = Trying(breaks=breaks, checks=checks, workers=workers)
    typer.echo(mutated(Path.cwd(), since, trying).said())


if __name__ == "__main__":
    typer.run(main)
