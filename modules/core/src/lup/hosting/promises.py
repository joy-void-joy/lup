"""The machine's parts, their promises: what the operator can count on of what runs on their machine.

Each is checked through the harness, the machine's parts started as the
machine's own (`machine=True`), every program they run stood in for as the
promise scripts it, so the gate checks what lup asks podman to do without
running it (`README.md` here, *Promises*).
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Literal, get_args

from pydantic import Field, JsonValue

import lup
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
    """A part of a project's plan, as a promise writes one: its module and class, what it holds, the file it's defined in, and the tools and services it serves, each called by an agent."""

    module: str
    part: str
    secrets: list[str] = []
    shared: bool = False
    source: str | None = None
    tools: list[str] = []
    services: list[str] = []

    def plan(self) -> JsonValue:
        """Return it as a plan says it, as JSON: promises read lup's plan only through what crosses."""
        doorways: list[JsonValue] = [
            {"door": door, "name": name, "parties": ["Agent"]}
            for door, names in [("tool", self.tools), ("service", self.services)]
            for name in names
        ]
        return {
            "module": self.module,
            "part": self.part,
            "holds": {"secrets": list[JsonValue](self.secrets), "shared": self.shared},
            "source": self.source,
            "doorways": doorways,
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
    """A project the promises open: harmon unless it says, where git keeps it, and the machine's interpreters."""

    repository: str = "harmon"
    common: str = "/srv/harmon.git"
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
        """A call coming in on a container's socket is by that container's project, whatever the call says it's by, or where it says nothing; one coming in on a socket no container lup started has is refused."""
        claimed = by.any(Agent) if by.any(bool) else None
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
            "by": None if claimed is None else claimed.model_dump(mode="json"),
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
                Answering(when=["image", "exists"], status=0),
                Answering(when=["run", "--interactive"], output=json.dumps(VAULT_PLAN)),
                Answering(when=["run", "--detach"]),
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
            HOME, programs={"git": committed.store}, machine=True
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
        started = await by.started(HOME, programs={"git": swapped}, machine=True)
        exported = await started.serve("exported", committed.exporting(), Machine())
        assert isinstance(exported, Refused) == (planted != files.nested)

    @lup.promise
    async def git_reads_the_repository_alone(self, by: Testing) -> None:
        """git, reading a commit's objects, is held to the repository's own git directory, reading no `commondir`, graft, replace ref, commit-graph or configuration but the repository's own, with nothing that could run code."""
        committed = Committed.of(by.any(Files))
        started = await by.started(
            HOME, programs={"git": committed.store}, machine=True
        )
        await started.serve("exported", committed.exporting(), Machine())
        runs = [each for each in started.heard.runs if each.program == "git"]
        pins = {
            "GIT_DIR": "/srv/harmon.git",
            "GIT_COMMON_DIR": "/srv/harmon.git",
            "GIT_GRAFT_FILE": os.devnull,
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
            HOME, programs={"git": committed.store}, machine=True
        )
        exported = await started.serve("exported", committed.exporting(), Machine())
        assert isinstance(exported, Refused)

    @lup.promise
    async def only_the_machine_writes_out_a_commit(self, by: Testing) -> None:
        """Only the machine's own parts may write out a commit: an agent or a project's code asking is refused, and git never runs for it."""
        committed = Committed.of(by.any(Files))
        caller = by.any(Agent) if by.any(bool) else Codebase(repository="harmon")
        started = await by.started(
            HOME, programs={"git": committed.store}, machine=True
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
            HOME, programs={"git": committed.store}, machine=True
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
        started = await by.started(HOME, machine=True)
        for each in approvals:
            asked = {"project": "harmon", "commit": each.commit}
            if each.landing:
                await started.serve("landed", asked, Machine())
            else:
                await started.run("hosting", "approve", asked, lup.Operator())
        approval = await started.serve("approval", {"project": "harmon"}, Machine())
        assert isinstance(approval, Accepted)
        last = approvals[-1].commit if approvals else None
        assert json.loads(approval.answer()) == {"commit": last}

    @lup.promise
    async def only_the_operator_or_their_review_approves(self, by: Testing) -> None:
        """Only the operator approves a commit to run, answering the question asked or reviewing a landing, which the machine records: an agent or a project's code asking to approve, record or read an approval is refused, and nothing is approved."""
        caller = by.any(Agent) if by.any(bool) else Codebase(repository="harmon")
        started = await by.started(HOME, machine=True)
        asked = {"project": "harmon", "commit": by.any(Approved).commit}
        approved = await started.run("hosting", "approve", asked, caller)
        landed = await started.serve("landed", asked, caller)
        read = await started.serve("approval", {"project": "harmon"}, caller)
        assert isinstance(approved, Refused)
        assert isinstance(landed, Refused)
        assert isinstance(read, Refused)
        approval = await started.serve("approval", {"project": "harmon"}, Machine())
        assert isinstance(approval, Accepted)
        assert json.loads(approval.answer()) == {"commit": None}

    @lup.promise
    async def the_question_shows_what_changed_what_holds_first(
        self, by: Testing
    ) -> None:
        """Before a commit runs, the operator is asked with each file changed since the commit approved before, read from each object's own bytes, those in a directory holding a part that holds something called out, and whether the dependencies changed."""
        was, now = by.any(Files), by.any(Files)
        before, after = Committed.of(was), Committed.of(now)
        store = Store(objects=[*before.store.objects, *after.store.objects])
        started = await by.started(HOME, programs={"git": store}, machine=True)
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
        started = await by.started(HOME, programs={"git": store}, machine=True)
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
        assert json.loads(diffed.answer()) == {"text": DIFF}
        [diff] = [each for each in started.heard.runs if "diff" in each.arguments]
        assert all(
            each in diff.arguments
            for each in ["--no-index", "--no-ext-diff", "--no-textconv"]
        )
        assert {"GIT_CONFIG_GLOBAL": os.devnull}.items() <= diff.env.items()


async def started_approved(
    by: Testing, podman: Scripted, committed: Committed | None = None
) -> Started:
    """Start the machine's parts, podman as `podman` scripts it, and a store of git's objects holding `committed`, a commit of harmon the operator approved."""
    approving = committed or Committed.of(Files())
    started = await by.started(
        HOME, programs={"podman": podman, "git": approving.store}, machine=True
    )
    await started.run(
        "hosting",
        "approve",
        {"project": "harmon", "commit": approving.commit},
        lup.Operator(),
    )
    return started


OPENING_PODMAN = Scripted(
    answers=[
        Answering(when=["image", "exists"], status=0),
        Answering(when=["run", "--interactive"], output=json.dumps(VAULT_PLAN)),
        Answering(when=["run", "--detach"]),
        Answering(when=["stop"]),
    ]
)
"""podman as the promises opening a project stand it in: the image there,
the plan of a part holding nothing and one holding a secret, and every run and
stop succeeding."""


class ProjectsPromises(Part):
    """What the operator can count on of what runs of a project: the commit they approved last, and nothing before."""

    @lup.promise
    async def nothing_of_a_project_runs_before_its_first_approval(
        self, by: Testing
    ) -> None:
        """A project nothing of which the operator approved yet is refused, and no container of it starts: lup asks them before its first run."""
        committed = Committed.of(by.any(Files))
        started = await by.started(
            HOME,
            programs={"podman": OPENING_PODMAN, "git": committed.store},
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
            HOME, programs={"podman": OPENING_PODMAN, "git": store}, machine=True
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
