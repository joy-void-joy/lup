"""Where `lup_dev` keeps what it stores, as models whose fields are the places.

The homes:
- lup's own state, under `$XDG_STATE_HOME/lup/`: each worktree's store, outside the
  worktree so the restore source is out of the agent's reach, and each
  repository's verdict log, the host zone its operator approved and the files
  they marked reviewed in its agents' drawers;
- each worktree engine's socket, under `$XDG_RUNTIME_DIR/lup/`, since a socket's
  path is limited in length;
- the host service's sockets and the launches it serves, under
  `$XDG_RUNTIME_DIR/lup/host/`, and its log under lup's state (`docs/launch.md`);
  each launch's compiled settings, its room's git configuration, its package
  managers' settings and lup's commands there, and the lock its launcher holds,
  under lup's state;
- lup's data, under `$XDG_DATA_HOME/lup/`: each repository's approved copies of
  `lup-dev`, which trust on launch installs and its process runs; and each
  repository's rooms' own directory, their package cache, each launch's
  environments and pyright's source at a release a room's image doesn't carry,
  which its rooms mount read-write (`RoomsLayout`); the rooms' own homes, each
  runtime's history and state, a project's or one every project shares, apart
  from every directory a room writes (`HomesLayout`); and each account's
  logins, one per runtime (`AccountsLayout`);
- the person's own configuration, under `$XDG_CONFIG_HOME/lup/`: their profiles
  file, and each profile's runtime configuration (`ProfilesLayout`);
- lup's cache, what can be fetched again, under `$XDG_CACHE_HOME/lup/`: pyright's
  source, kept for building the engine on the host, which no room mounts; and
  each runtime's CLIs, as its release channel publishes them, under `clis/`
  (`docs/launch.md`, *The CLIs*);
- inside every room, where its launch's sockets and what's lent are mounted, and
  where its image keeps pyright's source (`RoomPaths`);
- the record of each room image built, in lup's state;
- lup's inbox, its items and parties one file each, in lup's state;
- inside a worktree, `.lup/saved/`, where a refused version waits for the agent;
- inside a repository's own git directory, `lup/passes/`, the gate's passes,
  which its worktrees and their rooms share, and which outlast a room's session
  as lup's state there doesn't; and `lup/reports/`, the judge's reports too
  long for a hook, kept whole where every room reads them;
- inside `lup_dev`, the built engine (`Bundle`).
"""

import getpass
import hashlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.environments import STARTER

if TYPE_CHECKING:
    from lup_dev.settings import LupDevSettings

LOCALTIME = Path("/etc/localtime")
"""The host's time zone, which a room mounts read-only so its clock reads as the operator's."""


def digest(path: Path) -> str:
    """Name a directory by its absolute path, as a stable file name.

    >>> len(digest(Path("/work/lup")))
    64
    """
    return hashlib.sha256(str(path).encode()).hexdigest()


def short_digest(path: Path) -> str:
    """Name a directory by its absolute path, short enough for a socket's path.

    A Unix socket's path holds at most 107 bytes on Linux, 103 on macOS.

    >>> len(short_digest(Path("/work/lup")))
    32
    """
    return hashlib.blake2b(str(path).encode(), digest_size=16).hexdigest()


class RoomPaths(Model):
    """The paths lup places inside every room, as the room sees them, wherever the host keeps what's there."""

    sockets: Path = Path("/run/lup")
    """Where a room mounts its launch's socket directory, so its hook finds the host service."""
    lent: Path = Path("/lent")
    """Where a room finds each directory the operator lends it while it runs (`lup-dev mount`), one per name."""
    pyright: Path = Path("/opt/lup/pyright")
    """Where a room's image keeps pyright's source, a directory per release, which the engine's build in the room reads (`lup_dev/pyright_source.py`)."""
    path: list[Path] = [
        Path("/usr/local/sbin"),
        Path("/usr/local/bin"),
        Path("/usr/sbin"),
        Path("/usr/bin"),
        Path("/sbin"),
        Path("/bin"),
    ]
    """The room's own `PATH`, which a launch puts lup's commands before: the one
    Arch Linux's image sets, and podman's default for an image setting none."""


class Bundle(Model):
    """The built engine, shipped inside `lup_dev`: its script and the stubs beside it.

    The engine's build (`packages/lup-dev/checker/build.py`) writes it; git ignores
    it, and the package carries it when installed from a built checkout.
    """

    directory: Path = Path(__file__).parent / "codescan" / "bundle"

    @property
    def script(self) -> Path:
        """The engine itself, one JavaScript file run by Node."""
        return self.directory / "engine.js"

    @property
    def stubs(self) -> Path:
        """The standard library's stubs at pyright's pinned release, which it reads."""
        return self.directory / "typeshed-fallback"


