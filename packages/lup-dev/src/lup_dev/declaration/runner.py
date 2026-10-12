"""How a project runs its tools: `uv` spelled once, in `Uv`, for the gate and the judge.

Everything that runs a tool in the project's environment derives its command from
the project's runner (`docs/declaration.md`, *The runner*). Two commands, since the
gate may make and sync the environment, while the judge must never write the
project's files, `uv.lock` among them. A runner brings its own requirements, so a
project whose runner is `Plain()` needs no uv.
"""

from abc import ABC, abstractmethod
from typing import ClassVar, override

from lup.types import Model
from lup_dev.declaration.requirements import Requirement


class Runner(Model, ABC):
    """How a project runs its tools in its environment."""

    requirements: ClassVar[list[Requirement]] = []
    """What it needs from outside the project's environment, checked with the
    requirements of the module holding it."""

    @abstractmethod
    def command(self, tool: list[str]) -> list[str]:
        """Return the command the gate runs `tool` with: it may make or sync the environment."""

    @abstractmethod
    def judging(self, tool: list[str]) -> list[str]:
        """Return the command the judge runs `tool` with: it never writes the project's files."""

    @abstractmethod
    def environment(self) -> list[str]:
        """List the files, from the root, whose change means another environment."""


class Uv(Runner):
    """The environment uv makes from the project's `uv.lock`: lup's default.

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


class Plain(Runner):
    """Each tool as the `PATH` finds it, for a project with no environment manager.

    >>> Plain().command(["pytest"]), Plain().environment()
    (['pytest'], [])
    """

    @override
    def command(self, tool: list[str]) -> list[str]:
        return tool

    @override
    def judging(self, tool: list[str]) -> list[str]:
        return tool

    @override
    def environment(self) -> list[str]:
        return []
