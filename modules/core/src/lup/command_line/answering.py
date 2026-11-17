"""What the command line hands a call to, and what typing words on it did.

The command line parses words into a call that crosses (`lup.running.wire`), and
hands it to an answerer (`Answerer`), which sends it where it's answered and
returns its reply: in this process, over a project's parts started here
(`lup.environment.command_line.InProcess`), or through the program on the
operator's machine, which names who calls from the socket a call came in on.
Who calls is the answerer's to say, never the command line's, and so is what
they may run: the command line offers only what the plan the answerer offers
lets that party call (`README.md` here).
"""

from abc import ABC, abstractmethod

from lup.running.plan import Doorway, Plan
from lup.running.wire import Call, Caller, Reply
from lup.types import Model


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
            if way.door in ("tool", "command", "view") and party in way.parties
        ]

    def modules(self) -> list[str]:
        """List the modules with something `by` may call, by name, in the plan's order."""
        within = [each.module for each in self.runnable()]
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
    """What the help it showed lists, as each is typed: the modules, or one
    module's tools, commands and views; none where it showed no such list."""
    call: Call | None = None
    """The call it made; none where nothing ran."""
    reply: Reply | None = None
    """What the call's answerer replied; none where nothing ran."""
