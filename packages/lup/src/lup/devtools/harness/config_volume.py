"""A contained session's configuration home: one volume per repository and runtime.

Per repository, because every worktree of one repository shares the login,
the trust and the transcripts a ``--continue`` reopens, and keyed on the
shared git directory, the only name all of them agree on. Per runtime,
because a home both CLIs wrote into was a home each could read the other's
transcripts and credentials out of, holding both vendors' files mixed
together (``lup-claude-<repo>``, ``lup-codex-<repo>``). And not per person:
a volume every repository shared would be one repository's session reading
another's transcripts and writing settings every other project then applies.

Settings do not live here as decisions. A launch seeds them at every start
and carries a session's personal changes back to the host when it closes
(:mod:`lup.providers.claude.home_seed`), so what a volume holds is state:
the login, the trust, the history, the transcripts.

Before the split one volume served both runtimes (``lup-cfg-<repo>``), and
before that one per worktree (``lup-cfg-<worktree>``); Codex had one more per
digest of its settings (``lup-cfg-<repo>-codex-<digest>``). The first launch
that finds any of them moves what they hold into the split volumes once, by
what each runtime declares it keeps, and removes them.
"""

import io
import tarfile
from fnmatch import fnmatch
from pathlib import Path

import sh
from pydantic import BaseModel

from lup.harness.assets.home_seed import (
    RECORD,
    SeedFile,
    merged_names,
    read_tree,
    settle,
    text_of,
    write,
)
from lup.harness.image import ContainerEngine
from lup.harness.notice import Notice
from lup.providers.login import ProviderLogin
from lup.sandbox.rail import repository_layout, sibling_worktrees

# lup: ignore[constant-declaration] — where a split reads the old volume from
# inside its helper container, a path no image holds and nothing else mounts
SPLIT_SOURCE = "/lup-split-from"
"""Where a helper container mounts the volume being split, read-only."""


def shared_volume_name(root: Path) -> str:
    """What both runtimes' configuration home was called before the split."""
    return f"lup-cfg-{repository_layout(root).name()}"


def existing_volumes(engine: ContainerEngine) -> list[str]:
    """Every volume this engine holds, or nothing when it cannot be asked.

    An engine that will not answer is not a reason to fail a launch that is
    otherwise fine -- a split waits for a launch whose engine answers.
    """
    try:
        listed = sh.Command(engine.binary)("volume", "ls", "--format", "{{.Name}}")
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return []
    return str(listed).split()


def attached_containers(volume: str, engine: ContainerEngine) -> list[str]:
    """Every container, running or stopped, holding a volume."""
    try:
        listed = sh.Command(engine.binary)(
            "ps", "-a", "--filter", f"volume={volume}", "--format", "{{.Names}}"
        )
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return []
    return str(listed).split()


class HomeSplit(BaseModel, frozen=True):
    """How one volume's entries are shared out between runtimes' volumes."""

    owned: dict[str, list[str]]
    """Each runtime's volume word, and the entries it takes."""

    unknown: list[str] = []
    """Entries no runtime declares, which every runtime takes."""

    debris: list[str] = []
    """Entries a runtime declares nothing reads again, which none takes."""

    @classmethod
    def of(cls, entries: list[str], logins: list[ProviderLogin]) -> "HomeSplit":
        """Share ``entries`` out by what each runtime declares it keeps."""

        def named(entry: str, patterns: list[str]) -> bool:
            return any(fnmatch(entry, pattern) for pattern in patterns)

        debris = [
            entry
            for entry in entries
            if any(named(entry, login.home_debris) for login in logins)
        ]
        kept = [entry for entry in entries if entry not in debris]
        unknown = [
            entry
            for entry in kept
            if not any(named(entry, login.home_entries) for login in logins)
        ]
        return cls(
            owned={
                login.state_volume: [
                    entry
                    for entry in kept
                    if entry in unknown or named(entry, login.home_entries)
                ]
                for login in logins
            },
            unknown=unknown,
            debris=debris,
        )


