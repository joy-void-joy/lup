"""The maintaining session's room, from a resolved declaration and the worktree it's launched in.

A `lup.rooms.Container` on the host's network, its image the declaration's
(`launch/images.py`), with these mounted, each at its host path (`docs/launch.md`,
*The mounts*):
- the repository as one tree, read-write: its git directory and every worktree,
  so `git worktree add` and `remove` work as on the host, and an agent reads any
  other worktree it's pointed at. The tree is the nearest directory holding them
  all; one that would hold the operator's home is refused, since the whole of it
  would be writable;
- the git directory's `config` and `hooks/` read-only over it: they run on the
  host, so a hook or a `core.fsmonitor` written there would run at the
  operator's next git command. `hooks/` is made if it's missing, so the room
  can't make it. Where the git directory isn't the tree's root (a clone's
  `.git`), it's mounted on its own too, read-write as the tree is: a mount can't
  be moved from inside, where a plain directory holding the read-only mounts
  could be moved aside, and one of the room's own, its `config` among it, put
  in its place for the host's git to read (measured: `mv .git .git-real`
  succeeded under the mounts alone, and failed with "Device or resource busy"
  once `.git` was mounted on its own);
- what the project's runner needs for its environment (`Runner.room`);
- pyright's source in lup's cache, read-write, which the gate builds the engine
  from. Only that part: the cache holds the CLIs rooms run, which a room
  mustn't rewrite;
- the configuration of the editor `$EDITOR` or `$VISUAL` names, read-only, where
  it exists, so Ctrl+G opens it as the operator knows it;
- `/etc/localtime`, read-only, so the room's clock reads in the operator's zone;
- after the project's own, each other repository named for its sessions to
  read (`related`), whole and read-only, where it's on the host: a bare
  repository's git directory with its worktrees under it, or a clone's working
  tree with its `.git`, so a session reads its files, and its history through
  git (`docs/related-repositories.md`). A relative path is from the directory
  holding the project's own repository. One that's missing is passed over, for
  the launch to say; one overlapping the room's own mounts, the project itself
  or a directory holding it, is refused, since mounted it would sit read-only
  over or under what the room writes.

Its variables are the runner's, the git identity, read from the host's git as
`GIT_AUTHOR_*` and `GIT_COMMITTER_*` since `~/.gitconfig` isn't mounted, the
terminal's (`TerminalVariables`), and `XDG_CACHE_HOME` as the host's lup has it
(`Layout.cache`'s parent), so the engine's build in the room finds pyright's
source where it's mounted: the build takes the path from the same layout. What
the launch adds is the terminal compile's
and the launch command's: the launch's directory, its socket directory, the CLI
and the runtime's home.

The environment's interpreter must resolve under the room's mounts, or the room
refuses with the runner's remedy: without it, `uv run` in the room set about
remaking the shared `.venv` (`docs/launch.md`, *The project's environment,
shared with the host*). A system interpreter is outside every mount.

The room's git (`room_git`, `docs/host-tools.md`, *git through a remote
helper*): its own configuration in place of the operator's (`GIT_CONFIG_GLOBAL`,
`remote/config.py`), and lup's remote helper first on its `PATH`, both written
into the launch's directory and mounted read-only on every runtime, since not
every terminal mounts that directory. The host runs git in the repository's git
directory for the room, so a launch refuses a repository whose `config` would
have that git read what the room writes: one setting `extensions.worktreeConfig`,
under which git reads the git directory's `config.worktree` too, a file the room
writes; or one including, through `include.path` or any `includeIf` whatever its
condition, a file inside one of the room's mounts, each include resolved as git
resolves it (relative to the file holding it, `~` the operator's home, an
`:(optional)` one too) and followed through every file it includes
(`docs/field-notes.md`, *Host-side git in a repository the room writes*).
"""

import inspect
import shutil
import tomllib
from itertools import chain, count
from pathlib import Path
from shlex import split
from typing import TYPE_CHECKING

