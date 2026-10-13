"""The maintaining room: its repository's tree, its mounts and variables compared whole, and each refusal.

git runs for real on the test's repositories, with the operator's own git
configuration kept out; uv is stubbed through the runner's `Tools`, and no test
runs podman.
"""

from typing import TYPE_CHECKING

import pytest
import sh

from lup.rooms.container import Container, Image, Mount
from lup_dev import Modules, Plain, Project, Python
from lup_dev.catalog.room import RoomBase
from lup_dev.declaration.requirements import Printed, Tools
from lup_dev.declaration.resolve import resolve
from lup_dev.launch.images import definition
from lup_dev.launch.room import RoomError, maintaining_room, repository
from lup_dev.layout import LOCALTIME, Layout
from lup_dev.settings import TerminalVariables

if TYPE_CHECKING:
    from pathlib import Path

REMEDY = "uv sync --managed-python"


def git(root: Path, *arguments: str) -> None:
    sh.git(*arguments, _cwd=str(root), _tty_out=False)


@pytest.fixture(autouse=True)
def own_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the operator's git configuration out: an empty global file, no system one."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


class AskedUv(Tools):
    """uv's answers by the words after `--directory <root>`."""

    def __init__(self, store: Path, cache: Path, interpreter: Path) -> None:
        self.answers = {
            "python dir": store,
            "cache dir": cache,
            "python find": interpreter,
        }

    def found(self, program: str) -> bool:
        return True

    def run(self, command: list[str]) -> Printed:
        return Printed(code=0, output=f"{self.answers[' '.join(command[6:])]}\n")


class Machine:
    """The host as a room sees it: uv's store and cache, and a worktree's environment."""

    def __init__(self, tmp_path: Path, worktree: Path) -> None:
        self.store = tmp_path / "data" / "uv" / "python"
        self.cache = tmp_path / "cache" / "uv"
        self.layout = Layout(state=tmp_path / "state", cache=tmp_path / "cache" / "lup")
        python = self.store / "cpython-3.14-linux" / "bin" / "python3.14"
        python.parent.mkdir(parents=True)
        python.write_text("")
        self.link = worktree / ".venv" / "bin" / "python"
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(python)

    def tools(self, interpreter: Path | None = None) -> AskedUv:
        return AskedUv(self.store, self.cache, interpreter or self.link)


def terminal(**variables: str) -> TerminalVariables:
    unset: dict[str, str | None] = dict.fromkeys(TerminalVariables.model_fields)
    return TerminalVariables.model_validate({**unset, **variables})


# The repository's tree


def test_a_bare_repository_s_tree_is_its_own_directory(bare: Path) -> None:
    git(bare, "worktree", "add", "-q", "-b", "feat", "tree/feat")

    held = repository(bare / "tree" / "main")

    assert held.git == bare
    assert held.tree == bare
    assert sorted(held.worktrees) == [
        bare,
        bare / "tree" / "feat",
        bare / "tree" / "main",
    ]


def test_a_clone_s_tree_is_its_main_worktree(repo: Path) -> None:
    git(repo, "worktree", "add", "-q", "-b", "feat", ".worktrees/feat")

    held = repository(repo / ".worktrees" / "feat")

    assert held.git == repo / ".git"
    assert held.tree == repo
    assert held.worktrees == [repo, repo / ".worktrees" / "feat"]


def test_a_worktree_gone_from_disk_doesnt_widen_the_tree(
    repo: Path, tmp_path: Path
) -> None:
    gone = tmp_path / "elsewhere" / "gone"
    git(repo, "worktree", "add", "-q", "-b", "gone", str(gone))
    git(repo, "worktree", "lock", str(gone))
    for each in sorted(gone.rglob("*"), reverse=True):
        if each.is_dir() and not each.is_symlink():
            each.rmdir()
        else:
            each.unlink()
    gone.rmdir()

    assert repository(repo).tree == repo


def test_worktrees_meeting_above_the_home_are_refused(
    repo: Path, linked: Path, home: Path
) -> None:
    with pytest.raises(RoomError, match=r"meet only at .*, which holds your home"):
        repository(linked)


# The room whole


