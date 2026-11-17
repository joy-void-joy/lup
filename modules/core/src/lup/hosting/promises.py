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
from lup.testing import (
    Accepted,
    Answering,
    Refused,
    Repository,
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
            "image": {"definition": self.definition, "project": "harness"},
            "command": list(self.command),
            "workdir": "/srv/work",
            "binds": [
                {"source": each, "read_only": not self.writable}
                for each in self.sources
            ],
            "network": self.network,
            "gpu": self.gpu,
        }


PODMAN = Scripted(
    answers=[
        Answering(when=["run"]),
        Answering(when=["stop"]),
        Answering(when=["image", "exists"], status=1),
        Answering(when=["build"]),
    ]
)
"""podman as the promises stand it in: every run, stop and build succeeds, and
no image is there yet."""

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
        started = await by.started(
            Repository(declaration=HOME), programs={"podman": PODMAN}, machine=True
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
            Repository(declaration=HOME), programs={"podman": PODMAN}, machine=True
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
            Repository(declaration=HOME), programs={"podman": PODMAN}, machine=True
        )
        caller = by.any(Agent) if by.any(bool) else Codebase(repository=by.any(str))
        refused = await started.serve("started", asked.spec(), caller)
        stopped = await started.serve("stopped", {"name": asked.name}, caller)
        assert isinstance(refused, Refused)
        assert isinstance(stopped, Refused)
        assert started.ran("podman") == []

    @lup.promise
    async def an_image_is_built_only_where_it_isnt_there(self, by: Testing) -> None:
        """An image is built only where its tag isn't there yet: one already there is found, and nothing is built."""
        there = by.any(bool)
        podman = Scripted(
            answers=[
                Answering(when=["image", "exists"], status=0 if there else 1),
                Answering(when=["build"]),
            ]
        )
        started = await by.started(
            Repository(declaration=HOME), programs={"podman": podman}, machine=True
        )
        image = {"definition": "FROM scratch", "project": "harness"}
        built = await started.serve("built", image, Machine())
        assert isinstance(built, Accepted)
        assert json.loads(built.answer()) == {"built": not there}
        assert bool(podman_ran(started, "build")) != there

    @lup.promise
    async def podman_failing_is_a_refusal_saying_why(self, by: Testing) -> None:
        """podman failing to start a container refuses the call that asked, saying why, rather than leaving it believed running."""
        asked = by.any(Asked)
        podman = Scripted(answers=[Answering(when=["run"], status=125, error="no")])
        started = await by.started(
            Repository(declaration=HOME), programs={"podman": podman}, machine=True
        )
        refused = await started.serve("started", asked.spec(), Machine())
        assert isinstance(refused, Refused)
