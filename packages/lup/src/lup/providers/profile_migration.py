"""Bring accounts from where lup used to keep them into the person's config home.

Two places held profiles before one did: a checkout's ``.lup/profiles/<name>/``,
one directory per account holding a home per runtime, and the personal
registry at ``~/.lup/profiles.json``, naming a Claude home per account —
``~/.lup/homes/<name>`` unless one was registered elsewhere. Nothing reads
either any more, so an account left in one is an account no launch can
select; this moves what they hold, once, into
:meth:`~lup.providers.user_config.UserConfigFile.profiles_root`.

Moving rather than copying, because a login is a rotating chain: two copies
of one credential diverge the first time either renews, and the one left
behind is a stranger's. A registered home that lives somewhere of the
person's own choosing stays there and is linked, since the registry only
ever pointed at it. Nothing is overwritten: a name the destination already
holds keeps what it holds, and the source is left where it is and reported,
so running this again — or after a conflict is settled by hand — only ever
finishes the job.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from lup.channels.models import publish_atomic
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.providers.user_config import UserConfigFile

type MoveOutcome = Literal["moved", "linked", "kept", "refused"]
"""What became of one account: ``moved`` and ``linked`` finished; ``kept``
means the destination already held that name and the source is still where it
was; ``refused`` means the source named the runtime's default home, which
naming no profile already selects."""


class LegacyAccount(BaseModel, frozen=True):
    """One entry of the old personal registry, as it was written."""

    config_dir: str


class LegacyRegistry(BaseModel, frozen=True):
    """The old personal registry file, read only to be emptied."""

    profiles: dict[str, LegacyAccount] = {}
    active: str | None = None


class ProfileMove(BaseModel, frozen=True):
    """What became of one account found in an old location."""

    name: str
    source: Path
    destination: Path
    outcome: MoveOutcome

    def line(self) -> str:
        """This move as the command reports it."""
        match self.outcome:
            case "moved":
                return f"moved {self.name}: {self.source} → {self.destination}"
            case "linked":
                return f"linked {self.name}: {self.destination} → {self.source}"
            case "kept":
                return (
                    f"kept {self.name}: {self.destination} already exists, so "
                    f"{self.source} was left in place — merge it by hand, then "
                    "remove it"
                )
            case "refused":
                return (
                    f"skipped {self.name}: it named {self.source}, the default "
                    "home, which naming no profile already selects"
                )


class ProfileMigration(BaseModel, frozen=True):
    """Everything one run moved, and the selection it carried over."""

    moves: list[ProfileMove] = []
    selected: str | None = None
    """The old selection, where it became the person's; ``None`` where there
    was none to carry or the config file already recorded one."""

    def lines(self) -> list[str]:
        """The run as the command reports it, or a line saying it had nothing."""
        if not self.moves and self.selected is None:
            return ["nothing to migrate"]
        carried = [] if self.selected is None else [f"selected {self.selected}"]
        return [*(move.line() for move in self.moves), *carried]


def legacy_home() -> Path:
    """Where the old personal registry and the homes it made lived."""
    return Path.home() / ".lup"


def checkout_profiles(root: Path) -> Path:
    """Where a checkout used to keep its own profiles."""
    return root / ".lup" / "profiles"


def legacy_sources(root: Path, old_home: Path | None = None) -> list[Path]:
    """Every old location still holding something a launch would miss."""
    registry = (old_home or legacy_home()) / "profiles.json"
    kept = checkout_profiles(root)
    return [
        *([kept] if kept.is_dir() and any(kept.iterdir()) else []),
        *([registry] if registry.is_file() else []),
    ]


def legacy_notice(
    root: Path, config: UserConfigFile, old_home: Path | None = None
) -> str | None:
    """What a launch says while an old location still holds accounts."""
    sources = legacy_sources(root, old_home)
    if not sources:
        return None
    named = " and ".join(str(source) for source in sources)
    return (
        f"Profiles now live in {config.profiles_root()}, shared by every "
        f"checkout; {named} still hold accounts no launch selects. Move them "
        "once with `lup-devtools harness profile migrate`."
    )


def moved(source: Path, destination: Path) -> bool:
    """Move one directory where nothing is yet, answering whether it went."""
    if destination.exists() or destination.is_symlink():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)
    return True


def migrate_checkout(root: Path, config: UserConfigFile) -> list[ProfileMove]:
    """Move a checkout's profile directories, a runtime's home at a time.

    A name the destination lacks moves whole. One it already holds moves only
    the homes it lacks, since the same person may have signed one runtime in
    here and another there; a home both hold stays behind, reported.
    """
    kept = checkout_profiles(root)
    if not kept.is_dir():
        return []

    def settled(source: Path) -> Iterator[ProfileMove]:
        destination = config.profiles_root() / source.name
        if moved(source, destination):
            yield ProfileMove(
                name=source.name,
                source=source,
                destination=destination,
                outcome="moved",
            )
            return
        for home in sorted(source.iterdir()):
            target = destination / home.name
            yield ProfileMove(
                name=source.name,
                source=home,
                destination=target,
                outcome="moved" if moved(home, target) else "kept",
            )
        if not any(source.iterdir()):
            source.rmdir()

    names = sorted(entry for entry in kept.iterdir() if entry.is_dir())
    return [move for source in names for move in settled(source)]


def migrate_registry(config: UserConfigFile, old_home: Path) -> list[ProfileMove]:
    """Move the old registry's accounts, and empty it of every one that went.

    A home lup made for an entry, under the old home, moves into the profile;
    a home registered somewhere of the person's own is linked from it and
    stays where they put it. The registry only ever held Claude homes.
    """
    registry_path = old_home / "profiles.json"
    if not registry_path.is_file():
        return []
    registry = LegacyRegistry.model_validate_json(
        registry_path.read_text(encoding="utf-8")
    )
    made = (old_home / "homes").resolve()

    def settled(name: str, account: LegacyAccount) -> ProfileMove:
        source = Path(account.config_dir).expanduser()
        destination = config.profiles_root() / name / CLAUDE_LOGIN.home_subdir

        def outcome() -> MoveOutcome:
            if not CLAUDE_LOGIN.nameable(source):
                return "refused"
            if destination.exists() or destination.is_symlink():
                return "kept"
            if source.is_dir() and source.resolve().is_relative_to(made):
                return "moved" if moved(source, destination) else "kept"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(source, target_is_directory=True)
            return "linked"

        return ProfileMove(
            name=name, source=source, destination=destination, outcome=outcome()
        )

    moves = [
        settled(name, account) for name, account in sorted(registry.profiles.items())
    ]
    remaining = {
        move.name: registry.profiles[move.name]
        for move in moves
        if move.outcome == "kept"
    }
    if remaining:
        publish_atomic(
            registry_path,
            registry.model_copy(
                update={
                    "profiles": remaining,
                    "active": registry.active if registry.active in remaining else None,
                }
            ),
        )
    else:
        registry_path.unlink()
    if made.is_dir() and not any(made.iterdir()):
        made.rmdir()
    return moves


def migrate_profiles(
    root: Path, config: UserConfigFile, old_home: Path | None = None
) -> ProfileMigration:
    """Move every account both old locations hold, and carry one selection over.

    The checkout's selection is preferred to the old registry's; either
    becomes the person's only where their config file records none, since a
    selection already made there is theirs and one of these was only a
    checkout's, and only where that account arrived.
    """
    registry_home = old_home or legacy_home()
    kept = checkout_profiles(root)
    active_file = kept / ".active"
    checkout_active = (
        active_file.read_text(encoding="utf-8").strip() or None
        if active_file.is_file()
        else None
    )
    registry_path = registry_home / "profiles.json"
    registry_active = (
        LegacyRegistry.model_validate_json(
            registry_path.read_text(encoding="utf-8")
        ).active
        if registry_path.is_file()
        else None
    )
    moves = [*migrate_checkout(root, config), *migrate_registry(config, registry_home)]
    if active_file.is_file():
        active_file.unlink()
    if kept.is_dir() and not any(kept.iterdir()):
        kept.rmdir()
    carried = checkout_active or registry_active
    selected = (
        carried
        if carried is not None
        and config.load().profile is None
        and (config.profiles_root() / carried).is_dir()
        else None
    )
    if selected is not None:
        config.select_profile(selected)
    return ProfileMigration(moves=moves, selected=selected)