class PyrightDownloads(Model):
    """What a fetch of pyright's source downloads, beside the release and removed once it's installed, so a place keeps the source alone.

    pnpm keeps its store, its cache and its state where XDG's variables name,
    the pnpm release it switches to among them. On the source's own file system,
    so pnpm links its files from the store rather than copying them, and they
    outlive the store's removal. In the image's build, which has no home for
    pnpm, it's pnpm's home too, holding the settings a room's has.
    """

    home: Path

    @property
    def data(self) -> Path:
        """`XDG_DATA_HOME` for pnpm: its store, which the source's `node_modules` link from."""
        return self.home / "data"

    @property
    def cache(self) -> Path:
        """`XDG_CACHE_HOME` for pnpm: the registry's metadata."""
        return self.home / "cache"

    @property
    def state(self) -> Path:
        """`XDG_STATE_HOME` for pnpm."""
        return self.home / "state"


class PyrightLayout(Model):
    """One place keeping pyright's source for the engine's build, a directory per release: the host's cache, a room's image, or the project's rooms' own directory (`lup_dev/pyright_source.py`).

    A release's directory is whole once it holds its mark: a fetch clones beside
    it and moves the clone in, installs its dependencies, and marks it last.
    """

    home: Path

    def release(self, release: str) -> Path:
        """Say where release `release` is kept."""
        return self.home / release

    def installed(self, release: str) -> Path:
        """Say where a release is marked whole, its dependencies installed: a file holding the release, written last."""
        return self.release(release) / ".lup-installed"

    def partial(self, release: str) -> Path:
        """Where a fetch clones release `release` before moving it into place."""
        return self.home / f"{release}.partial"

    def downloads(self, release: str) -> PyrightDownloads:
        """Say where a fetch of release `release` keeps what its package managers download, beside it."""
        return PyrightDownloads(home=self.home / f"{release}.downloads")

    @property
    def lock(self) -> Path:
        """The lock a fetch holds, so two builds fetching at once don't clone over each other."""
        return self.home / ".lup-fetching.lock"


class StoreLayout(Model):
    """Where one worktree's store keeps its parts, under its own directory."""

    home: Path

    @property
    def snapshots(self) -> Path:
        """The bare repository holding the snapshots and the trees lup keeps."""
        return self.home / "snapshots.git"

    @property
    def lock(self) -> Path:
        """The lock a checkpoint holds while it judges and moves the accepted tree."""
        return self.home / "store.lock"

    @property
    def reading(self) -> Path:
        """The index a reader of the worktree as it stands snapshots through, beside the judge's own (`lup_dev.policy.since`)."""
        return self.home / "reading.index"

    @property
    def state(self) -> Path:
        """The worktree's state between checkpoints: commits seen, saved versions."""
        return self.home / "state.json"

    @property
    def calls(self) -> Path:
        """The calls in flight, each with its session, kept under `calls_lock`."""
        return self.home / "running.json"

    @property
    def calls_lock(self) -> Path:
        """The lock guarding `calls`, since hooks for parallel calls run at once."""
        return self.home / "calls.lock"

    @property
    def sessions(self) -> Path:
        """One file per session that ran in this worktree."""
        return self.home / "sessions"

    @property
    def holds(self) -> Path:
        """One file per hold: a change waiting for the operator's answer."""
        return self.home / "holds"

    @property
    def importers(self) -> Path:
        """The importers pass: whether one runs, what's left, what it found."""
        return self.home / "importers.json"

    @property
    def importers_lock(self) -> Path:
        """The lock guarding `importers`."""
        return self.home / "importers.lock"

    @property
    def importers_run(self) -> Path:
        """The lock the running pass holds for its whole life, which the OS frees."""
        return self.home / "importers.run.lock"

    @property
    def importers_log(self) -> Path:
        """What the background pass prints, kept for when it fails."""
        return self.home / "importers.log"

    @property
    def engine_lock(self) -> Path:
        """The lock a client holds while it starts the worktree's engine."""
        return self.home / "engine.lock"

    @property
    def engine_log(self) -> Path:
        """What the worktree's engine prints, kept for when it fails."""
        return self.home / "engine.log"

    def session(self, session: str) -> Path:
        """Say where one session's state is kept."""
        return self.sessions / f"{session}.json"

    def hold(self, hold: str) -> Path:
        """Say where one hold is kept."""
        return self.holds / f"{hold}.json"

    def waiter(self, hold: str) -> Path:
        """Say where the call waiting on hold `hold` holds its lock while it waits, which the OS frees where its process ends."""
        return self.holds / f"{hold}.lock"


class ReviewedLayout(Model):
    """Where one repository's files the operator marked reviewed in their agents' drawers keep the versions marked, by git's id for each (`lup_dev.policy.reviewed`); and where each branch's marks were kept before the review marks' store held them, which an older copy of lup still reads."""

    home: Path

    @property
    def branches(self) -> Path:
        """Where each branch's marks were kept before the review marks' store held them (`MarksLayout`): carried into it once, and kept for an older copy of lup, which reads them still."""
        return self.home / "branches"

    def branch(self, branch: str) -> Path:
        """Say where the marks on branch `branch` were kept, by a digest of its name, which may hold slashes."""
        return self.branches / f"{hashlib.sha256(branch.encode()).hexdigest()}.json"

    def version(self, version: str) -> Path:
        """Say where the content git's id `version` names is kept, as it was marked."""
        return self.home / "versions" / version


