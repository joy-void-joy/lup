"""The machine's parts, their promises: what the operator can count on of what runs on their machine.

Each is checked through the harness, the machine's parts started as the
machine's own (`machine=True`), every program they run stood in for as the
promise scripts it, so the gate checks what lup asks podman to do without
running it (`README.md` here, *Promises*). One runs a container's own program,
Python, for real, where its container would start it: what fails there is
Python's finding its modules, which no stand-in shows.
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Literal, get_args

from pydantic import Field, JsonValue

import lup
import lup.hosting
import lup.testing
from lup import Agent, Codebase, Machine, Model, Part
from lup.testing import (
    Accepted,
    Answering,
    Refused,
    Responding,
    Scripted,
    Started,
    Testing,
)

HOME = """
from lup import Modules, Project
from lup.hosting.module import Hosting

project = Project(modules=Modules.default().add(Hosting()))
"""
"""The home repository's declaration, as lup's own declares it: lup's default
modules and the machine's parts."""


class Planned(Model):
    """A part of a project's plan, as a promise writes one: its module and class, what it holds, the file it's defined in, the tools and services it serves, each called by an agent, and the packages its programs are in."""

    module: str
    part: str
    secrets: list[str] = []
    shared: bool = False
    git: bool = False
    github: list[str] = []
    packages: list[str] = []
    hears: list[str] = []
    """The events its methods run at, by their classes' names."""
    source: str | None = None
    tools: list[str] = []
    services: list[str] = []
    here: list[str] = []
    """Commands of the operator's that `lup` answers where it's typed."""
    commands: list[str] = []
    """Commands of the operator's carried to where the part runs."""

    def plan(self) -> JsonValue:
        """Return it as a plan says it, as JSON: promises read lup's plan only through what crosses."""
        doorways: list[JsonValue] = [
            *(
                {"door": door, "name": name, "parties": ["Agent"]}
                for door, names in [("tool", self.tools), ("service", self.services)]
                for name in names
            ),
            *(
                {"door": "command", "name": name, "parties": ["Operator"], "here": True}
                for name in self.here
            ),
            *(
                {"door": "command", "name": name, "parties": ["Operator"]}
                for name in self.commands
            ),
        ]
        return {
            "module": self.module,
            "part": self.part,
            "holds": {
                "secrets": list[JsonValue](self.secrets),
                "shared": self.shared,
                "git": self.git,
                "github": list[JsonValue](self.github),
            },
            "source": self.source,
            "doorways": doorways,
            "packages": list[JsonValue](self.packages),
            "hears": list[JsonValue](self.hears),
        }


def plan_of(*parts: Planned) -> JsonValue:
    """Return a project's plan holding `parts`, as JSON."""
    return {
        "format": 1,
        "parts": [each.plan() for each in parts],
        "tools": [],
        "files": [],
    }


NOTES_PLAN = plan_of(Planned(module="notes", part="Notes", tools=["note"]))
"""A project's plan of one part holding nothing, serving a tool."""

VAULT_PLAN = plan_of(
    Planned(module="notes", part="Notes"),
    Planned(module="vault", part="Vault", secrets=["key"]),
)
"""A project's plan of a part holding nothing and one holding a secret."""

BASE = "docker.io/library/archlinux@sha256:4bf33b21a715aac0b48ce6e9eaed4782a898eae96f88f5da3635572129c2584a"
"""A base image named by its digest, as every image lup builds starts from."""


class Kept(Model):
    """A secret's value, as the operator gives one."""

    value: str = Field(min_length=1, max_length=40)


class Asked(Model):
    """A container a promise asks the machine's parts to start, drawn from what varies."""

    name: Literal["harmon-bot", "lup-project", "story-reader"]
    definition: Literal["FROM scratch", "FROM archlinux:base"]
    command: list[Literal["python", "-m", "lup.environment.running", "--version"]] = (
        Field(default=[], max_length=4)
    )
    sources: list[Literal["/srv/a", "/srv/with,comma", "/srv/data"]] = Field(
        default=[], max_length=3
    )
    writable: bool = False
    network: Literal["host", "private"] = "host"
    gpu: bool = False

    def spec(self) -> dict[str, JsonValue]:
        """Return the container as the machine's parts are asked to start it, as its JSON."""
        return {
            "name": self.name,
            "image": {
                "base": BASE,
                "definition": self.definition,
                "project": "harness",
            },
            "command": list(self.command),
            "workdir": "/srv/work",
            "binds": [
                {"source": each, "read_only": not self.writable}
                for each in self.sources
            ],
            "network": self.network,
            "gpu": self.gpu,
        }


class Unpinned(Model):
    """A base image named otherwise than by its digest."""

    base: Literal["archlinux:base", "docker.io/library/archlinux"]


class Unowned(Model):
    """A path a container would mount that isn't its own."""

    source: Literal["srv/a", "./a", "../a"]


class Tied(Model):
    """A door two parts serve one name behind."""

    door: Literal["tool", "service"]


class Unsafe(Model):
    """A name that's no single name in a path or on podman's command line."""

    name: Literal["../operator", ".hidden", "a/b", "-rm", "", "nöt-ascii", "a b"]


class Opens(Model):
    """A project the promises open: harmon unless it says, and where git keeps it."""

    repository: str = "harmon"
    common: str = "/srv/harmon.git"

    def given(self) -> JsonValue:
        """Return it as the machine's parts are given it."""
        return self.model_dump(mode="json")


async def placed(
    started: Started, repository: str, plan: JsonValue, parts: list[str]
) -> str:
    """Place a container running `parts` of `repository`, whose plan is `plan`, as the machine's parts do, and return its directory of sockets."""
    made = await started.serve(
        "directory", {"container": f"lup-{repository}"}, Machine()
    )
    assert isinstance(made, Accepted)
    directory: str = json.loads(made.answer())["path"]
    placement: JsonValue = {
        "repository": repository,
        "parts": list[JsonValue](parts),
        "container": f"lup-{repository}",
        "directory": directory,
    }
    await started.serve(
        "placed",
        {"repository": repository, "plan": plan, "placements": [placement]},
        Machine(),
    )
    return directory


VERSIONED = Answering(when=["version"], output="6.1.0\n")
"""podman saying its version, as lup asks before the part holding it starts."""

PODMAN = Scripted(
    answers=[
        VERSIONED,
        Answering(when=["run"]),
        Answering(when=["stop"]),
        Answering(when=["image", "exists"], status=1),
        Answering(when=["pull"]),
        Answering(when=["build"]),
    ]
)
"""podman as the promises stand it in: every run, stop, fetch and build
succeeds, and no image is there yet."""

type Wall = Literal[
    "--rm",
    "--init",
    "--pull=never",
    "--userns=keep-id",
    "--cap-drop=all",
    "--security-opt=no-new-privileges",
]
"""What every container lup starts stands behind, as podman's options."""


def acted(started: Started) -> list[list[str]]:
    """Return the arguments of each run of podman the machine's parts asked for beyond asking its version, which they do as they start."""
    return [
        each for each in started.ran("podman") if not (each and each[0] == "version")
    ]


def podman_ran(started: Started, verb: str) -> list[list[str]]:
    """Return the arguments of each run of podman the machine's parts asked for whose first is `verb`."""
    return [each for each in started.ran("podman") if each and each[0] == verb]


