"""Rooms: the wall's parts, and podman's command lines through a recording executor.

No test runs podman.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from lup.rooms import (
    Container,
    ContainerError,
    Image,
    Mask,
    Mount,
    Podman,
)
from lup.rooms.engine import Exited, Invocation, Process, StoredImage
from lup.sessions.errors import RealCallInTestError

if TYPE_CHECKING:
    from collections.abc import Callable

IMAGE = Image(
    definition="FROM archlinux\nRUN pacman -Sy --noconfirm git\n", project="lup"
)


class Recorder:
    """Runs nothing: records each process, and answers with the next scripted exit."""

    def __init__(self, *exits: Exited) -> None:
        self.exits = list(exits)
        self.processes: list[Process] = []
        self.contexts: list[bool] = []

    def __call__(self, process: Process) -> Exited:
        self.processes.append(process)
        self.contexts.append(Path(process.arguments[-1]).is_dir())
        return self.exits.pop(0)


def podman(*exits: Exited) -> tuple[Podman, Recorder]:
    recorder = Recorder(*exits)
    return Podman(execute=recorder), recorder


# The wall's parts


def test_an_image_is_tagged_by_its_definition_and_project() -> None:
    tag = IMAGE.tag
    repository, _, digest = tag.partition(":")

    assert repository == "localhost/lup-room"
    assert len(digest) == 64
    assert int(digest, 16) >= 0
    assert IMAGE.model_copy().tag == tag
    assert Image(definition=IMAGE.definition + "RUN true\n", project="lup").tag != tag
    assert Image(definition=IMAGE.definition, project="adlib").tag != tag


def test_a_mount_is_at_its_own_path_unless_given_a_target() -> None:
    assert Mount(source=Path("/srv/a")).destination == Path("/srv/a")
    assert Mount(source=Path("/srv/a"), target=Path("/b")).destination == Path("/b")


@pytest.mark.parametrize(
    "build",
    [
        lambda: Mount(source=Path("relative")),
        lambda: Mount(source=Path("/srv/a"), target=Path("b")),
        lambda: Mask(target=Path("tree/other")),
    ],
)
def test_mounted_paths_are_absolute(build: Callable[[], object]) -> None:
    with pytest.raises(ValidationError, match="absolute"):
        build()


def test_a_run_sets_home_itself() -> None:
    with pytest.raises(ValidationError, match="HOME"):
        Invocation(
            container=Container(image=IMAGE, env={"HOME": "/root"}),
            command=["true"],
            workdir=Path("/srv"),
            home=Path("/home/op"),
        )


# Podman's command lines


def test_a_run_carries_the_wall_the_terminal_the_variables_and_the_mounts() -> None:
    engine, _ = podman()
    container = Container(
        image=IMAGE,
        mounts=[
            Mount(source=Path("/srv/lup.git")),
            Mount(source=Path("/srv/lup.git/config"), read_only=True),
            Mask(target=Path("/srv/lup.git/tree/other")),
            Mount(source=Path("/home/op/.claude")),
            Mount(source=Path("/home/op/.cache/uv")),
            Mount(source=Path("/home/op/.local/share/uv/python"), read_only=True),
            Mount(source=Path('/srv/a,b "c"'), target=Path("/mnt/c")),
        ],
        env={"TERM": "xterm-256color", "LANG": "en_US.UTF-8"},
        network="host",
    )
    invocation = Invocation(
        container=container,
        command=["/opt/clis/claude", "--resume"],
        workdir=Path("/srv/lup.git/tree/dev"),
        home=Path("/home/op"),
        terminal=True,
    )

    assert engine.command(invocation) == [
        "podman",
        "run",
        "--rm",
        "--init",
        "--pull=never",
        "--log-driver=none",
        "--userns=keep-id",
        "--cap-drop=all",
        "--security-opt=no-new-privileges",
        "--interactive",
        "--tty",
        "--detach-keys=",
        "--network=host",
        "--workdir=/srv/lup.git/tree/dev",
        "--env=TERM=xterm-256color",
        "--env=LANG=en_US.UTF-8",
        "--env=HOME=/home/op",
        "--mount=type=tmpfs,destination=/home/op,tmpfs-mode=0700,U=true",
        "--mount=type=tmpfs,destination=/home/op/.cache,tmpfs-mode=0700,U=true",
        "--mount=type=tmpfs,destination=/home/op/.local,tmpfs-mode=0700,U=true",
        "--mount=type=tmpfs,destination=/home/op/.local/share,tmpfs-mode=0700,U=true",
        "--mount=type=tmpfs,destination=/home/op/.local/share/uv,tmpfs-mode=0700,U=true",
        "--mount=type=bind,source=/srv/lup.git,destination=/srv/lup.git",
        "--mount=type=bind,source=/srv/lup.git/config,destination=/srv/lup.git/config,ro=true",
        "--mount=type=tmpfs,destination=/srv/lup.git/tree/other,notmpcopyup",
        "--mount=type=bind,source=/home/op/.claude,destination=/home/op/.claude",
        "--mount=type=bind,source=/home/op/.cache/uv,destination=/home/op/.cache/uv",
        (
            "--mount=type=bind,source=/home/op/.local/share/uv/python,"
            "destination=/home/op/.local/share/uv/python,ro=true"
        ),
        '--mount=type=bind,"source=/srv/a,b ""c""",destination=/mnt/c',
        IMAGE.tag,
        "/opt/clis/claude",
        "--resume",
    ]


