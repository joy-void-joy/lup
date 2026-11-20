"""The gate's promises: what an agent or the operator typing `lup gate check` in a worktree can count on.

Each runs the check through the harness on a worktree in a temporary directory,
git and each step's program stood in for as the promise scripts them (git
answering as a repository there would, ruff laying out what it's given), and
reads what ran, where, in what order, and whether the check was refused, never
its words (`README.md` here, *Promises*).
"""

import hashlib
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import lup
from lup import Agent, Model, Module, Modules, Operator, Part, Project, Step, Steps
from lup.testing import (
    Accepted,
    Answering,
    Refused,
    Responding,
    Scripted,
    Testing,
)

if TYPE_CHECKING:
    from collections.abc import Generator

LAID_OUT = "laid = 'out'\n"
"""What a Python file holds once ruff's formatter, as the promises stand it in, has laid it out."""
LOCAL = "lup_project.local.py"
"""The repository's own layer of the declaration, which git ignores."""


class Checking(Model):
    """What the gate is asked, as `lup gate check` takes it."""

    fix: bool = False
    again: bool = False
    directory: Path | None = None


class Worktree(Model):
    """A worktree in a temporary directory, its git directory inside it, as a clone's is."""

    root: Path

    def files(self) -> list[Path]:
        """List the files git would commit: every file under the root but the git directory's and the local layer, which git ignores."""
        return sorted(
            each
            for each in self.root.rglob("*")
            if each.is_file()
            and ".git" not in each.relative_to(self.root).parts
            and each.name != LOCAL
        )

    def tree(self) -> str:
        """Return the tree git would commit the files as: a digest of each file's path and content."""
        digest = hashlib.sha1(usedforsecurity=False)
        for each in self.files():
            digest.update(str(each.relative_to(self.root)).encode())
            digest.update(each.read_bytes())
        return digest.hexdigest()


class Git(Model, Responding):
    """git, stood in for: answering what the gate asks of the worktree at `worktree`."""

    worktree: Worktree

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer what the gate asks: the worktree's root, its git directory, whether it's bare, its index, and the tree its files make."""
        del given
        root = self.worktree.root
        match arguments:
            case ["-C", _, "rev-parse", "--show-toplevel"]:
                return Answering(output=f"{root}\n")
            case ["-C", _, "rev-parse", "--path-format=absolute", "--git-common-dir"]:
                return Answering(output=f"{root}/.git\n")
            case ["-C", _, "config", "--bool", "core.bare"]:
                return Answering(output="false\n")
            case [
                "-C",
                _,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                "index",
            ]:
                return Answering(output=f"{root}/.git/index\n")
            case ["-C", _, "add", "--all"]:
                return Answering()
            case ["-C", _, "write-tree"]:
                return Answering(output=f"{self.worktree.tree()}\n")
            case _:
                return None


class Ruff(Model, Responding):
    """ruff's formatter, stood in for: a Python file is laid out where it holds `LAID_OUT`, which its fix writes."""

    worktree: Worktree

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Check the worktree's layout, or lay it out."""
        del given
        python = [each for each in self.worktree.files() if each.suffix == ".py"]
        match arguments:
            case ["format", "--check"]:
                unlaid = [each for each in python if each.read_text() != LAID_OUT]
                return Answering(status=1 if unlaid else 0)
            case ["format"]:
                for each in python:
                    each.write_text(LAID_OUT)
                return Answering()
            case _:
                return None


class Noting(Module):
    """A module of the project's own declaring a step of its own beside the gate's."""

    name = "noting"
    steps: Steps = Steps.of(Step(name="notes", command=["notes", "--all"]))


def project() -> Project:
    """Return a project of lup's default modules, the gate among them, and one declaring a step of its own."""
    return Project(modules=Modules.default().add(Noting()))


@contextmanager
def worktree(*, laid_out: bool = True) -> Generator[Worktree]:
    """Make a worktree in a temporary directory holding one Python file, laid out where `laid_out`, and its git directory."""
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        (root / ".git").mkdir()
        (root / "main.py").write_text(LAID_OUT if laid_out else "laid='out'\n")
        yield Worktree(root=root)


