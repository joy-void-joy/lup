"""The command line's promises: what someone typing on it, the operator in their terminal or an agent in their room, can count on.

Each is checked through the harness over the example modules defined here,
words typed as a party types them (`Started.typed`), what it did read from
what it answers: what its help listed, the call it made, what it printed and
how it ended, never the words of its help or of a refusal (`README.md` here,
*Promises*).
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

import lup
from lup import (
    Agent,
    Blocks,
    Common,
    Line,
    Model,
    Module,
    Modules,
    Operator,
    Part,
    Parts,
    Project,
    ProjectError,
    Repository,
)
from lup.testing import Accepted, Testing, TypedIn, raises
lazy from lup import Core


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


class Posting(Model):
    """A jot posted to a repository's board, kept where git keeps the repository: both filled from where it's typed, where they're left out."""

    text: str
    repository: Repository
    common: Common


type Named = Literal["harmon", "lup-next.git", "story_2"]
"""A repository's name, as lup takes one."""


class Typing(Model):
    """Where a promise types: in a repository's worktree, or outside any, and another repository it names."""

    within: Named | None
    other: Named
    """Another repository, which `-r` names."""


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

    @lup.command
    async def post(self, posting: Posting, by: Operator) -> Posting:
        """Post a jot to a repository's board, answering what was posted."""
        return posting

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


class Stamping(Part):
    """A command a project adds to the core, as the core's own are typed: at `lup`'s top level."""

    @lup.command
    async def stamp(self, clearing: Clearing, by: Operator) -> str:
        """Stamp a jot."""
        return f"stamped {clearing.number}"


class Stamp(Module):
    """A module named as a command of the core's is typed."""

    name = "stamp"


class Tallied(Model):
    """Which lup answered a tally, and who it was for."""

    where: str
    by: str


class Tallying(Part):
    """Tallies, one run where it's typed and one carried to where the project runs."""

    module: Tally

    @lup.command(here=True)
    async def tally(self, _asking: Asking, by: Agent | Operator) -> Tallied:
        """Tally the worktree it's typed in."""
        return Tallied(where=self.module.where, by=type(by).__name__)

    @lup.command
    async def peek(self, _asking: Asking, by: Agent | Operator) -> Tallied:
        """Peek at the tally where the project runs."""
        return Tallied(where=self.module.where, by=type(by).__name__)


class Tally(Module):
    """Tallying: a module with a command run where it's typed, saying which lup answers."""

    name = "tally"
    where: str = "machine"
    """Which lup this is, as its tallies say."""
    parts: Parts = Parts.of(Tallying)


def jotting() -> Project:
    """Return a project of lup's default modules, the jots and the seal."""
    return Project(modules=Modules.default().add(Jot(), Seal()))


def stamping() -> Project:
    """Return a project of lup's default modules, the core given a command of the project's own, the jots and the seal."""
    return Project(
        modules=Modules.default()
        .edit(Core(parts=Parts().add(Stamping)), why="a command typed at the top")
        .add(Jot(), Seal())
    )


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
    async def a_repository_left_out_is_the_one_typed_in(self, by: Testing) -> None:
        """A field naming a repository, or where git keeps it, left out, is the repository whose worktree the command line is typed in, and `-r` names another; typed outside any worktree, it's refused unless named, and nothing runs."""
        typing = by.any(Typing)
        started = await by.started(jotting())
        within = typing.within
        where = TypedIn(
            directory=Path("/srv/work"),
            repository=within,
            common=None if within is None else Path("/srv") / f"{within}.git",
        )
        other = Path("/srv") / f"{typing.other}.git"
        left = await started.typed(["jot", "post", "hi"], Operator(), typed_in=where)
        named = await started.typed(
            ["jot", "post", "-r", typing.other, f"--common={other}", "hi"],
            Operator(),
            typed_in=where,
        )
        assert named.status == 0
        posted = Posting.model_validate_json(named.output)
        assert (posted.repository, posted.common) == (typing.other, other)
        if within is None:
            assert left.call is None
            assert left.status != 0
        else:
            assert left.status == 0
            filled = Posting.model_validate_json(left.output)
            assert (filled.repository, filled.common) == (within, where.common)

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

    @lup.promise
    async def the_cores_methods_are_typed_at_the_top(self, by: Testing) -> None:
        """The core's tools, commands and views are typed at `lup`'s top level, without its name, and listed there beside the other modules, each typed by its name; the core is never typed by its own."""
        number = by.any(Clearing).number
        started = await by.started(stamping())
        top = await started.typed(["--help"], Operator())
        assert top.listed is not None
        assert all(each in top.listed for each in ["stamp", "jot", "seal"])
        assert "core" not in top.listed
        stamped = await started.typed(["stamp", str(number)], Operator())
        assert stamped.call is not None
        assert stamped.status == 0
        named = await started.typed(["core", "stamp", str(number)], Operator())
        assert named.call is None
        assert named.status != 0
        cleared = await started.typed(["jot", "clear", str(number)], Operator())
        assert cleared.call is not None

    @lup.promise
    async def a_module_named_as_the_cores_methods_is_refused(self, by: Testing) -> None:
        """A module whose name is typed as one of the core's tools, commands or views is refused as the declaration resolves, naming it: at `lup`'s top level, both would be typed alike."""
        shadowing = stamping().modules.add(Stamp())
        with raises(ProjectError) as refused:
            await by.started(Project(modules=shadowing))
        assert "stamp" in refused.raised().about

    @lup.promise
    async def a_command_marked_here_runs_in_the_worktree_typed_in(
        self, by: Testing
    ) -> None:
        """A command marked to run where it's typed is answered over the declaration of the worktree it's typed in, by the party lup's program on the operator's machine names, while every other call still goes through that program."""
        machine = await by.started(Project(modules=Modules.default().add(Tally())))
        worktree = await by.started(
            Project(modules=Modules.default().add(Tally(where="worktree")))
        )
        party = by.any(Agent) if by.any(bool) else Operator()
        here = await machine.typed(["tally", "tally"], party, here=worktree)
        through = await machine.typed(["tally", "peek"], party, here=worktree)
        assert here.status == 0
        assert through.status == 0
        tallied = Tallied.model_validate_json(here.output)
        peeked = Tallied.model_validate_json(through.output)
        assert tallied == Tallied(where="worktree", by=type(party).__name__)
        assert peeked == Tallied(where="machine", by=type(party).__name__)

    @lup.promise
    async def a_projects_command_offers_its_modules_alone(self, by: Testing) -> None:
        """A project's own command offers the methods of the modules it's given alone, the first's at its top level and the others' typed by their names, never the core's, which are lup's development side."""
        number = by.any(Clearing).number
        started = await by.started(stamping())
        command = ["jot", "seal"]
        top = await started.typed(["--help"], Operator(), command)
        assert top.listed is not None
        assert all(each in top.listed for each in ["jot-down", "clear", "seal"])
        assert all(each not in top.listed for each in ["stamp", "jot", "core"])
        cleared = await started.typed(["clear", str(number)], Operator(), command)
        assert cleared.call is not None
        assert cleared.status == 0
        sealed = await started.typed(["seal", "seal", str(number)], Operator(), command)
        assert sealed.call is not None
        stamped = await started.typed(["stamp", str(number)], Operator(), command)
        assert stamped.call is None
        assert stamped.status != 0
