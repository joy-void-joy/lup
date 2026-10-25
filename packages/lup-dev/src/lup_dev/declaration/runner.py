"""How a project runs its tools, for the gate, the judge and the room: `Runner`, and `Plain` for a project with no environment manager.

Everything that runs a tool in the project's environment derives its command from
the project's runner (`docs/declaration.md`, *The runner*); lup's default, `Uv`,
is uv's, beside the rest of what lup knows of uv
(`lup_dev.declaration.package_managers.uv`). Two commands, since the
gate may make and sync the environment, while the judge must never write the
project's files, `uv.lock` among them. A runner brings its own requirements, so a
project whose runner is `Plain()` needs no uv. It also says what a room mounts so
the environment works inside it, the one environment shared with the host
(`docs/launch.md`, *The project's environment, shared with the host*).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, override

from lup.rooms.container import Mount
from lup.types import Model
from lup_dev.declaration.requirements import Requirement, Tools
from lup_dev.errors import LupDevError


class RunnerError(LupDevError):
    """A runner that couldn't say what a room needs for the project's environment."""


class Interpreter(Model):
    """The interpreter a project's environment runs on, which a room must reach."""

    path: Path
    """As the runner finds it: the environment's own link to it, or the
    interpreter the environment would be made from."""
    remedy: str
    """How to move the environment onto an interpreter a room mounts, said when
    this one resolves outside every mount."""


class RoomNeeds(Model):
    """What a room mounts and sets so the project's environment works inside it, at its host paths."""

    mounts: list[Mount] = []
    env: dict[str, str] = {}
    """The variables the room sets for it."""
    interpreter: Interpreter | None = None
    """The environment's interpreter, which must resolve under the room's mounts;
    none for a runner with no environment of its own."""


# lup: ignore("interface-shape", why="`docs/launch.md` puts `room()` on the runner beside its three commands, so a project's own runner must say what a room mounts for its environment")
class Runner(Model, ABC):
    """How a project runs its tools in its environment, and what a room needs for it.

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

    @abstractmethod
    def room(self, root: Path, tools: Tools) -> RoomNeeds:
        """Say what a room mounts and sets for the environment of the worktree at `root`.

        Asked on the host as a launch builds the room, through `tools`, which a
        test stubs.
        """


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

    @override
    def room(self, root: Path, tools: Tools) -> RoomNeeds:
        """Mount nothing: the tools on the room's `PATH` are the image's own."""
        return RoomNeeds()


class Prefixed(Runner):
    """A runner kept as the commands it puts before a tool, and its files.

    It's how the judge holds a project's runner, which may be a class of the
    project's own that the judge's kept data can't bring back. By `Runner`'s
    contract those commands are the whole of a runner, so the judge runs each
    tool as the project's runner gives it, a stand-in declaration's included.

    >>> from lup_dev.declaration.package_managers.uv import Uv
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

    @override
    def room(self, root: Path, tools: Tools) -> RoomNeeds:
        """Refuse: a runner kept for judging holds its commands, not what a room mounts.

        A launch builds its room from a declaration that loaded, whose runner is
        the project's own.
        """
        message = (
            "a runner kept as its commands, standing in for a declaration that "
            "can't load, can't say what a room mounts: launch from a declaration "
            "that loads"
        )
        raise RunnerError(message)
