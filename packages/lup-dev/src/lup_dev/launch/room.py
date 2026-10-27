"""The maintaining session's room, from a resolved declaration and the worktree it's launched in.

A `lup.rooms.Container` on the host's network, its image the declaration's
packages and the operator's editor's (`launch/images.py`), with these mounted,
each at its host path (`docs/launch.md`, *The mounts*):
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
- what the project's runner needs for its environment (`Runner.room`), and the
  project's rooms' own directory, read-write: their package cache and each
  launch's environments, so the room's environment of each worktree is its own,
  fresh at each launch, outside the repository (`RoomEnvironments`);
- over each worktree's own environment, the host's (`Runner.venv`), where it's
  there as the room starts, an empty directory read-only, so the room neither
  reads nor writes what the operator's own `uv run` runs (`launch/hidden.py`);
- the configuration of the operator's editor, read-only, where it exists, so
  Ctrl+G opens it as the operator knows it;
- `/etc/localtime`, read-only, so the room's clock reads in the operator's zone;
- after the project's own, each other repository named for its sessions to
  read (`related`), whole and read-only, where it's on the host: a bare
  repository's git directory with its worktrees under it, or a clone's working
  tree with its `.git`, so a session reads its files, and its history through
  git (`docs/launch.md`, *Related repositories*). A relative path is from the directory
  holding the project's own repository. One that's missing is passed over, for
  the launch to say; one overlapping the room's own mounts, the project itself
  or a directory holding it, is refused, since mounted it would sit read-only
  over or under what the room writes.

Its variables are the runner's, the git identity, read from the host's git as
`GIT_AUTHOR_*` and `GIT_COMMITTER_*` since `~/.gitconfig` isn't mounted, the
terminal's (`TerminalVariables`). What the launch adds is the terminal
compile's and the launch command's: the launch's directory, its socket
directory, the CLI and the runtime's home.

pyright's source, for the engine's build in the room, is the room's own, never
the host's cache, which no room mounts: where the declaration holds a
`PyrightSource`, the image carries it at the release the worktree's `uv.lock`
pins (`launch/images.py`), and the room's variables name its project's rooms'
directory, where the build fetches a release the image doesn't carry
(`lup_dev/pyright_source.py`), pnpm held there to the package age as every
package manager in the room is.

The operator's editor is the one `$VISUAL` names, else `$EDITOR`, which Ctrl+G
opens (`OperatorsEditor`): where lup knows it (`Editors`), the room installs its
package, unless the declaration has it already, and mounts its configuration.

The directory of the interpreter the room's environment is made from, which the
runner finds without running anything of the project's (`Interpreter`), must
resolve under the room's mounts, or the room refuses with the runner's remedy:
without it, the room's tools would have no interpreter to make an environment
from (`docs/launch.md`, *The project's environment, the room's own*). A system
interpreter's is outside every mount.

The room's git (`room_git`, `docs/credentials.md`, *git through a remote
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

The package age gate (`RoomPackageAge`, `docs/launch.md`, *The package age
gate*): the user-level settings of each package manager the room's image holds,
as it spells them (`lup_dev.declaration.package_managers`), written into the
launch's directory and mounted read-only in the room's home, each refusing what
was published within `Core`'s `package_age`.
"""

import inspect
import json
import shutil
import tomllib
from itertools import chain, count
from pathlib import Path
from shlex import split
from typing import TYPE_CHECKING

from filelock import FileLock, Timeout

