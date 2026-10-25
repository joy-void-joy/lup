"""The maintaining room: its repository's tree, its mounts and variables compared whole, and each refusal.

git runs for real on the test's repositories, with the operator's own git
configuration kept out; uv is stubbed through the runner's `Tools`, and no test
runs podman.
"""

import inspect
import tomllib
from datetime import timedelta
from pathlib import Path
from typing import override

import pytest
from filelock import FileLock

from lup.programs import run
from lup.rooms.container import Container, Image, Mount
from lup_dev import (
    Core,
    Modules,
    Package,
    Packages,
    Plain,
    Project,
    Python,
    Repository,
    environments,
)
from lup_dev.catalog.room import Editors, RoomBase
from lup_dev.declaration.package_managers.manager import (
    HomeSettings,
    PackageManager,
    Ungated,
)
from lup_dev.declaration.requirements import Printed, Tools
from lup_dev.declaration.resolve import Resolved, resolve
from lup_dev.launch.images import definition
from lup_dev.launch.room import (
    Lent,
    OperatorsEditor,
    RelatedRepository,
    RoomEnvironments,
    RoomError,
    RoomPackageAge,
    lent,
    maintaining_room,
    related,
    repository,
    unclaimed,
)
from lup_dev.layout import LOCALTIME, LaunchLayout, Layout
from lup_dev.settings import TerminalVariables

REMEDY = "uv python install"
LAUNCH = "0f3a"
"""The launch's id, as the launch makes one."""


def naming(*paths: Path) -> list[Repository]:
    """A repository named at each of `paths`."""
    return [
        Repository(name=f"r{at}", path=path, about=f"repository {at}")
        for at, path in enumerate(paths)
    ]


def plain() -> Project:
    return Project(modules=Modules.default().edit(Python(runner=Plain())))


def git(root: Path, *arguments: str) -> None:
    run("git", *arguments, cwd=root)


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
    """uv's answers by the two words after `uv --no-config`."""

    def __init__(self, store: Path, interpreter: Path) -> None:
        self.answers = {"python dir": store, "python find": interpreter}

    def found(self, program: str) -> bool:
        return True

    def run(self, command: list[str]) -> Printed:
        return Printed(code=0, output=f"{self.answers[' '.join(command[2:4])]}\n")


class Machine:
    """The host as a room sees it: uv's store, its interpreter, lup's places, and the worktree's own environment."""

    def __init__(self, tmp_path: Path, worktree: Path) -> None:
        self.store = tmp_path / "data" / "uv" / "python"
        self.layout = scratch(tmp_path)
        self.python = self.store / "cpython-3.14-linux" / "bin" / "python3.14"
        self.python.parent.mkdir(parents=True)
        self.python.write_text("")
        self.environment = worktree / ".venv"
        (self.environment / "bin").mkdir(parents=True)
        (self.environment / "bin" / "python").symlink_to(self.python)

    def tools(self, interpreter: Path | None = None) -> AskedUv:
        return AskedUv(self.store, interpreter or self.python)


def scratch(tmp_path: Path) -> Layout:
    """lup's places, under the test's own directory."""
    return Layout(
        state=tmp_path / "state",
        cache=tmp_path / "cache" / "lup",
        data=tmp_path / "data" / "lup",
    )


