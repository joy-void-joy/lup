"""A module's parts: the classes it lists in its `parts` field, each grouping methods behind lup's doors.

A part is made once where it runs, as its container starts, so it may keep what
it holds between calls: a connection, a cache, a count (`README.md` here,
*Parts*). What must outlast it, or be read by others, it keeps in the core's
store.

Where it runs follows from what it holds. A part holding nothing runs in its
project's container. One holding a secret (a field typed `Secret`), the
operator's machine (`machine=True`) or anything else only approved code may
hold (`approved=True`) runs in a container of its own, from a commit the
operator approved, with what it holds alone, or on the machine.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Unpack, override

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError

from lup.declaration.errors import ProjectError
from lup.declaration.grammar import Named
from lup.doors.door import DoorError, Method, RefusedError
from lup.types import Model, MutableModel
lazy from lup.declaration.module import Module


class Secret(Model):
    """A secret a class holds: a field typed `Secret`, filled where the class runs with the value the operator stored under the field's name.

    Its value is never shown or written out with the class: it's left out of
    how the class prints and of its JSON.

    >>> token = Secret(value="hunter2")
    >>> token, token.model_dump()
    (Secret(), {})
    """

    value: str = Field(repr=False, exclude=True)
    """The secret itself."""


class Data(Model):
    """A directory a part keeps what it writes in: a field typed `Data`, given where the part runs, kept across its restarts, one for each such field.

    >>> Data(path=Path("/srv/lup/data/chat.Bot/cache")).path.name
    'cache'
    """

    path: Path
    """The directory: it's there, and the part's alone to write."""


class Runtime(Model):
    """A directory a part keeps what lasts only while it runs in: a field typed `Runtime`, given where the part runs, in memory, gone when the machine restarts, one for each such field: a socket, or a value handed over to be read once.

    >>> Runtime(path=Path("/run/user/1000/lup/hosting.Carrying/sockets")).path.name
    'sockets'
    """

    path: Path
    """The directory: it's there, and the part's alone to write."""


class Finished(Model):
    r"""How a program a part ran ended: its status, and what it printed and said, as the bytes it wrote.

    >>> Finished(status=1, error=b"no such image\n").said()
    'no such image'
    """

    status: int
    output: bytes = b""
    """What it printed on its standard output."""
    error: bytes = b""
    """What it wrote on its standard error."""

    def text(self) -> str:
        """Return what it printed, as text, a byte that isn't UTF-8 replaced."""
        return self.output.decode(errors="replace")

    def said(self) -> str:
        """Return what it wrote on its standard error, as text, without the blank around it, as a refusal quotes it."""
        return self.error.decode(errors="replace").strip()


class Runs(ABC):
    """What runs the programs a part declares, where it runs: the machine's own, or a stand-in a promise scripts."""

    @abstractmethod
    async def ran(
        self,
        program: Program,
        arguments: list[str],
        given: bytes | None,
        env: dict[str, str],
    ) -> Finished:
        """Run `program` with `arguments`, `given` on its input, `env` set beside the variables it runs with, and say how it ended, whatever its status.

        Raise `ProgramError` where it can't be run at all.
        """


class ProgramError(RefusedError):
    """A program a part declares can't be run: it isn't there, isn't at a version the part takes, or nothing runs programs where the part does; the call needing it is refused, saying why."""