from lup.programs import ProgramMissingError, run
from lup.rooms.container import Container, Image, Mask, Mount
from lup.rooms.engine import stopped
from lup.sessions import bridge
from lup.sessions.terminal import TerminalSettings
from lup.types import Model
from lup_dev import environments
from lup_dev.catalog.room import Editor, Editors, RoomBase
from lup_dev.clipboard import shim
from lup_dev.declaration.kinds import Package
from lup_dev.declaration.package_managers import PACKAGE_MANAGERS
from lup_dev.declaration.package_managers.manager import (
    HomeSettings,
    PackageManager,
    Ungated,
)
from lup_dev.declaration.requirements import Needed, Requirement
from lup_dev.declaration.runner import RoomNeeds, RoomPlaces
from lup_dev.errors import LupDevError
from lup_dev.forge.github import PROGRAM
from lup_dev.git import Git, nul_separated
from lup_dev.launch.hidden import Hidden, removed
from lup_dev.launch.images import definition
from lup_dev.layout import (
    LOCALTIME,
    CheckoutLayout,
    LaunchLayout,
    LaunchSockets,
    RoomPaths,
    RoomsLayout,
)
from lup_dev.pyright_source import Fetching, PyrightSourceError, Sources, pinned
from lup_dev.remote import helper
from lup_dev.remote.config import Gating, room_config

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from lup.rooms.engine import Podman
    from lup_dev.declaration import kinds
    from lup_dev.declaration.requirements import Tools
    from lup_dev.declaration.resolve import Resolved
    from lup_dev.declaration.runner import Interpreter, Runner
    from lup_dev.layout import Layout
    from lup_dev.settings import TerminalVariables


class RoomError(LupDevError):
    """A room the declaration and the machine can't make as they stand."""


QRENCODE = Requirement(
    tool="qrencode",
    optional=True,
    why=(
        "draws the dashboard's address as a QR code for your phone to scan, "
        "where the dashboard listens beyond localhost"
    ),
    install="your system's `qrencode` package",
)
"""What draws the dashboard's address for a phone (`qr_code`), an optional
requirement of the host among `host_needs`."""