class HostingPromises(Part):
    """What the operator can count on of the parts that run on their machine."""

    @lup.promise
    async def every_container_stands_behind_the_same_walls(self, by: Testing) -> None:
        """Every container lup starts, whatever asked for it and however, stands behind the same walls: the operator's uid inside, every capability dropped, no privilege gained, a limit on processes, reaped, removed when it ends, no image fetched, no log kept."""
        asked = by.any(Asked)
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        run = await started.serve("started", asked.spec(), Machine())
        assert isinstance(run, Accepted)
        [command] = podman_ran(started, "run")
        assert all(wall in command for wall in get_args(Wall.__value__))
        assert any(each.startswith("--pids-limit=") for each in command)
        assert f"--name={asked.name}" in command

    @lup.promise
    async def a_mount_is_read_only_unless_it_says(self, by: Testing) -> None:
        """A directory lup mounts into a container is read-only there unless the container's spec says otherwise, and lands at its own path, a path holding a comma as one path."""
        asked = by.any(Asked)
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        await started.serve("started", asked.spec(), Machine())
        [command] = podman_ran(started, "run")
        binds = [each for each in command if each.startswith("--mount=type=bind")]
        assert len(binds) == len(asked.sources)
        assert all(("ro=true" in each) != asked.writable for each in binds)

    @lup.promise
    async def only_the_machines_own_parts_start_a_container(self, by: Testing) -> None:
        """Only the machine's own parts may start or stop a container: an agent, or any project's code, the home repository's own branch among it, is refused, and podman never runs for it."""
        asked = by.any(Asked)
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        caller = by.any(Agent) if by.any(bool) else Codebase(repository=by.any(str))
        refused = await started.serve("started", asked.spec(), caller)
        stopped = await started.serve("stopped", {"name": asked.name}, caller)
        assert isinstance(refused, Refused)
        assert isinstance(stopped, Refused)
        assert acted(started) == []

    @lup.promise
    async def an_image_is_built_only_where_it_isnt_there(self, by: Testing) -> None:
        """An image is built only where its tag isn't there yet, its base fetched by its digest first where it isn't there either, and the build itself fetches nothing."""
        image = {"base": BASE, "definition": "FROM scratch", "project": "harness"}
        tagged, based = by.any(bool), by.any(bool)
        podman = Scripted(
            answers=[
                VERSIONED,
                Answering(when=["image", "exists", BASE], status=0 if based else 1),
                Answering(when=["image", "exists"], status=0 if tagged else 1),
                Answering(when=["pull", "--quiet", BASE]),
                Answering(when=["build"]),
            ]
        )
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": podman},
            machine=True,
        )
        built = await started.serve("built", image, Machine())
        assert isinstance(built, Accepted)
        assert json.loads(built.answer())["built"] == (not tagged)
        builds = podman_ran(started, "build")
        assert bool(builds) != tagged
        assert all("--pull=never" in each for each in builds)
        assert bool(podman_ran(started, "pull")) == (not tagged and not based)

    @lup.promise
    async def a_base_not_named_by_its_digest_is_refused(self, by: Testing) -> None:
        """An image whose base isn't named by its digest is refused, and nothing is fetched or built: what's fetched under a name could change."""
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        image: JsonValue = {
            "base": by.any(Unpinned).base,
            "definition": "FROM scratch",
            "project": "harness",
        }
        refused = await started.serve("built", image, Machine())
        assert isinstance(refused, Refused)
        assert acted(started) == []

    @lup.promise
    async def a_mount_through_a_link_or_relative_path_is_refused(
        self, by: Testing
    ) -> None:
        """A container mounting a path that isn't its own, a relative one or one through a link, is refused, and podman never runs: it would follow the path wherever it points."""
        asked = by.any(Asked)
        binds: list[JsonValue] = [{"source": by.any(Unowned).source}]
        spec = {**asked.spec(), "binds": binds}
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        refused = await started.serve("started", spec, Machine())
        assert isinstance(refused, Refused)
        assert acted(started) == []

    @lup.promise
    async def podman_failing_is_a_refusal_saying_why(self, by: Testing) -> None:
        """podman failing to start a container refuses the call that asked, saying why, rather than leaving it believed running."""
        asked = by.any(Asked)
        podman = Scripted(
            answers=[VERSIONED, Answering(when=["run"], status=125, error="no")]
        )
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": podman},
            machine=True,
        )
        refused = await started.serve("started", asked.spec(), Machine())
        assert isinstance(refused, Refused)

    @lup.promise
    async def a_part_is_handed_only_the_secrets_it_holds(self, by: Testing) -> None:
        """The machine's parts hand a part the secrets kept for its project that it holds, and name those that aren't kept, for the operator to be asked for; another project's secret of the same name is never among them."""
        kept, other = by.any(Kept), by.any(Kept)
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        operator = lup.Operator()
        await started.run(
            "hosting",
            "keep",
            {"project": "harmon", "name": "token", "value": kept.value},
            operator,
        )
        await started.run(
            "hosting",
            "keep",
            {"project": "story", "name": "token", "value": other.value},
            operator,
        )
        held = await started.serve(
            "held", {"project": "harmon", "names": ["token", "key"]}, Machine()
        )
        assert isinstance(held, Accepted)
        values = json.loads(held.answer())
        assert values["values"]["token"] == kept.value
        assert "key" in values["missing"]

    @lup.promise
    async def only_the_machine_reads_a_secret_and_only_the_operator_keeps_one(
        self, by: Testing
    ) -> None:
        """A secret kept is read only by the machine's own parts, and kept only by the operator: an agent or a project's code asking for one, or giving one, is refused."""
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        caller = by.any(Agent) if by.any(bool) else Codebase(repository="harmon")
        held = await started.serve(
            "held", {"project": "harmon", "names": ["token"]}, caller
        )
        given = await started.run(
            "hosting",
            "keep",
            {"project": "harmon", "name": "token", "value": "x"},
            caller,
        )
        assert isinstance(held, Refused)
        assert isinstance(given, Refused)

    @lup.promise
    async def a_call_is_by_whom_its_socket_says(self, by: Testing) -> None:
        """A call coming in on a container's socket is by that container's project, whatever the call says it's by, or where it says nothing; one coming in on a socket no container lup started has is refused."""
        claimed = by.any(Agent) if by.any(bool) else None
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        made = await started.serve("directory", {"container": "c"}, Machine())
        assert isinstance(made, Accepted)
        directory: str = json.loads(made.answer())["path"]
        await started.serve(
            "placed",
            {
                "repository": "harmon",
                "plan": NOTES_PLAN,
                "placements": [
                    {
                        "repository": "harmon",
                        "parts": ["notes.Notes"],
                        "container": "c",
                        "directory": directory,
                    }
                ],
            },
            Machine(),
        )
        call: JsonValue = {
            "format": 1,
            "kind": "tool",
            "tool": "note",
            "given": {},
            "by": None if claimed is None else claimed.model_dump(mode="json"),
        }
        route = await started.serve(
            "routed", {"directory": directory, "call": call}, Machine()
        )
        assert isinstance(route, Accepted)
        carried = json.loads(route.answer())
        assert carried["call"]["by"] == Codebase(repository="harmon").model_dump(
            mode="json"
        )
        assert carried["to"].endswith("listening.sock")
        stranger = await started.serve(
            "routed", {"directory": "/srv/elsewhere", "call": call}, Machine()
        )
        assert isinstance(stranger, Refused)

    @lup.promise
    async def a_parts_event_goes_from_its_projects_containers_alone(
        self, by: Testing
    ) -> None:
        """A part's own event is carried from a container of its project, and from nowhere else, to the parts of that project hearing it in its other containers: where none hears it, nothing's told or refused; where one is out of reach, it's refused, since a check that didn't run let nothing through."""
        heard_elsewhere = by.any(bool)
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        plan = plan_of(
            Planned(module="notes", part="Notes"),
            Planned(
                module="guard",
                part="Guard",
                secrets=["key"],
                hears=["Publishing"] if heard_elsewhere else [],
            ),
        )
        made = await started.serve("directory", {"container": "c"}, Machine())
        guarding = await started.serve("directory", {"container": "g"}, Machine())
        assert isinstance(made, Accepted)
        assert isinstance(guarding, Accepted)
        own: str = json.loads(made.answer())["path"]
        guard: str = json.loads(guarding.answer())["path"]
        await started.serve(
            "placed",
            {
                "repository": "harmon",
                "plan": plan,
                "placements": [
                    {
                        "repository": "harmon",
                        "parts": ["notes.Notes"],
                        "container": "c",
                        "directory": own,
                    },
                    {
                        "repository": "harmon",
                        "parts": ["guard.Guard"],
                        "container": "g",
                        "directory": guard,
                    },
                ],
            },
            Machine(),
        )
        told: JsonValue = {"event": "Publishing", "given": {}}
        fired = await started.serve("fired", {"directory": own, **told}, Machine())
        assert isinstance(fired, Accepted)
        heeded = json.loads(fired.answer())
        assert (heeded["refused"] is not None) == heard_elsewhere
        stray = await started.serve(
            "fired", {"directory": "/srv/nowhere", **told}, Machine()
        )
        assert isinstance(stray, Refused)

    @lup.promise
    async def a_call_from_a_room_is_by_its_session(self, by: Testing) -> None:
        """A call coming in on a session's room's socket is by that session's agent, or by the conversation of that session it names, a subagent's, whatever it says it's by; a conversation named from a project's container is refused, and so is a call from a room once it has stopped."""
        session, conversation = by.any(str), by.any(str) if by.any(bool) else None
        claimed = by.any(Agent) if by.any(bool) else None
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        container = await placed(started, "harmon", NOTES_PLAN, ["notes.Notes"])
        made = await started.serve("directory", {"container": "room"}, Machine())
        assert isinstance(made, Accepted)
        room: str = json.loads(made.answer())["path"]
        room_of: JsonValue = {
            "repository": "harmon",
            "session": session,
            "container": "room",
            "directory": room,
        }
        await started.serve("seated", room_of, Machine())
        call: JsonValue = {
            "format": 1,
            "kind": "tool",
            "tool": "note",
            "given": {},
            "by": None if claimed is None else claimed.model_dump(mode="json"),
            "conversation": conversation,
        }
        route = await started.serve(
            "routed", {"directory": room, "call": call}, Machine()
        )
        assert isinstance(route, Accepted)
        carried = json.loads(route.answer())["call"]
        assert carried["by"] == Agent.of(session, conversation).model_dump(mode="json")
        assert carried["conversation"] is None
        named: JsonValue = {**call, "conversation": by.any(str)}
        from_code = await started.serve(
            "routed", {"directory": container, "call": named}, Machine()
        )
        assert isinstance(from_code, Refused)
        await started.serve("left", {"session": session}, Machine())
        gone = await started.serve(
            "routed", {"directory": room, "call": call}, Machine()
        )
        assert isinstance(gone, Refused)

    @lup.promise
    async def a_part_holding_a_secret_runs_apart_given_only_its_own(
        self, by: Testing
    ) -> None:
        """Opening a project starts one container for its parts holding nothing, and one of its own for each part holding a secret, given that part's secrets alone; a part whose secret nothing kept waits, not started."""
        kept = by.any(bool)
        podman = Scripted(
            answers=[
                VERSIONED,
                Answering(when=["image", "exists"], status=0),
                Answering(when=["run", "--interactive"], output=json.dumps(VAULT_PLAN)),
                Answering(when=["run", "--detach"]),
                Answering(when=["stop"]),
            ]
        )
        started = await started_approved(by, podman)
        if kept:
            await started.run(
                "hosting",
                "keep",
                {"project": "harmon", "name": "key", "value": "k"},
                lup.Operator(),
            )
        opened = await started.serve("opened", Opens().given(), Machine())
        assert isinstance(opened, Accepted)
        result = json.loads(opened.answer())
        assert ("vault.Vault" in result["waiting"]) != kept
        detached = podman_ran(started, "run")
        names = [
            each
            for command in detached
            for each in command
            if each.startswith("--name=")
        ]
        assert "--name=lup-harmon-project-1" in names
        assert ("--name=lup-harmon-vault-Vault-1" in names) == kept

    @lup.promise
    async def a_call_reaches_its_own_projects_parts_or_the_machines(
        self, by: Testing
    ) -> None:
        """A call is carried to a part of the caller's own project running in its containers, or else to the machine's own parts: never to another project's part, nor to a part another project's plan says is the machine's."""
        claims = by.any(bool)
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        own = await placed(started, "harmon", NOTES_PLAN, ["notes.Notes"])
        claimed = plan_of(
            Planned(module="notes", part="Notes", shared=True, tools=["note"])
        )
        other = await placed(started, "story", claimed if claims else plan_of(), [])
        call: JsonValue = {
            "format": 1,
            "kind": "tool",
            "tool": "note",
            "given": {},
            "by": {"party": "operator"},
        }
        from_own = await started.serve(
            "routed", {"directory": own, "call": call}, Machine()
        )
        from_other = await started.serve(
            "routed", {"directory": other, "call": call}, Machine()
        )
        assert isinstance(from_own, Accepted)
        assert isinstance(from_other, Accepted)
        assert json.loads(from_own.answer())["to"] == f"{own}/listening.sock"
        assert json.loads(from_other.answer())["to"] is None

    @lup.promise
    async def a_plan_serving_a_name_twice_is_refused(self, by: Testing) -> None:
        """A project whose plan serves one name from two parts is refused before any of its containers starts, rather than a call going to whichever part comes first."""
        door = by.any(Tied).door
        tools, services = (["same"], []) if door == "tool" else ([], ["same"])
        tied = plan_of(
            Planned(module="notes", part="Notes", tools=tools, services=services),
            Planned(module="notes", part="Drafts", tools=tools, services=services),
        )
        podman = Scripted(
            answers=[
                VERSIONED,
                Answering(when=["image", "exists"], status=0),
                Answering(when=["run", "--interactive"], output=json.dumps(tied)),
                Answering(when=["run", "--detach"]),
            ]
        )
        started = await started_approved(by, podman)
        opened = await started.serve("opened", Opens().given(), Machine())
        assert isinstance(opened, Refused)
        assert podman_ran(started, "run") == [
            each for each in podman_ran(started, "run") if "--interactive" in each
        ]

    @lup.promise
    async def a_name_unsafe_as_a_path_is_refused(self, by: Testing) -> None:
        """A repository's, a module's or a part's name that could be read as more than one name in a path or on podman's command line is refused before any container starts."""
        unsafe = by.any(Unsafe)
        in_plan = by.any(bool)
        plan = plan_of(Planned(module=unsafe.name, part="Notes"))
        podman = Scripted(
            answers=[
                VERSIONED,
                Answering(when=["image", "exists"], status=0),
                Answering(when=["run", "--interactive"], output=json.dumps(plan)),
                Answering(when=["run", "--detach"]),
            ]
        )
        started = await started_approved(by, podman)
        opening = Opens() if in_plan else Opens(repository=unsafe.name)
        opened = await started.serve("opened", opening.given(), Machine())
        assert isinstance(opened, Refused)
        assert not [each for each in podman_ran(started, "run") if "--detach" in each]

    @lup.promise
    async def each_container_has_its_own_environment(self, by: Testing) -> None:
        """Each container of a project syncs its Python environment and uv's cache in directories of its own, so code running in one never writes what another imports."""
        podman = Scripted(
            answers=[
                VERSIONED,
                Answering(when=["image", "exists"], status=0),
                Answering(when=["run", "--interactive"], output=json.dumps(VAULT_PLAN)),
                Answering(when=["run", "--detach"]),
                Answering(when=["stop"]),
            ]
        )
        started = await started_approved(by, podman)
        await started.run(
            "hosting",
            "keep",
            {"project": "harmon", "name": "key", "value": "k"},
            lup.Operator(),
        )
        opened = await started.serve("opened", Opens().given(), Machine())
        assert isinstance(opened, Accepted)
        mounts = [
            each
            for command in podman_ran(started, "run")
            for each in command
            if each.startswith("--mount=")
            and ("/var/lup/environment" in each or "/var/lup/cache" in each)
        ]
        assert len(mounts) == 6
        assert len(dict.fromkeys(mounts)) == len(mounts)