class Program(Model, arbitrary_types_allowed=True):
    """A program a part runs, from outside its project's environment: a field typed `Program`, its default saying which, checked before the part starts, and run through the field.

    >>> Program(name="podman", version=">=5", probe=["--version"]).name
    'podman'
    """

    name: str
    """The program, as the `PATH` finds it."""
    version: str | None = None
    """The versions that will do, as a specifier (`>=5`); none for any."""
    probe: list[str] = []
    """The arguments that make it print its bare version, where `version` is
    given."""
    optional: bool = False
    """Whether its part may go without it: missing, the part doesn't start,
    said once, and nothing else stops."""
    why: str = ""
    """What the part runs it for, said where it's missing."""
    install: str = ""
    """How to install it, said where it's missing."""
    runs: Runs | None = Field(default=None, exclude=True, repr=False)
    """What runs it where the part runs, given as the part is made."""

    async def ran(
        self,
        *arguments: str,
        given: bytes | str | None = None,
        env: dict[str, str] | None = None,
    ) -> Finished:
        """Run it with `arguments`, `given` on its input, text as UTF-8, `env` set beside the variables it runs with, and say how it ended, whatever its status.

        Raise `ProgramError` where it can't be run.
        """
        if self.runs is None:
            message = (
                f"`{self.name}` is run where its part runs, which gives it what "
                "runs programs; nothing does here"
            )
            raise ProgramError(message, about=[self.name])
        sent = given.encode() if isinstance(given, str) else given
        return await self.runs.ran(self, list(arguments), sent, dict(env or {}))


class Given(Model, arbitrary_types_allowed=True):
    """What lup gives a part where it runs, beside its module: the secrets it holds, where it keeps its data, and what runs its programs."""

    secrets: dict[str, str] = {}
    """Each secret's value, by its name."""
    data: Path | None = None
    """The part's own directory, under which each field typed `Data` gets
    one; none where nothing gives it one."""
    runtime: Path | None = None
    """The part's own directory in memory, under which each field typed
    `Runtime` gets one; none where nothing gives it one."""
    runs: Runs | None = None
    """What runs the programs it declares; none where nothing runs any."""


class Holds(Model):
    """What a part holds, which only code the operator approved may: where it runs follows from it."""

    secrets: list[str] = []
    """The secrets it holds, by their names: its fields typed `Secret`."""
    machine: bool = False
    """Whether it runs on the operator's machine itself, outside any container."""
    approved: bool = False
    """Whether it holds something else only approved code may, as the store
    holds the operator's acts."""
    shared: bool = False
    """Whether it's one for the whole machine, serving every project, as the
    store is: run once, from the home repository's approved code."""

    def anything(self) -> bool:
        """Say whether it holds anything, and so runs apart, from approved code."""
        return bool(self.secrets) or self.machine or self.approved or self.shared


