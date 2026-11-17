"""The command line, its environment side: its calls answered in this process, `lup`'s own script, and a project's.

`InProcess` answers the command line's calls over a project's parts started in
this process at the first call, each as their container answers it
(`lup.environment.running.container.answered`), by the party whoever made it
names. It starts the parts that hold nothing and those whose every secret is
given; a call to another is refused, saying which secret it needs or that it
runs apart, on the operator's machine.

`main` is `lup`, over the declaration of the worktree it runs in, with its
layers. `command_line(name, *modules)` makes a project's own command: its
modules, run by whoever runs it, its parts' secrets read from the environment
and `.env` files; in development, the declaration of the worktree its code is
tracked in, with its layers (`lup/command_line/README.md`).
"""

import asyncio
import inspect
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from pydantic import TypeAdapter
from pydantic_settings import DotEnvSettingsSource, EnvSettingsSource

from lup.command_line.answering import Answerer, Offered
from lup.declaration.errors import ProjectError
from lup.declaration.grammar import listed
from lup.declaration.layout import MachineLayout, RepositoryLayout
from lup.declaration.module import Modules
from lup.declaration.project import Project
from lup.doors.door import Rejection, served
from lup.doors.parties import Operator
from lup.doors.parts import Runs, variable
from lup.environment.declaration import Resolved, read, resolve
from lup.environment.doors import Running
from lup.environment.running.calling import Calling
from lup.environment.running.container import REPLIES, answered
from lup.environment.running.loader import Loader, LoaderError, Places
from lup.environment.running.planning import plan_of
from lup.environment.running.programs import Local
from lup.environment.settings import LupSettings
from lup.programs import ProgramFailedError, run
from lup.running.plan import CORE, typed
from lup.running.wire import (
    Call,
    Caller,
    CommandCalled,
    Declined,
    Reply,
    ServiceCalled,
    ToolCalled,
    ViewCalled,
)
from lup.running.wire import (
    read as read_reply,
)
from lup.setup.part import Setup
from lup.types import MutableModel, Settings
lazy from lup.command_line import line
lazy from lup.environment.setup import SettingUp

if TYPE_CHECKING:
    from collections.abc import Callable

    from lup.declaration.module import Module
    from lup.doors.parts import Holds
    from lup.errors import LupError
    from lup.running.plan import PartPlan

CALLS = TypeAdapter[Call](Call)


