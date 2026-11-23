"""What the command line hands a call to, and what typing words on it did.

The command line parses words into a call that crosses (`lup.running.wire`), and
hands it to an answerer (`Answerer`), which sends it where it's answered and
returns its reply: in this process, over a project's parts started here
(`lup.environment.command_line.InProcess`), or through the program on the
operator's machine, which names who calls from the socket a call came in on,
but a command marked to run where it's typed, which this process answers over
the worktree's declaration (`Here`).
Who calls is the answerer's to say, never the command line's, and so is what
they may run: the command line offers only what the plan the answerer offers
lets that party call (`README.md` here).
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import get_args

from lup.doors.door import Rejection
from lup.errors import LupError
from lup.running.plan import Doorway, Offerable, Plan
from lup.running.wire import Call, Caller, CommandCalled, Declined, Reply, ViewCalled
from lup.shell.kinds import Verb
from lup.types import Model, MutableModel

SHOW = "show"
"""The verb that shows what's cited, the view its block opens, rather than run
a command it offers."""

TOOLS = "tool"
"""The group every tool the party may call is typed under: `lup tool concern …`."""

CITED = "cited"
"""The name of the view showing what's cited, with what it offers: the
inbox's (`Inboxes.cited`)."""


class Runnable(Model):
    """One method the command line offers: its module, and how calls to it are routed."""

    module: str
    """Its module's name, which the command line runs it under."""
    doorway: Doorway


class Offered(Model):
    """What an answerer offers the command line: who the calls it sends are by, and the plan of the project it sends them to."""

    by: Caller
    """Who the calls are by, as whoever carries them names them."""
    plan: Plan
    """The project's plan, of which the command line offers what `by` may
    call: each tool, command and view whose doorway names their party."""

    def runnable(self) -> list[Runnable]:
        """List each tool, command and view `by` may call, in the plan's order."""
        party = type(self.by).__name__
        return [
            Runnable(module=part.module, doorway=way)
            for part in self.plan.parts
            for way in part.doorways
            if way.door in get_args(Offerable.__value__) and party in way.parties
        ]

    def named(self) -> list[Runnable]:
        """List each command and view `by` may call that's typed by its name, in the plan's order: those reached by no verb."""
        return [
            each
            for each in self.runnable()
            if each.doorway.door != "tool" and each.doorway.verb is None
        ]

    def tools(self) -> list[Runnable]:
        """List each tool `by` may call, in the plan's order: typed under `tool`."""
        return [each for each in self.runnable() if each.doorway.door == "tool"]

    def verbs(self) -> list[Verb]:
        """List each verb a command `by` may run is reached by, as its module declares it, in the order declared; `show`, where `by` may read what's cited."""
        used = [each.doorway.verb for each in self.runnable() if each.doorway.verb]
        showing = [SHOW] if self.cited() is not None else []
        return [
            each.kind
            for each in self.plan.looks.verbs
            if each.kind.name in used or each.kind.name in showing
        ]

    def cited(self) -> Runnable | None:
        """Return the view showing what's cited, where `by` may read it (`lup <verb> <thing>`, `Inboxes.cited`); none where they may not."""
        return next(
            (
                each
                for each in self.runnable()
                if each.doorway.door == "view" and each.doorway.name == CITED
            ),
            None,
        )

    def alone(self, verb: str) -> Runnable | None:
        """Return the command `by` may run that `verb` runs with nothing cited; none where there's none."""
        return next(
            (
                each
                for each in self.runnable()
                if each.doorway.verb == verb and each.doorway.alone
            ),
            None,
        )

    def offered(self, module: str, command: str) -> Runnable | None:
        """Return the command named `command` of the module named `module` that `by` may run; none where there's none."""
        return next(
            (
                each
                for each in self.runnable()
                if each.module == module
                and each.doorway.door == "command"
                and each.doorway.name == command
            ),
            None,
        )

    def modules(self) -> list[str]:
        """List the modules with something `by` may call by its name, by name, in the plan's order."""
        within = [each.module for each in self.named()]
        named = [each.name for each in self.plan.modules]
        return [
            *(name for name in named if name in within),
            *(name for name in dict.fromkeys(within) if name not in named),
        ]

    def described(self, module: str) -> str:
        """Return the module named `module`'s one sentence, or nothing where the plan says none."""
        return next(
            (each.description for each in self.plan.modules if each.name == module), ""
        )

    def summarized(self, module: str) -> str:
        """Return what help lists the module named `module` by, its summary, or nothing where the plan says none."""
        return next(
            (each.summary for each in self.plan.modules if each.name == module), ""
        )


