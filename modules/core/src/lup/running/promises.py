"""How lup runs a project's modules, its promises: what the program on the operator's machine can count on of a plan, and of a container answering what crosses to it.

Each is checked through the harness over the example module defined here: its
plan as lup reads a declaration's, and a message crossing to its parts as a
container's socket would get it (`README.md` here, *Promises*).
"""

import json
from typing import Literal

from pydantic import Field, JsonValue

import lup
from lup import (
    Agent,
    Blocks,
    Codebase,
    Data,
    Line,
    Machine,
    Model,
    Module,
    Modules,
    Part,
    Parts,
    Project,
    Runtime,
    Secret,
    Span,
)
from lup.testing import Accepted, Refused, Testing


class Note(Model):
    """Something to note."""

    text: str = Field(max_length=40)


class Noted(Model):
    """What was noted."""

    text: str


class Ledger(Part):
    """The courier's part holding nothing: it runs in the project's own container."""

    @lup.tool
    async def jot(self, note: Note) -> Noted:
        """Note something."""
        return Noted(text=note.text)

    @lup.tool
    async def forwarded(self, note: Note) -> Noted:
        """Seal a note through another project's vault."""
        with lup.within("story"):
            return await Vault.sealed(note)

    @lup.view
    async def noting(self, note: Note) -> Blocks:
        """Show a note as a line."""
        return Blocks.of(Line.of("note", note.text))

    @lup.view
    async def smudged(self, note: Note) -> Blocks:
        """Show a note in a tone nobody declares."""
        return Blocks.of(Line(id="note", spans=[Span(text=note.text, tone="smudge")]))


class Vault(Part):
    """The courier's part holding a secret: it runs apart, from approved code."""

    key: Secret

    @lup.service
    async def sealed(self, note: Note, by: Codebase | Machine) -> Noted:
        """Seal a note with the key, for the project's code or the machine's own parts."""
        del by
        return Noted(text=f"{note.text}:{len(self.key.value)}")


class Archive(Part, shared=True):
    """The courier's part one for the whole machine, keeping what it's given."""

    shelf: Data
    desk: Runtime

    @lup.service
    async def shelved(self, note: Note, by: Codebase) -> Noted:
        """Keep a note on the shelf, under the project asking."""
        (self.shelf.path / by.repository).write_text(note.text)
        return Noted(text=note.text)

    @lup.service
    async def pinned(self, note: Note, by: Codebase) -> Noted:
        """Pin a note on the desk while the archive runs, under the project asking, and read back what's pinned, on the desk and not the shelf."""
        (self.desk.path / by.repository).write_text(note.text)
        shelved = (self.shelf.path / by.repository).exists()
        pinned = (self.desk.path / by.repository).read_text()
        return Noted(text=pinned if not shelved else "")


class Courier(Module):
    """Noting things, sealing them, and keeping them."""

    name = "courier"
    parts: Parts = Parts.of(Ledger, Vault, Archive)


def couriered() -> Project:
    """Return a project of lup's default modules and the courier."""
    return Project(modules=Modules.default().add(Courier()))


class Reply(Model):
    """A container's answer, as a promise reads it: answered or refused, and what it answered."""

    kind: str
    output: JsonValue = None


class Repository(Model):
    """A repository whose code calls a shared part."""

    name: Literal["harmon", "story", "lup"]


class Sending(Model):
    """A message crossing to a container: a call, one of another version of its shape, one no one vouched for, or none at all."""

    sent: Literal["a call", "another version", "unvouched", "no call"]
    version: int = Field(ge=2, le=9)