class Stored(Model):
    """An object of git's store: its id, and its content as git hashes it."""

    id: str
    content: bytes

    @classmethod
    def of(cls, kind: str, content: bytes) -> Stored:
        """Return the object of `kind` holding `content`, named by its id, as git names one in a repository of SHA-1."""
        framed = b"".join([f"{kind} {len(content)}".encode(), b"\0", content])
        return cls(
            id=hashlib.sha1(framed, usedforsecurity=False).hexdigest(),
            content=content,
        )


class Listed(Model):
    """One entry of a tree as a promise writes it: its mode, its name, and its object."""

    mode: str
    name: str
    object: Stored


def tree_of(entries: list[Listed]) -> Stored:
    """Return the tree object holding `entries`, each its mode, its name and its object's raw id."""
    content = b"".join(
        b"".join(
            [
                f"{each.mode} {each.name}".encode(),
                b"\0",
                bytes.fromhex(each.object.id),
            ]
        )
        for each in entries
    )
    return Stored.of("tree", content)


DIFF = "diff --git a/before/README.md b/after/README.md\n"
"""What git's diff says, as the promises' store of git's objects stands it in."""


class Store(Model, Responding):
    """git's object store as a promise stands it in: each object by its id, answering `git cat-file --batch=%(objectsize)` as git does, an object it lacks said missing."""

    objects: list[Stored] = []

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer a `cat-file` run, each object asked on its own line: its size on a line, its content, then a newline; and a `diff` run, as git's saying two directories differ."""
        if "diff" in arguments:
            return Answering(status=1, output=DIFF)
        if "cat-file" not in arguments or given is None:
            return None
        held = {each.id: each.content for each in self.objects}

        def told(asked: str) -> bytes:
            content = held.get(asked)
            if content is None:
                return f"{asked} missing\n".encode()
            return b"".join([f"{len(content)}\n".encode(), content, b"\n"])

        return Answering(
            output=b"".join(told(each) for each in given.decode().splitlines())
        )