class Answerer(ABC):
    """What carries the command line's calls to where they're answered, and says who they're by.

    Each carries them its own way: in this process, over a project's parts
    started here, or through the program on the operator's machine, from a room
    or the operator's terminal.
    """

    @abstractmethod
    async def offered(self) -> Offered:
        """Return who the calls are by and the plan of the project they go to: what the command line offers, and parses words for."""

    @abstractmethod
    async def answered(self, call: Call) -> Reply:
        """Send `call` where it's answered, by whoever `offered` says, and return its reply: what it answered, or why it's refused.

        The call says nobody makes it: whoever carries it says who does, the
        program on the operator's machine from the socket it came in on.
        """

    @abstractmethod
    async def stopped(self) -> None:
        """Stop what answering started where the command line runs, as it ends: a project's parts started in this process; nothing where the calls went elsewhere."""


class Here(MutableModel, Answerer, arbitrary_types_allowed=True):
    """The command line's calls carried through `through`, but a command marked to run where it's typed, which the answerer `here` makes answers in this process, over the worktree's declaration.

    `through` is lup's program on the operator's machine, as a room and the
    operator's terminal reach it: it says who the calls are by, and offers the
    plan whose commands say which run where they're typed
    (`Doorway.here`). `here` makes the answerer for those, by the party
    `through` names, at the first such call, so the worktree's declaration is
    read only where one is typed; where it can't be (`LupError`, a
    declaration that doesn't load among it), the call is refused, saying why.
    """

    through: Answerer
    here: Callable[[Caller], Answerer]
    made: Answerer | None = None
    """The answerer `here` made, once a command marked to run here came."""

    async def offered(self) -> Offered:
        """Return what `through` offers: who the calls are by, and the plan it runs."""
        return await self.through.offered()

    async def answered(self, call: Call) -> Reply:
        """Answer `call` in this process where it's a command `through`'s plan marks to run where it's typed, else send it through."""
        offered = await self.through.offered()
        match call:
            case (
                CommandCalled(module=module, command=name)
                | ViewCalled(module=module, view=name)
            ) if any(
                way.door == call.kind and way.name == name and way.here
                for part in offered.plan.parts
                if part.module == module
                for way in part.doorways
            ):
                try:
                    made = self.made or self.here(offered.by)
                except LupError as unmade:
                    reason = (
                        f"`{name}` of `{module}` runs where it's typed, over this "
                        f"worktree's declaration, which can't be read: {unmade}"
                    )
                    return Declined(
                        rejection=Rejection(submitted=call.given, reason=reason)
                    )
                self.made = made
                return await made.answered(call)
            case _:
                return await self.through.answered(call)

    async def stopped(self) -> None:
        """Stop what each answerer started here."""
        await self.through.stopped()
        if self.made is not None:
            await self.made.stopped()


class Typed(Model):
    """What the command line did with the words typed: what it printed, how it ended, what the help it showed listed, and the call it made."""

    status: int
    """Its exit status: 0 where it ran a call or showed help, 1 where the call
    was refused, 2 where the words didn't parse, so nothing ran."""
    output: str = ""
    """What it printed on its standard output."""
    error: str = ""
    """What it printed on its standard error."""
    listed: list[str] | None = None
    """What the help it showed lists, as each is typed: at the top, the tools,
    commands and views of the module typed there and the other modules; under
    a module, its own; none where it showed no such list."""
    call: Call | None = None
    """The call it made; none where nothing ran."""
    reply: Reply | None = None
    """What the call's answerer replied; none where nothing ran."""
