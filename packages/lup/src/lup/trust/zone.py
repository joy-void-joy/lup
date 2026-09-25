"""The host zone: every path of a checkout whose content a launch may run on the host.

Launching reads the checkout before any container exists: ``uv`` syncs an
environment from its manifest and lockfile, and the project's own package is
imported to generate the trees a session opens against. Everything a session
changed by any route -- an edit, a commit that lands at the next checkout, a
sibling worktree sharing the repository -- reaches the host that way. So the
launcher fingerprints what it is about to run before running any of it.

**What the zone is.** Every path the checkout's index tracks, minus the free
zones the operator approved, plus the machine registry (``sync.json.local``),
which is gitignored and still decides the next session's mounts, devices,
network and posture. Content is the working tree's bytes, because the working
tree is what the launch reads: a symbolic link is its target text, an
executable file keeps its bit, a submodule is the commit the index records,
and a tracked path missing from disk is simply absent.

**What the zone is not: untracked files.** A file nothing tracks is not
reviewed, and that is safe for a reason stated elsewhere and worth restating
here, because it is the premise the choice rests on. The launch does not run
from the checkout. It runs from an export of exactly this zone
(:mod:`lup.trust.handoff`), so an untracked file -- a planted ``sitecustomize``,
a poisoned ``__pycache__``, a stray module beside the package -- is not there
to be imported. Counting untracked files would buy nothing the export does not
already guarantee, and would turn every scratch file a session leaves outside
a free zone into a question at the next launch, which is how an operator
learns to approve without reading.

**How the checkout is read.** Through ``git``, because which paths are tracked
is the index's answer, and with every lever that could make that ``git`` run
something disarmed: no fsmonitor, no hooks, no pager, no optional locks, and
none of the caller's ``GIT_*`` variables. Content is never hashed by ``git``
-- it is read from disk and hashed here, into the launcher's own store
(:mod:`lup.trust.objects`), so no filter or attribute in the checkout is ever
consulted.
"""

import hashlib
import os
import stat
import tomllib
from collections.abc import Iterable, Sequence
from itertools import groupby
from pathlib import Path, PurePosixPath

import sh
from pydantic import BaseModel, field_validator

from lup.trust.approved import MACHINE_REGISTRY
from lup.trust.objects import EntryMode, ObjectStore, TreeEntry, parsed_tree, tree_data
from lup.types import EnvVars

# lup: ignore[library-default] — each word disarms one way a `git` reading a
# session-writable repository could start a program on the host
HARDENED_GIT = [
    "--no-pager",
    "--no-optional-locks",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.pager=cat",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "diff.external=",
    "-c",
    "credential.helper=",
    "-c",
    "protocol.allow=never",
]
"""What every ``git`` the launcher runs against a live checkout is started with.

The checkout's configuration is the one file a session must not be able to
turn into a program on the host, and it is also the file ``git`` reads first.
Its own mount is read-only inside the container, but a renamed ``.git`` or a
planted ``commondir`` is a configuration the lease never saw, so the reader
disarms every key that names a program for the plumbing it runs rather than
trusting what it finds. Command-line configuration outranks every file.
"""


class TrustError(Exception):
    """A launch that cannot establish what it would run, said in the operator's terms."""


class FreeZones(BaseModel, frozen=True):
    """The paths a session may change without a question, as a checkout declares them.

    Declared in ``pyproject.toml`` under ``[tool.lup.trust]``, because the
    launcher needs them before any of the checkout's code may run, and that
    file is data it can parse without executing anything. What a launch
    *uses* is never read from here directly: it is the list the operator last
    approved, kept in the launcher's own record, so widening the free zones is
    itself a change somebody reviews.
    """

    free: list[PurePosixPath] = []

    @field_validator("free")
    @classmethod
    def inside_the_checkout(cls, value: list[PurePosixPath]) -> list[PurePosixPath]:
        """Refuse a zone that would free the whole checkout or reach outside it."""
        for zone in value:
            if zone.is_absolute() or ".." in zone.parts or zone == PurePosixPath("."):
                raise ValueError(
                    f"free zone {zone.as_posix()!r} must name a path inside the "
                    "checkout, relative to its root"
                )
        return sorted(dict.fromkeys(value))

    def frees(self, path: PurePosixPath) -> bool:
        """Whether this path lies in a free zone."""
        return any(zone == path or zone in path.parents for zone in self.free)

    def spelled(self) -> list[str]:
        """The zones as a reader writes them, a directory with its trailing slash."""
        return [f"{zone.as_posix()}/" for zone in self.free]