class Files(Model):
    """A commit's files as a promise draws them: some at its root, one in a directory."""

    root: dict[Literal["README.md", "lup_project.py", "uv.lock"], str] = {}
    nested: str = ""
    """The content of `src/app.py`."""
    runnable: bool = False
    """Whether `run.sh` is in it, executable."""

    def expected(self) -> dict[str, str]:
        """Return each file an export of the commit holds, by its path from the root."""
        return {
            **self.root,
            "src/app.py": self.nested,
            **({"run.sh": "#!/bin/sh"} if self.runnable else {}),
        }


class Committed(Model):
    """A commit a promise wrote: its id, and the store holding it."""

    commit: str
    store: Store

    @classmethod
    def of(cls, files: Files, extra: list[Listed] | None = None) -> Committed:
        """Return a commit of `files`, `extra` at its root beside them, in a store of its own."""
        blobs = {
            name: Stored.of("blob", text.encode()) for name, text in files.root.items()
        }
        nested = Stored.of("blob", files.nested.encode())
        source = tree_of([Listed(mode="100644", name="app.py", object=nested)])
        runnable = Stored.of("blob", b"#!/bin/sh")
        entries = [
            *(
                Listed(mode="100644", name=name, object=blob)
                for name, blob in blobs.items()
            ),
            Listed(mode="40000", name="src", object=source),
            *(
                [Listed(mode="100755", name="run.sh", object=runnable)]
                if files.runnable
                else []
            ),
            *(extra or []),
        ]
        root = tree_of(entries)
        commit = Stored.of(
            "commit",
            f"tree {root.id}\nauthor a <a> 0 +0000\ncommitter a <a> 0 +0000\n\nm\n".encode(),
        )
        objects = [
            commit,
            root,
            source,
            nested,
            *(each.object for each in entries),
        ]
        return cls(commit=commit.id, store=Store(objects=objects))

    def exporting(self) -> JsonValue:
        """Return what the machine's parts are asked to write out this commit."""
        return {
            "repository": "harmon",
            "common": "/srv/harmon.git",
            "commit": self.commit,
        }


class Escaping(Model):
    """A link in a commit pointing outside its export."""

    to: Literal["../outside", "../../etc/passwd", "/etc/passwd", "src/../../x"]


def files_in(path: Path) -> dict[str, str]:
    """Return each file under `path`, by its path from it, with its text."""
    return {
        each.relative_to(path).as_posix(): each.read_text()
        for each in path.rglob("*")
        if each.is_file()
    }


class TreesPromises(Part):
    """What the operator can count on of what runs from a commit they approved: its files are what the commit names."""

    @lup.promise
    async def an_export_holds_what_the_commit_names(self, by: Testing) -> None:
        """A commit written out holds each file its tree names, with the content its id says, an executable file kept executable, and nothing else."""
        files = by.any(Files)
        committed = Committed.of(files)
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"git": committed.store},
            machine=True,
        )
        exported = await started.serve("exported", committed.exporting(), Machine())
        assert isinstance(exported, Accepted)
        path = Path(json.loads(exported.answer())["path"])
        assert files_in(path) == files.expected()
        assert os.access(path / "run.sh", os.X_OK) == files.runnable

    @lup.promise
    async def an_object_that_isnt_what_its_id_says_is_refused(
        self, by: Testing
    ) -> None:
        """A store holding, under an id a commit names, content that isn't what the id says, as a room could plant, refuses the export: nothing is written out from it."""
        files = by.any(Files)
        planted = by.any(str)
        committed = Committed.of(files)
        named = Stored.of("blob", files.nested.encode()).id
        swapped = Store(
            objects=[
                Stored(id=each.id, content=planted.encode())
                if each.id == named
                else each
                for each in committed.store.objects
            ]
        )
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"git": swapped},
            machine=True,
        )
        exported = await started.serve("exported", committed.exporting(), Machine())
        assert isinstance(exported, Refused) == (planted != files.nested)

    @lup.promise
    async def git_reads_the_repository_alone(self, by: Testing) -> None:
        """git, reading a commit's objects, is held to the repository's own git directory, reading no `commondir`, graft, shallow file, replace ref, commit-graph or configuration but the repository's own, with nothing that could run code."""
        committed = Committed.of(by.any(Files))
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"git": committed.store},
            machine=True,
        )
        await started.serve("exported", committed.exporting(), Machine())
        runs = [each for each in started.heard.runs if each.program == "git"]
        pins = {
            "GIT_DIR": "/srv/harmon.git",
            "GIT_COMMON_DIR": "/srv/harmon.git",
            "GIT_GRAFT_FILE": os.devnull,
            "GIT_SHALLOW_FILE": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_LAZY_FETCH": "1",
        }
        assert runs
        for each in runs:
            assert pins.items() <= each.env.items()
            command = each.arguments.index("cat-file")
            assert each.arguments.index("--no-replace-objects") < command
            assert "core.commitGraph=false" in each.arguments
            assert "core.fsmonitor=false" in each.arguments
            assert f"core.hooksPath={os.devnull}" in each.arguments

    @lup.promise
    async def a_link_leaving_the_export_is_refused(self, by: Testing) -> None:
        """A commit holding a link that points outside its export is refused, rather than written out to lead a container elsewhere."""
        escaping = by.any(Escaping)
        link = Listed(
            mode="120000",
            name="escape",
            object=Stored.of("blob", escaping.to.encode()),
        )
        committed = Committed.of(by.any(Files), [link])
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"git": committed.store},
            machine=True,
        )
        exported = await started.serve("exported", committed.exporting(), Machine())
        assert isinstance(exported, Refused)

    @lup.promise
    async def only_the_machine_writes_out_a_commit(self, by: Testing) -> None:
        """Only the machine's own parts may write out a commit: an agent or a project's code asking is refused, and git never runs for it."""
        committed = Committed.of(by.any(Files))
        caller = by.any(Agent) if by.any(bool) else Codebase(repository="harmon")
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"git": committed.store},
            machine=True,
        )
        exported = await started.serve("exported", committed.exporting(), caller)
        assert isinstance(exported, Refused)
        assert started.ran("git") == []

    @lup.promise
    async def an_abbreviated_commit_is_refused(self, by: Testing) -> None:
        """A commit named otherwise than by its whole id, abbreviated or by a ref, is refused before git runs: those name whatever the store says."""
        named = by.any(Abbreviated)
        committed = Committed.of(Files())
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"git": committed.store},
            machine=True,
        )
        asked = {
            "repository": "harmon",
            "common": "/srv/harmon.git",
            "commit": named.commit,
        }
        exported = await started.serve("exported", asked, Machine())
        assert isinstance(exported, Refused)
        assert started.ran("git") == []


class Abbreviated(Model):
    """A commit named otherwise than by its whole id."""

    commit: Literal[
        "HEAD", "main", "e69de29", "E69DE29BB2D1D6434B8B29AE775AD8C2E48C5391"
    ]


