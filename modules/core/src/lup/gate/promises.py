"""The gate's promises: what an agent or the operator typing `lup gate check` in a worktree can count on.

Each runs the check through the harness on a scratch repository in a temporary
directory, git run for real (`lup.testing.RealGit`) and each step's program
stood in for as the promise scripts it (ruff laying out what it's given), and
reads what ran, where, in what order, and whether the check was refused, never
its words (`README.md` here, *Promises*).
"""

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import lup
from lup import (
    Agent,
    Model,
    Module,
    Modules,
    Operator,
    Part,
    Project,
    Step,
    Steps,
)
from lup.testing import (
    Accepted,
    Answering,
    RealGit,
    Refused,
    Responding,
    Scripted,
    Testing,
)
lazy from lup import Gate

if TYPE_CHECKING:
    from collections.abc import Generator

LAID_OUT = "laid = 'out'\n"
"""What a Python file holds once ruff's formatter, as the promises stand it in, has laid it out."""
LOCAL = "lup_project.local.py"
"""The repository's own layer of the declaration, which its `.gitignore` ignores."""


class Checking(Model):
    """What the gate is asked, as `lup gate check` takes it."""

    fix: bool = False
    again: bool = False
    directory: Path | None = None


class Worktree(Model):
    """A scratch repository's worktree in a temporary directory, a clone's."""

    root: Path

    def python(self) -> list[Path]:
        """List the Python files of the worktree, outside its git directory, but the local layer, which git ignores."""
        return sorted(
            each
            for each in self.root.rglob("*.py")
            if ".git" not in each.relative_to(self.root).parts and each.name != LOCAL
        )


class Ruff(Model, Responding):
    """ruff's formatter, stood in for: a Python file is laid out where it holds `LAID_OUT`, which its fix writes."""

    worktree: Worktree

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Check the worktree's layout, or lay it out."""
        del given
        python = self.worktree.python()
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
    """Return a project of lup's default modules, the gate among them, and one declaring a step of its own; `Private`, whose step the promises don't stand in for, dropped."""
    return Project(
        modules=Modules.default()
        .drop(
            "private",
            why="the promises stand in for the gate's steps and the project's own alone",
        )
        .add(Noting())
    )


def formatting() -> Project:
    """Return a project of lup's default modules, its gate the format step alone and its fix, so nothing runs beside it; `Private`, whose step would, dropped."""
    alone = Steps.of(
        Step(
            name="format", command=["ruff", "format", "--check"], fix=["ruff", "format"]
        )
    )
    return Project(
        modules=Modules.default()
        .drop("private", why="its step would run beside the format step")
        .edit(Gate(steps=alone))
    )


@contextmanager
def worktree(*, laid_out: bool = True) -> Generator[Worktree]:
    """Make a scratch repository in a temporary directory, its one commit holding a Python file, laid out where `laid_out`, and a `.gitignore` ignoring the local layer."""
    with tempfile.TemporaryDirectory() as scratch:
        git = RealGit()
        root = git.made(Path(scratch) / "project")
        git.committed(
            root,
            {
                "main.py": LAID_OUT if laid_out else "laid='out'\n",
                ".gitignore": f"/{LOCAL}\n",
                "docs/README.md": "the project\n",
            },
        )
        yield Worktree(root=root)


def standing(
    at: Worktree, failing: str | None = None
) -> dict[str, RealGit | Ruff | Scripted]:
    """Return git, run for real, and every step's program stood in for over the worktree `at`, each step passing but the program named `failing`."""

    def ending(name: str) -> Scripted:
        return Scripted(answers=[Answering(status=1 if name == failing else 0)])

    return {
        "git": RealGit(),
        "ruff": Ruff(worktree=at),
        "pytest": ending("pytest"),
        "lint-imports": ending("lint-imports"),
        "python": ending("python"),
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
                "gate", "check", Checking(directory=at.root / "docs"), party
            )
            stepped = [each for each in started.heard.runs if each.program != "git"]
        assert isinstance(checked, Refused if failing else Accepted)
        assert all(
            name in [each.program for each in stepped]
            for name in ["ruff", "pytest", "lint-imports", "python", "notes"]
        )
        assert all(each.cwd == at.root for each in stepped)

    @lup.promise
    async def a_pass_runs_nothing_again_on_the_same_files(self, by: Testing) -> None:
        """Once the gate passed on a worktree's files, checking the same files again runs no step, unless it's asked to run again; a file changed, or the repository's own layer of the declaration changed, runs every step."""
        with worktree() as at:
            started = await by.started(formatting(), programs=standing(at))
            asking = Checking(directory=at.root)

            async def stepped(checking: Checking) -> list[str]:
                before = len(started.heard.runs)
                checked = await started.run("gate", "check", checking, Operator())
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
        assert all("ruff" in each for each in [first, again, layered, changed])

    @lup.promise
    async def a_fix_runs_before_any_step_checks(self, by: Testing) -> None:
        """Asked to fix, the gate runs each step's fix before any step checks, so the files are checked as the fixes left them; unasked, it fixes nothing."""
        with worktree(laid_out=False) as at:
            started = await by.started(formatting(), programs=standing(at))
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
        assert all("--check" in each for each in runs[:fixing])
        assert any("--check" in each for each in runs[fixing:])

    @lup.promise
    async def a_heavy_import_fails_the_declaration_step(self, by: Testing) -> None:
        """The `declaration` step fails where loading the declaration imports a distribution lup doesn't need, naming it, and passes where it imports lup and the standard library alone.

        It loads a declaration in a fresh interpreter, which nothing in the
        harness's process can stand in for, so this runs it, and git, for real,
        in a temporary directory, as the programs' promises do.
        """
        del by
        light = "import json\n\nfrom lup import Project\n\nproject = Project()\n"
        heavy = f"import hypothesis\n\n{light}"
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            lup.programs.run("git", "init", "--quiet", cwd=root)
            declaration = root / "lup_project.py"
            weighing = [sys.executable, "-m", "lup.environment.weighing"]
            declaration.write_text(light)
            passed = lup.programs.run(*weighing, cwd=root, checked=False)
            declaration.write_text(heavy)
            failed = lup.programs.run(*weighing, cwd=root, checked=False)
        assert passed.status == 0
        assert failed.status != 0
        assert "hypothesis" in failed.text()

    @lup.promise
    async def outside_a_worktree_nothing_runs(self, by: Testing) -> None:
        """Typed outside any git worktree, the check is refused, and no step runs."""
        with tempfile.TemporaryDirectory() as scratch:
            nowhere = Path(scratch)
            started = await by.started(
                project(),
                programs={
                    "git": RealGit(),
                    "ruff": Scripted(answers=[Answering()]),
                },
            )
            checked = await started.run(
                "gate", "check", Checking(directory=nowhere), Agent.of("gate")
            )
        assert isinstance(checked, Refused)
        assert started.ran("ruff") == []