class Part(MutableModel, arbitrary_types_allowed=True):
    """A part of a module: its methods, each behind one of lup's doors, made once where it runs.

    A subclass that reads its module's settings declares `module`, typed as its
    module's class (`module: Echo`), and lup hands it the module, every layer
    applied. Its other fields are what it keeps while it runs, each with a
    default, but a `Secret`, which lup fills; what it holds says where it runs
    (`holds`).

    It says in its header what it holds beyond its secrets:
    `class Notices(Part, machine=True)` runs on the operator's machine,
    `class Store(Part, approved=True)` holds what only approved code may.
    """

    machine: ClassVar[bool] = False
    """Whether it runs on the operator's machine itself: its header's word."""
    approved: ClassVar[bool] = False
    """Whether it holds what only approved code may: its header's word."""
    shared: ClassVar[bool] = False
    """Whether it's one for the whole machine, serving every project: its
    header's word."""

    def __init_subclass__(
        cls,
        *,
        machine: bool | None = None,
        approved: bool | None = None,
        shared: bool | None = None,
        **kwargs: Unpack[ConfigDict],
    ) -> None:
        """Keep what the class's header says it holds, a subclass keeping its base's where it says nothing."""
        super().__init_subclass__(**kwargs)
        if machine is not None:
            cls.machine = machine
        if approved is not None:
            cls.approved = approved
        if shared is not None:
            cls.shared = shared

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Refuse a field of the class's own with no default, but a `Secret`, which lup fills, and a method named as a field, which the field would hide: lup makes the class with its module and its secrets alone."""
        super().__pydantic_init_subclass__(**kwargs)
        hidden = [
            f"`{field}`"
            for field, info in cls.model_fields.items()
            if isinstance(info.default, Method)
        ]
        if hidden:
            message = (
                f"`{cls.__name__}`'s method {', '.join(hidden)} takes the name of a "
                "field of its model, which hides it: name it otherwise"
            )
            raise DoorError(message, about=[cls.__name__])
        bare = [
            f"`{field}`"
            for field, info in cls.model_fields.items()
            if field != "module"
            and info.is_required()
            and info.annotation not in (Secret, Data, Runtime)
        ]
        if bare:
            message = (
                f"`{cls.__name__}` holds {', '.join(bare)} with no default: lup "
                "makes a part with its module and its "
                "secrets alone, so what it keeps starts from a default"
            )
            raise ProjectError(message, about=[cls.__name__])

    @classmethod
    def holds(cls) -> Holds:
        """Return what the class holds: its secrets, and what its header says."""
        return Holds(
            secrets=[
                field
                for field, info in cls.model_fields.items()
                if info.annotation is Secret
            ],
            machine=cls.machine,
            approved=cls.approved,
            shared=cls.shared,
        )

    @classmethod
    def made(cls, module: Module, given: Given) -> Part:
        """Make the part where it runs, with its module and what lup gives it: the value of each secret it holds, a directory for each field typed `Data` or `Runtime`, made where it isn't there, and what runs each program it declares.

        Raise `ProjectError` where a secret it holds isn't given, or it keeps
        data, or what lasts while it runs, and no directory is given.
        """
        secrets, data, runtime = given.secrets, given.data, given.runtime
        kept = [
            field for field, info in cls.model_fields.items() if info.annotation is Data
        ]
        lasting = [
            field
            for field, info in cls.model_fields.items()
            if info.annotation is Runtime
        ]
        if kept and data is None:
            message = (
                f"`{cls.__name__}` keeps data in {', '.join(f'`{name}`' for name in kept)}, "
                "and nothing gives it a directory to keep it in"
            )
            raise ProjectError(message, about=[cls.__name__])
        if lasting and runtime is None:
            message = (
                f"`{cls.__name__}` keeps what lasts while it runs in "
                f"{', '.join(f'`{name}`' for name in lasting)}, and nothing gives it "
                "a directory in memory to keep it in"
            )
            raise ProjectError(message, about=[cls.__name__])
        missing = [name for name in cls.holds().secrets if name not in secrets]
        if missing:
            message = (
                f"`{cls.__name__}` holds {', '.join(f'`{name}`' for name in missing)}, "
                "which nothing stored: the operator stores each under its name"
            )
            raise ProjectError(message, about=[cls.__name__])
        fields: dict[str, Module | Secret | Data | Runtime | Program] = {
            name: Secret(value=secrets[name]) for name in cls.holds().secrets
        }
        for name in kept:
            if data is not None:
                directory = data / name
                directory.mkdir(parents=True, exist_ok=True)
                fields[name] = Data(path=directory)
        for name in lasting:
            if runtime is not None:
                directory = runtime / name
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                fields[name] = Runtime(path=directory)
        for name, program in cls.programs().items():
            fields[name] = program.model_copy(update={"runs": given.runs})
        if "module" in cls.model_fields:
            fields["module"] = module
        return cls.model_validate(fields)

    @classmethod
    def programs(cls) -> dict[str, Program]:
        """Return each program the part declares, by its field's name, as its default says."""
        return {
            field: info.default
            for field, info in cls.model_fields.items()
            if isinstance(info.default, Program)
        }

    @classmethod
    def admits(cls, module: Module) -> bool:
        """Say whether the class can be made with `module`: whether the `module` it declares, where it does, is typed as that module's class."""
        # lup: ignore("dict-literal-key", why="pydantic lists a model's fields in a dict by name, and `module` is the one lup hands a class")
        declared = cls.model_fields.get("module")
        if declared is None or declared.annotation is None:
            return True
        try:
            TypeAdapter[object](declared.annotation).validate_python(module)
        except ValidationError:
            return False
        return True


class Parts(Named[type[Part]]):
    """A module's parts, each named by its class's name.

    `Parts.of(EchoPart)`; a module may hold several, and a project drops one by
    its class's name, `Parts().drop("EchoPart")`. Each is made with the module
    holding it, so a part reading its module types `module` as that module's
    class.
    """

    @override
    def named(self, entry: type[Part]) -> str:
        return entry.__name__