def host_needs() -> list[Needed]:
    """Return what the host needs to run a room, as requirements checked at once.

    Podman, rootless; git, which pushes and fetches for each room; and,
    optional, `gh`, without which lup's GitHub tools and the gate's issue states
    in a room are off; `notify-send`, without which the inbox raises no
    desktop notice; `wl-paste` or `xclip`, without which rooms reach no
    clipboard; and `qrencode`, without which `lup-dev dashboard` draws no QR
    code of the dashboard's address for a phone.
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
        Needed(module="lup-dev dashboard", requirement=QRENCODE),
    ]


def qr_code(text: str, requirement: Requirement = QRENCODE) -> str | None:
    """Return `text` as a QR code of block characters, which a terminal shows and a phone's camera reads; none where `requirement`'s program isn't installed.

    `lup-dev dashboard` draws the dashboard's address with it, the token in
    the address, so one visit is enough; where it's missing, the command says
    how to get it in the requirement's own words.
    """
    for program in requirement.programs():
        try:
            return run(program, "-t", "ANSIUTF8", text).text()
        except ProgramMissingError:
            continue
    return None


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
    roots = worktrees(git)
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


def worktrees(git: Git) -> list[Path]:
    """Return the root of each of the repository's worktrees, as `git worktree list` gives them, the main one first, whether or not it's on disk."""
    listed = git.run("worktree", "list", "--porcelain", "-z").output
    return [
        Path(field.removeprefix("worktree "))
        for field in nul_separated(listed)
        if field.startswith("worktree ")
    ]


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


class OperatorsEditor(Model):
    """The editor the operator uses: the program `$VISUAL` names on the host, else `$EDITOR`, as Ctrl+G opens it, and the editor lup knows by that name."""

    program: str | None
    """The program's name, a path's last part; none where neither variable
    names one."""
    known: Editor | None
    """The editor lup knows by that name (`Editors`), which the room installs;
    none where lup knows none."""

    @classmethod
    def of(cls, terminal: TerminalVariables) -> OperatorsEditor:
        """Return the editor `terminal`'s `$VISUAL` names, else its `$EDITOR`.

        Raise `RoomError` where that variable isn't a command line.

        >>> from lup_dev.settings import TerminalVariables
        >>> named = OperatorsEditor.of(TerminalVariables(term=None, colorterm=None,
        ...     lang=None, tz=None, editor="vim", visual="/usr/bin/nvim --clean"))
        >>> named.program, named.known and named.known.package
        ('nvim', 'neovim')
        """
        variable, command = (
            ("$VISUAL", terminal.visual)
            if terminal.visual
            else ("$EDITOR", terminal.editor)
        )
        try:
            words = split(command or "")
        except ValueError as failed:
            message = (
                f"`{variable}` isn't a command line ({failed}), so lup can't tell "
                "which editor the room installs and whose configuration it mounts"
            )
            raise RoomError(message) from failed
        if not words:
            return cls(program=None, known=None)
        program = Path(words[0]).name
        known = next(
            (each for each in Editors().editors if program in each.programs), None
        )
        return cls(program=program, known=known)

    def link(self, launch: LaunchLayout) -> None:
        """Link the name the operator runs their editor by to the program its package installs, among the launch's commands, where the two differ: `hx`, which Arch's helix installs as `helix`."""
        if self.known is None or self.program is None:
            return
        installed = self.known.links.get(self.program)
        if installed is None:
            return
        launch.bin.mkdir(parents=True, exist_ok=True)
        (launch.bin / self.program).symlink_to(installed)


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
    terminal: TerminalVariables,
    environments: RoomEnvironments,
    *,
    neighbours: list[RelatedRepository],
    shared: dict[str, Path] | None = None,
    lent: list[Lent] | None = None,
) -> Container:
    """Return the maintaining session's room for the worktree at `worktree`.

    `environments` is what the room gets for its environments, as the runner
    said (`RoomEnvironments.of`). `neighbours` are the other repositories named for the
    project's sessions, as the launch found them (`related`): each mounted one
    is mounted read-only after the project's own. `shared` is where each module
    whose data the room mounts keeps it, by the module's name: each mounted at
    its path, read-only unless the module says. `lent` are the directories the
    operator lends this launch from its command line, each mounted at its path,
    last. Raise `RoomError` where the
    repository's tree would hold the operator's home, where the operator's
    editor isn't a command line, where the environment's interpreter doesn't
    resolve under the room's mounts, where another repository overlaps them, or
    where the image carries pyright's source and the worktree's lock pins no
    one plain release of it.
    """
    home = Path.home()
    editor = OperatorsEditor.of(terminal).known
    held = repository(worktree)
    git = Git(cwd=worktree)
    needs = environments.needs

    def configured(key: str) -> str | None:
        found = git.run("config", "--get", key, ok=[0, 1])
        return found.output.decode().strip() if found.status == 0 else None

    def reached(interpreter: Interpreter, mounts: list[Mount]) -> None:
        resolved_home = interpreter.home.resolve()
        inside = any(
            resolved_home.is_relative_to(mount.source.resolve()) for mount in mounts
        )
        if inside and resolved_home.is_dir():
            return
        where = (
            "outside every mount of the room, as a system interpreter's is"
            if resolved_home.is_dir()
            else "and isn't there"
        )
        message = (
            f"The project's environment runs on the interpreter in "
            f"{interpreter.home}, which resolves to {resolved_home}, {where}: in "
            "the room the environment would have no interpreter, and its tools "
            "would set about remaking the environment the host shares. To launch, "
            f"{interpreter.remedy}"
        )
        raise RoomError(message)

    hooks = held.git / "hooks"
    hooks.mkdir(exist_ok=True)
    mounts = [
        Mount(source=held.tree),
        *([] if held.git == held.tree else [Mount(source=held.git)]),
        Mount(source=held.git / "config", read_only=True),
        Mount(source=hooks, read_only=True),
        *needs.mounts,
        *environments.mounts,
        *(
            Mount(source=home / path, read_only=True)
            for path in ([] if editor is None else editor.configuration)
            if (home / path).exists()
        ),
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
    packages = resolved.packages
    if editor is not None and editor.package not in [each.name for each in packages]:
        packages = [*packages, Package(name=editor.package, why=editor.why)]
    pyright = None if resolved.pyright_source is None else carried(resolved, worktree)
    return Container(
        image=Image(
            definition=definition(packages, RoomBase(), pyright),
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
            **environments.env,
            **identity,
            **terminal.passed(),
            **({} if pyright is None else Sources.room(environments.rooms.pyright)),
        },
        network="host",
    )


def carried(resolved: Resolved, worktree: Path) -> Fetching:
    """Return how the room's image fetches pyright's source: at the release the worktree's `uv.lock` pins, held to the declaration's package age.

    Raise `RoomError` where the lock pins no one plain release.
    """
    try:
        release = pinned(CheckoutLayout(root=worktree).lock)
    except PyrightSourceError as failed:
        message = (
            "The room's image carries pyright's source, for the engine's build in "
            f"the room, at the release the worktree's lock pins, but {failed}. Pin "
            "it once in the worktree's `uv.lock`, or launch from a worktree that does"
        )
        raise RoomError(message) from failed
    return Fetching(release=release, age=resolved.package_age)


class RoomEnvironments(Model):
    """What a room gets for an environment of its own in each worktree, the launch's, and what's hidden of the host's (`docs/launch.md`, *The project's environment, the room's own*).

    - **The project's rooms' own directory** (`RoomsLayout`), mounted read-write
      at its host path: the package cache their runner shares, and each
      launch's environments, one per worktree (`lup_dev/environments.py`), in
      one mount so an environment's files are links into the cache.
    - **lup's program first on the room's `PATH`,** under the name of each of
      the runner's programs (`RoomEnvironment.programs`), which tells it the
      environment of the worktree it runs in; the room's variables name the
      launch's environments, the variable the runner reads, and the repository.
    - **The start** (`before`): the runtime's CLI runs behind it, so the
      launch's worktree's environment is made in the background as the session
      starts (`RoomEnvironment.making`).
    - **The host's environment hidden** in each worktree (`Hidden`), the
      runner's own where it's inside the worktree (`Runner.venv`), whatever it
      gives the room: what the room writes there would run on the host at the
      operator's next `uv run`.
    - **At the launch's end** (`end`), its environments are removed, and each
      of the host's that appeared in a worktree while it ran, which only the
      room would have made: the operator's own made meanwhile goes too, to be
      made again.
    """

    rooms: RoomsLayout
    launch: LaunchLayout
    repository: Path
    """The repository's git directory, whose worktrees get environments of the
    launch's own, and whose worktrees are listed again at the end."""
    directory: Path
    """The launch's own environments, one per worktree: `rooms.launch(…)`."""
    needs: RoomNeeds
    """What the runner said the room needs for its environment."""
    hidden: Hidden

    @classmethod
    def of(
        cls,
        runner: Runner,
        worktree: Path,
        layout: Layout,
        launch: str,
        tools: Tools,
    ) -> RoomEnvironments:
        """Ask `runner`, through `tools`, what a room needs for the environment of the worktree at `worktree`, and find what it hides, for the launch `launch`.

        Raise `RoomError` where the repository's tree would hold the operator's
        home, and `RunnerError` where the runner can't say.
        """
        held = repository(worktree)
        rooms = layout.rooms(held.git)
        needs = runner.room(worktree, tools, RoomPlaces(cache=rooms.cache))
        venv = runner.venv()
        hidden = [] if venv is None or venv.is_absolute() else [venv]
        return cls(
            rooms=rooms,
            launch=layout.launch(launch),
            repository=held.git,
            directory=rooms.launch(launch),
            needs=needs,
            hidden=Hidden.of(held.tree, held.worktrees, hidden),
        )

    @property
    def own(self) -> Path | None:
        """The launch's environments, where its room has environments of its own: what the judge reads each worktree's from, for its hooks; none otherwise."""
        return None if self.needs.environment is None else self.directory

    @property
    def mounts(self) -> list[Mount]:
        """The project's rooms' directory, read-write, and what's hidden, read-only, each at its host path."""
        return [Mount(source=self.rooms.home), *self.hidden.mounts(self.launch)]

    @property
    def env(self) -> dict[str, str]:
        """The room's variables naming the launch's environments, the variable the runner reads, and the repository, where the room has environments of its own."""
        environment = self.needs.environment
        if environment is None:
            return {}
        return {
            environments.ENVIRONMENTS: str(self.directory),
            environments.VARIABLE: environment.variable,
            environments.REPOSITORY: str(self.repository),
        }

    @property
    def before(self) -> list[str]:
        """What the runtime's CLI runs behind: `lup-environment` and the command making the launch's worktree's environment, as a JSON list; nothing where there's none to make."""
        environment = self.needs.environment
        if environment is None or not environment.making:
            return []
        return [str(self.launch.wrapper), json.dumps(environment.making)]

    def write(self) -> None:
        """Make the project's rooms' cache and the launch's environments, write lup's program among the launch's commands, executable, link each of the runner's programs to it, and make what the hidden paths are mounted from."""
        self.rooms.cache.mkdir(parents=True, exist_ok=True)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.hidden.write(self.launch)
        environment = self.needs.environment
        if environment is None:
            return
        self.launch.bin.mkdir(parents=True, exist_ok=True)
        program = self.launch.wrapper
        program.write_text(programs(self.launch)[program])
        program.chmod(0o755)
        for name in environment.programs:
            self.launch.wrapping(name).symlink_to(program.name)

    def end(self) -> list[str]:
        """Remove the launch's environments, and each of the host's environments that appeared in a worktree while the room ran, and say each of those removed.

        The repository's worktrees are listed again, since the room may have
        added some; only those inside its tree are looked in.
        """
        removed(self.rooms.home, self.directory)
        appeared = self.hidden.appeared(worktrees(Git.pinned(self.repository)))
        return [
            (
                f"Removed {each}, an environment that appeared in a worktree while "
                "the room ran, which the room may have made: where it was your "
                "own, make it again."
            )
            for each in appeared
            if removed(self.hidden.tree, each)
        ]


