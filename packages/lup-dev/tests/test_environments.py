"""The room's environments: the one rule placing each worktree's, and `lup-environment`, run as the room runs it.

The program runs as a process of its own, as `uv` and as `lup-environment`, its
source written where a launch writes it with `uv` linked to it, in front of a
stand-in `uv` that says what it was told. git runs for real on the test's
repositories.
"""

import inspect
import json
import os
import shutil
import threading
from pathlib import Path

import pytest

from lup.programs import Ran, run
from lup_dev import environments
from lup_dev.environments import environment, failure, log
from lup_dev.policy.worktrees import place

PATIENCE = 60
"""How long, in seconds, a test waits for what the program started in the background."""

TOLD = """#!/bin/sh
# What the room's tools were told, then the status asked for.
printf '%s\\n' "${UV_PROJECT_ENVIRONMENT-unset}" "$*" > "$TOLD"
exit "${STATUS:-0}"
"""


class Room:
    """A launch's commands and the room's variables, around a stand-in `uv`."""

    def __init__(self, tmp_path: Path, repository: Path) -> None:
        self.bin = tmp_path / "launch" / "bin"
        self.bin.mkdir(parents=True)
        self.program = self.bin / environments.STARTER
        self.program.write_text(inspect.getsource(environments))
        self.program.chmod(0o755)
        (self.bin / "uv").symlink_to(self.program.name)
        real = tmp_path / "real"
        real.mkdir()
        (real / "uv").write_text(TOLD)
        (real / "uv").chmod(0o755)
        self.told = tmp_path / "told"
        self.environments = tmp_path / "rooms" / "environments" / "0f3a"
        self.env = {
            "PATH": os.pathsep.join([str(self.bin), str(real), os.environ["PATH"]]),
            "HOME": str(tmp_path),
            "GIT_CONFIG_GLOBAL": os.environ["GIT_CONFIG_GLOBAL"],
            "GIT_CONFIG_NOSYSTEM": "1",
            "TOLD": str(self.told),
            environments.ENVIRONMENTS: str(self.environments),
            environments.VARIABLE: "UV_PROJECT_ENVIRONMENT",
            environments.REPOSITORY: str(repository),
        }

    def run(self, cwd: Path, *arguments: str, **env: str) -> Ran:
        """Run `uv` with `arguments` in `cwd`, as the room's `PATH` finds it."""
        return run("uv", *arguments, cwd=cwd, env={**self.env, **env}, checked=False)

    def heard(self) -> list[str]:
        """Return what the stand-in `uv` was told: its environment, then its arguments."""
        return self.told.read_text().splitlines()


@pytest.fixture(autouse=True)
def own_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the operator's git configuration out: an empty global file, no system one."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def waited(path: Path) -> None:
    """Wait until `path` is there, as what the program started in the background leaves it."""
    pause = threading.Event()
    for _ in range(PATIENCE * 100):
        if path.exists():
            return
        pause.wait(0.01)
    message = f"{path} never appeared"
    raise AssertionError(message)


def test_each_worktree_s_environment_is_named_by_its_own_name_and_its_path() -> None:
    launch = Path("/rooms/lup/environments/0f3a")
    one = environment(launch, Path("/srv/a.git/tree/dev"))
    other = environment(launch, Path("/srv/b.git/tree/dev"))
    assert one.parent == other.parent == launch
    assert one.name.startswith("dev-")
    assert other.name.startswith("dev-")
    assert one != other
    assert environment(launch, Path("/srv/a.git/tree/dev")) == one


def test_uv_in_a_worktree_is_told_the_environment_the_judge_reads_for_it(
    bare: Path, tmp_path: Path
) -> None:
    room = Room(tmp_path, bare)
    worktree = bare / "tree" / "main"
    inside = worktree / "src" / "pkg"
    # The judge places a path by git, from the worktree's root it gives.
    found = place(inside / "core.py")
    assert found is not None
    assert found.worktree is not None
    judged = environment(room.environments, found.worktree)

    for directory in [worktree, inside]:
        ran = room.run(directory, "run", "pytest", "-x")
        assert ran.status == 0
        assert room.heard() == [str(judged), "run pytest -x"]


