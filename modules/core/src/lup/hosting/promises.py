"""The machine's parts, their promises: what the operator can count on of what runs on their machine.

Each is checked through the harness, the machine's parts started as the
machine's own (`machine=True`), every program they run stood in for as the
promise scripts it, so the gate checks what lup asks podman to do without
running it (`README.md` here, *Promises*).
"""

import json
from typing import Literal, get_args

from pydantic import Field, JsonValue

import lup
from lup import Agent, Codebase, Machine, Model, Part
from lup.testing import Accepted, Answering, Refused, Scripted, Started, Testing

HOME = """
from lup import Modules, Project
from lup.hosting.module import Hosting

project = Project(modules=Modules.default().add(Hosting()))
"""
"""The home repository's declaration, as lup's own declares it: lup's default
modules and the machine's parts."""


def plan_of(parts: list[JsonValue]) -> JsonValue:
    """Return a plan's JSON holding `parts`."""
    return {"format": 1, "parts": parts, "tools": [], "files": []}


NOTES_PLAN = plan_of(
    [
        {
            "module": "notes",
            "part": "Notes",
            "holds": {},
            "doorways": [{"door": "tool", "name": "note", "parties": ["Agent"]}],
        }
    ]
)
"""A project's plan of one part holding nothing, serving a tool."""