def unclaimed(rooms: RoomsLayout, served: list[str], layout: Layout) -> list[Path]:
    """Remove each launch's environments in `rooms` that no launch among `served` holds and no launcher runs for, as a launch that crashed leaves them, and return those removed.

    A launcher holds its launch's lock for its whole life (`LaunchLayout.lock`),
    so one whose lock can be taken has none left.
    """

    def gone() -> Iterator[Path]:
        for each in sorted(rooms.environments.iterdir()):
            if each.name in served:
                continue
            held = layout.launch(each.name).lock
            lock = FileLock(held, timeout=0)
            try:
                lock.acquire()
            except Timeout:
                continue
            try:
                if removed(rooms.home, each):
                    yield each
            finally:
                lock.release()
                held.unlink(missing_ok=True)

    return list(gone()) if rooms.environments.is_dir() else []


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
            "PATH": ":".join(
                str(each) for each in [self.launch.bin, *RoomPaths().path]
            ),
        }

    def write(self) -> None:
        """Write the room's git configuration and the helper into the launch's directory, the helper executable."""
        room_config(
            self.repository,
            self.launch.gitconfig,
            LaunchSockets(directory=RoomPaths().sockets).request,
            self.gating,
        )
        self.launch.bin.mkdir(parents=True, exist_ok=True)
        self.launch.helper.write_text(programs(self.launch)[self.launch.helper])
        self.launch.helper.chmod(0o755)