class Approved(Model):
    """A commit a promise approves: one of two, by its whole id."""

    commit: Literal[
        "1111111111111111111111111111111111111111",
        "2222222222222222222222222222222222222222",
    ]
    landing: bool = False
    """Whether a landing's review approved it, rather than the operator
    answering the question asked."""


class ApprovalsPromises(Part):
    """What the operator can count on of what runs: nothing they haven't approved, and what they're asked before it does."""

    @lup.promise
    async def what_runs_is_what_was_approved_last(self, by: Testing) -> None:
        """A project runs the commit approved last, by a landing's review or by the operator answering the question asked, and nothing before its first approval."""
        approvals = by.any(list[Approved])
        started = await by.started(
            lup.testing.Repository(declaration=HOME), machine=True
        )
        for each in approvals:
            asked = {"project": "harmon", "commit": each.commit}
            if each.landing:
                await started.serve("landed", asked, Machine())
            else:
                await started.run("hosting", "approve", asked, lup.Operator())
        approval = await started.serve("approval", {"project": "harmon"}, Machine())
        assert isinstance(approval, Accepted)
        last = approvals[-1].commit if approvals else None
        assert json.loads(approval.answer())["commit"] == last

    @lup.promise
    async def only_the_operator_or_their_review_approves(self, by: Testing) -> None:
        """Only the operator approves a commit to run, answering the question asked or reviewing a landing, which the machine records: an agent or a project's code asking to approve, record or read an approval is refused, and nothing is approved."""
        caller = by.any(Agent) if by.any(bool) else Codebase(repository="harmon")
        started = await by.started(
            lup.testing.Repository(declaration=HOME), machine=True
        )
        asked = {"project": "harmon", "commit": by.any(Approved).commit}
        approved = await started.run("hosting", "approve", asked, caller)
        landed = await started.serve("landed", asked, caller)
        read = await started.serve("approval", {"project": "harmon"}, caller)
        assert isinstance(approved, Refused)
        assert isinstance(landed, Refused)
        assert isinstance(read, Refused)
        approval = await started.serve("approval", {"project": "harmon"}, Machine())
        assert isinstance(approval, Accepted)
        assert json.loads(approval.answer())["commit"] is None

    @lup.promise
    async def the_question_shows_what_changed_what_holds_first(
        self, by: Testing
    ) -> None:
        """Before a commit runs, the operator is asked with each file changed since the commit approved before, read from each object's own bytes, those in a directory holding a part that holds something called out, and whether the dependencies changed."""
        was, now = by.any(Files), by.any(Files)
        before, after = Committed.of(was), Committed.of(now)
        store = Store(objects=[*before.store.objects, *after.store.objects])
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"git": store},
            machine=True,
        )
        await started.run(
            "hosting",
            "approve",
            {"project": "harmon", "commit": before.commit},
            lup.Operator(),
        )
        plan = plan_of(
            Planned(module="chat", part="Bot", secrets=["token"], source="src/app.py")
        )
        asked = await started.serve(
            "question",
            {
                "project": "harmon",
                "common": "/srv/harmon.git",
                "tip": after.commit,
                "plan": plan,
            },
            Machine(),
        )
        assert isinstance(asked, Accepted)
        question = json.loads(asked.answer())
        old, new = was.expected(), now.expected()
        changed = sorted(
            path for path in old.keys() | new.keys() if old.get(path) != new.get(path)
        )
        assert [each["path"] for each in question["changes"]] == changed
        holding = [path for path in changed if path.startswith("src/")]
        assert [each["path"] for each in question["holding"]] == holding
        assert question["dependencies"] == ("uv.lock" in changed)

    @lup.promise
    async def the_whole_diff_is_of_what_would_run(self, by: Testing) -> None:
        """The whole diff the operator reads is git's comparison of the two commits written out, each file what its id says, with no repository, configuration or diff driver of anyone's having a say in it."""
        was, now = by.any(Files), by.any(Files)
        before, after = Committed.of(was), Committed.of(now)
        store = Store(objects=[*before.store.objects, *after.store.objects])
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"git": store},
            machine=True,
        )
        diffed = await started.serve(
            "diffed",
            {
                "repository": "harmon",
                "common": "/srv/harmon.git",
                "before": before.commit,
                "after": after.commit,
            },
            Machine(),
        )
        assert isinstance(diffed, Accepted)
        assert json.loads(diffed.answer())["text"] == DIFF
        [diff] = [each for each in started.heard.runs if "diff" in each.arguments]
        assert all(
            each in diff.arguments
            for each in ["--no-index", "--no-ext-diff", "--no-textconv"]
        )
        assert {"GIT_CONFIG_GLOBAL": os.devnull}.items() <= diff.env.items()


async def started_approved(
    by: Testing,
    podman: Scripted | Responding,
    committed: Committed | None = None,
    gh: Scripted | None = None,
) -> Started:
    """Start the machine's parts, podman as `podman` scripts it, `gh` as it scripts it where it's given, and a store of git's objects holding `committed`, a commit of harmon the operator approved."""
    approving = committed or Committed.of(Files())
    started = await by.started(
        lup.testing.Repository(declaration=HOME),
        programs={
            "podman": podman,
            "git": approving.store,
            "uv": UV,
            **({} if gh is None else {"gh": gh}),
        },
        machine=True,
    )
    await started.run(
        "hosting",
        "approve",
        {"project": "harmon", "commit": approving.commit},
        lup.Operator(),
    )
    return started


UV = Scripted(answers=[Answering(when=["python", "dir"], output="/srv/python\n")])
"""uv as the promises stand it in: saying the machine keeps Python at
`/srv/python`."""

OPENING_PODMAN = Scripted(
    answers=[
        VERSIONED,
        Answering(
            when=["ps"],
            output=json.dumps([{"Names": ["lup-harmon-project-1"]}]),
        ),
        Answering(when=["image", "exists"], status=0),
        Answering(when=["run", "--interactive"], output=json.dumps(VAULT_PLAN)),
        Answering(when=["run", "--detach"]),
        Answering(when=["stop"]),
    ]
)
"""podman as the promises opening a project stand it in: the image there,
the plan of a part holding nothing and one holding a secret, and every run and
stop succeeding."""


class Repository(Model):
    """A project a caller may say they ask about."""

    name: Literal["harmon", "story", "lup"]


