"""uv, as lup knows it: `Uv`, the environment it makes from a project's `uv.lock`, lup's default runner.

Everything lup asks of uv is spelled here (`docs/declaration.md`, *The runner*).
"""

from pathlib import Path
from shlex import join
from typing import override

from lup.rooms.container import Mount
from lup_dev.declaration.requirements import Requirement, Tools
from lup_dev.declaration.runner import Interpreter, RoomNeeds, Runner, RunnerError


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
            package="uv",
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
