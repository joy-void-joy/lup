"""uv, as lup knows it: the environment it makes from a project's `uv.lock`, `Uv`, lup's default runner, and the package age its user-level settings keep in a room.

Everything lup asks of uv is spelled here (`docs/declaration.md`, *The runner*;
`docs/launch.md`, *The package age gate*).
"""

import tomllib
from datetime import timedelta
from pathlib import Path
from shlex import join
from typing import ClassVar, override

from pydantic import Field, TypeAdapter

from lup.rooms.container import Mount
from lup.types import Model
from lup_dev.declaration.package_managers.manager import (
    HomeSettings,
    PackageManager,
    Ungated,
)
from lup_dev.declaration.requirements import Requirement, Tools
from lup_dev.declaration.runner import Interpreter, RoomNeeds, Runner, RunnerError


class UvSettings(Model):
    """uv's settings as a project gives them, in its `uv.toml` or its `pyproject.toml`'s `[tool.uv]`: the package age, where it sets one."""

    exclude_newer: str | None = Field(default=None, alias="exclude-newer")
    """A date or a duration, as uv takes it; none where it's unset."""


class UvProject(Model):
    """The part of a `pyproject.toml` uv reads a project's settings from."""

    class Tool(Model):
        """`[tool]`, for `[tool.uv]`."""

        uv: UvSettings = UvSettings()

    tool: Tool = Tool()


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
    >>> Uv().judging(["python"])
    ['env', '-u', 'VIRTUAL_ENV', 'uv', 'run', '--frozen', '--quiet', 'python']
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

        `--frozen` reads `uv.lock` without relocking, so the judge never writes
        it, and `VIRTUAL_ENV` is unset so the judge's own environment, which it
        inherits, isn't taken for the project's.
        """
        return ["env", "-u", "VIRTUAL_ENV", "uv", "run", "--frozen", "--quiet", *tool]

    @override
    def environment(self) -> list[str]:
        return ["pyproject.toml", "uv.toml", "uv.lock", ".python-version"]

    @override
    def room(self, root: Path, tools: Tools) -> RoomNeeds:
        """Mount uv's interpreters read-only and its cache read-write, where uv keeps them on the host.

        uv is asked from `root`, whose configuration may move either, and with
        `VIRTUAL_ENV` unset, as the judge runs it. The worktree's `.venv` links
        to an interpreter in uv's store, so mounting the store at its path makes
        the one environment valid in the room as on the host. In the room,
        `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR` name the same two places, and
        `UV_PYTHON_DOWNLOADS=never` stops uv from fetching an interpreter: with
        the environment's interpreter missing, `uv run` set about remaking the
        shared `.venv` (`docs/field-notes.md`, *Rooms*). The cache is made if
        it's missing, since a mount needs its source. The interpreter is the one
        `uv python find` names: the environment's own link, or where there's no
        environment yet, the interpreter uv would make it from.
        """

        def asked(*command: str) -> Path:
            asking = [
                "env",
                "-u",
                "VIRTUAL_ENV",
                "uv",
                "--directory",
                str(root),
                *command,
            ]
            ran = tools.run(asking)
            if ran.code != 0:
                message = (
                    f"`{join(asking)}` failed with status {ran.code}, so lup can't "
                    "say what the room mounts for the project's environment"
                )
                raise RunnerError(message)
            return Path(ran.output.strip())

        store = asked("python", "dir")
        cache = asked("cache", "dir")
        interpreter = asked("python", "find")
        cache.mkdir(parents=True, exist_ok=True)
        return RoomNeeds(
            mounts=[Mount(source=store, read_only=True), Mount(source=cache)],
            env={
                "UV_CACHE_DIR": str(cache),
                "UV_PYTHON_INSTALL_DIR": str(store),
                "UV_PYTHON_DOWNLOADS": "never",
            },
            interpreter=Interpreter(
                path=interpreter,
                remedy=(
                    "run `uv sync --managed-python` in the project, which remakes "
                    "`.venv` on a Python uv manages, installing one if there's none"
                ),
            ),
        )