def declared_free_zones(manifest: bytes) -> FreeZones:
    """The free zones one ``pyproject.toml``'s bytes declare, none where it declares none.

    Read from bytes rather than a path so the caller decides which copy is
    meant: the one in the snapshot being approved, never a second read of a
    file that may have changed since it was hashed.
    """
    try:
        table = tomllib.loads(manifest.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise TrustError(f"pyproject.toml does not parse: {error}") from error
    tool = table["tool"] if "tool" in table else {}
    lup = tool["lup"] if isinstance(tool, dict) and "lup" in tool else {}
    trust = lup["trust"] if isinstance(lup, dict) and "trust" in lup else {}
    return FreeZones.model_validate(trust if isinstance(trust, dict) else {})


class ZoneEntry(BaseModel, frozen=True):
    """One path of the host zone, and the object its content hashed to."""

    path: PurePosixPath
    mode: EntryMode
    oid: str


class HostZone(BaseModel, frozen=True):
    """One reading of a checkout's host zone, stored as a git tree."""

    tree: str
    entries: list[ZoneEntry]

    def at(self, path: PurePosixPath) -> ZoneEntry | None:
        """The entry at one path, or ``None`` where the zone holds nothing there."""
        return next((entry for entry in self.entries if entry.path == path), None)

    def without(self, zones: FreeZones, store: ObjectStore) -> "HostZone":
        """This zone with every path the given free zones cover taken out, stored."""
        return zone_of(
            [entry for entry in self.entries if not zones.frees(entry.path)], store
        )


class IndexEntry(BaseModel, frozen=True):
    """One path the index tracks, with what the index records for it."""

    path: PurePosixPath
    mode: str
    oid: str


def git_environment(inherited: EnvVars) -> EnvVars:
    """The environment a hardened ``git`` runs under: the caller's, minus git's own.

    A ``GIT_DIR`` or ``GIT_CONFIG_PARAMETERS`` the operator happened to have
    exported would aim the reader at another repository or hand it keys it
    was not meant to read, so every ``GIT_*`` variable is dropped and the two
    this reader wants are set.
    """
    return {
        **{
            name: value
            for name, value in inherited.items()
            if not name.startswith("GIT_")
        },
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }


class LiveCheckout(BaseModel, frozen=True):
    """A checkout on disk, read the way the launcher is allowed to read one."""

    root: Path
    common: Path
    environment: EnvVars

    @classmethod
    def at(cls, start: Path, inherited: EnvVars) -> "LiveCheckout":
        """The checkout enclosing ``start``, with its shared git directory resolved."""
        environment = git_environment(inherited)

        def asked(*question: str) -> Path:
            spoken = hardened_git(start, environment, "rev-parse", *question)
            return Path(os.fsdecode(spoken.removesuffix(b"\n")))

        try:
            root = asked("--show-toplevel")
            common = asked("--path-format=absolute", "--git-common-dir")
        except sh.CommandNotFound as error:
            raise TrustError(
                "git is not installed here, and the host zone is what git tracks"
            ) from error
        except sh.ErrorReturnCode as error:
            raise TrustError(
                f"{start} is not inside a git checkout, so there is no host zone "
                f"to review: {error.stderr.decode('utf-8', 'replace').strip()}"
            ) from error
        return cls(
            root=root.resolve(), common=common.resolve(), environment=environment
        )

    def tracked(self) -> list[IndexEntry]:
        """Every path the index tracks, once each, with its recorded mode and object.

        A path mid-merge appears at several stages; the working tree is what
        is hashed either way, so the first record for a path is enough.
        """
        listed = hardened_git(self.root, self.environment, "ls-files", "-z", "--stage")
        entries = [
            index_entry(record)
            # lup: ignore[string-split] — git's own `-z` listing, one record per
            # NUL by that format's definition
            for record in listed.split(b"\0")
            if record
        ]
        return list({entry.path: entry for entry in reversed(entries)}.values())

    def name(self) -> str:
        """What to call this repository in a listing: its shared directory's name."""
        return (
            self.common.parent.name
            if self.common.name == ".git"
            else self.common.name.removesuffix(".git")
        )

    def identity(self) -> str:
        """Where this repository's trust is recorded: its name and its shared directory's digest.

        Per repository rather than per worktree, because sibling worktrees
        share one object store and one set of branches, and an approval of a
        tree is an approval of that content wherever it is checked out.
        """
        digest = hashlib.sha256(str(self.common).encode("utf-8")).hexdigest()
        return f"{self.name()}-{digest}"


def hardened_git(where: Path, environment: EnvVars, *arguments: str) -> bytes:
    """Run one ``git`` against a checkout with every program-naming lever disarmed."""
    ran = sh.Command("git")(
        *HARDENED_GIT,
        "-C",
        str(where),
        *arguments,
        _env=environment,
        _tty_out=False,
        _return_cmd=True,
    )
    return ran.stdout


def index_entry(record: bytes) -> IndexEntry:
    """One ``ls-files --stage -z`` record: ``<mode> <object> <stage>\\t<path>``."""
    # lup: ignore[string-split] — the stage record's fields, separated by the
    # one tab and the single spaces that format defines
    header, tab, path = record.partition(b"\t")
    fields = header.split()
    if not tab or len(fields) != 3:
        raise TrustError(f"git listed an index record it does not parse: {record!r}")
    mode, oid, _stage = fields
    return IndexEntry(
        path=PurePosixPath(os.fsdecode(path)),
        mode=mode.decode("ascii"),
        oid=oid.decode("ascii"),
    )


def working_entry(
    root: Path, path: PurePosixPath, index: IndexEntry | None, store: ObjectStore
) -> ZoneEntry | None:
    """What one path holds on disk, stored, or ``None`` where it holds nothing.

    A submodule is the commit the index records, because its content is
    another repository's and hashing a directory would describe neither. A
    tracked path that is now a directory, a socket or nothing at all is absent
    from the zone, which the review shows as the removal it is.
    """
    if index is not None and index.mode == "160000":
        return ZoneEntry(path=path, mode="160000", oid=index.oid)
    located = root / path
    try:
        described = located.lstat()
    except FileNotFoundError:
        return None
    match stat.S_IFMT(described.st_mode):
        case stat.S_IFLNK:
            target = os.fsencode(located.readlink())
            return ZoneEntry(path=path, mode="120000", oid=store.write("blob", target))
        case stat.S_IFREG:
            executable = described.st_mode & stat.S_IXUSR
            return ZoneEntry(
                path=path,
                mode="100755" if executable else "100644",
                oid=store.write("blob", located.read_bytes()),
            )
        case _:
            return None


def written_tree(entries: Sequence[ZoneEntry], depth: int, store: ObjectStore) -> str:
    """Store the tree for entries sharing their first ``depth`` path parts.

    Grouped by the part at ``depth``: a group whose only member ends there is
    a file, anything longer is a directory written first, bottom up, which is
    the only order git's ids can be computed in.
    """

    def part(entry: ZoneEntry) -> str:
        return entry.path.parts[depth]

    listed = [
        (
            TreeEntry(name=os.fsencode(name), mode=members[0].mode, oid=members[0].oid)
            if len(members) == 1 and len(members[0].path.parts) == depth + 1
            else TreeEntry(
                name=os.fsencode(name),
                mode="40000",
                oid=written_tree(members, depth + 1, store),
            )
        )
        for name, grouped in groupby(sorted(entries, key=part), key=part)
        for members in [list(grouped)]
    ]
    return store.write("tree", tree_data(listed))


def zone_of(entries: Iterable[ZoneEntry], store: ObjectStore) -> HostZone:
    """A zone over these entries, its tree stored."""
    ordered = sorted(entries, key=lambda entry: entry.path.parts)
    return HostZone(tree=written_tree(ordered, 0, store), entries=ordered)


def host_zone(
    checkout: LiveCheckout,
    store: ObjectStore,
    free: FreeZones,
    untracked: Sequence[PurePosixPath] = (MACHINE_REGISTRY,),
) -> HostZone:
    """Read the checkout's host zone into the store, and name the tree it hashed to.

    ``untracked`` are the paths reviewed although nothing tracks them: the
    machine registry, which a session can rewrite and which decides the next
    launch's boundary. Each is taken only where it is a file at that path.
    """
    listed = {entry.path: entry for entry in checkout.tracked()}
    extra = [path for path in untracked if path not in listed]
    paths = [path for path in [*listed, *extra] if not free.frees(path)]
    read = [
        entry
        for path in paths
        if (entry := working_entry(checkout.root, path, listed.get(path), store))
        is not None
    ]
    return zone_of(read, store)


def snapshot(store: ObjectStore, tree: str) -> HostZone:
    """Read a stored tree back into its entries, verifying every object on the way.

    Raises :class:`~lup.trust.objects.ObjectUnreadable` where any tree the
    snapshot names is missing or corrupt; the blobs are verified when their
    content is read.
    """

    def walked(oid: str, prefix: PurePosixPath) -> list[ZoneEntry]:
        return [
            found
            for entry in parsed_tree(store.read(oid, "tree"))
            for found in (
                walked(entry.oid, prefix / os.fsdecode(entry.name))
                if entry.mode == "40000"
                else [
                    ZoneEntry(
                        path=prefix / os.fsdecode(entry.name),
                        mode=entry.mode,
                        oid=entry.oid,
                    )
                ]
            )
        ]

    return HostZone(tree=tree, entries=walked(tree, PurePosixPath()))