def room_for(
    resolved: Resolved,
    worktree: Path,
    layout: Layout,
    terminal: TerminalVariables,
    tools: Tools,
    *,
    neighbours: list[RelatedRepository],
    shared: dict[str, Path] | None = None,
    lent: list[Lent] | None = None,
) -> Container:
    """The maintaining room, with what the runner gives it for its environments, as a launch makes both."""
    return maintaining_room(
        resolved,
        worktree,
        layout,
        terminal,
        RoomEnvironments.of(resolved.runner, worktree, layout, LAUNCH, tools),
        neighbours=neighbours,
        shared=shared,
        lent=lent,
    )


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

    room = room_for(
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
        neighbours=[],
    )

    localtime = [Mount(source=LOCALTIME, read_only=True)] if LOCALTIME.exists() else []
    [vim] = [each for each in Editors().editors if each.package == "vim"]
    packages = [*resolved.packages, Package(name="vim", why=vim.why)]
    rooms = machine.layout.rooms(bare)
    assert room == Container(
        image=Image(definition=definition(packages, RoomBase()), project=str(bare)),
        mounts=[
            Mount(source=bare),
            Mount(source=bare / "config", read_only=True),
            Mount(source=bare / "hooks", read_only=True),
            Mount(source=machine.store, read_only=True),
            Mount(source=rooms.home),
            Mount(
                source=machine.layout.launch(LAUNCH).empty_directory,
                target=worktree / ".venv",
                read_only=True,
            ),
            Mount(source=tmp_path / "cache" / "lup" / "pyright"),
            Mount(source=home / ".vim", read_only=True),
            *localtime,
        ],
        env={
            "UV_CACHE_DIR": str(rooms.cache),
            "UV_PYTHON_INSTALL_DIR": str(machine.store),
            "UV_PYTHON_DOWNLOADS": "never",
            environments.ENVIRONMENTS: str(rooms.launch(LAUNCH)),
            environments.VARIABLE: "UV_PROJECT_ENVIRONMENT",
            environments.REPOSITORY: str(bare),
            "GIT_AUTHOR_NAME": "Test",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "TERM": "xterm-kitty",
            "COLORTERM": "truecolor",
            "LANG": "en_US.UTF-8",
            "EDITOR": "/usr/bin/nvim --clean",
            "VISUAL": "vim",
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
        network="host",
    )
    assert (tmp_path / "cache" / "lup" / "pyright").is_dir()


def test_the_room_makes_the_hooks_directory_it_holds_read_only(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)
    for each in sorted((bare / "hooks").rglob("*"), reverse=True):
        each.unlink()
    (bare / "hooks").rmdir()

    room = room_for(
        resolve(Project()),
        worktree,
        machine.layout,
        terminal(),
        machine.tools(),
        neighbours=[],
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

    room = room_for(
        resolve(Project()),
        worktree,
        machine.layout,
        terminal(),
        machine.tools(),
        neighbours=[],
    )

    assert not any(name.startswith("GIT_") for name in room.env)


def test_a_module_s_data_is_mounted_read_only_where_the_launch_places_it(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)
    kept = tmp_path / "data" / "modules" / "transcripts" / "digest"
    room = room_for(
        resolve(Project()),
        worktree,
        machine.layout,
        terminal(),
        machine.tools(),
        neighbours=[],
        shared={"transcripts": kept},
    )
    assert room.mounts[-1] == Mount(source=kept, read_only=True)


def test_a_plain_runner_mounts_and_checks_nothing_of_uv(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    layout = scratch(tmp_path)
    resolved = resolve(Project(modules=Modules.default().edit(Python(runner=Plain()))))

    room = room_for(
        resolved,
        worktree,
        layout,
        terminal(),
        AskedUv(tmp_path / "none", tmp_path / "none"),
        neighbours=[],
    )

    assert not any(name.startswith(("UV_", "LUP_")) for name in room.env)
    assert [each.source for each in room.mounts if isinstance(each, Mount)][:5] == [
        bare,
        bare / "config",
        bare / "hooks",
        layout.rooms(bare).home,
        tmp_path / "cache" / "lup" / "pyright",
    ]


def test_a_clone_s_git_directory_is_mounted_on_its_own_so_the_room_cant_move_it(
    repo: Path, tmp_path: Path, home: Path
) -> None:
    layout = scratch(tmp_path)
    resolved = resolve(Project(modules=Modules.default().edit(Python(runner=Plain()))))

    room = room_for(
        resolved,
        repo,
        layout,
        terminal(),
        AskedUv(tmp_path / "none", tmp_path / "none"),
        neighbours=[],
    )

    assert room.mounts[:4] == [
        Mount(source=repo),
        Mount(source=repo / ".git"),
        Mount(source=repo / ".git" / "config", read_only=True),
        Mount(source=repo / ".git" / "hooks", read_only=True),
    ]


# Refusals


def test_an_interpreter_outside_the_store_is_refused(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)
    system = tmp_path / "usr" / "bin" / "python3.14"
    system.parent.mkdir(parents=True)
    system.write_text("")

    with pytest.raises(
        RoomError,
        match=r"outside every mount of the room, as a system interpreter's is",
    ) as refused:
        room_for(
            resolve(Project()),
            worktree,
            machine.layout,
            terminal(),
            machine.tools(system),
            neighbours=[],
        )
    assert str(system.parent) in str(refused.value)
    assert REMEDY in str(refused.value)


def test_an_interpreter_thats_gone_is_refused(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)

    with pytest.raises(RoomError, match=r"and isn't there") as refused:
        room_for(
            resolve(Project()),
            worktree,
            machine.layout,
            terminal(),
            machine.tools(tmp_path / "gone" / "bin" / "python3"),
            neighbours=[],
        )
    assert REMEDY in str(refused.value)


# The room's environments


def test_a_launch_s_environments_are_its_own_and_go_with_it(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)
    (worktree / "uv.lock").write_text("")
    rooms = machine.layout.rooms(bare)
    launch = machine.layout.launch(LAUNCH)

    made = RoomEnvironments.of(
        resolve(Project()).runner, worktree, machine.layout, LAUNCH, machine.tools()
    )
    made.write()

    assert made.own == rooms.launch(LAUNCH)
    assert made.before == [str(launch.wrapper), '["uv", "sync", "--frozen"]']
    assert launch.wrapper.read_text() == inspect.getsource(environments)
    assert launch.wrapper.stat().st_mode & 0o111
    assert launch.wrapping("uv").readlink() == Path(environments.STARTER)
    assert rooms.cache.is_dir()
    assert made.directory.is_dir()
    # The room makes environments of its own, a worktree, and one in it the
    # host's tools would run.
    (environments.environment(made.directory, worktree) / "bin").mkdir(parents=True)
    git(bare, "worktree", "add", "-q", "tree/new", "-b", "new")
    (bare / "tree" / "new" / ".venv").mkdir()

    said = made.end()

    assert not made.directory.exists()
    assert rooms.cache.is_dir()
    assert not (bare / "tree" / "new" / ".venv").exists()
    assert (worktree / ".venv" / "bin" / "python").is_symlink()
    assert said == [
        (
            f"Removed {bare / 'tree' / 'new' / '.venv'}, an environment that "
            "appeared in a worktree while the room ran, which the room may have "
            "made: where it was your own, make it again."
        )
    ]


def test_a_plain_runner_s_room_has_no_environments_of_its_own(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    layout = scratch(tmp_path)
    made = RoomEnvironments.of(
        resolve(plain()).runner,
        worktree,
        layout,
        LAUNCH,
        AskedUv(tmp_path / "none", tmp_path / "none"),
    )
    made.write()
    assert made.own is None
    assert made.env == {}
    assert made.before == []
    assert made.hidden.found == []
    assert not layout.launch(LAUNCH).wrapper.exists()


def test_the_environments_a_crashed_launch_left_are_removed_and_no_others(
    tmp_path: Path,
) -> None:
    layout = scratch(tmp_path)
    rooms = layout.rooms(tmp_path / "repo.git")
    for each in ["crashed", "served", "running"]:
        (rooms.launch(each) / "dev-0123").mkdir(parents=True)
    layout.launches.mkdir(parents=True)

    with FileLock(layout.launch("running").lock):
        gone = unclaimed(rooms, ["served"], layout)

    assert gone == [rooms.launch("crashed")]
    assert sorted(each.name for each in rooms.environments.iterdir()) == [
        "running",
        "served",
    ]


def test_an_editor_that_isnt_a_command_line_is_refused(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)

    with pytest.raises(RoomError, match=r"`\$EDITOR` isn't a command line"):
        room_for(
            resolve(Project()),
            worktree,
            machine.layout,
            terminal(editor='nvim "unclosed'),
            machine.tools(),
            neighbours=[],
        )


# The operator's editor


def installed(room: Container) -> list[str]:
    """The packages the room's image installs, by name."""
    [line] = [
        each for each in room.image.definition.splitlines() if "pacman -Syu" in each
    ]
    return line.split(" -- ")[1].removesuffix(" \\").split()


@pytest.mark.parametrize(
    ("variables", "package"),
    [
        ({"editor": "nvim"}, "neovim"),
        ({"editor": "nvim", "visual": "emacs -nw"}, "emacs-nox"),
        ({"editor": "vim", "visual": ""}, "vim"),
        ({"editor": "/usr/local/bin/hx"}, "helix"),
    ],
)
def test_the_room_installs_the_editor_visual_names_else_editor(
    bare: Path, tmp_path: Path, home: Path, variables: dict[str, str], package: str
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)

    room = room_for(
        resolve(Project()),
        worktree,
        machine.layout,
        terminal(**variables),
        machine.tools(),
        neighbours=[],
    )

    editors = {each.package for each in Editors().editors}
    assert [name for name in installed(room) if name in editors] == ["nano", package]


def test_an_editor_lup_doesnt_know_adds_nothing_beside_nano(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)
    (home / ".config" / "kak").mkdir(parents=True)
    resolved = resolve(Project())

    room = room_for(
        resolved,
        worktree,
        machine.layout,
        terminal(editor="kak"),
        machine.tools(),
        neighbours=[],
    )

    assert room.image.definition == definition(resolved.packages, RoomBase())
    assert not [
        each
        for each in room.mounts
        if isinstance(each, Mount) and each.source.is_relative_to(home)
    ]


def test_an_editor_the_declaration_installs_already_is_installed_once(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    machine = Machine(tmp_path, worktree)
    layer = Core(packages=Packages().add(Package(name="vim", why="the project's own")))
    resolved = resolve(Project(modules=Modules.default().edit(layer)))

    for named in ["nano", "vim"]:
        room = room_for(
            resolved,
            worktree,
            machine.layout,
            terminal(editor=named),
            machine.tools(),
            neighbours=[],
        )
        assert room.image.definition == definition(resolved.packages, RoomBase())
    assert installed(room).count("vim") == 1


def test_hx_is_linked_to_helix_among_the_launch_s_commands(tmp_path: Path) -> None:
    launch = LaunchLayout(directory=tmp_path / "launch")

    OperatorsEditor.of(terminal(visual="hx")).link(launch)

    assert (launch.bin / "hx").readlink() == Path("/usr/bin/helix")


@pytest.mark.parametrize("named", ["helix", "nvim", "kak", ""])
def test_an_editor_run_by_its_package_s_own_name_is_linked_to_nothing(
    tmp_path: Path, named: str
) -> None:
    launch = LaunchLayout(directory=tmp_path / "launch")

    OperatorsEditor.of(terminal(editor=named)).link(launch)

    assert not launch.bin.exists()


# Other repositories, read-only


def test_a_relative_path_is_from_the_directory_holding_a_bare_repository(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    (tmp_path / "notes.git").mkdir()
    named = naming(Path("notes.git"), Path("gone.git"))

    found = related(named, bare / "tree" / "main")

    assert found == [
        RelatedRepository(
            name="r0",
            path=(tmp_path / "notes.git").resolve(),
            about="repository 0",
            github=None,
            mounted=True,
        ),
        RelatedRepository(
            name="r1",
            path=(tmp_path / "gone.git").resolve(),
            about="repository 1",
            github=None,
            mounted=False,
        ),
    ]


def test_a_relative_path_is_from_the_directory_holding_a_clone_s_working_tree(
    repo: Path, tmp_path: Path
) -> None:
    git(repo, "worktree", "add", "-q", "-b", "feat", ".worktrees/feat")
    (tmp_path / "notes").mkdir()

    [found] = related(naming(Path("notes")), repo / ".worktrees" / "feat")

    assert found.path == (tmp_path / "notes").resolve()
    assert found.mounted


def test_an_absolute_path_and_one_from_the_home_are_where_they_say(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    (home / "src" / "x.git").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere" / "y.git"

    found = related(naming(Path("~/src/x.git"), elsewhere), bare / "tree" / "main")

    assert [(each.path, each.mounted) for each in found] == [
        ((home / "src" / "x.git").resolve(), True),
        (elsewhere.resolve(), False),
    ]


def test_each_repository_there_is_mounted_read_only_at_its_host_path_after_the_project_s(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    layout = scratch(tmp_path)
    neighbours = related(naming(Path("work"), Path("gone.git")), worktree)

    room = room_for(
        resolve(plain()),
        worktree,
        layout,
        terminal(),
        AskedUv(tmp_path / "none", tmp_path / "none"),
        neighbours=neighbours,
    )

    localtime = [Mount(source=LOCALTIME, read_only=True)] if LOCALTIME.exists() else []
    assert room.mounts == [
        Mount(source=bare),
        Mount(source=bare / "config", read_only=True),
        Mount(source=bare / "hooks", read_only=True),
        Mount(source=layout.rooms(bare).home),
        Mount(source=tmp_path / "cache" / "lup" / "pyright"),
        *localtime,
        Mount(source=(tmp_path / "work").resolve(), read_only=True),
    ]


def test_each_directory_lent_is_mounted_at_its_path_last_read_only_or_writable(
    bare: Path, tmp_path: Path, home: Path
) -> None:
    worktree = bare / "tree" / "main"
    layout = scratch(tmp_path)
    reading = tmp_path / "reading"
    writing = tmp_path / "writing"
    reading.mkdir()
    writing.mkdir()
    lending = [
        *lent([reading], read_only=True),
        *lent([writing], read_only=False),
    ]

    room = room_for(
        resolve(plain()),
        worktree,
        layout,
        terminal(),
        AskedUv(tmp_path / "none", tmp_path / "none"),
        neighbours=[],
        lent=lending,
    )

    assert room.mounts[-2:] == [
        Mount(source=reading.resolve(), read_only=True),
        Mount(source=writing.resolve(), read_only=False),
    ]


def test_a_directory_lent_says_whether_it_s_a_repository_and_its_description(
    repo: Path, tmp_path: Path
) -> None:
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "work"\ndescription = "A made-up library."\n'
    )
    plain_directory = tmp_path / "plain"
    plain_directory.mkdir()

    assert lent([repo, plain_directory], read_only=True) == [
        Lent(
            path=repo.resolve(),
            read_only=True,
            repository=True,
            about="A made-up library.",
        ),
        Lent(path=plain_directory.resolve(), read_only=True, repository=False),
    ]


@pytest.mark.parametrize(
    "named",
    [Path("proj.git"), Path("proj.git/tree/main"), Path("..")],
    ids=["the project itself", "inside the project", "holding the project"],
)
def test_a_repository_overlapping_the_room_s_own_mounts_is_refused(
    bare: Path, tmp_path: Path, home: Path, named: Path
) -> None:
    worktree = bare / "tree" / "main"
    layout = scratch(tmp_path)

    with pytest.raises(
        RoomError,
        match=(
            r"The repository `r0` named for sessions to read, at .*, overlaps"
            r" the room's own mount of "
        ),
    ) as refused:
        room_for(
            resolve(plain()),
            worktree,
            layout,
            terminal(),
            AskedUv(tmp_path / "none", tmp_path / "none"),
            neighbours=related(naming(named), worktree),
        )
    assert str((tmp_path / named).resolve()) in str(refused.value)


# The package age gate


class Recorded(PackageManager):
    """A package manager answering as a test says, whatever the project."""

    package = "pip"
    answer: HomeSettings | Ungated

    @override
    def aged(self, root: Path, age: timedelta) -> HomeSettings | Ungated:
        del root, age
        return self.answer


def resolved_with(*names: str) -> Resolved:
    """lup's defaults with these packages in the room's image, and a package age of 5 days."""
    return resolve(
        Project(
            modules=Modules.default().edit(
                Core(
                    package_age=timedelta(days=5),
                    packages=Packages().add(
                        *(Package(name=name, why="a test's") for name in names)
                    ),
                )
            )
        )
    )


def test_each_package_manager_the_image_holds_gets_its_settings_at_the_declared_age(
    tmp_path: Path, home: Path
) -> None:
    launch = LaunchLayout(directory=tmp_path / "launch")
    (tmp_path / "pyproject.toml").write_text('[tool.uv]\nexclude-newer = "1 week"\n')
    gate = RoomPackageAge.of(launch, resolved_with("npm"), tmp_path)
    assert gate.ungated == []
    assert [each.path for each in gate.settings] == [
        Path(".npmrc"),
        Path(".config/uv/uv.toml"),
    ]
    gate.write()
    assert (launch.home / ".npmrc").read_text().splitlines()[1:] == [
        "min-release-age=5.0"
    ]
    assert tomllib.loads((launch.home / ".config/uv/uv.toml").read_text()) == {
        "exclude-newer": "P5D"
    }
    assert gate.mounts == [
        Mount(source=launch.home / ".npmrc", target=home / ".npmrc", read_only=True),
        Mount(
            source=launch.home / ".config/uv/uv.toml",
            target=home / ".config/uv/uv.toml",
            read_only=True,
        ),
    ]


def test_a_package_manager_the_image_doesnt_hold_gets_nothing(
    tmp_path: Path, home: Path
) -> None:
    del home
    launch = LaunchLayout(directory=tmp_path / "launch")
    plain_image = resolve(plain())
    assert "npm" not in [each.name for each in plain_image.packages]
    assert "uv" not in [each.name for each in plain_image.packages]
    gate = RoomPackageAge.of(launch, plain_image, tmp_path)
    assert gate.settings == []
    assert gate.ungated == []
    assert gate.mounts == []


def test_a_package_manager_getting_none_says_why_and_mounts_nothing(
    tmp_path: Path, home: Path
) -> None:
    del home
    why = Ungated(why="pip keeps no age here")
    gate = RoomPackageAge.of(
        LaunchLayout(directory=tmp_path / "launch"),
        resolved_with("pip"),
        tmp_path,
        managers=[Recorded(answer=why)],
    )
    assert gate.settings == []
    assert gate.ungated == [why]
    assert gate.mounts == []