class MarksLayout(Model):
    """Where one repository's review marks are kept (`lup_dev.inbox.marks`): one file of each module's, and the lock each is written under."""

    home: Path

    def module(self, module: str) -> Path:
        """Say where module `module`'s marks are kept, one file for all of them."""
        return self.home / f"{module}.json"

    def lock(self, module: str) -> Path:
        """Say where the lock module `module`'s marks are written under is held, so two writers never lose one's mark."""
        return self.home / f"{module}.lock"

    def modules(self) -> list[Path]:
        """List each module's marks kept here, the file of each (`module`), its lock left out."""
        return sorted(self.home.glob("*.json")) if self.home.is_dir() else []


class CheckoutLayout(Model):
    """The places inside a worktree that lup reads or writes."""

    root: Path

    @property
    def pyproject(self) -> Path:
        """The worktree's own project file, which says where its packages are."""
        return self.root / "pyproject.toml"

    @property
    def declaration(self) -> Path:
        """The project's declaration, binding `project`, which nothing points at."""
        return self.root / "lup_project.py"

    @property
    def declaration_package(self) -> Path:
        """The declaration as a package, once the project's own modules outgrow a file.

        Its `__init__.py` binds `project`; a worktree holds one form or the other.
        """
        return self.root / self.declaration.stem

    @property
    def package(self) -> Path:
        """The file that makes `root` a Python package."""
        return self.root / "__init__.py"

    @property
    def home(self) -> Path:
        """Lup's own directory in the worktree, which git ignores."""
        return self.root / ".lup"

    @property
    def saved(self) -> Path:
        """Where refused versions are saved, one numbered directory per refusal."""
        return self.home / "saved"

    @property
    def rules_reference(self) -> Path:
        """The reference to lup's rules, compiled from the engine's table: lup's own."""
        return self.root / "docs" / "rules.md"

    @property
    def local_declaration(self) -> Path:
        """The person's own layer of the declaration, which git ignores.

        Loaded after the project's declaration and layered on top of it, in the
        same grammar (`docs/declaration.md`, *A person's own layer*); trust on
        launch approves it by its content.
        """
        return self.root / f"{self.declaration.stem}.local.py"

    @property
    def local_guidance(self) -> Path:
        """The person's own section of a session's guidance, which git ignores.

        Appended after every section the declaration names, so it holds where they
        differ (`docs/launch.md`, *Guidance*).
        """
        return self.root / "AGENTS.local.md"

    @property
    def lock(self) -> Path:
        """The project's `uv.lock`, which pins the `lup-dev` the host runs for it, and in lup the pyright whose source the engine is built from."""
        return self.root / "uv.lock"

    def saved_copy(self, number: int, path: Path) -> Path:
        """Say where the version refused in refusal `number` is saved, by its path."""
        return self.saved / str(number) / path


class GitDirectoryLayout(Model):
    """What lup keeps in a repository's own git directory: shared by every worktree of it and their rooms, and kept across sessions."""

    common: Path
    """The repository's common git directory."""

    @property
    def passes(self) -> Path:
        """The gate's passes, one file each, named by the files it passed on (`lup_dev.gate`, `Passes`)."""
        return self.common / "lup" / "passes"

    @property
    def gates(self) -> Path:
        """The lock each run of the gate on a commit holds on the worktree it made, by that worktree's name, so a later run tells one left by a run that's gone from one still running (`lup_dev.gate`, `at_commit`)."""
        return self.common / "lup" / "gates"

    @property
    def due(self) -> Path:
        """The deferred work the gate last found due, which a session is told at their start (`codescan.contract.Due`)."""
        return self.common / "lup" / "due.json"

    @property
    def reports(self) -> Path:
        """The judge's reports too long for a hook to tell whole, each kept whole in a file of its own, which the shortened report names (`policy.report.Reports`); in the git directory, so a report spanning several worktrees has one home every room reads."""
        return self.common / "lup" / "reports"


class PackageLayout(Model):
    """One package of a uv workspace, at its directory: what a copy of it is built from."""

    root: Path

    @property
    def pyproject(self) -> Path:
        """Its project file: its name, its dependencies and how it's built."""
        return self.root / "pyproject.toml"

    @property
    def source(self) -> Path:
        """Its modules, under uv's build backend's default module root."""
        return self.root / "src"

    @property
    def engine(self) -> Path:
        """`lup-dev`'s engine's source, which its build bundles into the package.

        The build is `checker/build.py` there; the gate and trust on launch run it
        as the declaration's step that builds a file.
        """
        return self.root / "checker"

    @property
    def page(self) -> Path:
        """The dashboard's page's source, which its build bundles into the package (`docs/dashboard.md`, *The page*)."""
        return self.root / "page"

    @property
    def build(self) -> Path:
        """The script building what a package carries beside its modules: the dashboard's page."""
        return self.root / "build.py"


class LaunchSockets(Model):
    """One launch's socket directory, which its room mounts at `/run/lup`.

    The directory is mounted rather than each socket, since a socket mounted as a
    file stays bound to the old one when the service restarts.
    """

    directory: Path

    @property
    def hook(self) -> Path:
        """The socket the room's hook command sends each payload to."""
        return self.directory / "hook.sock"

    @property
    def mcp(self) -> Path:
        """The socket lup's tools are served on: one MCP session per connection, bridged from the session's stdio server."""
        return self.directory / "mcp.sock"

    @property
    def request(self) -> Path:
        """The socket the room's programs send requests to: one typed request per connection, one reply."""
        return self.directory / "request.sock"

    @property
    def messages(self) -> Path:
        """Where the session's own messaging socket is put, through which the host service starts a turn of an idle session, where their runtime has one."""
        return self.directory / "messages.sock"