from lup.rooms.container import Container, Image, Mask, Mount
from lup.sessions import bridge
from lup.sessions.terminal import TerminalSettings
from lup.types import Model
from lup_dev.catalog.room import Editors, RoomBase
from lup_dev.clipboard import shim
from lup_dev.declaration.requirements import Needed, Requirement
from lup_dev.errors import LupDevError
from lup_dev.forge.github import PROGRAM
from lup_dev.git import Git, nul_separated
from lup_dev.launch.images import definition
from lup_dev.layout import (
    LOCALTIME,
    ROOM_LENT,
    ROOM_PATH,
    ROOM_SOCKETS,
    LaunchLayout,
    LaunchSockets,
)
from lup_dev.remote import helper
from lup_dev.remote.config import Gating, room_config

if TYPE_CHECKING:
    from lup.rooms.engine import Podman
    from lup_dev.declaration import kinds
    from lup_dev.declaration.requirements import Tools
    from lup_dev.declaration.resolve import Resolved
    from lup_dev.declaration.runner import Interpreter
    from lup_dev.layout import Layout
    from lup_dev.settings import TerminalVariables


class RoomError(LupDevError):
    """A room the declaration and the machine can't make as they stand."""


def host_needs() -> list[Needed]:
    """Return what the host needs to run a room, as requirements checked at once.

    Podman, rootless; git, which pushes and fetches for each room; and,
    optional, `gh`, without which lup's GitHub tools and the gate's issue states
    in a room are off; `notify-send`, without which the inbox raises no
    desktop notice; and `wl-paste` or `xclip`, without which rooms reach no
    clipboard.
    """
    podman = Requirement(
        tool="podman",
        why="runs each session's room, rootless",
        install="your system's `podman` package, set up for rootless containers",
    )
    git = Requirement(
        tool="git",
        why="pushes and fetches for each room, with your credentials",
        install="your system's `git` package",
    )
    gh = Requirement(
        tool=PROGRAM,
        optional=True,
        why=(
            "reaches GitHub with your login for lup's GitHub tools, and for the "
            "gate's issue states in a room"
        ),
        install="your system's `github-cli` package, then `gh auth login`",
    )
    notices = Requirement(
        tool="notify-send",
        optional=True,
        why="raises a desktop notice when something reaches your inbox",
        install="your system's `libnotify` package",
    )
    clipboard = Requirement(
        any_of=["wl-paste", "xclip"],
        optional=True,
        why="reads and writes your clipboard for the rooms' sessions",
        install="your system's `wl-clipboard` package under Wayland, `xclip` under X",
    )
    return [
        Needed(module="lup-dev launch", requirement=podman),
        Needed(module="lup-dev launch", requirement=git),
        Needed(module="lup-dev launch", requirement=gh),
        Needed(module="lup-dev inbox", requirement=notices),
        Needed(module="lup-dev launch", requirement=clipboard),
    ]


class Repository(Model):
    """A repository as a room mounts it."""

    git: Path
    """Its git directory, which every worktree shares (`git rev-parse --git-common-dir`)."""
    worktrees: list[Path]
    """Each worktree's root that exists, as `git worktree list` gives it; a bare
    repository's own directory among them."""
    main: Path
    """The main worktree, which `git worktree list` gives first: a clone's root, or
    a bare repository's own directory. The runtimes ask about it for a linked
    worktree, so a launch trusts it too."""
    tree: Path
    """The nearest directory holding the git directory and every worktree, mounted whole."""


def repository(worktree: Path) -> Repository:
    """Return the repository of the worktree at `worktree`, and the tree a room mounts for it.

    Raise `RoomError` where that tree would hold the operator's home.
    """
    git = Git(cwd=worktree)
    common = Path(git.text("rev-parse", "--path-format=absolute", "--git-common-dir"))
    listed = git.run("worktree", "list", "--porcelain", "-z").output
    roots = [
        Path(field.removeprefix("worktree "))
        for field in nul_separated(listed)
        if field.startswith("worktree ")
    ]
    present = [root for root in roots if root.exists()]
    tree = next(
        each
        for each in [common, *common.parents]
        if all(root.is_relative_to(each) for root in present)
    )
    home = Path.home()
    if home.is_relative_to(tree):
        places = ", ".join(str(each) for each in [common, *present])
        message = (
            f"The repository's git directory and worktrees ({places}) meet only at "
            f"{tree}, which holds your home ({home}): a room mounts them as one "
            "tree, read-write, and this one would hold everything under it. Keep "
            "the worktrees under one directory with the git directory "
            "(`git worktree move`), and launch again"
        )
        raise RoomError(message)
    [main, *_] = roots
    return Repository(git=common, worktrees=present, main=main, tree=tree)


