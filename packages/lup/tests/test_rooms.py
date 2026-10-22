"""Rooms: the wall's parts, podman's command lines through a recording executor, and a launch through a recording engine.

No test runs podman.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from pydantic import ValidationError

from lup.adapters.claude import Claude
from lup.programs import Ran
from lup.rooms import (
    Container,
    ContainerEngine,
    ContainerError,
    Image,
    Mask,
    Mount,
    Podman,
    Room,
)
from lup.rooms.engine import Invocation, Process, StoredImage
from lup.sessions.contract import guarded
from lup.sessions.errors import RealCallInTestError
from lup.sessions.terminal import Cli, TerminalSettings

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

IMAGE = Image(
    definition="FROM archlinux\nRUN pacman -Sy --noconfirm git\n", project="lup"
)


def exited(status: int, output: str = "") -> Ran:
    """Return how a scripted podman ended: its status, and what it printed."""
    return Ran(command=["podman"], status=status, output=output.encode())


class Recorder:
    """Runs nothing: records each process, and answers with the next scripted exit."""

    def __init__(self, *exits: Ran) -> None:
        self.exits = list(exits)
        self.processes: list[Process] = []
        self.contexts: list[bool] = []

    def __call__(self, process: Process) -> Ran:
        self.processes.append(process)
        self.contexts.append(Path(process.arguments[-1]).is_dir())
        return self.exits.pop(0)


def podman(*exits: Ran) -> tuple[Podman, Recorder]:
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
    assert Image(definition=IMAGE.definition, project="zoetrope").tag != tag


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


def test_a_mount_receiving_what_s_mounted_later_is_a_slave() -> None:
    engine, _ = podman()
    invocation = Invocation(
        container=Container(
            image=IMAGE,
            mounts=[
                Mount(source=Path("/srv/lent"), target=Path("/lent"), receives=True)
            ],
        ),
        command=["true"],
        workdir=Path("/srv/lent"),
        home=Path("/home/op"),
    )
    assert (
        "--mount=type=bind,source=/srv/lent,destination=/lent,bind-propagation=rslave"
        in engine.command(invocation)
    )


def unshared(recorder: Recorder) -> list[list[str]]:
    """The commands run in podman's namespace, without `podman unshare`."""
    return [
        each.arguments[2:]
        for each in recorder.processes
        if each.arguments[:2] == ["podman", "unshare"]
    ]


def test_a_directory_shared_then_lent_read_only_is_made_so_before_it_spreads(
    tmp_path: Path,
) -> None:
    lent = tmp_path / "lent"
    stage = tmp_path / "stage"
    at = lent / "atlas"
    for each in [lent, stage, at]:
        each.mkdir()
    engine, recorder = podman(*[exited(0)] * 10)

    engine.shared(lent)
    engine.private(stage)
    engine.lend(Path("/src/atlas"), at, stage, read_only=True)
    engine.released(lent)

    staged = str(stage / "atlas")
    assert unshared(recorder) == [
        ["mount", "--bind", str(lent), str(lent)],
        ["mount", "--make-shared", str(lent)],
        ["mount", "--bind", str(stage), str(stage)],
        ["mount", "--make-private", str(stage)],
        ["mount", "--bind", "/src/atlas", staged],
        ["mount", "-o", "remount,bind,ro", staged],
        ["mount", "--bind", staged, str(at)],
        ["umount", staged],
        ["umount", "--recursive", str(lent)],
    ]
    assert not (stage / "atlas").exists()


def test_a_directory_lent_writable_is_mounted_where_it_spreads_at_once(
    tmp_path: Path,
) -> None:
    engine, recorder = podman(exited(0))
    engine.lend(Path("/src/atlas"), tmp_path / "atlas", tmp_path, read_only=False)
    assert unshared(recorder) == [
        ["mount", "--bind", "/src/atlas", str(tmp_path / "atlas")]
    ]


def test_a_command_in_podman_s_namespace_that_fails_raises(tmp_path: Path) -> None:
    engine, _ = podman(exited(32))
    with pytest.raises(ContainerError, match="`podman unshare umount --recursive"):
        engine.released(tmp_path)


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
    engine, recorder = podman(exited(1), exited(0))

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
    engine, recorder = podman(exited(0))

    assert engine.ensure(IMAGE) is False
    assert len(recorder.processes) == 1


@pytest.mark.parametrize(
    "exits",
    [[exited(125)], [exited(1), exited(1)]],
    ids=["exists-failed", "build-failed"],
)
def test_ensure_refuses_when_podman_fails(exits: list[Ran]) -> None:
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
    engine, recorder = podman(exited(3), exited(125))

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
        exited(0, json.dumps(listed)), exited(0)
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
    engine, _ = podman(exited(125), exited(2))
    stored = StoredImage(
        id="f98ed7c489b3", created=datetime.now(UTC), size=1, containers=1
    )

    with pytest.raises(ContainerError, match="list"):
        engine.images("lup")
    with pytest.raises(ContainerError, match="remove"):
        engine.remove(stored)