class InProcess(MutableModel, Answerer, arbitrary_types_allowed=True):
    """The command line's calls answered in this process: a project's parts started here at the first call, and each call answered as their container answers it, by the party whoever made this names."""

    by: Caller
    """Who every call is by: whoever runs the command line, as whoever made
    this vouches."""
    resolved: Resolved
    """The project's declaration, resolved."""
    repository: str
    """The repository whose code runs: who a service its code calls is called
    by."""
    secrets: dict[str, str] = {}
    """The value of each secret a part holds, by its name, as given."""
    command: str | None = None
    """The project's command, whose name the environment variable holding a
    secret starts with (`variable`); none where secrets aren't read from the
    environment, so a part holding one runs apart."""
    running: Running | None = None
    """The parts started here, once a call has come."""
    runs: Runs | None = None
    """What runs the programs the parts started here declare; none where
    nothing does, and a part's program is refused."""
    offering: list[str] | None = None
    """The modules whose methods it offers, by name: those a project's own
    command is given, never the core's, which are lup's development side; none
    for every module the project resolves to, as `lup` offers them."""

    async def offered(self) -> Offered:
        """Return who the calls are by, and the project's plan, of the modules it offers alone."""
        plan = plan_of(self.resolved, [])
        offering = self.offering
        return Offered(
            by=self.by, plan=plan if offering is None else plan.only(offering)
        )

    def startable(self) -> list[str]:
        """Name each part started here, `module.Part`: those holding nothing beyond secrets, every one of which is given."""
        return [
            each.named()
            for each in self.resolved.doors.served
            if self.here(each.part.holds())
        ]

    def here(self, holds: Holds) -> bool:
        """Say whether a part holding `holds` is started here: it holds nothing but secrets, each given."""
        apart = holds.machine or holds.approved or holds.shared
        return not apart and all(each in self.secrets for each in holds.secrets)

    def elsewhere(self, part: PartPlan) -> str:
        """Say why a call to `part`, which isn't started here, can't be answered here: the secrets it needs, or that it runs apart."""
        missing = [each for each in part.holds.secrets if each not in self.secrets]
        apart = part.holds.machine or part.holds.approved or part.holds.shared
        if missing and not apart and self.command is not None:
            named = [variable(self.command, each) for each in missing]
            return (
                f"`{part.named()}` holds {listed(missing)}, given here by the "
                f"environment variable {listed(named)}, or a line of `.env` or "
                "`.env.local` setting it, which isn't set"
            )
        return (
            f"`{part.named()}` runs apart, from the commit the operator approved, "
            "through lup's program on their machine, which this command line "
            "doesn't reach"
        )

    def serving(self, call: Call) -> PartPlan | None:
        """Return the part `call` reaches, as the plan routes it; none where no part serves it."""
        plan = plan_of(self.resolved, [])
        match call:
            case ToolCalled(tool=name):
                return plan.serving("tool", name)
            case ServiceCalled(service=name):
                return plan.serving("service", name)
            case CommandCalled(module=module, command=name):
                return plan.serving("command", name, module)
            case ViewCalled(module=module, view=name):
                return plan.serving("view", name, module)

    async def answered(self, call: Call) -> Reply:
        """Answer `call` over the parts started here, starting them at the first, as their container answers it, by the party this names; refused where its part isn't started here, saying why."""
        part = self.serving(call)
        if part is not None and part.named() not in self.startable():
            rejection = Rejection(submitted=call.given, reason=self.elsewhere(part))
            return Declined(rejection=rejection)
        if self.running is None:
            self.running = await self.resolved.doors.started(
                self.repository, self.secrets, only=self.startable(), runs=self.runs
            )
        made = call.model_copy(update={"by": self.by})
        text = await answered(
            self.running, CALLS.dump_json(made), looks=self.resolved.looks
        )
        return read_reply(text, REPLIES)

    async def stopped(self) -> None:
        """Stop the parts started here, if a call started them."""
        if self.running is not None:
            await self.running.stopped()
            self.running = None


def ran(answerer: Answerer, name: str, words: list[str], top: str | None) -> NoReturn:
    """Run the command line called `name` on `words` over `answerer`, the methods of the module named `top` typed at its top level, printing what it prints, stop what it started in this process, and end with its status."""

    async def running() -> int:
        try:
            done = await line.typed(
                words, answerer, name, sys.stdout, sys.stderr, top=top
            )
        finally:
            await answerer.stopped()
        return done.status

    raise SystemExit(asyncio.run(running()))


def refused(name: str, failure: LupError) -> NoReturn:
    """End the command line called `name`, saying why it can't run: its declaration doesn't load, or it isn't in a repository."""
    sys.stderr.write(f"{name}: {failure}\n")
    raise SystemExit(1)


def machine() -> MachineLayout:
    """Return where this machine keeps the layer every repository on it reads."""
    return MachineLayout(configuration=LupSettings().xdg_config_home)


def setting_up(words: list[str]) -> bool:
    """Say whether `words` name one of lup's own commands setting a repository up, `lup init` or `lup new`.

    >>> setting_up(["init"]), setting_up(["new", "--help"]), setting_up(["hosting"])
    (True, True, False)
    """
    match line.reached(words):
        case [first, *_]:
            return first in [typed(name) for name in served(Setup)]
        case _:
            return False