class LegacyVolumes(BaseModel, frozen=True):
    """The configuration-home volumes an older launch made for one repository."""

    shared: str | None = None
    """The one both runtimes wrote into, where it still exists."""

    scoped: dict[str, list[str]] = {}
    """Each runtime's volume word, and the volumes it had per settings digest."""

    branches: list[str] = []
    """The per-worktree volumes that preceded the shared one."""

    @classmethod
    def found(
        cls,
        root: Path,
        existing: list[str],
        logins: list[ProviderLogin],
        worktrees: list[str],
    ) -> "LegacyVolumes":
        """Which of this repository's old volumes the engine still holds."""
        shared = shared_volume_name(root)
        branches = [f"lup-cfg-{name}" for name in worktrees]
        return cls(
            shared=shared if shared in existing else None,
            scoped={
                login.state_volume: sorted(
                    name
                    for name in existing
                    if name.startswith(f"{shared}-{login.state_volume}-")
                )
                for login in logins
            },
            branches=sorted(
                name for name in existing if name in branches and name != shared
            ),
        )

    def every(self) -> list[str]:
        """Every old volume, the shared one first."""
        return [
            *([self.shared] if self.shared is not None else []),
            *(name for names in self.scoped.values() for name in names),
            *self.branches,
        ]


class HomeHelper(BaseModel, frozen=True):
    """A throwaway container reading or filling configuration-home volumes.

    Run from the image a session runs in and as the identity it runs as, so
    what it copies arrives owned by whoever the next session is, with the
    volume mounted where a session mounts it. Never on a network, and never
    through the entrypoint, which would seed the very volume being filled.
    """

    engine: ContainerEngine
    tag: str
    uid: int
    gid: int
    config_home: str

    def argv(self, program: str, mounts: list[str], arguments: list[str]) -> list[str]:
        """The command starting one program in a fresh helper container."""
        return [
            self.engine.binary,
            "run",
            "--rm",
            "--network",
            "none",
            *self.engine.identity_arguments(self.uid, self.gid),
            "--entrypoint",
            program,
            *[word for mount in mounts for word in ("-v", mount)],
            self.tag,
            *arguments,
        ]

    def run(self, program: str, mounts: list[str], arguments: list[str]) -> str:
        """Run one program in a fresh helper container, answering what it printed."""
        argv = self.argv(program, mounts, arguments)
        return str(sh.Command(argv[0])(*argv[1:]))

    def entries(self, volume: str) -> list[str]:
        """Every name at the top of a volume."""
        listed = self.run("ls", [f"{volume}:{SPLIT_SOURCE}:ro"], ["-A", SPLIT_SOURCE])
        return listed.splitlines()

    def fill(self, source: str, target: str, entries: list[str]) -> None:
        """Copy entries between volumes, keeping whatever the target already holds."""
        if not entries:
            return
        self.run(
            "cp",
            [f"{source}:{SPLIT_SOURCE}:ro", f"{target}:{self.config_home}"],
            [
                "-a",
                "--update=none",
                *(f"{SPLIT_SOURCE}/{entry}" for entry in entries),
                f"{self.config_home}/",
            ],
        )

    def read(self, volume: str, names: list[str]) -> list["HomeFile"]:
        """The named files at the top of a volume, as they stand, and only those it has.

        One archive from one container rather than a container per file, and
        a name the volume lacks is left out of it rather than failing it.
        """
        argv = self.argv(
            "tar",
            [f"{volume}:{SPLIT_SOURCE}:ro"],
            ["-C", SPLIT_SOURCE, "-cf", "-", "--ignore-failed-read", *names],
        )
        archive = sh.Command(argv[0])(*argv[1:], _return_cmd=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as held:
            return [
                HomeFile(name=member.name, content=extracted.read())
                for member in held.getmembers()
                if member.isfile() and (extracted := held.extractfile(member))
            ]


class HomeFile(BaseModel, frozen=True):
    """One file read out of a configuration-home volume."""

    name: str
    content: bytes

    def text(self) -> str:
        """The file as the UTF-8 text every file read here is."""
        return self.content.decode("utf-8")


def named_file(files: list[HomeFile], name: str) -> HomeFile | None:
    """The file of that name among those read, if the volume had it."""
    return next((held for held in files if held.name == name), None)


class HomeSeedPlaces(BaseModel, frozen=True):
    """Where one launch lays its seed out, and where it learns what the seed came to.

    ``seed`` is laid out as :attr:`~lup.harness.image.Image.home_seed`
    describes and mounted read-only; ``applied`` is written on the host with
    each file the seed comes to against the volume as it stands, which is what
    the session starts from and what its changes are measured against.
    """

    seed: Path
    applied: Path


def settle_home_seed(
    helper: HomeHelper, volume: str, places: HomeSeedPlaces
) -> list[Notice]:
    """Work out what a seed comes to against a volume, and say what it overrides.

    The same three-way merge the image's entrypoint applies at start
    (:mod:`lup.harness.assets.home_seed`), run here first on what the volume
    holds, so the launch knows what it applied — each session's own seed —
    and can say where the person's settings overrode a key a running session
    had changed too. A volume that cannot be read is taken as empty, which
    the entrypoint's own merge then corrects in the session's favour.
    """
    seed = read_tree(places.seed)
    managed = (text_of(seed, "managed") or "").split()
    names = [*managed, *merged_names(seed)]
    try:
        held = [
            SeedFile(file.name, file.text())
            for file in helper.read(volume, [*names, RECORD])
        ]
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        held = []
    settled = settle(seed, held, managed)
    for outcome in settled:
        write(places.applied / outcome.file.name, outcome.file.text)
    return [
        Notice(
            text=(
                f"Settings: {conflict} was changed both by a session still running "
                "in this repository and in your own settings; yours win."
            ),
            urgency="warning",
        )
        for outcome in settled
        for conflict in outcome.conflicts
    ]


class RuntimeVolume(BaseModel, frozen=True):
    """One runtime's configuration-home declaration, and the volume it now lives in."""

    login: ProviderLogin
    volume: str


def remove_volume(name: str, engine: ContainerEngine) -> bool:
    """Remove one volume, answering whether it went."""
    try:
        sh.Command(engine.binary)("volume", "rm", name)
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return False
    return True


def split_config_volumes(
    root: Path,
    helper: HomeHelper,
    runtimes: list[RuntimeVolume],
    existing: list[str] | None = None,
) -> list[Notice]:
    """Move this repository's old configuration homes into one volume per runtime.

    Once, and safely again: every copy keeps what the target already holds,
    so a split interrupted part-way finishes on the next launch without
    overwriting what a session wrote in between, and the old volumes go only
    after every copy landed. A volume some container still holds — a session
    opened before the split — postpones the whole split to a launch after it
    closes, since its files are still being written.

    The shared volume's entries go to each runtime that declares them, an
    entry nobody declares to every runtime, said aloud; debris goes nowhere.
    A per-digest volume was one runtime's alone and goes to that runtime.
    Per-worktree volumes were superseded before the split and are removed
    without being read.
    """
    engine = helper.engine
    logins = [runtime.login for runtime in runtimes]
    targets = {runtime.login.state_volume: runtime.volume for runtime in runtimes}
    volumes = existing if existing is not None else existing_volumes(engine)
    worktrees = [root.name, *(path.name for path in sibling_worktrees(root))]
    legacy = LegacyVolumes.found(root, volumes, logins, worktrees)
    old = legacy.every()
    if not old:
        return []
    held = {name: attached_containers(name, engine) for name in old}
    busy = [f"{name} ({', '.join(users)})" for name, users in held.items() if users]
    if busy:
        return [
            Notice(
                text=(
                    "Config home: still in use by an open session, so its move "
                    "into one volume per runtime waits for the first launch "
                    f"after it closes: {'; '.join(busy)}. This session starts "
                    "in the new volume without it."
                ),
                urgency="warning",
            )
        ]
    split = HomeSplit(owned={})
    try:
        if legacy.shared is not None:
            split = HomeSplit.of(helper.entries(legacy.shared), logins)
            for word, entries in split.owned.items():
                helper.fill(legacy.shared, targets[word], entries)
        for word, scoped in legacy.scoped.items():
            for volume in scoped:
                entries = helper.entries(volume)
                debris = HomeSplit.of(entries, logins).debris
                kept = [entry for entry in entries if entry not in debris]
                helper.fill(volume, targets[word], kept)
    except (sh.CommandNotFound, sh.ErrorReturnCode) as error:
        return [
            Notice(
                text=(
                    f"Config home: moving {', '.join(old)} into "
                    f"{', '.join(targets.values())} failed, so nothing was "
                    f"removed and the next launch tries again: {error}"
                ),
                urgency="warning",
            )
        ]
    removed = [name for name in old if remove_volume(name, engine)]
    kept = [name for name in old if name not in removed]
    said = (
        f"Config home: moved into {', '.join(targets.values())}, one volume per "
        "runtime"
        + (f"; removed {', '.join(removed)}" if removed else "")
        + (f"; could not remove {', '.join(kept)}, which nothing reads" if kept else "")
        + "."
    )
    return [
        Notice(text=said, urgency="detail"),
        *(
            [
                Notice(
                    text=(
                        "Config home: no runtime declares "
                        f"{', '.join(split.unknown)}, so each runtime's volume "
                        "was given a copy."
                    ),
                    urgency="warning",
                )
            ]
            if split.unknown
            else []
        ),
        *(
            [
                Notice(
                    text=(
                        "Config home: left behind what nothing reads again: "
                        f"{', '.join(split.debris)}."
                    ),
                    urgency="detail",
                )
            ]
            if split.debris
            else []
        ),
    ]