class Described(Model):
    """The part of a `pyproject.toml` a lent directory's description is read from."""

    class Project(Model):
        """`[project]`, for its description."""

        description: str | None = None

    project: Project = Project()


class Lent(Model):
    """A directory the operator lends one launch from its command line: where it is, whether the room may write it, and what's known of it."""

    path: Path
    """Where it is on the host, absolute and resolved: where the room mounts it."""
    read_only: bool
    repository: bool
    """Whether it's in a git repository, whose history a session reads with git."""
    about: str | None = None
    """Its `pyproject.toml`'s description, where it has one: nothing is declared
    for a directory lent."""


def lent(paths: list[Path], *, read_only: bool) -> list[Lent]:
    """Describe each directory at `paths`, lent to a launch from its command line: `--mount` read-only, `--mount-rw` writable.

    Each is what the launch found there: whether git sees a repository, and its
    `pyproject.toml`'s description. Nothing is asked of the operator beyond
    the path.
    """

    def described(path: Path) -> Lent:
        pyproject = path / "pyproject.toml"
        about = (
            Described.model_validate(
                tomllib.loads(pyproject.read_text())
            ).project.description
            if pyproject.is_file()
            else None
        )
        found = Git(cwd=path).run("rev-parse", "--git-dir", ok=[0, 128])
        return Lent(
            path=path.resolve(),
            read_only=read_only,
            repository=found.status == 0,
            about=about,
        )

    return [described(each) for each in paths]


class RelatedRepository(Model):
    """Another repository named for the project's sessions to read, as a launch finds it on the host."""

    name: str
    path: Path
    """Where it is on the host, absolute and resolved: where the room mounts it."""
    about: str
    """What it is, and what it's for here, as its entry says."""
    github: str | None
    """Its `owner/name` on GitHub, where its entry gives one."""
    mounted: bool
    """Whether the room mounts it: false where nothing is at its path, which the
    launch says once."""


def related(named: list[kinds.Repository], worktree: Path) -> list[RelatedRepository]:
    """Find on the host each other repository `named`, for a launch in the worktree at `worktree`.

    A relative path is from the directory holding the project's own repository:
    the parent of a bare repository's git directory, or of a clone's working
    tree. A leading `~` is the operator's home. One is mounted where a
    directory is at its path.
    """
    holding = repository(worktree).main.parent

    def found(declared: kinds.Repository) -> RelatedRepository:
        path = declared.on_host(holding)
        return RelatedRepository(
            name=declared.name,
            path=path,
            about=declared.about,
            github=declared.github,
            mounted=path.is_dir(),
        )

    return [found(each) for each in named]


def apart(other: RelatedRepository, mounts: list[Mount]) -> None:
    """Raise `RoomError` where another repository overlaps one of the room's own mounts: inside it, as the project itself is, or holding it."""
    overlapping = [
        mount.source
        for mount in mounts
        if other.path.is_relative_to(mount.source.resolve())
        or mount.source.resolve().is_relative_to(other.path)
    ]
    if overlapping:
        message = (
            f"The repository `{other.name}` named for sessions to read, at "
            f"{other.path}, overlaps the room's own mount of {overlapping[0]}: "
            "another repository is mounted read-only beside the project's, so it "
            "can't be the project itself, sit inside what the room mounts, or "
            "hold it. Give it its own path, or drop it, to launch"
        )
        raise RoomError(message)