def test_the_maintaining_room_mounts_and_sets_what_the_note_lists(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)
    (home / ".config" / "nvim").mkdir(parents=True)
    (home / ".vim").mkdir()
    (home / ".nanorc").write_text("")
    resolved = resolve(Project())

    room = maintaining_room(
        resolved,
        worktree,
        machine.layout,
        terminal(
            term="xterm-kitty",
            colorterm="truecolor",
            lang="en_US.UTF-8",
            editor="/usr/bin/nvim --clean",
            visual="vim",
        ),
        machine.tools(),
    )

    localtime = [Mount(source=LOCALTIME, read_only=True)] if LOCALTIME.exists() else []
    assert room == Container(
        image=Image(
            definition=definition(resolved.packages, RoomBase()), project=str(bare)
        ),
        mounts=[
            Mount(source=bare),
            Mount(source=bare / "config", read_only=True),
            Mount(source=bare / "hooks", read_only=True),
            Mount(source=machine.store, read_only=True),
            Mount(source=machine.cache),
            Mount(source=tmp_path / "cache" / "lup" / "pyright"),
            Mount(source=home / ".vim", read_only=True),
            Mount(source=home / ".config" / "nvim", read_only=True),
            *localtime,
        ],
        env={
            "UV_CACHE_DIR": str(machine.cache),
            "UV_PYTHON_INSTALL_DIR": str(machine.store),
            "UV_PYTHON_DOWNLOADS": "never",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "TERM": "xterm-kitty",
            "COLORTERM": "truecolor",
            "LANG": "en_US.UTF-8",
            "EDITOR": "/usr/bin/nvim --clean",
            "VISUAL": "vim",
        },
        network="host",
    )
    assert (tmp_path / "cache" / "lup" / "pyright").is_dir()
    assert machine.cache.is_dir()


def test_the_room_makes_the_hooks_directory_it_holds_read_only(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)
    for each in sorted((bare / "hooks").rglob("*"), reverse=True):
        each.unlink()
    (bare / "hooks").rmdir()

    room = maintaining_room(
        resolve(Project()), worktree, machine.layout, terminal(), machine.tools()
    )

    assert (bare / "hooks").is_dir()
    assert Mount(source=bare / "hooks", read_only=True) in room.mounts


def test_without_a_git_identity_none_is_passed(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    git(bare, "config", "--unset", "user.name")
    git(bare, "config", "--unset", "user.email")
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)

    room = maintaining_room(
        resolve(Project()), worktree, machine.layout, terminal(), machine.tools()
    )

    assert not any(name.startswith("GIT_") for name in room.env)


def test_a_plain_runner_mounts_and_checks_nothing_of_uv(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    layout = Layout(state=tmp_path / "state", cache=tmp_path / "cache" / "lup")
    resolved = resolve(Project(modules=Modules.default().edit(Python(runner=Plain()))))

    room = maintaining_room(
        resolved,
        worktree,
        layout,
        terminal(),
        AskedUv(tmp_path / "none", tmp_path / "none", tmp_path / "none"),
    )

    assert not any(name.startswith("UV_") for name in room.env)
    assert [each.source for each in room.mounts if isinstance(each, Mount)][:4] == [
        bare,
        bare / "config",
        bare / "hooks",
        tmp_path / "cache" / "lup" / "pyright",
    ]


# Refusals


def test_an_environment_on_a_system_interpreter_is_refused(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)
    system = tmp_path / "usr" / "bin" / "python3.14"
    system.parent.mkdir(parents=True)
    system.write_text("")
    machine.link.unlink()
    machine.link.symlink_to(system)

    with pytest.raises(
        RoomError, match=r"outside every mount of the room, as a system interpreter is"
    ) as refused:
        maintaining_room(
            resolve(Project()), worktree, machine.layout, terminal(), machine.tools()
        )
    assert str(system) in str(refused.value)
    assert REMEDY in str(refused.value)


def test_an_environment_whose_interpreter_is_gone_is_refused(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)
    machine.link.resolve().unlink()

    with pytest.raises(RoomError, match=r"and isn't there") as refused:
        maintaining_room(
            resolve(Project()), worktree, machine.layout, terminal(), machine.tools()
        )
    assert REMEDY in str(refused.value)


def test_an_editor_that_isnt_a_command_line_is_refused(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)

    with pytest.raises(
        RoomError, match=r"`\$EDITOR` or `\$VISUAL` isn't a command line"
    ):
        maintaining_room(
            resolve(Project()),
            worktree,
            machine.layout,
            terminal(editor='nvim "unclosed'),
            machine.tools(),
        )