class RoomClipboard(Model):
    """What a room gets for the operator's clipboard: `wl-paste` and `wl-copy` first on its `PATH`, beside git's helper, reaching the host; and a Wayland display named, so its programs reach for them (`docs/launch.md`, *The clipboard*)."""

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


class RoomPackageAge(Model):
    """What a room gets for the package age gate: the user-level settings of each package manager its image holds, each refusing what was published within the age (`docs/launch.md`, *The package age gate*).

    Each is a file of the launch's own, under its `home`, mounted read-only
    where its package manager reads it in the room's home.
    """

    launch: LaunchLayout
    home: Path
    """The room's home: the operator's home path, as the room has it."""
    settings: list[HomeSettings]
    ungated: list[Ungated] = []
    """Why each package manager the image holds that gets no settings doesn't,
    which the launch says."""

    @classmethod
    def of(
        cls,
        launch: LaunchLayout,
        resolved: Resolved,
        root: Path,
        managers: list[PackageManager] = PACKAGE_MANAGERS,
    ) -> RoomPackageAge:
        """Ask each of `managers` the room's image holds for its settings keeping the declaration's package age, for the project at `root`."""
        held = [each.name for each in resolved.packages]
        aged = [
            manager.aged(root, resolved.package_age)
            for manager in managers
            if manager.package in held
        ]
        return cls(
            launch=launch,
            home=Path.home(),
            settings=[each for each in aged if isinstance(each, HomeSettings)],
            ungated=[each for each in aged if isinstance(each, Ungated)],
        )

    @property
    def mounts(self) -> list[Mount]:
        """Each file, read-only, where its package manager reads it in the room's home."""
        return [
            Mount(
                source=self.launch.home / each.path,
                target=self.home / each.path,
                read_only=True,
            )
            for each in self.settings
        ]

    def write(self) -> None:
        """Write each file into the launch's `home`, at its path there."""
        for each in self.settings:
            written = self.launch.home / each.path
            written.parent.mkdir(parents=True, exist_ok=True)
            written.write_text(each.text)


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
    return Mount(source=launch.lent, target=RoomPaths().lent, receives=True)