VAULT_PLAN = plan_of(
    [
        {"module": "notes", "part": "Notes", "holds": {}, "doorways": []},
        {
            "module": "vault",
            "part": "Vault",
            "holds": {"secrets": ["key"]},
            "doorways": [],
        },
    ]
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
    """A project the promises open: harmon unless it says, its tree and the machine's interpreters."""

    repository: str = "harmon"
    root: str = "/srv/harmon"
    interpreters: str = "/srv/python"

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


PODMAN = Scripted(
    answers=[
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
    "--log-driver=none",
    "--userns=keep-id",
    "--cap-drop=all",
    "--security-opt=no-new-privileges",
]
"""What every container lup starts stands behind, as podman's options."""


def podman_ran(started: Started, verb: str) -> list[list[str]]:
    """Return the arguments of each run of podman the machine's parts asked for whose first is `verb`."""
    return [each for each in started.ran("podman") if each and each[0] == verb]


class HostingPromises(Part):
    """What the operator can count on of the parts that run on their machine."""

    @lup.promise
    async def every_container_stands_behind_the_same_walls(self, by: Testing) -> None:
        """Every container lup starts, whatever asked for it and however, stands behind the same walls: the operator's uid inside, every capability dropped, no privilege gained, a limit on processes, reaped, removed when it ends, no image fetched, no log kept."""
        asked = by.any(Asked)
        started = await by.started(HOME, programs={"podman": PODMAN}, machine=True)
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
        started = await by.started(HOME, programs={"podman": PODMAN}, machine=True)
        await started.serve("started", asked.spec(), Machine())
        [command] = podman_ran(started, "run")
        binds = [each for each in command if each.startswith("--mount=type=bind")]
        assert len(binds) == len(asked.sources)
        assert all(("ro=true" in each) != asked.writable for each in binds)

    @lup.promise
    async def only_the_machines_own_parts_start_a_container(self, by: Testing) -> None:
        """Only the machine's own parts may start or stop a container: an agent, or any project's code, the home repository's own branch among it, is refused, and podman never runs for it."""
        asked = by.any(Asked)
        started = await by.started(HOME, programs={"podman": PODMAN}, machine=True)
        caller = by.any(Agent) if by.any(bool) else Codebase(repository=by.any(str))
        refused = await started.serve("started", asked.spec(), caller)
        stopped = await started.serve("stopped", {"name": asked.name}, caller)
        assert isinstance(refused, Refused)
        assert isinstance(stopped, Refused)
        assert started.ran("podman") == []

    @lup.promise
    async def an_image_is_built_only_where_it_isnt_there(self, by: Testing) -> None:
        """An image is built only where its tag isn't there yet, its base fetched by its digest first where it isn't there either, and the build itself fetches nothing."""
        image = {"base": BASE, "definition": "FROM scratch", "project": "harness"}
        tagged, based = by.any(bool), by.any(bool)
        podman = Scripted(
            answers=[
                Answering(when=["image", "exists", BASE], status=0 if based else 1),
                Answering(when=["image", "exists"], status=0 if tagged else 1),
                Answering(when=["pull", "--quiet", BASE]),
                Answering(when=["build"]),
            ]
        )
        started = await by.started(HOME, programs={"podman": podman}, machine=True)
        built = await started.serve("built", image, Machine())
        assert isinstance(built, Accepted)
        assert json.loads(built.answer()) == {"built": not tagged}
        builds = podman_ran(started, "build")
        assert bool(builds) != tagged
        assert all("--pull=never" in each for each in builds)
        assert bool(podman_ran(started, "pull")) == (not tagged and not based)

    @lup.promise
    async def a_base_not_named_by_its_digest_is_refused(self, by: Testing) -> None:
        """An image whose base isn't named by its digest is refused, and nothing is fetched or built: what's fetched under a name could change."""
        started = await by.started(HOME, programs={"podman": PODMAN}, machine=True)
        image: JsonValue = {
            "base": by.any(Unpinned).base,
            "definition": "FROM scratch",
            "project": "harness",
        }
        refused = await started.serve("built", image, Machine())
        assert isinstance(refused, Refused)
        assert started.ran("podman") == []

    @lup.promise
    async def a_mount_through_a_link_or_relative_path_is_refused(
        self, by: Testing
    ) -> None:
        """A container mounting a path that isn't its own, a relative one or one through a link, is refused, and podman never runs: it would follow the path wherever it points."""
        asked = by.any(Asked)
        binds: list[JsonValue] = [{"source": by.any(Unowned).source}]
        spec = {**asked.spec(), "binds": binds}
        started = await by.started(HOME, programs={"podman": PODMAN}, machine=True)
        refused = await started.serve("started", spec, Machine())
        assert isinstance(refused, Refused)
        assert started.ran("podman") == []

    @lup.promise
    async def podman_failing_is_a_refusal_saying_why(self, by: Testing) -> None:
        """podman failing to start a container refuses the call that asked, saying why, rather than leaving it believed running."""
        asked = by.any(Asked)
        podman = Scripted(answers=[Answering(when=["run"], status=125, error="no")])
        started = await by.started(HOME, programs={"podman": podman}, machine=True)
        refused = await started.serve("started", asked.spec(), Machine())
        assert isinstance(refused, Refused)

    @lup.promise
    async def a_part_is_handed_only_the_secrets_it_holds(self, by: Testing) -> None:
        """The machine's parts hand a part the secrets kept for its project that it holds, and name those that aren't kept, for the operator to be asked for; another project's secret of the same name is never among them."""
        kept, other = by.any(Kept), by.any(Kept)
        started = await by.started(HOME, programs={"podman": PODMAN}, machine=True)
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
        assert values["values"] == {"token": kept.value}
        assert values["missing"] == ["key"]

    @lup.promise
    async def only_the_machine_reads_a_secret_and_only_the_operator_keeps_one(
        self, by: Testing
    ) -> None:
        """A secret kept is read only by the machine's own parts, and kept only by the operator: an agent or a project's code asking for one, or giving one, is refused."""
        started = await by.started(HOME, programs={"podman": PODMAN}, machine=True)
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
        """A call coming in on a container's socket is by that container's project, whatever the call says it's by; one coming in on a socket no container lup started has is refused."""
        claimed = by.any(Agent)
        started = await by.started(HOME, programs={"podman": PODMAN}, machine=True)
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
            "by": claimed.model_dump(mode="json"),
        }
        route = await started.serve(
            "routed", {"directory": directory, "call": call}, Machine()
        )
        assert isinstance(route, Accepted)
        carried = json.loads(route.answer())
        assert carried["call"]["by"] == {"party": "code", "repository": "harmon"}
        assert carried["to"].endswith("listening.sock")
        stranger = await started.serve(
            "routed", {"directory": "/srv/elsewhere", "call": call}, Machine()
        )
        assert isinstance(stranger, Refused)

    @lup.promise
    async def a_part_holding_a_secret_runs_apart_given_only_its_own(
        self, by: Testing
    ) -> None:
        """Opening a project starts one container for its parts holding nothing, and one of its own for each part holding a secret, given that part's secrets alone; a part whose secret nothing kept waits, not started."""
        kept = by.any(bool)
        podman = Scripted(
            answers=[
                Answering(when=["image", "exists"], status=0),
                Answering(when=["run", "--interactive"], output=json.dumps(VAULT_PLAN)),
                Answering(when=["run", "--detach"]),
            ]
        )
        started = await by.started(HOME, programs={"podman": podman}, machine=True)
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
        assert "--name=lup-harmon-project" in names
        assert ("--name=lup-harmon-vault-Vault" in names) == kept

    @lup.promise
    async def a_call_reaches_its_own_projects_parts_or_the_machines(
        self, by: Testing
    ) -> None:
        """A call is carried to a part of the caller's own project running in its containers, or else to the machine's own parts: never to another project's part, nor to a part another project's plan says is the machine's."""
        claims = by.any(bool)
        started = await by.started(HOME, programs={"podman": PODMAN}, machine=True)
        own = await placed(started, "harmon", NOTES_PLAN, ["notes.Notes"])
        claimed = plan_of(
            [
                {
                    "module": "notes",
                    "part": "Notes",
                    "holds": {"shared": True},
                    "doorways": [
                        {"door": "tool", "name": "note", "parties": ["Agent"]}
                    ],
                }
            ]
        )
        other = await placed(started, "story", claimed if claims else plan_of([]), [])
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
        door = by.any(Tied)
        doorway: JsonValue = {"door": door.door, "name": "same", "parties": ["Agent"]}
        parts: list[JsonValue] = [
            {"module": "notes", "part": part, "holds": {}, "doorways": [doorway]}
            for part in ["Notes", "Drafts"]
        ]
        tied = plan_of(parts)
        podman = Scripted(
            answers=[
                Answering(when=["image", "exists"], status=0),
                Answering(when=["run", "--interactive"], output=json.dumps(tied)),
                Answering(when=["run", "--detach"]),
            ]
        )
        started = await by.started(HOME, programs={"podman": podman}, machine=True)
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
        plan = plan_of(
            [{"module": unsafe.name, "part": "Notes", "holds": {}, "doorways": []}]
        )
        podman = Scripted(
            answers=[
                Answering(when=["image", "exists"], status=0),
                Answering(when=["run", "--interactive"], output=json.dumps(plan)),
                Answering(when=["run", "--detach"]),
            ]
        )
        started = await by.started(HOME, programs={"podman": podman}, machine=True)
        opening = Opens() if in_plan else Opens(repository=unsafe.name)
        opened = await started.serve("opened", opening.given(), Machine())
        assert isinstance(opened, Refused)
        assert not [each for each in podman_ran(started, "run") if "--detach" in each]

    @lup.promise
    async def each_container_has_its_own_environment(self, by: Testing) -> None:
        """Each container of a project syncs its Python environment and uv's cache in directories of its own, so code running in one never writes what another imports."""
        podman = Scripted(
            answers=[
                Answering(when=["image", "exists"], status=0),
                Answering(when=["run", "--interactive"], output=json.dumps(VAULT_PLAN)),
                Answering(when=["run", "--detach"]),
            ]
        )
        started = await by.started(HOME, programs={"podman": podman}, machine=True)
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