class ProjectsPromises(Part):
    """What the operator can count on of what runs of a project: the commit they approved last, and nothing before."""

    @lup.promise
    async def nothing_of_a_project_runs_before_its_first_approval(
        self, by: Testing
    ) -> None:
        """A project nothing of which the operator approved yet is refused, and no container of it starts: lup asks them before its first run."""
        committed = Committed.of(by.any(Files))
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": OPENING_PODMAN, "git": committed.store, "uv": UV},
            machine=True,
        )
        opened = await started.serve("opened", Opens().given(), Machine())
        assert isinstance(opened, Refused)
        assert podman_ran(started, "run") == []

    @lup.promise
    async def a_project_runs_the_commit_approved_last(self, by: Testing) -> None:
        """A project's containers run the commit the operator approved last, written out from git's objects and mounted read-only, never one approved before it."""
        first, last = Committed.of(by.any(Files)), Committed.of(by.any(Files))
        store = Store(objects=[*first.store.objects, *last.store.objects])
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": OPENING_PODMAN, "git": store, "uv": UV},
            machine=True,
        )
        for each in [first, last]:
            await started.run(
                "hosting",
                "approve",
                {"project": "harmon", "commit": each.commit},
                lup.Operator(),
            )
        opened = await started.serve("opened", Opens().given(), Machine())
        assert isinstance(opened, Accepted)
        assert json.loads(opened.answer())["commit"] == last.commit
        mounted = [
            each
            for command in podman_ran(started, "run")
            for each in command
            if each.startswith("--mount=type=bind") and "/harmon/" in each
        ]
        assert mounted
        assert all(f"/harmon/{last.commit}," in each for each in mounted)
        assert all("ro=true" in each for each in mounted)

    @lup.promise
    async def opening_again_stops_what_ran_before(self, by: Testing) -> None:
        """Opening a project again stops each container it ran before, before starting those of the commit approved last, so two never run under one name."""
        started = await started_approved(by, OPENING_PODMAN)
        await started.run(
            "hosting",
            "keep",
            {"project": "harmon", "name": "key", "value": "k"},
            lup.Operator(),
        )
        first = await started.serve("opened", Opens().given(), Machine())
        again = await started.serve("opened", Opens().given(), Machine())
        assert isinstance(first, Accepted)
        assert isinstance(again, Accepted)
        containers: list[str] = json.loads(first.answer())["containers"]
        stopped = [each[-1] for each in podman_ran(started, "stop")]
        assert stopped == containers

    @lup.promise
    async def a_caller_is_offered_what_their_socket_says_they_may_call(
        self, by: Testing
    ) -> None:
        """A caller asking what they may call is told who they are from the socket they asked on, whatever they say, and offered their own project's plan: never another project's, nor a part the machine runs; a socket no container lup started has is refused."""
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        own = await placed(
            started,
            "harmon",
            plan_of(
                Planned(module="notes", part="Notes", tools=["note"]),
                Planned(module="notes", part="Desk", shared=True, tools=["desk"]),
            ),
            ["notes.Notes"],
        )
        await placed(
            started,
            "story",
            plan_of(Planned(module="tales", part="Tales", tools=["tell"])),
            ["tales.Tales"],
        )
        asked = by.any(Repository).name
        offered = await started.serve(
            "offered", {"directory": own, "repository": asked}, Machine()
        )
        assert isinstance(offered, Accepted)
        offer = json.loads(offered.answer())
        assert offer["by"] == Codebase(repository="harmon").model_dump(mode="json")
        parts = [each["part"] for each in offer["plan"]["parts"]]
        assert "Notes" in parts
        assert all(each not in parts for each in ["Desk", "Tales"])
        stranger = await started.serve(
            "offered", {"directory": "/srv/elsewhere"}, Machine()
        )
        assert isinstance(stranger, Refused)

    @lup.promise
    async def a_restart_cuts_no_call(self, by: Testing) -> None:
        """Opening a project it runs starts the containers of this opening beside those running, and stops those only once every container of this opening has started, so calls always have somewhere to go."""
        started = await started_approved(by, OPENING_PODMAN)
        await started.run(
            "hosting",
            "keep",
            {"project": "harmon", "name": "key", "value": "k"},
            lup.Operator(),
        )
        first = await started.serve("opened", Opens().given(), Machine())
        again = await started.serve("opened", Opens().given(), Machine())
        assert isinstance(first, Accepted)
        assert isinstance(again, Accepted)
        before: list[str] = json.loads(first.answer())["containers"]
        after: list[str] = json.loads(again.answer())["containers"]
        assert not [each for each in after if each in before]
        runs = [
            each
            for each in started.ran("podman")
            if (each and each[0] == "stop") or "--detach" in each
        ]
        last_start = max(
            index
            for index, each in enumerate(runs)
            if any(f"--name={name}" in each for name in after)
        )
        first_stop = min(
            index for index, each in enumerate(runs) if each and each[0] == "stop"
        )
        assert last_start < first_stop

    @lup.promise
    async def a_restart_that_fails_leaves_the_project_running(
        self, by: Testing
    ) -> None:
        """Where a container of a project's opening doesn't start, those of the opening that did are stopped, the opening is refused, and the containers the project ran before go on running."""
        podman = Failing(allowed=by.any(Allowed).allowed)
        started = await started_approved(by, podman)
        await started.run(
            "hosting",
            "keep",
            {"project": "harmon", "name": "key", "value": "k"},
            lup.Operator(),
        )
        first = await started.serve("opened", Opens().given(), Machine())
        again = await started.serve("opened", Opens().given(), Machine())
        assert isinstance(first, Accepted) == (podman.allowed >= 2)
        assert isinstance(again, Accepted) == (podman.allowed >= 4)
        if not isinstance(first, Accepted) or isinstance(again, Accepted):
            return
        before: list[str] = json.loads(first.answer())["containers"]
        stopped = [each[-1] for each in podman_ran(started, "stop")]
        assert not [each for each in stopped if each in before]


class Allowed(Model):
    """How many containers a promise's podman starts before it fails to."""

    allowed: int = Field(ge=0, le=4)


class Failing(lup.MutableModel, Responding):
    """podman as a promise stands it in where it fails to start a container past the first `allowed`: the image there, the plan of a part holding nothing and one holding a secret."""

    allowed: int
    started: int = 0

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer each run, failing to start a container past the first `allowed`."""
        del given
        if arguments and arguments[0] == "version":
            return VERSIONED
        if "--detach" in arguments:
            self.started += 1
            return Answering(status=0 if self.started <= self.allowed else 125)
        if "--interactive" in arguments:
            return Answering(output=json.dumps(VAULT_PLAN))
        return Answering()


class LendingPromises(Part):
    """What the operator can count on of what their machine lends a part acting for agents: only to a part holding it, running apart."""

    @lup.promise
    async def a_part_is_lent_the_git_directory_and_login_it_holds(
        self, by: Testing
    ) -> None:
        """A part holding the project's git directory and the operator's GitHub login runs in a container of its own: the git directory bound read-write at its own path, its `config` and `hooks/` read-only over it, and its image installing the packages its programs are in; where `gh` lends no login, it waits, not started. A part holding nothing is lent neither."""
        logged = by.any(bool)
        plan = plan_of(
            Planned(module="notes", part="Notes"),
            Planned(
                module="github",
                part="Forge",
                git=True,
                github=["login"],
                packages=["github-cli"],
            ),
        )
        podman = Scripted(
            answers=[
                VERSIONED,
                Answering(when=["image", "exists"], status=0),
                Answering(when=["run", "--interactive"], output=json.dumps(plan)),
                Answering(when=["run", "--detach"]),
                Answering(when=["stop"]),
            ]
        )
        gh = Scripted(
            answers=[
                Answering(when=["auth", "token"], output="gho_lent\n")
                if logged
                else Answering(when=["auth", "token"], status=1, error="not logged in")
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            common = Path(directory) / "harmon.git"
            (common / "hooks").mkdir(parents=True)
            (common / "config").touch()
            started = await started_approved(by, podman, gh=gh)
            opened = await started.serve(
                "opened", Opens(common=str(common)).given(), Machine()
            )
        assert isinstance(opened, Accepted)
        result = json.loads(opened.answer())
        assert ("github.Forge" in result["unlent"]) != logged
        detached = [each for each in podman_ran(started, "run") if "--detach" in each]
        forge = [
            each for each in detached if "--name=lup-harmon-github-Forge-1" in each
        ]
        project = [each for each in detached if "--name=lup-harmon-project-1" in each]
        assert len(forge) == int(logged)
        assert len(project) == 1
        assert not [
            each
            for each in project[0]
            if each.startswith("--mount=") and str(common) in each
        ]
        for command in forge:
            mounts = [
                each
                for each in command
                if each.startswith("--mount=") and str(common) in each
            ]
            writable = [each for each in mounts if "ro=true" not in each]
            assert writable
            assert all(each.endswith(f"destination={common}") for each in writable)
            assert any(f"destination={common / 'config'}" in each for each in mounts)
            assert any(f"destination={common / 'hooks'}" in each for each in mounts)
        images = dict.fromkeys(
            each[-1] for each in podman_ran(started, "image") if each[1] == "exists"
        )
        assert len(images) == 1 + int(logged)


class ClearingPromises(Part):
    """What the operator can count on of the machine's parts starting again: nothing left running that no call reaches."""

    @lup.promise
    async def the_machine_stops_every_container_it_left(self, by: Testing) -> None:
        """Every container lup starts is labelled as lup's and its project's, and clearing stops every container so labelled, as the machine's parts start, those a machine that stopped before left among them; only the machine's own parts may clear."""
        asked = by.any(Asked)
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        await started.serve("started", asked.spec(), Machine())
        [command] = podman_ran(started, "run")
        assert "--label=lup.machine" in command
        assert "--label=lup.project=harness" in command
        refused = await started.serve("cleared", {}, by.any(Agent))
        assert isinstance(refused, Refused)
        cleared = await started.serve("cleared", {}, Machine())
        assert isinstance(cleared, Accepted)
        stopped = podman_ran(started, "stop")
        assert stopped
        assert all("--filter=label=lup.machine" in each for each in stopped)

    @lup.promise
    async def the_machine_opens_again_what_it_ran(self, by: Testing) -> None:
        """As the machine's parts start, they open again each project they ran before they last stopped, at the commit approved last; with nothing run before, they open nothing."""
        ran = by.any(bool)
        started = await started_approved(by, OPENING_PODMAN)
        if ran:
            await started.serve("opened", Opens().given(), Machine())
        resumed = await started.serve("resumed", {}, Machine())
        assert isinstance(resumed, Accepted)
        answer = json.loads(resumed.answer())
        assert ("harmon" in answer["opened"]) == ran

    @lup.promise
    async def a_project_registered_is_opened_as_the_machine_starts(
        self, by: Testing
    ) -> None:
        """The operator registers a project with their lup without opening it, and it's opened as the machine's parts start, once a commit of it is approved; a name another project, at another git directory, holds already is refused."""
        started = await started_approved(by, OPENING_PODMAN)
        operator = lup.Operator()
        registered = await started.run("hosting", "register", Opens().given(), operator)
        taken = await started.run(
            "hosting",
            "register",
            {"repository": "harmon", "common": "/srv/elsewhere.git"},
            operator,
        )
        assert isinstance(registered, Accepted)
        assert isinstance(taken, Refused)
        assert podman_ran(started, "run") == []
        resumed = await started.serve("resumed", {}, Machine())
        assert isinstance(resumed, Accepted)
        assert "harmon" in json.loads(resumed.answer())["opened"]


