"""Setting a repository up's promises: what the operator typing `lup init` or `lup new` can count on.

Each runs the command through the harness, as the operator, in a temporary
directory, git and uv stood in for as each promise scripts them (`git` answering
as a repository there would), and reads what it answered and the files it
wrote, never its words (`README.md` here, *Promises*).
"""

import sys
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import lup
from lup import Model, Operator, Part, Project
from lup.testing import (
    Accepted,
    Answering,
    Refused,
    Repository,
    Responding,
    Scripted,
    Testing,
)

if TYPE_CHECKING:
    from collections.abc import Generator

COMMIT = "0123456789abcdef0123456789abcdef01234567"
"""The commit git says lup's own checkout is at."""


class Git(Model, Responding):
    """git, stood in for: answering what lup asks of a repository whose worktree is `root`, or of none where it's none, and making one where asked."""

    root: Path | None = None

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer what lup asks: a worktree's root, its shared directory, whether it's bare, a checkout's `HEAD`, or a repository made."""
        del given
        root = self.root
        match arguments:
            case ["-C", _, "rev-parse", "--show-toplevel"]:
                if root is None:
                    return Answering(status=128, error="fatal: not a git repository")
                return Answering(output=f"{root}\n")
            case ["-C", _, "rev-parse", "--path-format=absolute", "--git-common-dir"]:
                return Answering(output=f"{root}/.git\n")
            case ["-C", _, "config", "--bool", "core.bare"]:
                return Answering(output="false\n")
            case ["-C", _, "rev-parse", "HEAD"]:
                return Answering(output=f"{COMMIT}\n")
            case ["-C", _, "init"]:
                return Answering()
            case _:
                return None


class Missing(Model):
    """A program the command said isn't there."""

    name: str


class Done(Model):
    """What setting a repository up answered, as the command line prints it."""

    root: Path
    declaration: Path
    ignored: bool
    dependency: str
    module: Path | None = None
    missing: list[Missing] = []


class Taken(Model):
    """A name a new project can't take: the core's, one of the core's commands, or a package Python has."""

    name: Literal["core", "init", "new", "json"]


def standing(
    root: Path | None, lacking: str | None = None
) -> dict[str, Git | Scripted]:
    """Return git and uv stood in for, git answering for a repository at `root`, and uv doing whatever it's asked; without the one named `lacking`."""
    programs: dict[str, Git | Scripted] = {
        "git": Git(root=root),
        "uv": Scripted(answers=[Answering()]),
    }
    return {name: each for name, each in programs.items() if name != lacking}


def adding(run: list[str]) -> list[str]:
    """Return what `run` of uv added, where it's a `uv add`; nothing otherwise."""
    match run:
        case ["--directory", _, "add", "--no-sync", *requirements]:
            return requirements
        case _:
            return []


def added(runs: list[list[str]]) -> list[str]:
    """Return what each `uv add` among `runs` added, in order."""
    return [each for run in runs for each in adding(run)]


def entries(directory: Path) -> list[Path]:
    """List what `directory` holds."""
    return list(directory.iterdir())


@contextmanager
def importable(source: Path) -> Generator[None]:
    """Let the packages under `source` be imported while the block runs, as a project's environment installs them, then forget each imported from there."""
    sys.path.append(str(source))
    try:
        yield
    finally:
        sys.path.remove(str(source))
        imported = [
            name
            for name, module in list(sys.modules.items())
            if (file := getattr(module, "__file__", None)) is not None
            and Path(file).is_relative_to(source)
        ]
        for name in imported:
            del sys.modules[name]