def lend(
    podman: Podman,
    launch: LaunchLayout,
    source: Path,
    *,
    read_only: bool,
    name: str | None = None,
) -> Path:
    """Lend the host's directory `source` to a launch's running room, and return where the room finds it: under `RoomPaths.lent`, by `name`, the directory's own by default, numbered where that's taken.

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
    return RoomPaths().lent / free


def cleared(podman: Podman, container: str, say: Callable[[str], None]) -> None:
    """Remove a container left under the name a launch's container is about to take, saying so; raise `RoomError` where one runs under it.

    The host service gives a launch a name no launch it serves holds, so a
    container already under it was left by a launch the service
    doesn't know: one that ended before its container started, or before
    `--rm` removed it. One running is a session the service lost track of, at
    a restart say, and is the operator's to end.
    """
    state = podman.state(container)
    if state is None:
        return
    if not stopped(state):
        message = (
            f"a container named {container} is {state}, and no launch the host "
            "service knows holds it: end that session, or remove it with "
            f"`podman rm -f {container}`, and launch again"
        )
        raise RoomError(message)
    podman.discard(container)
    say(f"Removed the container {container}, {state}, which a launch that ended left.")


def unlent(podman: Podman, launch: LaunchLayout) -> None:
    """Unmount everything lent to a launch's room, and remove its places.

    The host's own view of them holds only the empty directories mounted on in
    podman's namespace, so removing them removes nothing lent.
    """
    for each in [launch.lent, launch.stage]:
        if each.is_dir():
            podman.released(each)
            shutil.rmtree(each)


def vacated(launch: LaunchLayout) -> None:
    """Remove a launch's room's home, with what the room wrote there, once its room is gone.

    Each directory in it is made its owner's to write first, since a room leaves
    read-only ones, as Go's module cache is, which `shutil.rmtree` can't empty.
    No link is followed: `Path.walk` lists one among the files, and
    `shutil.rmtree` removes the link, not what it points at. Nothing writes the
    home by then, so its paths hold still while they're read.
    """
    home = launch.room_home
    if home.is_symlink() or not home.is_dir():
        return
    home.chmod(0o700)
    for directory, inside, _ in home.walk():
        for name in inside:
            (directory / name).chmod(0o700)
    shutil.rmtree(home)


def programs(launch: LaunchLayout) -> dict[Path, str]:
    """Return the programs a launch writes for its room to run, by where they go: git's remote helper, the clipboard's `wl-paste` and `wl-copy`, `lup-environment`, which the runner's programs link to, and lup's MCP bridge for its tool servers."""
    clipboard = inspect.getsource(shim)
    return {
        launch.helper: inspect.getsource(helper),
        launch.pasting: clipboard,
        launch.copying: clipboard,
        launch.wrapper: inspect.getsource(environments),
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