def maintaining_room(
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
    """Return the maintaining session's room for the worktree at `worktree`.

    `tools` is how the runner asks the host where its environment's parts are;
    a test stubs it. `neighbours` are the other repositories named for the
    project's sessions, as the launch found them (`related`): each mounted one
    is mounted read-only after the project's own. `shared` is where each module
    whose data the room mounts keeps it, by the module's name: each mounted at
    its path, read-only unless the module says. `lent` are the directories the
    operator lends this launch from its command line, each mounted at its path,
    last. Raise `RoomError` where the
    repository's tree would hold the operator's home, where `$EDITOR` or
    `$VISUAL` isn't a command line, where the environment's interpreter doesn't
    resolve under the room's mounts, or where another repository overlaps them.
    """
    home = Path.home()
    held = repository(worktree)
    git = Git(cwd=worktree)
    needs = resolved.runner.room(worktree, tools)

    def configured(key: str) -> str | None:
        found = git.run("config", "--get", key, ok=[0, 1])
        return found.output.decode().strip() if found.status == 0 else None

    def editors() -> list[Mount]:
        named = [command for command in [terminal.editor, terminal.visual] if command]
        try:
            programs = [Path(words[0]).name for words in map(split, named) if words]
        except ValueError as failed:
            message = (
                f"`$EDITOR` or `$VISUAL` isn't a command line ({failed}), so lup "
                "can't tell which editor's configuration the room mounts"
            )
            raise RoomError(message) from failed
        configuration = dict.fromkeys(
            home / path
            for editor in Editors().editors
            if any(program in editor.programs for program in programs)
            for path in editor.configuration
        )
        return [
            Mount(source=path, read_only=True)
            for path in configuration
            if path.exists()
        ]

    def reached(interpreter: Interpreter, mounts: list[Mount]) -> None:
        resolved_path = interpreter.path.resolve()
        inside = any(
            resolved_path.is_relative_to(mount.source.resolve()) for mount in mounts
        )
        if inside and resolved_path.is_file():
            return
        where = (
            "outside every mount of the room, as a system interpreter is"
            if resolved_path.is_file()
            else "and isn't there"
        )
        message = (
            f"The project's environment runs on {interpreter.path}, which resolves "
            f"to {resolved_path}, {where}: in the room the environment would have "
            "no interpreter, and its tools would set about remaking the "
            f"environment the host shares. To launch, {interpreter.remedy}"
        )
        raise RoomError(message)

    hooks = held.git / "hooks"
    hooks.mkdir(exist_ok=True)
    pyright = layout.pyright_source
    pyright.mkdir(parents=True, exist_ok=True)
    mounts = [
        Mount(source=held.tree),
        *([] if held.git == held.tree else [Mount(source=held.git)]),
        Mount(source=held.git / "config", read_only=True),
        Mount(source=hooks, read_only=True),
        *needs.mounts,
        Mount(source=pyright),
        *editors(),
        *([Mount(source=LOCALTIME, read_only=True)] if LOCALTIME.exists() else []),
        *(
            Mount(source=place, read_only=each.read_only)
            for each in resolved.shared
            if (place := (shared or {}).get(each.module)) is not None
        ),
    ]
    if needs.interpreter is not None:
        reached(needs.interpreter, mounts)
    for each in neighbours:
        apart(each, mounts)
    name = configured("user.name")
    email = configured("user.email")
    identity = {
        **(
            {}
            if name is None
            else {"GIT_AUTHOR_NAME": name, "GIT_COMMITTER_NAME": name}
        ),
        **(
            {}
            if email is None
            else {"GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_EMAIL": email}
        ),
    }
    return Container(
        image=Image(
            definition=definition(resolved.packages, RoomBase()),
            project=str(held.git),
        ),
        mounts=[
            *mounts,
            *(
                Mount(source=each.path, read_only=True)
                for each in neighbours
                if each.mounted
            ),
            *(Mount(source=each.path, read_only=each.read_only) for each in lent or []),
        ],
        env={
            **needs.env,
            **identity,
            **terminal.passed(),
            "XDG_CACHE_HOME": str(layout.cache.parent),
        },
        network="host",
    )


class RoomGit(Model):
    """What a room gets for git beside the tree: its own git configuration, and lup's remote helper first on its `PATH`."""

    repository: Path
    """The repository's git directory on the host, whose remotes the
    configuration names."""
    launch: LaunchLayout
    """The launch's own places, where both are written."""
    gating: Gating
    """What a push runs first, before it updates a gated ref."""

    @property
    def mounts(self) -> list[Mount]:
        """Both, read-only, at their host paths."""
        return [
            Mount(source=self.launch.bin, read_only=True),
            Mount(source=self.launch.gitconfig, read_only=True),
        ]

    @property
    def env(self) -> dict[str, str]:
        """The room's variables for git: the configuration in place of the operator's, and the helper's directory first on the `PATH`."""
        return {
            "GIT_CONFIG_GLOBAL": str(self.launch.gitconfig),
            "PATH": ":".join(str(each) for each in [self.launch.bin, *ROOM_PATH]),
        }

    def write(self) -> None:
        """Write the room's git configuration and the helper into the launch's directory, the helper executable."""
        room_config(
            self.repository,
            self.launch.gitconfig,
            LaunchSockets(directory=ROOM_SOCKETS).request,
            self.gating,
        )
        self.launch.bin.mkdir(parents=True, exist_ok=True)
        self.launch.helper.write_text(programs(self.launch)[self.launch.helper])
        self.launch.helper.chmod(0o755)


class RoomClipboard(Model):
    """What a room gets for the operator's clipboard: `wl-paste` and `wl-copy` first on its `PATH`, beside git's helper, reaching the host; and a Wayland display named, so its programs reach for them (`docs/host-tools.md`, *The clipboard*)."""

    launch: LaunchLayout
    display: str = "lup"
    """The Wayland display the room names: none is there, but a program
    choosing its clipboard by it reaches for `wl-paste` and `wl-copy`."""

    @property
    def env(self) -> dict[str, str]:
        """The room's variable naming its display."""
        return {"WAYLAND_DISPLAY": self.display}

    def write(self) -> None:
        """Write both programs into the launch's commands, executable."""
        self.launch.bin.mkdir(parents=True, exist_ok=True)
        wanted = programs(self.launch)
        for path in [self.launch.pasting, self.launch.copying]:
            path.write_text(wanted[path])
            path.chmod(0o755)


def receiving(podman: Podman, launch: LaunchLayout) -> Mount:
    """Prepare a launch's room to receive what the operator lends it while it runs, and return the room's mount doing so.

    Its two places (`LaunchLayout.lent`, `.stage`) are made, the first shared and
    the second private in podman's namespace, before the room starts: a room
    receives only what's mounted under a mount that was shared when it started
    (measured, `docs/field-notes.md`, *Lending to a running room*).
    """
    for each in [launch.lent, launch.stage]:
        each.mkdir(parents=True, exist_ok=True)
    podman.shared(launch.lent)
    podman.private(launch.stage)
    return Mount(source=launch.lent, target=ROOM_LENT, receives=True)


def lend(
    podman: Podman,
    launch: LaunchLayout,
    source: Path,
    *,
    read_only: bool,
    name: str | None = None,
) -> Path:
    """Lend the host's directory `source` to a launch's running room, and return where the room finds it: under `ROOM_LENT`, by `name`, the directory's own by default, numbered where that's taken.

    Raise `RoomError` where the launch's room can't receive it, started before
    rooms could.
    """
    if not launch.lent.is_dir():
        message = (
            "this launch's room started before a running room could be lent a "
            "directory: lend it at the next launch, `lup-dev launch <runtime> "
            f"--mount {source}`"
        )
        raise RoomError(message)
    wanted = name or source.name
    taken = [each.name for each in launch.lent.iterdir()]
    named = chain([wanted], (f"{wanted}-{n}" for n in count(2)))
    free = next(each for each in named if each not in taken)
    at = launch.lent / free
    at.mkdir()
    podman.lend(source, at, launch.stage, read_only=read_only)
    return ROOM_LENT / free


def unlent(podman: Podman, launch: LaunchLayout) -> None:
    """Unmount everything lent to a launch's room, and remove its places.

    The host's own view of them holds only the empty directories mounted on in
    podman's namespace, so removing them removes nothing lent.
    """
    for each in [launch.lent, launch.stage]:
        if each.is_dir():
            podman.released(each)
            shutil.rmtree(each)


def programs(launch: LaunchLayout) -> dict[Path, str]:
    """Return the programs a launch writes for its room to run, by where they go: git's remote helper, the clipboard's `wl-paste` and `wl-copy`, and lup's MCP bridge for its tool servers."""
    clipboard = inspect.getsource(shim)
    return {
        launch.helper: inspect.getsource(helper),
        launch.pasting: clipboard,
        launch.copying: clipboard,
        TerminalSettings(directory=launch.directory).bridge: inspect.getsource(bridge),
    }


def refreshed(launch: LaunchLayout) -> list[Path]:
    """Rewrite each program a launch's room runs that differs from this copy's, and return those rewritten.

    A program the launch didn't write stays unwritten: a session with no tool
    servers has no bridge. Each is rewritten in place, its file kept, since a
    room mounting that one file (as a runtime's adapter may mount the bridge)
    keeps seeing the file it mounted, where a replaced one it wouldn't. The
    room runs the helper anew at each push and fetch; a bridge already running
    keeps its own code until the next launch.
    """
    wanted = programs(launch)
    changed = [
        path
        for path, text in wanted.items()
        if path.is_file() and path.read_text() != text
    ]
    for path in changed:
        path.write_text(wanted[path])
    return changed


def room_git(
    repository: Path, launch: LaunchLayout, mounts: list[Mount | Mask], gating: Gating
) -> RoomGit:
    """Return what a room gets for git, for the repository whose git directory is `repository`, once its `config` is checked.

    `mounts` is everything else the room mounts: the room's own and its
    terminal's; `gating`, what a push runs first. Raise `RoomError` where the
    repository's `config` would have the host's git read what the room writes:
    setting `extensions.worktreeConfig`, or including a file inside one of the
    room's mounts, through any file it includes in turn.
    """
    git = Git.pinned(repository)
    room = RoomGit(repository=repository, launch=launch, gating=gating)
    sources = [
        each.source for each in [*mounts, *room.mounts] if isinstance(each, Mount)
    ]

    def holding(path: Path) -> list[Path]:
        places = [path, path.resolve()]
        return [
            source
            for source in sources
            if any(place.is_relative_to(source) for place in places)
        ]

    def read(config: Path, *arguments: str) -> list[str]:
        """Read `config` alone, its includes not followed: each value, or each key."""
        found = git.run(
            "config",
            "--file",
            str(config),
            "--no-includes",
            "-z",
            *arguments,
            ok=[0, 1],
        )
        return nul_separated(found.output)

    def included(config: Path) -> list[Path]:
        keys = read(config, "--name-only", "--get-regexp", r"^include(if\..*)?\.path$")
        written = [
            value
            for key in dict.fromkeys(keys)
            for value in read(config, "--get-all", key)
        ]
        named = [
            Path(each).expanduser()
            for value in written
            for each in dict.fromkeys([value, value.removeprefix(":(optional)")])
        ]
        return [each if each.is_absolute() else config.parent / each for each in named]

    def walked(config: Path, seen: list[Path]) -> list[Path]:
        here = config.resolve()
        if here in seen:
            return seen
        if "true" in read(
            config, "--type=bool", "--get-all", "extensions.worktreeConfig"
        ):
            message = (
                f"{config} sets `extensions.worktreeConfig`, under which git reads the "
                f"git directory's `config.worktree` too ({repository / 'config.worktree'}), "
                "a file the room writes: the host's git, pushing and fetching for the "
                "room, would read what the room put there. Unset it to launch"
            )
            raise RoomError(message)
        files = included(config)
        for each in files:
            held = holding(each)
            if held:
                message = (
                    f"{config} includes {each}, inside the room's mount of {held[0]}: "
                    "the host's git, pushing and fetching for the room, would read "
                    "what the room wrote there. Move the included file out of the "
                    "room's mounts, or drop the include, to launch"
                )
                raise RoomError(message)
        checked = [*seen, here]
        for each in files:
            if each.is_file():
                checked = walked(each, checked)
        return checked

    walked(repository / "config", [])
    return room