def test_a_named_container_is_run_by_its_name_and_asked_after() -> None:
    engine, recorder = podman(exited(0), exited(1), exited(125))
    invocation = Invocation(
        container=Container(
            image=IMAGE, mounts=[Mount(source=Path("/srv/repo"))], name="lup-1a2b"
        ),
        command=["true"],
        workdir=Path("/srv/repo"),
        home=Path("/home/op"),
    )
    command = engine.command(invocation)

    assert command[command.index("--security-opt=no-new-privileges") + 1] == (
        "--name=lup-1a2b"
    )
    assert engine.exists("lup-1a2b")
    assert not engine.exists("lup-1a2b")
    with pytest.raises(ContainerError, match="lup-1a2b"):
        engine.exists("lup-1a2b")
    assert (
        recorder.processes
        == [Process(arguments=["podman", "container", "exists", "lup-1a2b"])] * 3
    )
    unnamed = invocation.model_copy(
        update={"container": invocation.container.model_copy(update={"name": None})}
    )
    assert not any(each.startswith("--name") for each in engine.command(unnamed))


def test_a_container_is_renamed_and_a_rename_podman_refuses_raises() -> None:
    engine, recorder = podman(exited(0), exited(125))

    engine.rename("lup-1a2b", "lup-atlas-dev")
    with pytest.raises(ContainerError, match="rename the container lup-1a2b"):
        engine.rename("lup-1a2b", "lup-atlas-dev")

    assert (
        recorder.processes
        == [Process(arguments=["podman", "rename", "lup-1a2b", "lup-atlas-dev"])] * 2
    )


def test_podman_itself_is_refused_in_tests() -> None:
    with pytest.raises(RealCallInTestError, match="podman"):
        Podman().ensure(IMAGE)


@pytest.fixture
def unguarded() -> Iterator[None]:
    """Let the test run a stand-in for podman, which the guard refuses otherwise."""
    token = guarded.set(False)
    yield
    guarded.reset(token)


@pytest.mark.usefixtures("unguarded")
def test_a_podman_that_isnt_there_is_the_engine_s_error(tmp_path: Path) -> None:
    with pytest.raises(ContainerError, match="can't be run"):
        Podman(program=str(tmp_path / "podman")).images("lup")


@pytest.mark.usefixtures("unguarded")
def test_a_kept_run_s_failure_says_what_podman_said(tmp_path: Path) -> None:
    program = tmp_path / "podman"
    # It reads its input to the end, which a kept run closes, so it doesn't wait.
    program.write_text("#!/bin/sh\ncat\necho 'Error: no store' >&2\nexit 125\n")
    program.chmod(0o755)
    with pytest.raises(ContainerError, match=r"\(status 125\): Error: no store"):
        Podman(program=str(program)).images("lup")


# A launch


class RecordingEngine(ContainerEngine):
    """Builds and runs nothing: records what it was asked."""

    def __init__(self) -> None:
        self.ensured: list[Image] = []
        self.ran: list[Invocation] = []

    @override
    def ensure(self, image: Image) -> bool:
        self.ensured.append(image)
        return False

    @override
    def run(self, invocation: Invocation) -> int:
        self.ran.append(invocation)
        return 7


@pytest.fixture
def worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    worktree = tmp_path / "lup.git" / "tree" / "dev"
    worktree.mkdir(parents=True)
    monkeypatch.chdir(worktree)
    return worktree


def test_a_launch_runs_the_agents_terminal_in_the_room(
    tmp_path: Path, worktree: Path
) -> None:
    repository = tmp_path / "lup.git"
    launch = tmp_path / "state" / "launch-1"
    engine = RecordingEngine()
    own = [Mount(source=repository), Mask(target=repository / "tree" / "other")]
    room = Room(
        agent=Claude(model="opus"),
        container=Container(
            image=IMAGE, mounts=own, env={"TERM": "xterm"}, name="lup-1a2b"
        ),
        engine=engine,
    )
    settings = TerminalSettings(
        directory=launch,
        cli=Cli(program=Path("/opt/clis/claude")),
        trusted=[worktree, repository],
    )
    terminal = Claude(model="opus").terminal(settings)

    status = room.launch(arguments=["--resume"], settings=settings)

    assert status == 7
    assert engine.ensured == [IMAGE]
    assert engine.ran == [
        Invocation(
            container=Container(
                image=IMAGE,
                mounts=[*own, *terminal.mounts],
                env={"TERM": "xterm", **terminal.env},
                name="lup-1a2b",
            ),
            command=[*terminal.command, "--resume"],
            workdir=worktree,
            home=tmp_path / "home",
            terminal=False,
        )
    ]
    assert {path: path.read_text() for path in terminal.files} == terminal.files


def test_a_launch_refuses_a_working_directory_the_room_doesnt_mount(
    tmp_path: Path, worktree: Path
) -> None:
    engine = RecordingEngine()
    room = Room(
        agent=Claude(model="opus"),
        container=Container(image=IMAGE, mounts=[Mount(source=tmp_path / "elsewhere")]),
        engine=engine,
    )
    launch = tmp_path / "launch"

    with pytest.raises(ContainerError, match="doesn't mount the working directory"):
        room.launch(
            arguments=[],
            settings=TerminalSettings(
                directory=launch, cli=Cli(program=Path("/opt/clis/claude"))
            ),
        )
    assert not launch.exists()
    assert engine.ensured == []
    assert engine.ran == []


def test_a_launch_refuses_variables_the_terminal_needs_otherwise(
    tmp_path: Path, worktree: Path
) -> None:
    room = Room(
        agent=Claude(model="opus"),
        container=Container(
            image=IMAGE,
            mounts=[Mount(source=worktree)],
            env={"DISABLE_AUTOUPDATER": "0"},
        ),
        engine=RecordingEngine(),
    )

    with pytest.raises(ContainerError, match="DISABLE_AUTOUPDATER"):
        room.launch(
            arguments=[],
            settings=TerminalSettings(
                directory=tmp_path / "launch", cli=Cli(program=Path("/opt/clis/claude"))
            ),
        )