class InboxLayout(Model):
    """Where an earlier lup's inbox kept its items and its parties, one JSON file each (`docs/inbox.md`, *Kept on the ledger*).

    The host service converts them onto the ledger the first time it starts on
    one holding no item, and leaves them as they were (`lup_dev.inbox.conversion`);
    no room mounts them.
    """

    home: Path

    @property
    def items(self) -> Path:
        """Each item, a file named by its number."""
        return self.home / "items"

    @property
    def parties(self) -> Path:
        """Each conversation that has spoken, a file named by its key."""
        return self.home / "parties"

    @property
    def diffs(self) -> Path:
        """Each approval's whole diff, a file named by its item's number."""
        return self.home / "diffs"

    @property
    def files(self) -> Path:
        """Each file an approval or a held change touches, whole: all of one item's in a file named by its number."""
        return self.home / "files"

    @property
    def draft(self) -> Path:
        """The operator's draft reply, kept until they send it (`docs/dashboard.md`, *The review*)."""
        return self.home / "draft.json"

    @property
    def order(self) -> Path:
        """Where the dashboard's review lays out its groups, as the operator has seen them, kept for every page and across reloads (`docs/dashboard.md`, *The review*)."""
        return self.home / "order.json"

    @property
    def talks(self) -> Path:
        """What the operator writes on each conversation they read in the dashboard, a file named by its key (`docs/dashboard.md`, *The drawers*)."""
        return self.home / "talks"

    def talk(self, key: str) -> Path:
        """Say where what the operator writes on the conversation keyed `key` is kept."""
        return self.talks / f"{key}.json"

    def item(self, number: int) -> Path:
        """Say where item `number` is kept."""
        return self.items / f"{number}.json"

    def diff(self, number: int) -> Path:
        """Say where approval `number`'s whole diff is kept."""
        return self.diffs / f"{number}.json"

    def changed(self, number: int) -> Path:
        """Say where the files approval or held change `number` touches are kept."""
        return self.files / f"{number}.json"

    def party(self, key: str) -> Path:
        """Say where the conversation keyed `key` is kept."""
        return self.parties / f"{key}.json"


class HostLayout(Model):
    """Where the host service keeps its sockets and the launches it serves, and its log.

    Its sockets and its records of the launches live under lup's runtime directory,
    which a reboot empties as it ends every room; its log lives in lup's state.
    """

    sockets: Path
    state: Path

    @property
    def control(self) -> Path:
        """The control socket, on the host only, taking typed requests."""
        return self.sockets / "control.sock"

    @property
    def watch(self) -> Path:
        """The watch socket, on the host only: each connection one control request, answered again each time its reply changes (`host/watch.py`)."""
        return self.sockets / "watch.sock"

    @property
    def lock(self) -> Path:
        """The lock the running service holds for its whole life, which the OS frees."""
        return self.sockets / "service.lock"

    @property
    def launches(self) -> Path:
        """Each launch served: its socket directory, and its record beside it."""
        return self.sockets / "launches"

    @property
    def log(self) -> Path:
        """What a service started in the background prints, kept for when it fails."""
        return self.state / "service.log"

    @property
    def names(self) -> Path:
        """The name each session last had, by the runtime's id for them, kept in lup's state so a session resumed in a later launch takes it back."""
        return self.state / "session-names.json"

    def home_of(self, runtime: str, session: str) -> Path:
        """Say where the home a launched session of `runtime` keeps their record in is kept, by the runtime's id for the session: written once, from the launch the service first heard the session from, so a room naming another's session later can't move it (`lup_dev.launch.homes.kept`)."""
        return self.state / "homes" / runtime / session

    @property
    def dashboard_token(self) -> Path:
        """The token the dashboard's API wants (`host/dashboard.py`), kept in lup's state, which no room mounts, so a page left open outlasts a restart."""
        return self.state / "dashboard.token"

    @property
    def timings(self) -> Path:
        """What pages measured of themselves in the operator's browser, the dashboard's among them (`host/timings.py`): a directory per page, kept 14 days in lup's state, which `host-copy` never copies."""
        return self.state / "timings"

    def launch(self, launch: str) -> LaunchSockets:
        """Say where launch `launch`'s sockets are."""
        return LaunchSockets(directory=self.launches / launch)

    def ended(self, payload: str) -> Path:
        """Say where the service marks a hook its runtime ended before its answer, by its payload's digest, for a hold its call waits on to give up (`hung_up`, `host/service.py`)."""
        return self.sockets / "ended" / hashlib.sha256(payload.encode()).hexdigest()

    def record(self, launch: str) -> Path:
        """Say where launch `launch` is recorded, so a restarted service serves it."""
        return self.launches / f"{launch}.json"

    def conversations(self, launch: str) -> Path:
        """Say where launch `launch`'s conversations are kept, their names, their parents and the spawns not yet linked, so a restarted service knows them."""
        return self.launches / f"{launch}.conversations.json"

    @property
    def processes(self) -> Path:
        """Where each repository's processes answer, outside every directory a room mounts."""
        return self.sockets / "processes"

    def process(self, process: str) -> Path:
        """Say where process `process` of a repository's answers, its judge and its modules: a socket for each process, so one ending removes no other's, named by the process alone, so its path stays short enough for a socket's."""
        return self.processes / f"{process}.sock"