class SetupPromises(Part):
    """What the operator setting a repository up for lup can count on."""

    @lup.promise
    async def init_declares_lups_defaults(self, by: Testing) -> None:
        """`lup init` in a repository writes a declaration that loads and resolves to lup's default modules, and adds lup's core to the project through uv, pinned to a commit."""
        with tempfile.TemporaryDirectory() as made:
            root = Path(made)
            started = await by.started(Project(), programs=standing(root))
            answered = await started.run(
                "core", "init", {"directory": str(root)}, Operator()
            )
            assert isinstance(answered, Accepted)
            done = Done.model_validate_json(answered.answer())
            assert done.declaration.parent == root
            declared = await by.started(
                Repository(declaration=done.declaration.read_text())
            )
            defaults = await by.started(Project())
            assert [each.name for each in declared.modules] == [
                each.name for each in defaults.modules
            ]
            assert added(started.ran("uv")) == [done.dependency]
            assert COMMIT in done.dependency

    @lup.promise
    async def init_never_overwrites_a_declaration(self, by: Testing) -> None:
        """`lup init` where a declaration is there already refuses, and leaves it, and everything else, as it was."""
        written = by.any(str).encode(errors="surrogatepass")
        with tempfile.TemporaryDirectory() as made:
            root = Path(made)
            declaration = root / "lup_project.py"
            declaration.write_bytes(written)
            started = await by.started(Project(), programs=standing(root))
            answered = await started.run(
                "core", "init", {"directory": str(root)}, Operator()
            )
            assert isinstance(answered, Refused)
            assert declaration.read_bytes() == written
            assert entries(root) == [declaration]
            assert added(started.ran("uv")) == []

    @lup.promise
    async def init_ignores_the_local_layer_once(self, by: Testing) -> None:
        """`lup init` leaves one line ignoring the repository's local layer in its `.gitignore`, adding it only where none was there, and keeps every line that was."""
        had = by.any(bool)
        ended = by.any(bool)
        ignoring = "/lup_project.local.py"
        before = "build/" + (f"\n{ignoring}" if had else "") + ("\n" if ended else "")
        with tempfile.TemporaryDirectory() as made:
            root = Path(made)
            (root / ".gitignore").write_text(before)
            started = await by.started(Project(), programs=standing(root))
            answered = await started.run(
                "core", "init", {"directory": str(root)}, Operator()
            )
            assert isinstance(answered, Accepted)
            done = Done.model_validate_json(answered.answer())
            lines = (root / ".gitignore").read_text().splitlines()
            assert lines.count(ignoring) == 1
            assert "build/" in lines
            assert done.ignored == (not had)

    @lup.promise
    async def init_writes_nothing_where_uv_refuses_the_core(self, by: Testing) -> None:
        """`lup init` where uv can't add lup's core to the project refuses, writing neither its declaration nor its gitignore line."""
        with tempfile.TemporaryDirectory() as made:
            root = Path(made)
            refusing = Scripted(
                answers=[
                    Answering(when=["--directory", str(root), "add"], status=1),
                    Answering(),
                ]
            )
            programs = {**standing(root), "uv": refusing}
            started = await by.started(Project(), programs=programs)
            answered = await started.run(
                "core", "init", {"directory": str(root)}, Operator()
            )
            assert isinstance(answered, Refused)
            assert entries(root) == []

    @lup.promise
    async def a_missing_program_refuses_with_nothing_written(self, by: Testing) -> None:
        """`lup init` and `lup new`, where git or uv isn't there, refuse before anything runs or is written."""
        lacking = "git" if by.any(bool) else "uv"
        new = by.any(bool)
        with tempfile.TemporaryDirectory() as made:
            root = Path(made)
            started = await by.started(Project(), programs=standing(root, lacking))
            if new:
                given = {"name": "orchard", "directory": str(root)}
                answered = await started.run("core", "new", given, Operator())
            else:
                given = {"directory": str(root)}
                answered = await started.run("core", "init", given, Operator())
            assert isinstance(answered, Refused)
            assert entries(root) == []
            assert started.ran("git") == []
            assert started.ran("uv") == []

    @lup.promise
    async def init_says_which_optional_programs_are_missing(self, by: Testing) -> None:
        """`lup init` says which programs lup's other parts run aren't there, podman among them, and none that is, at a version its part takes."""
        there = by.any(bool)
        with tempfile.TemporaryDirectory() as made:
            root = Path(made)
            fitting = Scripted(answers=[Answering(output="5.4.2\n")])
            podman = {"podman": fitting} if there else {}
            programs = {**standing(root), **podman}
            started = await by.started(Project(), programs=programs)
            answered = await started.run(
                "core", "init", {"directory": str(root)}, Operator()
            )
            assert isinstance(answered, Accepted)
            done = Done.model_validate_json(answered.answer())
            missing = [each.name for each in done.missing]
            assert ("podman" in missing) == (not there)
            assert all(each not in missing for each in ["git", "uv"])

    @lup.promise
    async def new_makes_a_project_selecting_its_own_module(self, by: Testing) -> None:
        """`lup new <name>` makes a project in a directory of that name, whose every Python file compiles and every TOML file reads, whose declaration loads and selects a module of its own, which is a member of its uv workspace."""
        with tempfile.TemporaryDirectory() as made:
            started = await by.started(Project(), programs=standing(None))
            given = {"name": "orchard", "directory": made}
            answered = await started.run("core", "new", given, Operator())
            assert isinstance(answered, Accepted)
            done = Done.model_validate_json(answered.answer())
            project = Path(made) / "orchard"
            assert done.root == project
            assert done.module is not None
            assert done.module.is_relative_to(project)
            for each in project.rglob("*.py"):
                compile(each.read_text(), str(each), "exec")
            for each in project.rglob("*.toml"):
                tomllib.loads(each.read_text())
            with importable(done.module / "src"):
                declared = await by.started(
                    Repository(declaration=done.declaration.read_text())
                )
            assert "orchard" in [each.name for each in declared.modules]
            assert ["-C", str(project), "init"] in started.ran("git")
            member = f"./{done.module.relative_to(project)}"
            assert member in added(started.ran("uv"))

    @lup.promise
    async def new_refuses_a_name_it_cant_take(self, by: Testing) -> None:
        """`lup new` refuses, with nothing run or written, a name that would shadow the core, one of `lup`'s commands, or a package Python has."""
        name = by.any(Taken).name
        with tempfile.TemporaryDirectory() as made:
            started = await by.started(Project(), programs=standing(None))
            given = {"name": name, "directory": made}
            answered = await started.run("core", "new", given, Operator())
            assert isinstance(answered, Refused)
            assert entries(Path(made)) == []
            assert started.ran("git") == []
            assert started.ran("uv") == []