def standing(
    at: Worktree, failing: str | None = None
) -> dict[str, Git | Ruff | Scripted]:
    """Return git and every step's program stood in for over the worktree `at`, each step passing but the program named `failing`."""

    def ending(name: str) -> Scripted:
        return Scripted(answers=[Answering(status=1 if name == failing else 0)])

    return {
        "git": Git(worktree=at),
        "ruff": Ruff(worktree=at),
        "pytest": ending("pytest"),
        "lint-imports": ending("lint-imports"),
        "notes": ending("notes"),
    }


class GatePromises(Part):
    """What someone typing `lup gate check` in a worktree can count on."""

    @lup.promise
    async def every_step_runs_from_the_root_even_after_one_fails(
        self, by: Testing
    ) -> None:
        """Every module's steps run, each from the worktree's root, every one even where another fails, and the check is refused where any fails."""
        failing = by.any(bool)
        party = by.any(Agent) if by.any(bool) else Operator()
        with worktree() as at:
            started = await by.started(
                project(), programs=standing(at, "pytest" if failing else None)
            )
            checked = await started.run(
                "gate", "check", Checking(directory=at.root / ".git"), party
            )
            stepped = [each for each in started.heard.runs if each.program != "git"]
        assert isinstance(checked, Refused if failing else Accepted)
        assert all(
            name in [each.program for each in stepped]
            for name in ["ruff", "pytest", "lint-imports", "notes"]
        )
        assert all(each.cwd == at.root for each in stepped)

    @lup.promise
    async def a_pass_runs_nothing_again_on_the_same_files(self, by: Testing) -> None:
        """Once the gate passed on a worktree's files, checking the same files again runs no step, unless it's asked to run again; a file changed, or the repository's own layer of the declaration changed, runs every step."""
        party = by.any(Agent) if by.any(bool) else Operator()
        with worktree() as at:
            started = await by.started(project(), programs=standing(at))
            asking = Checking(directory=at.root)

            async def stepped(checking: Checking) -> list[str]:
                before = len(started.heard.runs)
                checked = await started.run("gate", "check", checking, party)
                assert isinstance(checked, Accepted)
                return [
                    each.program
                    for each in started.heard.runs[before:]
                    if each.program != "git"
                ]

            first = await stepped(asking)
            same = await stepped(asking)
            again = await stepped(asking.model_copy(update={"again": True}))
            (at.root / LOCAL).write_text("project = None\n")
            layered = await stepped(asking)
            (at.root / "other.py").write_text(LAID_OUT)
            changed = await stepped(asking)
        assert same == []
        assert all("pytest" in each for each in [first, again, layered, changed])

    @lup.promise
    async def a_fix_runs_before_any_step_checks(self, by: Testing) -> None:
        """Asked to fix, the gate runs each step's fix before any step checks, so the files are checked as the fixes left them; unasked, it fixes nothing."""
        with worktree(laid_out=False) as at:
            started = await by.started(project(), programs=standing(at))
            unfixed = await started.run(
                "gate", "check", Checking(directory=at.root), Operator()
            )
            fixed = await started.run(
                "gate", "check", Checking(directory=at.root, fix=True), Operator()
            )
            runs = [
                each.arguments for each in started.heard.runs if each.program == "ruff"
            ]
        assert isinstance(unfixed, Refused)
        assert isinstance(fixed, Accepted)
        fixing = runs.index(["format"])
        assert ["format", "--check"] in runs[fixing:]
        assert runs[:fixing] == [["format", "--check"]]

    @lup.promise
    async def outside_a_worktree_nothing_runs(self, by: Testing) -> None:
        """Typed outside any git worktree, the check is refused, and no step runs."""
        with tempfile.TemporaryDirectory() as scratch:
            nowhere = Path(scratch)
            started = await by.started(
                project(),
                programs={
                    "git": Scripted(answers=[Answering(status=128)]),
                    "ruff": Scripted(answers=[Answering()]),
                },
            )
            checked = await started.run(
                "gate", "check", Checking(directory=nowhere), by.any(Agent)
            )
        assert isinstance(checked, Refused)
        assert started.ran("ruff") == []