class JudgeLayout(Model):
    """One repository's approved copies of `lup-dev`, which judge its launches' hooks.

    Trust on launch installs each copy the operator approves in a directory of
    its own (`CopyLayout`), never over one a process runs, and `bin` names the
    one that judges: a link to its commands, switched to the next in one rename
    (`lup_dev/copies.py`). Each repository's are its own, so a second
    project's approval doesn't replace the first's (`docs/trust.md`).
    """

    home: Path

    @property
    def copies(self) -> Path:
        """Each copy installed, a directory of its own."""
        return self.home / "copies"

    def named(self, name: str) -> CopyLayout:
        """Say where the copy named `name` is installed."""
        return CopyLayout(home=self.copies / name)

    @property
    def bin(self) -> Path:
        """The link to the commands of the copy that judges."""
        return self.home / "bin"

    def command(self, name: str) -> Path:
        """Say where the command `name` of the copy that judges is found, through the link: `lup-dev`, by its package's name."""
        return self.bin / name

    @property
    def lock(self) -> Path:
        """Held while a copy is installed and switched to, and while the copies to remove are chosen."""
        return self.home / "install.lock"

    @property
    def in_place(self) -> Path:
        """The environment of a copy installed at the repository's home itself rather than in a directory of its own, which goes once the link names another and no process runs it."""
        return self.home / "tools"


class CopyLayout(Model):
    """One copy of `lup-dev` approved for a repository, installed as a uv tool of its own (`UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`)."""

    home: Path

    @property
    def tools(self) -> Path:
        """Where uv keeps the copy's environment."""
        return self.home / "tools"

    @property
    def bin(self) -> Path:
        """Where uv puts the copy's commands."""
        return self.home / "bin"

    def command(self, name: str) -> Path:
        """Say where the copy's command `name` is: `lup-dev`, by its package's name."""
        return self.bin / name


class LaunchLayout(Model):
    """One launch's own places in lup's state: what's compiled for it, and its launcher's lock."""

    directory: Path
    """lup's settings and guidance compiled for the launch, mounted read-only into
    its room; removed when the launch ends."""

    @property
    def lock(self) -> Path:
        """The lock its launcher holds for its whole life, which the OS frees.

        A launch whose lock can be taken has no launcher left, so a later launch
        may end it once its container is gone too.
        """
        return self.directory.with_name(f"{self.directory.name}.lock")

    @property
    def gitconfig(self) -> Path:
        """The room's git configuration, in place of the operator's (`GIT_CONFIG_GLOBAL`), mounted read-only."""
        return self.directory / "gitconfig"

    @property
    def bin(self) -> Path:
        """The commands lup gives the room, first on its `PATH`, mounted read-only."""
        return self.directory / "bin"

    @property
    def helper(self) -> Path:
        """The remote helper git runs for a `lup::` URL, found on the `PATH` by its name."""
        return self.bin / "git-remote-lup"

    @property
    def pasting(self) -> Path:
        """`wl-paste`, the room's way to read the operator's clipboard through the host (`clipboard/shim.py`)."""
        return self.bin / "wl-paste"

    @property
    def copying(self) -> Path:
        """`wl-copy`, the room's way to write the operator's clipboard through the host, the same program as `pasting`."""
        return self.bin / "wl-copy"

    @property
    def wrapper(self) -> Path:
        """`lup-environment`, which tells the runner's tools the environment of the worktree each runs in, under each of their names, and makes the launch's worktree's before the CLI starts (`lup_dev/environments.py`)."""
        return self.bin / STARTER

    def wrapping(self, program: str) -> Path:
        """Say where the runner's program `program` is wrapped among the room's commands: a link to `wrapper`."""
        return self.bin / program

    @property
    def empty_directory(self) -> Path:
        """An empty directory of the launch's own, mounted read-only over each directory hidden from the room."""
        return self.directory / "hidden" / "directory"

    @property
    def empty_file(self) -> Path:
        """An empty file of the launch's own, mounted read-only over each file hidden from the room."""
        return self.directory / "hidden" / "file"

    @property
    def home(self) -> Path:
        """What the launch puts in its room's home, each file at its path there, mounted read-only: the package managers' user-level settings."""
        return self.directory / "home"

    @property
    def runtime_home(self) -> Path:
        """The runtime's own directory for the launch, which its variable names, inside the launch's directory, mounted read-write at its path: its configuration, settings and state, gone with the launch, and links into the history its rooms share (`docs/launch.md`, *A home of the rooms' own*)."""
        return self.directory / "runtime-home"

    @property
    def room_home(self) -> Path:
        """The room's home itself, mounted read-write at the operator's home path, so what the room writes there is on disk (`Room.home_source`): beside the launch's directory, which the room mounts, rather than in it; removed when the launch ends (`vacated`)."""
        return self.directory.with_name(f"{self.directory.name}.home")

    @property
    def lent(self) -> Path:
        """Where what the operator lends the room while it runs is mounted, each directory by its name: a shared mount in podman's namespace, which the room mounts at `RoomPaths.lent` and receives mounts through; removed when the launch ends."""
        return self.directory.with_name(f"{self.directory.name}.lent")

    @property
    def stage(self) -> Path:
        """Where a directory lent read-only is made so before it's mounted in `lent`: a private mount in podman's namespace; removed when the launch ends."""
        return self.directory.with_name(f"{self.directory.name}.stage")