def test_a_worktree_added_while_the_room_runs_gets_its_own(
    bare: Path, tmp_path: Path
) -> None:
    room = Room(tmp_path, bare)
    run("git", "worktree", "add", "-q", "tree/new", "-b", "new", cwd=bare)
    added = bare / "tree" / "new"
    room.run(added, "sync")
    assert room.heard() == [str(environment(room.environments, added)), "sync"]
    room.run(bare / "tree" / "main", "sync")
    assert room.heard()[0] == str(
        environment(room.environments, bare / "tree" / "main")
    )


def test_outside_the_launch_s_repository_an_inherited_environment_is_dropped(
    bare: Path, repo: Path, tmp_path: Path
) -> None:
    room = Room(tmp_path, bare)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for directory in [repo, scratch, bare]:
        room.run(directory, "sync", UV_PROJECT_ENVIRONMENT="/inherited")
        assert room.heard() == ["unset", "sync"]


def test_the_real_uv_s_status_is_the_caller_s(bare: Path, tmp_path: Path) -> None:
    room = Room(tmp_path, bare)
    ran = room.run(bare / "tree" / "main", "lock", "--check", STATUS="3")
    assert ran.status == 3
    assert room.heard()[1] == "lock --check"


def test_without_a_uv_beside_lup_s_the_program_says_so(
    bare: Path, tmp_path: Path
) -> None:
    room = Room(tmp_path, bare)
    # git and Python, which the program runs on, and no other `uv`.
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ["git", "python3"]:
        found = shutil.which(name)
        assert found is not None
        (tools / name).symlink_to(found)
    ran = room.run(
        bare / "tree" / "main",
        "sync",
        PATH=os.pathsep.join([str(room.bin), str(tools)]),
    )
    assert ran.status == 1
    assert "no `uv` on the `PATH` beside lup's" in ran.said()


def started(room: Room, cwd: Path, command: list[str], **env: str) -> Ran:
    """Run `lup-environment` as the room's start does, with `command` making the environment and a stand-in CLI after it."""
    return run(
        room.program,
        json.dumps(command),
        "sh",
        "-c",
        "echo the CLI ran with $0",
        "--resume",
        cwd=cwd,
        env={**room.env, **env},
        checked=False,
    )


def test_the_start_makes_the_worktree_s_environment_in_the_background_and_runs_the_cli(
    bare: Path, tmp_path: Path
) -> None:
    room = Room(tmp_path, bare)
    worktree = bare / "tree" / "main"
    made = environment(room.environments, worktree)

    ran = started(room, worktree, ["uv", "sync", "--frozen"])

    assert ran.status == 0
    assert ran.text() == "the CLI ran with --resume"
    waited(room.told)
    # Through the room's `uv`, so it's made where the judge reads it.
    assert room.heard() == [str(made), "sync --frozen"]
    assert log(made).is_file()
    assert not failure(made).exists()


def test_a_start_that_fails_is_said_once_at_the_next_uv_in_the_worktree(
    bare: Path, tmp_path: Path
) -> None:
    room = Room(tmp_path, bare)
    worktree = bare / "tree" / "main"
    made = environment(room.environments, worktree)

    ran = started(room, worktree, ["uv", "sync", "--frozen"], STATUS="2")

    assert ran.status == 0
    waited(failure(made))
    first = room.run(worktree, "run", "pytest")
    second = room.run(worktree, "run", "pytest")
    assert (
        "lup: making this worktree's environment at the room's start failed "
        f"(status 2); what it printed is in {log(made)}."
    ) in first.said()
    assert "lup:" not in second.said()


def test_a_start_with_nothing_to_make_or_no_worktree_starts_nothing(
    bare: Path, tmp_path: Path
) -> None:
    room = Room(tmp_path, bare)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for cwd, command in [(bare / "tree" / "main", []), (elsewhere, ["uv", "sync"])]:
        ran = started(room, cwd, command)
        assert ran.text() == "the CLI ran with --resume"
    assert not room.environments.exists()
    assert not room.told.exists()


@pytest.mark.parametrize("first", ["", "{}", '["uv", 1]'])
def test_a_start_s_command_that_isnt_a_list_of_words_is_refused(
    bare: Path, tmp_path: Path, first: str
) -> None:
    room = Room(tmp_path, bare)
    ran = run(
        room.program,
        first,
        "true",
        cwd=bare / "tree" / "main",
        env=room.env,
        checked=False,
    )
    assert ran.status == 1
    assert "lup: `lup-environment`'s first argument" in ran.said()