class Podmanless(Model):
    """podman as a promise checks the machine without it: not there, at a version lup doesn't take, saying something that's no version, or at one it takes."""

    version: Literal["", "4.9.3", "not a version", "6.1.0"]
    """What it says its version is; nothing for not there at all."""


class WithoutPromises(Part):
    """What the operator can count on of the machine without a program it uses: the parts needing it don't start, the others do."""

    @lup.promise
    async def without_podman_only_what_needs_it_is_refused(self, by: Testing) -> None:
        """Without podman, or with one at a version lup doesn't take, the part holding it isn't made and what needs it is refused, saying it's podman and why, while the machine's other parts answer: the operator can still keep a secret; with one it takes, it starts containers."""
        podman = by.any(Podmanless).version
        programs: dict[str, Scripted | Responding] = (
            {"uv": UV}
            if not podman
            else {
                "uv": UV,
                "podman": Scripted(
                    answers=[
                        Answering(when=["version"], output=f"{podman}\n"),
                        Answering(when=["run"]),
                    ]
                ),
            }
        )
        started = await by.started(
            lup.testing.Repository(declaration=HOME), programs=programs, machine=True
        )
        run = await started.serve("started", by.any(Asked).spec(), Machine())
        kept = await started.run(
            "hosting",
            "keep",
            {"project": "harmon", "name": "token", "value": "t"},
            lup.Operator(),
        )
        status = await started.run("hosting", "status", {}, lup.Operator())
        assert isinstance(kept, Accepted)
        assert isinstance(status, Accepted)
        assert isinstance(run, Accepted) == (podman == "6.1.0")
        assert bool(podman_ran(started, "run")) == (podman == "6.1.0")
        if isinstance(run, Refused):
            assert "podman" in run.rejection.about

    @lup.promise
    async def the_machine_stopping_stops_its_projects(self, by: Testing) -> None:
        """As the machine's parts stop, every container of every project they run is stopped: nothing would route calls to it."""
        started = await started_approved(by, OPENING_PODMAN)
        await started.run(
            "hosting",
            "keep",
            {"project": "harmon", "name": "key", "value": "k"},
            lup.Operator(),
        )
        opened = await started.serve("opened", Opens().given(), Machine())
        assert isinstance(opened, Accepted)
        containers: list[str] = json.loads(opened.answer())["containers"]
        await started.stopped()
        stopped = [each[-1] for each in podman_ran(started, "stop")]
        assert stopped == containers

    @lup.promise
    async def the_operator_sees_what_the_machine_runs(self, by: Testing) -> None:
        """The operator can ask what the machine runs: each project open with the commit it runs and its containers, each registered and not open; an agent or a project's code can't."""
        opened = by.any(bool)
        committed = Committed.of(Files())
        started = await started_approved(by, OPENING_PODMAN, committed)
        await started.run("hosting", "register", Opens().given(), lup.Operator())
        if opened:
            await started.serve("opened", Opens().given(), Machine())
        status = await started.run("hosting", "status", {}, lup.Operator())
        refused = await started.run("hosting", "status", {}, by.any(Agent))
        assert isinstance(status, Accepted)
        assert isinstance(refused, Refused)
        said = status.answer()
        assert "harmon" in said
        assert (committed.commit in said) == opened
        assert ("lup-harmon-project-1" in said) == opened

    @lup.promise
    async def what_a_container_prints_is_kept_capped(self, by: Testing) -> None:
        """What a project's container prints goes to a file of its own, capped in size, which no container mounts; a container run to its end, whose output its caller reads, keeps nothing."""
        started = await started_approved(by, OPENING_PODMAN)
        opened = await started.serve("opened", Opens().given(), Machine())
        assert isinstance(opened, Accepted)
        runs = podman_ran(started, "run")
        detached = [each for each in runs if "--detach" in each]
        planned = [each for each in runs if "--interactive" in each]
        assert detached
        for command in detached:
            assert "--log-driver=k8s-file" in command
            [path] = [each for each in command if each.startswith("--log-opt=path=")]
            assert path.endswith(".log")
            assert not [
                each
                for each in command
                if each.startswith("--mount=") and "outputs" in each
            ]
            assert any(each.startswith("--log-opt=max-size=") for each in command)
        assert all("--log-driver=none" in command for command in planned)


class HereCommand(Model):
    """A command `lup` answers where it's typed, as a promise names one."""

    name: Literal["init", "new", "check"]


class HerePromises(Part):
    """What the operator can count on of a command `lup` answers where it's typed: the machine never carries it."""

    @lup.promise
    async def a_command_answered_where_typed_is_never_carried(
        self, by: Testing
    ) -> None:
        """A call to a command `lup` answers where it's typed, over that worktree's declaration, is refused by the machine rather than carried to the project's container, where it would mean nothing; the project's other calls are carried as ever, another command of the same part's among them."""
        command = by.any(HereCommand).name
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        plan = plan_of(
            Planned(
                module="notes",
                part="Notes",
                tools=["note"],
                here=[command],
                commands=["tidy"],
            )
        )
        directory = await placed(started, "harmon", plan, ["notes.Notes"])
        other: JsonValue = {
            "format": 1,
            "kind": "command",
            "module": "notes",
            "command": "tidy",
            "given": {},
        }
        alongside = await started.serve(
            "routed", {"directory": directory, "call": other}, Machine()
        )
        assert isinstance(alongside, Accepted)
        assert json.loads(alongside.answer())["to"] is not None
        here: JsonValue = {
            "format": 1,
            "kind": "command",
            "module": "notes",
            "command": command,
            "given": {},
        }
        tool: JsonValue = {"format": 1, "kind": "tool", "tool": "note", "given": {}}
        refused = await started.serve(
            "routed", {"directory": directory, "call": here}, Machine()
        )
        carried = await started.serve(
            "routed", {"directory": directory, "call": tool}, Machine()
        )
        assert isinstance(refused, Refused)
        assert isinstance(carried, Accepted)

    @lup.promise
    async def status_says_why_a_project_isnt_open(self, by: Testing) -> None:
        """Where opening a project registered was refused, the operator's status says why, beside saying it isn't open."""
        podman = Scripted(
            answers=[
                VERSIONED,
                Answering(when=["stop"]),
                Answering(when=["image", "exists"], status=125),
            ]
        )
        started = await started_approved(by, podman)
        await started.run("hosting", "register", Opens().given(), lup.Operator())
        resumed = await started.serve("resumed", {}, Machine())
        status = await started.run("hosting", "status", {}, lup.Operator())
        assert isinstance(resumed, Accepted)
        assert isinstance(status, Accepted)
        said = status.answer()
        assert json.loads(resumed.answer())["refused"]["harmon"] in said
        assert "lup-harmon-project-1" not in said


