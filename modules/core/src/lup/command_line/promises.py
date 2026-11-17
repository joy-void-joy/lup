"""The command line's promises: what someone typing on it, the operator in their terminal or an agent in their room, can count on.

Each is checked through the harness over the example modules defined here,
words typed as a party types them (`Started.typed`), what it did read from
what it answers: what its help listed, the call it made, what it printed and
how it ended, never the words of its help or of a refusal (`README.md` here,
*Promises*).
"""

import json
from typing import Literal

from pydantic import Field

import lup
from lup import (
    Agent,
    Blocks,
    Line,
    Model,
    Module,
    Modules,
    Operator,
    Part,
    Parts,
    Project,
)
from lup.testing import Accepted, Testing


class Jotted(Model):
    """A jot, as it's typed: its text an argument, the rest options."""

    text: str
    loud: bool = False
    tags: list[str] = []
    shade: Literal["dark", "light"] = "dark"
    times: int = Field(default=1, ge=1, le=9)


class PileOf(Model):
    """Which pile of jots to show."""

    pile: str


class Count(Model):
    """How many jots were made."""

    jotted: int


class Asking(Model):
    """Nothing to give."""


class Clearing(Model):
    """Which jot to clear."""

    number: int = Field(ge=0, le=99)


class Jotting(Part):
    """Jots, made by the operator or an agent, cleared by the operator alone."""

    jotted: int = 0

    @lup.command
    async def jot_down(self, jotted: Jotted, by: Agent | Operator) -> Jotted:
        """Jot something down, answering what was jotted."""
        self.jotted += 1
        return jotted

    @lup.command
    async def clear(self, clearing: Clearing, by: Operator) -> str:
        """Clear a jot."""
        return f"cleared {clearing.number}"

    @lup.tool(reads=True)
    async def count(self, _asking: Asking) -> Count:
        """Say how many jots were made."""
        return Count(jotted=self.jotted)

    @lup.view
    async def pile(self, of: PileOf) -> Blocks:
        """Show a pile of jots."""
        return Blocks.of(Line.of("1", of.pile), Line.of("2", "the end"))


class Jot(Module):
    """Jots in piles: an example module the command line's promises type at."""

    name = "jot"
    parts: Parts = Parts.of(Jotting)


class Sealing(Part):
    """What only the operator runs."""

    @lup.command
    async def seal(self, clearing: Clearing, by: Operator) -> str:
        """Seal a jot."""
        return f"sealed {clearing.number}"


class Seal(Module):
    """Sealing jots: a module with nothing an agent may run."""

    name = "seal"
    parts: Parts = Parts.of(Sealing)


def jotting() -> Project:
    """Return a project of lup's default modules, the jots and the seal."""
    return Project(modules=Modules.default().add(Jot(), Seal()))


def words(jotted: Jotted) -> list[str]:
    """Return the words that type `jotted` for `jot down`, each option given its value in its own word, and the text after `--`, so no value reads as an option."""
    return [
        "jot",
        "jot-down",
        *(["--loud"] if jotted.loud else []),
        *(f"--tags={each}" for each in jotted.tags),
        f"--shade={jotted.shade}",
        f"--times={jotted.times}",
        "--",
        jotted.text,
    ]


class CommandLinePromises(Part):
    """What someone typing on the command line can count on."""

    @lup.promise
    async def help_lists_only_what_the_party_may_run(self, by: Testing) -> None:
        """The help lists the modules with something the party typing may run, and, under a module, its tools, commands and views their `by` admits: the operator's commands for the operator, an agent's tools for an agent, a view for both."""
        started = await by.started(jotting())
        agent = by.any(Agent)
        top = await started.typed(["--help"], Operator())
        assert top.listed is not None
        assert all(each in top.listed for each in ["jot", "seal"])
        theirs = await started.typed(["--help"], agent)
        assert theirs.listed is not None
        assert "jot" in theirs.listed
        assert "seal" not in theirs.listed
        operators = await started.typed(["jot", "--help"], Operator())
        agents = await started.typed(["jot"], agent)
        assert operators.listed is not None
        assert agents.listed is not None
        assert all(each in operators.listed for each in ["jot-down", "clear", "pile"])
        assert "count" not in operators.listed
        assert all(each in agents.listed for each in ["jot-down", "count", "pile"])
        assert "clear" not in agents.listed
        assert all(each.status == 0 and each.call is None for each in [top, agents])

    @lup.promise
    async def an_agent_cant_run_the_operators_command(self, by: Testing) -> None:
        """A command for the operator alone, typed by an agent in their room, isn't run: nothing is called, and the line ends failed; typed by the operator, it runs."""
        number = by.any(Clearing).number
        started = await by.started(jotting())
        refused = await started.typed(["jot", "clear", str(number)], by.any(Agent))
        assert refused.call is None
        assert refused.status != 0
        sealed = await started.typed(["seal", "seal", str(number)], by.any(Agent))
        assert sealed.call is None
        ran = await started.typed(["jot", "clear", str(number)], Operator())
        assert ran.call is not None
        assert ran.status == 0

    @lup.promise
    async def a_missing_argument_is_refused_with_nothing_run(self, by: Testing) -> None:
        """A command typed without an argument it needs is refused as the words are read: nothing is called, nothing changes, nothing is asked for, and the line ends failed."""
        started = await by.started(jotting())
        party = by.any(Agent) if by.any(bool) else Operator()
        typed = await started.typed(["jot", "jot-down"], party)
        assert typed.call is None
        assert typed.status != 0
        counted = await started.call("count", Asking(), by.any(Agent))
        assert isinstance(counted, Accepted)
        assert counted.output == Count(jotted=0)

    @lup.promise
    async def a_command_prints_what_it_answers(self, by: Testing) -> None:
        """A command's fields are its arguments and options, a flag a `bool`'s and a repeated option a `list`'s, and what it answers is printed: a model as its JSON, words as they are."""
        jotted = by.any(Jotted)
        started = await by.started(jotting())
        typed = await started.typed(words(jotted), by.any(Agent))
        assert typed.status == 0
        assert json.loads(typed.output) == jotted.model_dump(mode="json")
        number = by.any(Clearing).number
        cleared = await started.typed(["jot", "clear", str(number)], Operator())
        answered = await started.run(
            "jot", "clear", Clearing(number=number), Operator()
        )
        assert isinstance(answered, Accepted)
        assert isinstance(answered.output, str)
        assert cleared.output.splitlines() == answered.output.splitlines()

    @lup.promise
    async def a_view_prints_its_text(self, by: Testing) -> None:
        """A view typed by whoever may read it prints its text, what the operator sees said in lines (`Blocks.text`)."""
        pile = by.any(PileOf)
        started = await by.started(jotting())
        reader = by.any(Agent) if by.any(bool) else Operator()
        typed = await started.typed(["jot", "pile", "--", pile.pile], reader)
        viewed = await started.view("jot", "pile", pile, reader)
        assert isinstance(viewed, Accepted)
        assert isinstance(viewed.output, Blocks)
        assert typed.status == 0
        assert typed.output.splitlines() == viewed.output.text().splitlines()