class RunningPromises(Part):
    """What the program on the operator's machine can count on of a declaration's plan, and of a container answering what crosses to it."""

    @lup.promise
    async def a_part_runs_apart_exactly_where_it_holds_something(
        self, by: Testing
    ) -> None:
        """A plan runs a part apart, from approved code, exactly where it holds something (a secret, the machine, what only approved code may, or the whole machine's share); the rest run together in the project's own container."""
        started = await by.started(couriered(), secrets={"key": by.any(str)})
        apart = [each.part for each in started.plan.parts if each.apart()]
        assert "Ledger" not in apart
        assert "Vault" in apart
        assert "Archive" in apart
        assert all(each.apart() == each.holds.anything() for each in started.plan.parts)

    @lup.promise
    async def a_plan_routes_every_call_a_party_makes(self, by: Testing) -> None:
        """A plan names, for each method a party calls, its door, its name, who may call it and the fields of what it takes, so the program routes a call, and the command line offers it, without running the declaration; hooks and promises, which no party calls, aren't among them."""
        started = await by.started(couriered(), secrets={"key": by.any(str)})
        noting = started.plan.serving("tool", "jot")
        assert noting is not None
        assert noting.part == "Ledger"
        assert started.plan.serving("view", "noting", "courier") is not None
        sealing = started.plan.serving("service", "sealed")
        assert sealing is not None
        [way] = [each for each in sealing.doorways if each.name == "sealed"]
        assert "Codebase" in way.parties
        ways = [way for each in started.plan.parts for way in each.doorways]
        assert all(way.door in ("tool", "service", "command", "view") for way in ways)
        couriers = [
            way
            for each in started.plan.parts
            if each.module == "courier"
            for way in each.doorways
        ]
        assert all(
            "text" in json.dumps(way.input_schema)
            for way in couriers
            if way.name in ("note", "noting", "sealed")
        )
        assert "courier" in [each.name for each in started.plan.modules]

    @lup.promise
    async def a_call_crossing_is_answered_as_through_its_door(
        self, by: Testing
    ) -> None:
        """A call crossing to a container is answered as its door answers it: what the method answered, as JSON."""
        note = by.any(Note)
        agent = by.any(Agent)
        started = await by.started(couriered(), secrets={"key": by.any(str)})
        sent = {
            "format": 1,
            "kind": "tool",
            "tool": "jot",
            "given": note.model_dump(mode="json"),
            "by": agent.model_dump(mode="json"),
        }
        reply = Reply.model_validate_json(
            await started.crossed(json.dumps(sent).encode())
        )
        assert reply.kind == "answered"
        assert Noted.model_validate(reply.output) == Noted(text=note.text)

    @lup.promise
    async def a_view_crossing_is_answered_with_its_blocks(self, by: Testing) -> None:
        """A view read across to a container is answered with its blocks, as JSON; one whose blocks name a kind nobody declares is refused, the container going on."""
        note = by.any(Note)
        started = await by.started(couriered(), secrets={"key": by.any(str)})

        def read(view: str) -> bytes:
            sent = {
                "format": 1,
                "kind": "view",
                "module": "courier",
                "view": view,
                "given": note.model_dump(mode="json"),
                "by": by.any(Agent).model_dump(mode="json"),
            }
            return json.dumps(sent).encode()

        shown = Reply.model_validate_json(await started.crossed(read("noting")))
        assert shown.kind == "answered"
        assert Blocks.model_validate(shown.output).text() == note.text
        smudged = Reply.model_validate_json(await started.crossed(read("smudged")))
        assert smudged.kind == "refused"

    @lup.promise
    async def nothing_crossing_makes_a_container_fail(self, by: Testing) -> None:
        """Whatever crosses to a container, a call, one of another version of its shape, one saying no one's `by`, or something that's no call, is answered: run, or refused, never failing the container; and a call reaches a part only as the program on the operator's machine vouched for it."""
        sending = by.any(Sending)
        started = await by.started(couriered(), secrets={"key": by.any(str)})
        call: dict[str, JsonValue] = {
            "kind": "tool",
            "tool": "jot",
            "given": {"text": "x"},
            "by": {"party": "agent", "id": "a", "session": "a"},
        }
        match sending.sent:
            case "a call":
                sent: dict[str, JsonValue] = {"format": 1, **call}
            case "another version":
                sent = {"format": sending.version, **call}
            case "unvouched":
                sent = {"format": 1, **call, "by": None}
            case "no call":
                sent = {"format": 1, "kind": "letter"}
        reply = Reply.model_validate_json(
            await started.crossed(json.dumps(sent).encode())
        )
        assert reply.kind == ("answered" if sending.sent == "a call" else "refused")

    @lup.promise
    async def a_part_keeping_data_keeps_it_in_a_directory_of_its_own(
        self, by: Testing
    ) -> None:
        """A part with a field typed `Data` is given a directory of its own where it runs, there to write in, and a shared part serving several projects is told which one calls by its `Codebase`."""
        note = by.any(Note)
        repository = by.any(Repository).name
        started = await by.started(
            couriered(), secrets={"key": by.any(str)}, repository=repository
        )
        shelved = await started.serve("shelved", note, Codebase(repository=repository))
        assert isinstance(shelved, Accepted)
        assert shelved.output == Noted(text=note.text)

    @lup.promise
    async def a_part_keeping_what_lasts_while_it_runs_has_a_directory_apart(
        self, by: Testing
    ) -> None:
        """A part with a field typed `Runtime` is given a directory of its own where it runs, apart from its `Data`, there to write what lasts only while it runs."""
        note = by.any(Note)
        repository = by.any(Repository).name
        started = await by.started(
            couriered(), secrets={"key": by.any(str)}, repository=repository
        )
        pinned = await started.serve("pinned", note, Codebase(repository=repository))
        assert isinstance(pinned, Accepted)
        assert pinned.output == Noted(text=note.text)


class Naming(Model):
    """Whose code a promise runs a part's tool as: a project's, or the machine's own."""

    machine: bool


class WithinPromises(Part):
    """What a project can count on of a call naming another project: only the machine's own parts may."""

    @lup.promise
    async def only_the_machines_code_names_a_project(self, by: Testing) -> None:
        """A service call made within a project another than the caller's own (`lup.within`) is refused where a project's code makes it, and carried where the machine's own parts make it: a project's code calls its own project's parts alone."""
        naming = by.any(Naming)
        note = by.any(Note)
        started = await by.started(
            couriered(), secrets={"key": by.any(str)}, machine=naming.machine
        )
        called = await started.call("forwarded", note, by.any(Agent))
        assert isinstance(called, Accepted) == naming.machine
        if isinstance(called, Refused):
            assert "Vault.sealed" in called.rejection.about