class Flaky(lup.MutableModel, Responding):
    """podman as a promise stands it in where building an image fails its first `failing` times, as fetching packages does when the network does."""

    failing: int
    built: int = 0

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer each run, failing a build the first `failing` times."""
        del given
        if arguments and arguments[0] == "version":
            return VERSIONED
        if arguments and arguments[0] == "image":
            return Answering(status=1)
        if arguments and arguments[0] == "build":
            self.built += 1
            return Answering(status=1 if self.built <= self.failing else 0)
        return Answering()


class Failures(Model):
    """How many times a promise's podman fails to build before it builds."""

    failing: int = Field(ge=0, le=4)


class BuildingPromises(Part):
    """What the operator can count on of an image built over a network that fails at times."""

    @lup.promise
    async def a_build_failing_for_a_moment_is_built_again(self, by: Testing) -> None:
        """An image whose build fails is built again, three times at most: a failure that passes is built; one that doesn't is refused, saying podman's words."""
        podman = Flaky(failing=by.any(Failures).failing)
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": podman},
            machine=True,
        )
        image = {"base": BASE, "definition": "FROM scratch", "project": "harness"}
        built = await started.serve("built", image, Machine())
        assert isinstance(built, Accepted) == (podman.failing < 3)
        assert podman.built == min(podman.failing + 1, 3)


class MachinewidePromises(Part):
    """What the operator can count on of a part one for the whole machine that doesn't hold the machine: it runs in a container of its own, from the machine's own code, holding only what it declares."""

    @lup.promise
    async def a_part_one_for_the_machine_runs_in_a_container_of_its_own(
        self, by: Testing
    ) -> None:
        """A part one for the whole machine that doesn't hold the machine runs in a container of its own, from the machine's own environment, tree and source read-only, never from a working directory, its data the directory it kept on the machine; a part holding the machine starts no container; one that doesn't come up listening is stopped and said; and a project's call to one that did is carried there, never answered on the machine."""
        listens = by.any(bool)
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": OPENING_PODMAN, "uv": UV},
            machine=True,
        )
        plan = plan_of(
            Planned(module="chat", part="Desk", shared=True, tools=["note"]),
            Planned(module="hosting", part="Keeper", shared=True),
        )
        keeper = json.loads(json.dumps(plan))
        keeper["parts"][1]["holds"]["machine"] = True
        made = await started.serve(
            "directory", {"container": "lup-machine-chat-Desk-1"}, Machine()
        )
        assert isinstance(made, Accepted)
        if listens:
            (Path(json.loads(made.answer())["path"]) / "listening.sock").touch()
        with tempfile.TemporaryDirectory() as state:
            data = Path(state) / "data"
            sharing: JsonValue = {
                "repository": "lup",
                "root": "/srv/lup",
                "declaration": "lup_project.py",
                "environment": "/srv/environment",
                "paths": ["/srv/src"],
                "data": str(data),
                "plan": keeper,
            }
            shared = await started.serve("machinewide", sharing, Machine())
            kept = (data / "chat.Desk").is_dir()
        assert kept
        assert isinstance(shared, Accepted)
        answer = json.loads(shared.answer())
        container = "lup-machine-chat-Desk-1"
        assert (container in answer["containers"]) == listens
        assert ("chat.Desk" in answer["failed"]) != listens
        stopped = [each[-1] for each in podman_ran(started, "stop")]
        assert (container in stopped) != listens
        [command] = [
            each for each in podman_ran(started, "run") if f"--name={container}" in each
        ]
        assert "-I" in command
        assert "--workdir=/" in command
        mounts = [each for each in command if each.startswith("--mount=")]
        environment = [
            each for each in mounts if "/srv/environment" in each or "/srv/src" in each
        ]
        data = [each for each in mounts if "/data/chat.Desk" in each]
        assert len(environment) == 2
        assert all("ro=true" in each for each in environment)
        assert data
        assert not any("ro=true" in each for each in data)
        assert not [each for each in mounts if "Keeper" in each]
        status = await started.run("hosting", "status", {}, lup.Operator())
        assert isinstance(status, Accepted)
        assert (f"  {container}, " in status.answer()) == listens
        if not listens:
            return
        project = await placed(started, "harmon", NOTES_PLAN, ["notes.Notes"])
        await started.serve(
            "placed",
            {"repository": "lup", "plan": keeper, "placements": []},
            Machine(),
        )
        call: JsonValue = {"format": 1, "kind": "tool", "tool": "note", "given": {}}
        hosted = await started.serve(
            "routed", {"directory": project, "call": call}, Machine()
        )
        assert isinstance(hosted, Accepted)
        assert json.loads(hosted.answer())["to"] is not None

    @lup.promise
    async def a_machinewide_container_starts_whatever_its_tree_holds(
        self, by: Testing
    ) -> None:
        """The program a container of a part one for the whole machine runs starts the machine's own lup whatever the tree it starts in holds: run where its container would start it, in the installed `lup`'s tree, whose `secrets.py` would stand in for the standard library's, it plans the installed `lup`'s declaration."""
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": OPENING_PODMAN, "uv": UV},
            machine=True,
        )
        tree = Path(lup.hosting.__file__).parent
        environment = Path(sys.prefix)
        plan = plan_of(Planned(module="chat", part="Desk", shared=True, tools=["note"]))
        with tempfile.TemporaryDirectory() as state:
            sharing: JsonValue = {
                "repository": "lup",
                "root": str(tree),
                "declaration": "installed.py",
                "environment": str(environment),
                "data": str(Path(state) / "data"),
                "plan": plan,
            }
            shared = await started.serve("machinewide", sharing, Machine())
        assert isinstance(shared, Accepted)
        [command] = [
            each
            for each in podman_ran(started, "run")
            if "--name=lup-machine-chat-Desk-1" in each
        ]
        [workdir] = [
            each.removeprefix("--workdir=")
            for each in command
            if each.startswith("--workdir=")
        ]
        program = command[command.index(str(environment / "bin" / "python")) :]
        planning = {"format": 1, "kind": "plan", "root": str(tree)}
        ran = lup.programs.run(
            *program,
            cwd=Path(workdir),
            stdin=json.dumps({**planning, "declaration": "installed.py"}),
            checked=False,
        )
        assert ran.status == 0, ran.said()
        assert json.loads(ran.text())["parts"]


class Aim(Model):
    """Which project the machine's own call names, as a promise draws it: one running the part, another, or none."""

    project: Literal["harmon", "story", "unknown"] | None


class AimingPromises(Part):
    """What the operator can count on of the machine calling one project's part: it reaches that project's container, and no other."""

    @lup.promise
    async def the_machines_call_reaches_the_project_it_names(self, by: Testing) -> None:
        """A service call the machine's own parts make to a part one per project goes to the container of the project the call names, never another project's: one naming no project, or a project running no such part, is refused; and only the machine's own parts may aim one."""
        aim = by.any(Aim).project
        started = await by.started(
            lup.testing.Repository(declaration=HOME),
            programs={"podman": PODMAN},
            machine=True,
        )
        served = plan_of(Planned(module="remote", part="Remotes", services=["pushed"]))
        harmon = await placed(started, "harmon", served, ["remote.Remotes"])
        story = await placed(started, "story", served, ["remote.Remotes"])
        aiming: JsonValue = {"service": "pushed", "project": aim}
        aimed = await started.serve("aimed", aiming, Machine())
        refused = await started.serve("aimed", aiming, by.any(Agent))
        assert isinstance(refused, Refused)
        match aim:
            case "harmon" | "story":
                assert isinstance(aimed, Accepted)
                own = harmon if aim == "harmon" else story
                assert json.loads(aimed.answer())["to"] == f"{own}/listening.sock"
            case _:
                assert isinstance(aimed, Refused)