class RoomsLayout(Model):
    """One repository's rooms' own directory, outside the repository, which each of its rooms mounts read-write at its host path: their package cache, and each launch's environments.

    One directory, so an environment's files are links into the cache: no hard
    link crosses two mounts (`docs/field-notes.md`, *uv's environments across a
    room's mounts*). One per repository, so one project's room can't write what
    another's installs from.
    """

    home: Path

    @property
    def cache(self) -> Path:
        """The runner's package cache, which the repository's rooms share."""
        return self.home / "cache"

    @property
    def environments(self) -> Path:
        """Each launch's environments, a directory each, named by the launch."""
        return self.home / "environments"

    def launch(self, launch: str) -> Path:
        """Say where launch `launch`'s environments are, one per worktree, each placed by `lup_dev.environments.environment`; removed when it ends."""
        return self.environments / launch

    @property
    def pyright(self) -> PyrightLayout:
        """Where the engine's build in a room fetches pyright's source at a release the room's image doesn't carry, once for the project's rooms; never read on the host."""
        return PyrightLayout(home=self.home / "pyright")


class HomesLayout(Model):
    """The rooms' own homes for each runtime, in place of the operator's own directories: each project's, and the one shared by every project whose profile chooses it (`docs/launch.md`, *A home of the rooms' own*).

    A runtime's rooms share their history in one, which each mounts read-write
    at its path, the runtime's own directory for the launch linking into it
    (`LaunchLayout.runtime_home`). Each sits apart from every directory a room
    writes, the project's rooms' own directory among them, and only the home
    itself is mounted: a mount point can't be moved from inside a room, but a
    directory above one can, and the host follows a link in a mount's source.
    Under the rooms' directory, a running room could move the directory
    holding a home aside and leave a link to the operator's own runtime
    directory in its place, which the next launch would mount read-write.
    """

    home: Path

    def project(self, repository: Path, runtime: str) -> Path:
        """Say where the rooms of the repository whose git directory is `repository` keep runtime `runtime`'s home: shared by its worktrees and its profiles, by the adapter's name for the runtime."""
        return self.home / "projects" / digest(repository) / runtime

    def shared(self, runtime: str) -> Path:
        """Say where runtime `runtime`'s home every project shares is, for a profile choosing one home across projects."""
        return self.home / "shared" / runtime


class ToldLayout(Model):
    """What a launch told the operator once, so a later launch doesn't tell it again: each account's login seen to change, what was last left out of each profile's configuration, each repository's records moved from the operator's own directories, and how to replace their host login."""

    home: Path

    def login(self, account: str, runtime: str) -> Path:
        """Say where it's marked that the operator was told what a change of account `account`'s login for runtime `runtime` means."""
        return self.home / "logins" / account / runtime

    def migrated(self, repository: Path, runtime: str) -> Path:
        """Say where it's marked that runtime `runtime`'s records of the repository whose git directory is `repository` were moved from the operator's own directory, so a launch doesn't offer to move what a host session writes there since."""
        return self.home / "migrated" / digest(repository) / runtime

    def host_login(self, runtime: str) -> Path:
        """Say where it's marked that a launch told the operator how to replace their own login for runtime `runtime`, which every room could read before rooms had homes of their own."""
        return self.home / "host-logins" / runtime

    def left_out(self, profile: str, runtime: str) -> Path:
        """Say where what was last left out of profile `profile`'s configuration for runtime `runtime` is kept."""
        return self.home / "left-out" / profile / f"{runtime}.json"


class AccountLayout(Model):
    """One account's logins, a directory per runtime, each holding the file its runtime's sign-in writes (`docs/launch.md`, *Accounts and profiles*).

    Kept by the account's name, never by a project's, so every room on the
    account shares one login: a sign-in in one is every room's. A runtime's
    directory is named by its adapter's name for it, and the file inside is
    the adapter's to name.
    """

    home: Path

    def runtime(self, runtime: str) -> Path:
        """Say where the account keeps runtime `runtime`'s login, by its adapter's name for it."""
        return self.home / runtime


class AccountsLayout(Model):
    """Every account's logins, a directory each, under lup's data."""

    home: Path

    def account(self, name: str) -> AccountLayout:
        """Say where the account `name` keeps its logins."""
        return AccountLayout(home=self.home / name)


class ProfileLayout(Model):
    """One profile's own runtime configuration, a directory per runtime, layered over the operator's own."""

    home: Path

    def runtime(self, runtime: str) -> Path:
        """Say where the profile keeps runtime `runtime`'s configuration, by its adapter's name for it."""
        return self.home / runtime


