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
    """How a project runs its tools in its environment.

    Its contract: a runner runs a tool by putting its own command before it, as
    `uv run`, `poetry run` and `conda run -n …` do. `command(tool)` is
    `command([])` followed by `tool`, and `judging(tool)` is `judging([])`
    followed by `tool`. The judge keeps a declaration it read as plain data, to
    stand in for one that can't load, so it keeps a project's runner as those
    commands and its environment's files (`Prefixed`) rather than as its class: a
    runner that rewrote the tool itself would be judged with other commands than
    it gives.
    """

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


class Prefixed(Runner):
    """A runner kept as the commands it puts before a tool, and its files.

    It's how the judge holds a project's runner, which may be a class of the
    project's own that the judge's kept data can't bring back. By `Runner`'s
    contract those commands are the whole of a runner, so the judge runs each
    tool as the project's runner gives it, a stand-in declaration's included.

    >>> kept = Prefixed.of(Uv())
    >>> kept.judging(["ruff"]) == Uv().judging(["ruff"])
    True
    >>> kept.environment() == Uv().environment()
    True
    """

    gate: list[str]
    """What the gate puts before a tool: the runner's `command([])`."""
    judge: list[str]
    """What the judge puts before a tool: the runner's `judging([])`."""
    files: list[str]
    """The files, from the root, whose change means another environment."""

    @classmethod
    def of(cls, runner: Runner) -> Prefixed:
        """Keep `runner` as the commands it puts before a tool, and its files."""
        return cls(
            gate=runner.command([]),
            judge=runner.judging([]),
            files=runner.environment(),
        )

    @override
    def command(self, tool: list[str]) -> list[str]:
        return [*self.gate, *tool]

    @override
    def judging(self, tool: list[str]) -> list[str]:
        return [*self.judge, *tool]

    @override
    def environment(self) -> list[str]:
        return self.files