def test_a_run_without_a_terminal_on_its_own_network() -> None:
    engine, _ = podman()
    invocation = Invocation(
        container=Container(image=IMAGE, mounts=[Mount(source=Path("/srv/repo"))]),
        command=["true"],
        workdir=Path("/srv/repo"),
        home=Path("/home/op"),
    )

    command = engine.command(invocation)

    assert "--interactive" not in command
    assert "--tty" not in command
    assert "--network=private" in command


def test_a_mount_at_a_directory_inside_the_home_isnt_a_tmpfs_too() -> None:
    engine, _ = podman()
    invocation = Invocation(
        container=Container(
            image=IMAGE,
            mounts=[
                Mount(source=Path("/srv/cache")),
                Mount(source=Path("/srv/cache"), target=Path("/home/op/.cache")),
                Mount(source=Path("/srv/uv"), target=Path("/home/op/.cache/uv")),
            ],
        ),
        command=["true"],
        workdir=Path("/srv/cache"),
        home=Path("/home/op"),
    )

    owned = [
        argument
        for argument in engine.command(invocation)
        if argument.startswith("--mount=type=tmpfs")
    ]

    assert owned == ["--mount=type=tmpfs,destination=/home/op,tmpfs-mode=0700,U=true"]


def test_ensure_builds_a_missing_image_with_its_projects_label() -> None:
    engine, recorder = podman(Exited(status=1), Exited(status=0))

    assert engine.ensure(IMAGE) is True

    exists, build = recorder.processes
    assert exists == Process(arguments=["podman", "image", "exists", IMAGE.tag])
    assert build.arguments[:-1] == [
        "podman",
        "build",
        "--tag",
        IMAGE.tag,
        "--label",
        "lup.project=lup",
        "--file",
        "-",
    ]
    assert build.input == IMAGE.definition
    assert recorder.contexts[1] is True, "the build's context is an empty directory"
    assert not Path(build.arguments[-1]).exists(), "the context goes after the build"


def test_ensure_leaves_an_image_already_built() -> None:
    engine, recorder = podman(Exited(status=0))

    assert engine.ensure(IMAGE) is False
    assert len(recorder.processes) == 1


@pytest.mark.parametrize(
    "exits",
    [[Exited(status=125)], [Exited(status=1), Exited(status=1)]],
    ids=["exists-failed", "build-failed"],
)
def test_ensure_refuses_when_podman_fails(exits: list[Exited]) -> None:
    engine, _ = podman(*exits)

    with pytest.raises(ContainerError, match=IMAGE.tag):
        engine.ensure(IMAGE)


def test_run_returns_the_programs_status_and_refuses_podmans_own_failure() -> None:
    invocation = Invocation(
        container=Container(image=IMAGE, mounts=[Mount(source=Path("/srv/repo"))]),
        command=["true"],
        workdir=Path("/srv/repo"),
        home=Path("/home/op"),
    )
    engine, recorder = podman(Exited(status=3), Exited(status=125))

    assert engine.run(invocation) == 3
    assert recorder.processes[0] == Process(arguments=engine.command(invocation))
    with pytest.raises(ContainerError, match="status 125"):
        engine.run(invocation)


def test_a_projects_images_are_listed_and_one_removed() -> None:
    listed = [
        {
            "Id": "f98ed7c489b3",
            "ParentId": "9c6b477c56c9",
            "Names": [IMAGE.tag],
            "Size": 545056570,
            "Labels": {"lup.project": "lup"},
            "Containers": 0,
            "Created": 1791846953,
            "CreatedAt": "2026-10-12T23:15:53Z",
        },
        {"Id": "0a1b2c3d4e5f", "Size": 1, "Containers": 2, "Created": 1791846000},
    ]
    engine, recorder = podman(
        Exited(status=0, output=json.dumps(listed)), Exited(status=0)
    )

    images = engine.images("lup")
    engine.remove(images[0])

    assert images == [
        StoredImage(
            id="f98ed7c489b3",
            names=[IMAGE.tag],
            created=datetime(2026, 10, 12, 23, 15, 53, tzinfo=UTC),
            size=545056570,
            containers=0,
        ),
        StoredImage(
            id="0a1b2c3d4e5f",
            created=datetime.fromtimestamp(1791846000, UTC),
            size=1,
            containers=2,
        ),
    ]
    assert recorder.processes == [
        Process(
            arguments=[
                "podman",
                "images",
                "--filter",
                "label=lup.project=lup",
                "--format",
                "json",
            ],
            capture=True,
        ),
        Process(arguments=["podman", "image", "rm", "f98ed7c489b3"]),
    ]


def test_listing_and_removing_refuse_when_podman_fails() -> None:
    engine, _ = podman(Exited(status=125), Exited(status=2))
    stored = StoredImage(
        id="f98ed7c489b3", created=datetime.now(UTC), size=1, containers=1
    )

    with pytest.raises(ContainerError, match="list"):
        engine.images("lup")
    with pytest.raises(ContainerError, match="remove"):
        engine.remove(stored)


def test_podman_itself_is_refused_in_tests() -> None:
    with pytest.raises(RealCallInTestError, match="podman"):
        Podman().ensure(IMAGE)