class ProfilesLayout(Model):
    """The person's profiles: the file declaring them, and each one's own runtime configuration."""

    home: Path

    @property
    def declared(self) -> Path:
        """The file declaring them, in the declaration's grammar, which trust on launch approves by its content."""
        return self.home / "profiles.py"

    def profile(self, name: str) -> ProfileLayout:
        """Say where the profile `name` keeps its own runtime configuration."""
        return ProfileLayout(home=self.home / "profiles" / name)


class CliCacheLayout(Model):
    """Where one runtime's CLIs are cached, a directory per version (`docs/launch.md`, *The CLIs*).

    A version's directory holds what its release channel published, checked: the
    binary, or the package it ships in. A download is staged beside the versions
    and moved among them once checked, so a version's directory is only ever whole.
    """

    home: Path

    @property
    def versions(self) -> Path:
        """Each version kept, in a directory named by the version."""
        return self.home / "versions"

    @property
    def staging(self) -> Path:
        """Where a download waits until it's checked."""
        return self.home / "staging"

    @property
    def lock(self) -> Path:
        """The lock a launch holds while it updates the cache, so two launches download once."""
        return self.home / "cache.lock"

    def version(self, version: str) -> Path:
        """Say where version `version` is kept."""
        return self.versions / version


class Layout(Model):
    """Where lup's state lives for one user: `$XDG_STATE_HOME/lup`, its sockets and its cache."""

    state: Path
    runtime: Path = Path(tempfile.gettempdir()) / f"lup-{getpass.getuser()}"
    """lup's sockets: `$XDG_RUNTIME_DIR/lup`, or the user's own temporary directory."""
    cache: Path = Path.home() / ".cache" / "lup"
    """lup's cache, what can be fetched again: `$XDG_CACHE_HOME/lup`, or `~/.cache/lup`."""
    data: Path = Path.home() / ".local" / "share" / "lup"
    """lup's data, the copies of `lup-dev` it installs among it: `$XDG_DATA_HOME/lup`,
    or `~/.local/share/lup`."""
    config: Path = Path.home() / ".config" / "lup"
    """The person's own configuration, their profiles among it: `$XDG_CONFIG_HOME/lup`,
    or `~/.config/lup`."""

    @classmethod
    def of(cls, settings: LupDevSettings) -> Layout:
        """Place lup's state, sockets, cache, data and the person's configuration where the settings say, or XDG's defaults."""
        home = settings.xdg_state_home or Path.home() / ".local" / "state"
        cache = (settings.xdg_cache_home or Path.home() / ".cache") / "lup"
        data = (settings.xdg_data_home or Path.home() / ".local" / "share") / "lup"
        config = (settings.xdg_config_home or Path.home() / ".config") / "lup"
        if settings.xdg_runtime_dir is None:
            return cls(state=home / "lup", cache=cache, data=data, config=config)
        return cls(
            state=home / "lup",
            runtime=settings.xdg_runtime_dir / "lup",
            cache=cache,
            data=data,
            config=config,
        )

    @property
    def accounts(self) -> AccountsLayout:
        """Where every account keeps its logins: `~/.local/share/lup/accounts/<name>/`."""
        return AccountsLayout(home=self.data / "accounts")

    @property
    def told(self) -> ToldLayout:
        """What a launch told the operator once, in lup's state."""
        return ToldLayout(home=self.state / "told")

    @property
    def homes(self) -> HomesLayout:
        """Where the rooms keep each runtime's history and state: `~/.local/share/lup/homes/`."""
        return HomesLayout(home=self.data / "homes")

    @property
    def written(self) -> list[Path]:
        """The directories of lup's data rooms write: every project's rooms' own directory, under `rooms/`, and the rooms' homes."""
        return [self.data / "rooms", self.homes.home]

    def room_home(self, repository: Path, runtime: str, *, shared: bool) -> Path:
        """Say where a launch in the repository whose git directory is `repository` keeps runtime `runtime`'s history and state: the one rule placing a room's home, which the launch mounts and the host reads a launched session's record from.

        The project's own home, or, `shared`, the one every project shares,
        as the launch's profile chooses (`Profile.rooms_home`).
        """
        if shared:
            return self.homes.shared(runtime)
        return self.homes.project(repository, runtime)

    @property
    def profiles(self) -> ProfilesLayout:
        """Where the person's profiles are declared and keep their own runtime configuration: `~/.config/lup/`."""
        return ProfilesLayout(home=self.config)

    @property
    def pyright_source(self) -> PyrightLayout:
        """The host's own copies of pyright's source, which the engine's builds there fetch and build from: trust on launch's, and the operator's own.

        The host's alone: no room mounts it, since what a room wrote there would
        be bundled into the host's engine at the next approval. A room reads its
        image's, and its project's rooms' (`RoomsLayout.pyright`).
        """
        return PyrightLayout(home=self.cache / "pyright")

    @property
    def builds(self) -> Path:
        """Each room image built: one JSON line each, with its duration and size."""
        return self.state / "rooms" / "builds.jsonl"

    def engine_socket(self, worktree: Path) -> Path:
        """Say where the engine of the worktree at `worktree` listens."""
        return self.runtime / f"{short_digest(worktree)}.sock"

    def clis(self, runtime: str) -> CliCacheLayout:
        """Say where the CLIs of a runtime are cached, by the name its adapter gives it."""
        return CliCacheLayout(home=self.cache / "clis" / runtime)

    @property
    def host(self) -> HostLayout:
        """Where the host service, one per user, keeps its sockets, records and log."""
        return HostLayout(sockets=self.runtime / "host", state=self.state / "host")

    @property
    def inbox(self) -> InboxLayout:
        """Where an earlier lup's inbox kept its items and its parties, one per user, which the host service converts onto the ledger once."""
        return InboxLayout(home=self.state / "inbox")

    def module_data(self, module: str, repository: Path) -> Path:
        """Say where module `module` keeps its own data for the repository whose git directory is `repository`."""
        return self.data / "modules" / module / digest(repository)

    def rooms(self, repository: Path) -> RoomsLayout:
        """Say where the rooms of the repository whose git directory is `repository` keep their package cache and their environments."""
        return RoomsLayout(home=self.data / "rooms" / digest(repository))

    @property
    def judges(self) -> Path:
        """Every repository's approved copies of `lup-dev`, a directory each."""
        return self.data / "judges"

    def judge(self, repository: Path) -> JudgeLayout:
        """Say where a repository's approved copies of `lup-dev` are installed, by its git directory."""
        return JudgeLayout(home=self.judges / digest(repository))

    @property
    def launches(self) -> Path:
        """Each launch's own places: its compiled settings, and its launcher's lock."""
        return self.state / "launches"

    def launch(self, launch: str) -> LaunchLayout:
        """Say where launch `launch`'s own places are."""
        return LaunchLayout(directory=self.launches / launch)

    @property
    def worktrees(self) -> Path:
        """Every worktree's store, one directory each."""
        return self.state / "worktrees"

    @property
    def session_index(self) -> Path:
        """Each session's repository and the worktrees they hold, by session id."""
        return self.state / "session-index"

    def store(self, worktree: Path) -> StoreLayout:
        """Say where the store of the worktree at `worktree` lives."""
        return StoreLayout(home=self.worktrees / digest(worktree))

    @property
    def repositories(self) -> Path:
        """What lup keeps about each repository, a directory each, named by its git directory's digest."""
        return self.state / "repositories"

    def repository(self, repository: Path) -> Path:
        """Say where what lup keeps about a repository lives, by its git directory."""
        return self.repositories / digest(repository)

    def verdicts(self, repository: Path) -> Path:
        """Say where the verdict log of a repository lives, by its git directory."""
        return self.repository(repository) / "verdicts.jsonl"

    def reviewed(self, repository: Path) -> ReviewedLayout:
        """Say where the versions of a repository's files the operator marked reviewed are kept, by its git directory."""
        return ReviewedLayout(home=self.repository(repository) / "reviewed")

    def marks(self, repository: Path) -> MarksLayout:
        """Say where a repository's review marks are kept, by its git directory."""
        return self.marks_in(self.repository(repository))

    def marks_in(self, kept: Path) -> MarksLayout:
        """Say where the review marks of the repository whose directory of lup's is `kept` (`repository`) are kept."""
        return MarksLayout(home=kept / "marks")

    def every_marks(self) -> list[MarksLayout]:
        """Return where each repository lup keeps something of keeps its review marks, by the directory of lup's each has (`repositories`)."""
        kept = self.repositories
        found = (
            sorted(each for each in kept.iterdir() if each.is_dir())
            if kept.is_dir()
            else []
        )
        return [self.marks_in(each) for each in found]

    def heads(self, repository: Path) -> Path:
        """Say where each worktree's `HEAD` at its last checkpoint is kept."""
        return self.repository(repository) / "heads.json"

    def declaration(self, repository: Path) -> Path:
        """Say where the last of a repository's declarations that loaded is kept.

        It's kept resolved, as the values judging reads.
        """
        return self.repository(repository) / "last-declaration.json"

    def exported(self, repository: Path, commit: str, local: str | None = None) -> Path:
        """Say where a commit's modules are exported, to import its declaration.

        With `local`, the person's own layer approved with it, which the export
        holds beside the declaration: one export for each copy of it.
        """
        exports = self.repository(repository) / "declarations"
        if local is None:
            return exports / commit
        return exports / f"{commit}-{hashlib.sha256(local.encode()).hexdigest()}"

    def session(self, session: str) -> Path:
        """Say where a session's repository and the worktrees they hold are kept."""
        return self.session_index / f"{session}.json"

    def warned(self, session: str) -> Path:
        """Say where the failures a session's operator was warned of are kept."""
        return self.session_index / f"{session}.warned.json"

    def conversations(self, session: str) -> Path:
        """Say where a session's subagents at work, and their last block, are kept."""
        return self.session_index / f"{session}.conversations.json"

    def approved(self, repository: Path) -> Path:
        """Say where a repository's host zone the operator approved last is kept.

        The commit approved, the zone's fingerprint there, its paths and the
        `lup-dev` it runs (`docs/trust.md`).
        """
        return self.repository(repository) / "approved.json"