def main() -> None:
    """Run `lup` on the words it's given, through lup's program on the operator's machine, which says who calls: over the socket `LUP_CALLING` names, as in a room, else over the machine's own, the machine started first where nothing answers there.

    Through the program, nothing of the project's code runs here: the command
    line lists and parses the plan the program offers. Where podman isn't
    there, as in a room no lup started, no machine is started: `lup` answers
    in this process, as the operator, over the declaration of the worktree it
    runs in, and says so.

    `lup init` and `lup new` come first: they're lup's own program acting on
    the operator's machine, writing their files and running their git and uv,
    never a project's code, so they're answered here, as the operator, over
    lup's default modules alone, before any declaration is read, then register
    the repository with the machine (`SettingUp`, `lup/setup/README.md`).
    """
    words = sys.argv[1:]
    if setting_up(words):
        lups = SettingUp(
            by=Operator(), resolved=resolve(Project()), repository="lup", runs=Local()
        )
        ran(lups, "lup", words, CORE)
    calling = LupSettings().lup_calling
    try:
        layout = RepositoryLayout.found(Path.cwd())
        if calling is None and shutil.which("podman") is not None:
            loader = Loader(
                places=Places.found(),
                machine=machine(),
                interactive=sys.stdin.isatty(),
            )
            calling = asyncio.run(loader.ensured())
            said = asyncio.run(loader.reviewed(calling, layout))
            if said is not None:
                sys.stderr.write(f"lup: {said}\n")
        if calling is not None:
            ran(
                Calling(socket=calling, repository=layout.main.name),
                "lup",
                words,
                CORE,
            )
        sys.stderr.write(
            "lup: podman isn't here, so no machine runs: this answers in this "
            "process, over this worktree's declaration\n"
        )
        resolved = resolve(read(layout, machine()).project)
    except (ProgramFailedError, ProjectError, LoaderError) as failure:
        refused("lup", failure)
    answerer = InProcess(
        by=Operator(),
        resolved=resolved,
        repository=layout.main.name,
        runs=Local(),
    )
    ran(answerer, "lup", words, CORE)


def developed(modules: list[Module]) -> Project | None:
    """Return the declaration, with its layers, of the worktree tracking the code of one of `modules`, where it holds one: a project's command in development; none where none does, as installed.

    Where the code lives says it, not where the command runs, so an installed
    command run inside another project's worktree never reads that project's
    declaration.
    """
    for module in modules:
        source = Path(inspect.getfile(type(module)))
        try:
            layout = RepositoryLayout.found(source.parent)
        except ProgramFailedError:
            continue
        tracked = run(
            "git",
            "ls-files",
            "--error-unmatch",
            "--",
            str(source),
            cwd=layout.root,
            checked=False,
        )
        if tracked.status == 0 and layout.declaration.is_file():
            return read(layout, machine()).project
    return None


class Secrets(Settings):
    """Where a project's command reads the secrets its parts hold: the environment, and `.env` files, as pydantic's settings read them."""


def secrets_of(name: str, held: list[str]) -> dict[str, str]:
    """Return the value of each secret in `held` that's set: by the environment variable named after the command `name` and it (`HARMON_TOKEN`), or a line of `.env` or `.env.local` in the current directory setting it, the environment first, then `.env.local`, then `.env`.

    Variables are read as pydantic's settings read them, whatever their case.
    """
    environment = EnvSettingsSource(Secrets).env_vars
    files = DotEnvSettingsSource(Secrets, env_file=[".env", ".env.local"]).env_vars
    keys = {each: variable(name, each).lower() for each in held}
    found = {each: environment.get(key) or files.get(key) for each, key in keys.items()}
    return {each: value for each, value in found.items() if value is not None}


def command_line(name: str, *modules: Module) -> Callable[[], None]:
    """Return a project's own command, called `name`: the command line over lup's default modules and `modules`, run in this process by whoever runs it, for a project's `[project.scripts]` to name.

    It offers the methods of `modules` alone, the first's at its top level and
    the others' under their names, never the core's, which are lup's
    development side: `harmon` isn't `lup`. In development, where one of
    `modules` is code a worktree tracks and that worktree holds a declaration,
    the declaration, with its layers, says the modules and their settings
    instead (`developed`). Each secret a part holds is read from the
    environment (`secrets_of`).
    """

    def main() -> None:
        try:
            project = developed(list(modules)) or Project(
                modules=Modules.default().add(*modules)
            )
            resolved = resolve(project)
        except ProjectError as failure:
            refused(name, failure)
        held = [
            secret
            for each in resolved.doors.served
            for secret in each.part.holds().secrets
        ]
        answerer = InProcess(
            by=Operator(),
            resolved=resolved,
            repository=name,
            secrets=secrets_of(name, list(dict.fromkeys(held))),
            command=name,
            runs=Local(),
            offering=[each.name for each in modules],
        )
        ran(answerer, name, sys.argv[1:], modules[0].name if modules else None)

    return main
