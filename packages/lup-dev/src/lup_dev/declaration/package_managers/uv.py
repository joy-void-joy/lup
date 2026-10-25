"""uv, as lup knows it: the environment it makes from a project's `uv.lock`, `Uv`, lup's default runner, and the package age its user-level settings keep in a room.

Everything lup asks of uv is spelled here (`docs/declaration.md`, *The runner*;
`docs/launch.md`, *The package age gate*).
"""

import tomllib
from datetime import timedelta
from pathlib import Path
from shlex import join
from typing import ClassVar, override

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import Field, TypeAdapter

from lup.rooms.container import Mount
from lup.types import Model
from lup_dev.confined import Confined
from lup_dev.declaration.package_managers.manager import (
    HomeSettings,
    PackageManager,
    Ungated,
)
from lup_dev.declaration.requirements import Printed, Requirement, Tools
from lup_dev.declaration.runner import (
    Interpreter,
    RoomEnvironment,
    RoomNeeds,
    RoomPlaces,
    Runner,
    RunnerError,
)


class UvSettings(Model):
    """uv's settings as a project gives them, in its `uv.toml` or its `pyproject.toml`'s `[tool.uv]`: the package age, where it sets one."""

    exclude_newer: str | None = Field(default=None, alias="exclude-newer")
    """A date or a duration, as uv takes it; none where it's unset."""


class UvProject(Model):
    """The part of a `pyproject.toml` uv reads a project's settings from, and its Python."""

    class Tool(Model):
        """`[tool]`, for `[tool.uv]`."""

        uv: UvSettings = UvSettings()

    class Project(Model):
        """`[project]`, for the Python it requires."""

        requires_python: str | None = Field(default=None, alias="requires-python")

    tool: Tool = Tool()
    project: Project = Project()


class UvManager(PackageManager):
    """uv as a room's package manager, keeping the package age in `~/.config/uv/uv.toml` as `exclude-newer`."""

    package = "uv"
    settings: ClassVar[Path] = Path(".config/uv/uv.toml")
    """Where uv reads its user-level settings, from the home: the room sets no
    `XDG_CONFIG_HOME`."""

    @override
    def aged(self, root: Path, age: timedelta) -> HomeSettings | Ungated:
        """Return `~/.config/uv/uv.toml` holding `age` as `exclude-newer`, where the project at `root` sets its own; else why it gets none.

        Where the project sets none, a user-level one changes the resolution its
        `uv.lock` records: the room's first `uv run` relocked it, downgrading
        what was newer than the age, and the host's next `uv run` relocked it
        again. Where it sets its own, that one outranks the user-level one, which
        leaves its lock alone and is what `uvx`, `uv tool` and `uv pip` read,
        since they read no project's settings. uv reads a project's settings from
        a `uv.toml` at its root where there's one, ignoring the `[tool.uv]` of a
        `pyproject.toml` beside it whatever the `uv.toml` sets, and from that
        `[tool.uv]` otherwise. The age is an ISO 8601 duration, as pydantic
        writes one (`docs/field-notes.md`, *User-level package age settings*).
        """

        def sets_its_own() -> bool:
            config = root / "uv.toml"
            if config.is_file():
                own = UvSettings.model_validate(tomllib.loads(config.read_text()))
                return own.exclude_newer is not None
            pyproject = root / "pyproject.toml"
            if not pyproject.is_file():
                return False
            project = UvProject.model_validate(tomllib.loads(pyproject.read_text()))
            return project.tool.uv.exclude_newer is not None

        span = TypeAdapter(timedelta).dump_python(age, mode="json")
        if not sets_its_own():
            return Ungated(
                why=(
                    "This project sets no `exclude-newer` of its own for uv (its "
                    "`uv.toml`, else its `pyproject.toml`'s `[tool.uv]`), so the "
                    "room gets none at the user level, which would have uv relock "
                    "a `uv.lock` resolved without it. `uvx`, `uv tool` and `uv pip` "
                    "there install packages of any age. Add `exclude-newer = "
                    f'"{span}"` to `[tool.uv]` to gate them, and the project\'s own '
                    "`uv run`."
                )
            )
        return HomeSettings(
            path=self.settings,
            text=(
                "# lup's package age, from the declaration's `Core.package_age`, "
                "for uv's tools: the project's own `exclude-newer` outranks it.\n"
                f'exclude-newer = "{span}"\n'
            ),
        )


