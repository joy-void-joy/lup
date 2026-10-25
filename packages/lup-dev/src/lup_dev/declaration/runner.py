"""How a project runs its tools, for the gate and the room, and where its environment is, for the judge: `Runner`, and `Plain` for a project with no environment manager.

Everything that runs a tool in the project's environment derives its command from
the project's runner (`docs/declaration.md`, *The runner*); lup's default, `Uv`,
is uv's, beside the rest of what lup knows of uv
(`lup_dev.declaration.package_managers.uv`). Two commands, since the gate may make
and sync the environment, while a gate run on a commit must never write the
project's files, `uv.lock` among them. The host never runs a project's
environment: the judge reads it as files, from the directory the runner names
(`venv`). A runner brings its own requirements, so a project whose runner is
`Plain()` needs no uv. It also says what a room needs for an environment of its
own, made outside the repository in the launch's own directory, each
worktree's fresh at each launch, while the host's is hidden from the room
(`docs/launch.md`, *The project's environment, the room's own*).
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

    home: Path
    """The directory holding it, as the runner finds it on the host without
    running anything of the project's: that of the interpreter the room's
    environment is made from."""
    remedy: str
    """How to give the room an interpreter it mounts, said when this one
    resolves outside every mount."""


class RoomPlaces(Model):
    """Where a launch keeps what its room's environments need, outside the repository: in the project's rooms' own directory, which the room mounts read-write at its host path (`lup_dev.layout.RoomsLayout`)."""

    cache: Path
    """The runner's package cache, which the project's rooms share: in the one
    mount with the environments, so an environment made there links into it."""


class RoomEnvironment(Model):
    """How the runner's tools in a room are told the environment of the worktree they run in, which the launch makes in its own directory rather than in the worktree.

    lup's program, first on the room's `PATH` under each of `programs`' names,
    sets `variable` to that worktree's environment, then runs the real program
    (`lup_dev/environments.py`); the host's judge reads the same environment,
    for a hook of the room.
    """

    variable: str
    """The variable naming the environment's directory to the runner's tools,
    as an absolute path: uv's `UV_PROJECT_ENVIRONMENT`."""
    programs: list[str]
    """The programs that read it, each wrapped: `uv`."""
    making: list[str] = []
    """The command making the launch's worktree's environment, which the room
    runs in the background at its start, through the wrapped programs, so the
    judge reads it from the session's first write; none where there's nothing to
    make."""


class RoomNeeds(Model):
    """What a room mounts and sets so the project's environment works inside it, at its host paths."""

    mounts: list[Mount] = []
    env: dict[str, str] = {}
    """The variables the room sets for it."""
    interpreter: Interpreter | None = None
    """The environment's interpreter, which must resolve under the room's mounts;
    none for a runner with no environment of its own."""
    environment: RoomEnvironment | None = None
    """How the room's tools find each worktree's environment, the launch's own;
    none where the room has no environment of its own."""


# lup: ignore("interface-shape", why="`docs/declaration.md` puts `venv()` and `room()` on the runner beside its commands and files, so a project's own runner must say where the judge reads its environment and what a room mounts for it")
class Runner(Model, ABC):
    """How a project runs its tools in its environment, where that environment is, and what a room needs for it.

    Its contract: a runner runs a tool by putting its own command before it, as
    `uv run`, `poetry run` and `conda run -n …` do. `command(tool)` is
    `command([])` followed by `tool`, and `judging(tool)` is `judging([])`
    followed by `tool`. The judge keeps a declaration it read as plain data, to
    stand in for one that can't load, so it keeps a project's runner as those
    commands, its environment's directory and its files (`Prefixed`) rather than
    as its class: a runner that rewrote the tool itself would be run with other
    commands than it gives.
    """

    requirements: ClassVar[list[Requirement]] = []
    """What it needs from outside the project's environment, checked with the
    requirements of the module holding it."""

    @abstractmethod
    def command(self, tool: list[str]) -> list[str]:
        """Return the command the gate runs `tool` with: it may make or sync the environment."""

    @abstractmethod
    def judging(self, tool: list[str]) -> list[str]:
        """Return the command a gate run on a commit runs `tool` with: it never writes the project's files.

        `lup-dev check --at` runs the commit's own gate so, in the room, for a
        push and for `land`'s merge (`lup_dev.gate`, `at_commit`).
        """

    @abstractmethod
    def environment(self) -> list[str]:
        """List the files, from the root, whose change means another environment."""

    @abstractmethod
    def venv(self) -> Path | None:
        """Return the directory of the project's virtual environment, from the worktree's root or absolute; none where it has none.

        It holds the environment's `pyvenv.cfg` and its `site-packages`, as
        `python -m venv`, uv and poetry's in-project environments do. The judge
        reads it as files, on the host, and never runs anything in it: the engine
        gives pyright its `site-packages`, the paths its `.pth` files list, and the
        Python its `pyvenv.cfg` records. This is the host's: a room hides it where
        it's inside the worktree, and has an environment of its own where `room()`
        names one, which the judge reads for the room's hooks.
        """

    @abstractmethod
    def room(self, root: Path, tools: Tools, places: RoomPlaces) -> RoomNeeds:
        """Say what a room mounts and sets for the environment of the worktree at `root`, its own kept in `places`.

        Asked on the host as a launch builds the room, through `tools`, which a
        test stubs.
        """


class Plain(Runner):
    """Each tool as the `PATH` finds it, for a project with no environment manager.

    With no environment of its own, the judge reads the project's own files and
    the standard library's stubs alone.

    >>> Plain().command(["pytest"]), Plain().environment(), Plain().venv()
    (['pytest'], [], None)
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
    def venv(self) -> Path | None:
        return None

    @override
    def room(self, root: Path, tools: Tools, places: RoomPlaces) -> RoomNeeds:
        """Mount nothing: the tools on the room's `PATH` are the image's own."""
        return RoomNeeds()


class Prefixed(Runner):
    """A runner kept as the commands it puts before a tool, its environment's directory, and its files.

    It's how the judge holds a project's runner, which may be a class of the
    project's own that the judge's kept data can't bring back. By `Runner`'s
    contract those commands are the whole of a runner, so each tool runs as the
    project's runner gives it, and the judge reads the environment it names, a
    stand-in declaration's included.

    >>> from lup_dev.declaration.package_managers.uv import Uv
    >>> kept = Prefixed.of(Uv())
    >>> kept.judging(["ruff"]) == Uv().judging(["ruff"])
    True
    >>> kept.environment() == Uv().environment(), kept.venv() == Uv().venv()
    (True, True)
    """

    gate: list[str]
    """What the gate puts before a tool: the runner's `command([])`."""
    judge: list[str]
    """What a gate run on a commit puts before a tool: the runner's `judging([])`."""
    files: list[str]
    """The files, from the root, whose change means another environment."""
    directory: Path | None = None
    """The environment's directory, the runner's `venv()`. A declaration kept
    before runners named one has none, so it's judged with no environment until a
    declaration loads."""

    @classmethod
    def of(cls, runner: Runner) -> Prefixed:
        """Keep `runner` as the commands it puts before a tool, its environment's directory, and its files."""
        return cls(
            gate=runner.command([]),
            judge=runner.judging([]),
            files=runner.environment(),
            directory=runner.venv(),
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
    def venv(self) -> Path | None:
        return self.directory

    @override
    def room(self, root: Path, tools: Tools, places: RoomPlaces) -> RoomNeeds:
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