class Uv(Runner):
    """The environment uv makes from the project's `uv.lock`: lup's default runner.

    >>> Uv().command(["ruff", "check"])
    ['uv', 'run', 'ruff', 'check']
    >>> Uv().judging(["lup-dev", "check"])
    ['env', '-u', 'VIRTUAL_ENV', 'uv', 'run', '--frozen', '--quiet', 'lup-dev', 'check']
    >>> Uv().venv()
    PosixPath('.venv')
    """

    requirements = [
        Requirement(
            tool="uv",
            why="runs the project's tools",
            install="https://docs.astral.sh/uv/getting-started/installation/",
            package=UvManager.package,
        )
    ]

    @override
    def command(self, tool: list[str]) -> list[str]:
        return ["uv", "run", *tool]

    @override
    def judging(self, tool: list[str]) -> list[str]:
        """Return `tool` run where uv puts the project, without relocking or syncing.

        `--frozen` reads `uv.lock` without relocking, so a gate run on a commit
        never writes it, and `VIRTUAL_ENV` is unset so the environment of the
        session running it isn't taken for the commit's.
        """
        return ["env", "-u", "VIRTUAL_ENV", "uv", "run", "--frozen", "--quiet", *tool]

    @override
    def environment(self) -> list[str]:
        return ["pyproject.toml", "uv.toml", "uv.lock", ".python-version"]

    @override
    def venv(self) -> Path | None:
        """Return `.venv`, where `uv run` makes the project's environment on the host.

        A `UV_PROJECT_ENVIRONMENT` in the host's variables, which moves it for the
        host's own `uv run`, isn't read: the judge reads `.venv`, or for a room's
        hook the room's own environment (`room`).
        """
        return Path(".venv")

    @override
    def room(self, root: Path, tools: Tools, places: RoomPlaces) -> RoomNeeds:
        """Give the room an environment of its own for each worktree, its files links into the cache in `places`, and mount uv's interpreters read-only where uv keeps them on the host.

        In the room:
        - lup's `uv` sets `UV_PROJECT_ENVIRONMENT` to the launch's environment
          of the worktree it runs in, an absolute path, which uv uses as it is;
          where the project has a `uv.lock`, `uv sync --frozen` makes the
          launch's worktree's at the room's start;
        - `UV_CACHE_DIR` is the cache in `places`, which the room mounts with the
          launch's environments, so an environment links into it rather than
          copying it: a project's own `cache-dir` doesn't apply in a room
          (`docs/launch.md`, *The project's environment, the room's own*);
        - `UV_PYTHON_INSTALL_DIR` names uv's store, mounted read-only at its host
          path, and `UV_PYTHON_DOWNLOADS=never` stops uv from fetching an
          interpreter into it.

        uv is asked from outside any project, with no settings file read
        (`--no-config`), so nothing of the worktree's decides what the room
        mounts and nothing in it runs. The interpreter is the one uv's store
        holds for the project's Python (`requested`), found among uv's managed
        interpreters alone, no virtual environment and no project consulted: the
        room's uv makes its environments from the store. Raise `RunnerError`
        where uv can't say, or its store holds no interpreter for the project.
        """

        def asked(*command: str) -> Printed:
            asking = ["uv", "--no-config", *command]
            return tools.run(asking)

        def failure(command: list[str], ran: Printed, *, why: str) -> RunnerError:
            message = (
                f"`{join(['uv', '--no-config', *command])}` failed with status "
                f"{ran.code}, so {why}"
            )
            return RunnerError(message)

        directory = ["python", "dir"]
        listed = asked(*directory)
        if listed.code != 0:
            raise failure(
                directory,
                listed,
                why="lup can't say what the room mounts for the project's environment",
            )
        store = Path(listed.output.strip())
        request = requested(root)
        finding = [
            "python",
            "find",
            "--managed-python",
            "--system",
            "--no-project",
            *request,
        ]
        found = asked(*finding)
        install = join(["uv", "python", "install", *request])
        if found.code != 0:
            raise failure(
                finding,
                found,
                why=(
                    "uv's store holds no Python for the project, which the room "
                    f"makes its environment from: `{install}` on the host puts one "
                    "there"
                ),
            )
        lock = root / "uv.lock"
        return RoomNeeds(
            mounts=[Mount(source=store, read_only=True)],
            env={
                "UV_CACHE_DIR": str(places.cache),
                "UV_PYTHON_INSTALL_DIR": str(store),
                "UV_PYTHON_DOWNLOADS": "never",
            },
            interpreter=Interpreter(
                home=Path(found.output.strip()).parent,
                remedy=f"run `{install}` on the host, which puts one in uv's store",
            ),
            environment=RoomEnvironment(
                variable="UV_PROJECT_ENVIRONMENT",
                programs=["uv"],
                making=["uv", "sync", "--frozen"] if lock.is_file() else [],
            ),
        )


def requested(root: Path) -> list[str]:
    r"""Return the Python the project at `root` asks for, as a request to `uv python find`: its `.python-version`, else its `requires-python`, else none.

    Only a version (`3.14`, `3.14.0`) or a version specifier (`>=3.14`) is asked
    for: uv runs a path it's asked for, to query it, and a room writes these
    files. Raise `RunnerError` for any other request uv takes, an
    implementation's name among them (`cpython@3.14`).

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as scratch:
    ...     root = Path(scratch)
    ...     _ = (root / "pyproject.toml").write_text(
    ...         '[project]\nname = "p"\nrequires-python = ">=3.14"\n'
    ...     )
    ...     without = requested(root)
    ...     _ = (root / ".python-version").write_text("# pinned\n3.14\n")
    ...     without, requested(root)
    (['>=3.14'], ['3.14'])
    """
    worktree = Confined(root=root)
    pinned = worktree.text(Path(".python-version"))
    lines = [] if pinned is None else pinned.splitlines()
    named = [
        line.strip() for line in lines if line.strip() and not line.startswith("#")
    ]
    if named:
        where, request = ".python-version", named[0]
    else:
        project = worktree.text(Path("pyproject.toml"))
        required = (
            None
            if project is None
            else UvProject.model_validate(
                tomllib.loads(project)
            ).project.requires_python
        )
        if required is None:
            return []
        where, request = "pyproject.toml", required
    if versioned(request):
        return [request]
    message = (
        f"The project's `{where}` asks for the Python `{request}`, which isn't a "
        "version or a version specifier: lup asks uv for no other, since uv runs "
        "an interpreter named by its path to query it. Name its version there."
    )
    raise RunnerError(message)


def versioned(request: str) -> bool:
    """Say whether `request` is a version or a version specifier, as `packaging` reads them.

    >>> versioned("3.14"), versioned(">=3.12,<3.15"), versioned("/tmp/python3")
    (True, True, False)
    """
    try:
        Version(request)
    except InvalidVersion:
        try:
            SpecifierSet(request)
        except InvalidSpecifier:
            return False
    return True
