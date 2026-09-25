"""The accounts one person keeps, as directories beside their lup config.

A name is a directory rather than an entry in a registry, so the configuration
home an account runs under — and whatever else it earns — sit together under
``profiles/<name>/`` in the person's lup config home
(:class:`~lup.providers.user_config.UserConfigFile`). Making the directory the
origin is what keeps one name meaning one account however it is spelled, to a
launch, a command tree, a setup wizard or a declaration's ``profile``: there
is no second list to register a profile in, and so none to fall out of step.

Per person rather than per checkout, because an account belongs to whoever
signs in: kept in a checkout, every new repository started signed out.

Nothing here names a provider. The subdirectory a configuration home takes
inside each profile is the runtime login's word, so one name holds a home for
every runtime side by side, and ``profile=work`` means the same account on
Claude Code and on Codex. Which name answers for a caller naming none is the
``profile`` the person's config file records.
"""

from pathlib import Path

from lup.providers.login import ProviderLogin
from lup.providers.profiles import (
    ProfileDirectory,
    ProfileNames,
    ProfileRegistrar,
    ProfileStateLocations,
)
from lup.providers.user_config import UserConfigFile
from lup.types import EnvVars


class ProfileFolders:
    """The directory layout, as a plain collaborator both capabilities share.

    A collaborator rather than a base class: an implementation that inherited
    its reading would be inheriting behavior alongside a capability, and the
    two classes below would then be one class answering for two powers.
    """

    def __init__(self, config: UserConfigFile, home_subdir: str) -> None:
        self.config = config
        self.root = config.profiles_root()
        self.home_subdir = home_subdir

    def names(self) -> list[str]:
        """Every profile directory under the root, in display order.

        A root that does not exist yet holds no profiles rather than
        failing: a person acquires one the first time they add a profile,
        and every reader before that should see an empty roster instead of
        an error about a directory nobody has had reason to create.
        """
        if not self.root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.root.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        )

    def home_for(self, name: str) -> Path:
        """The configuration home that name's directory holds."""
        return self.root / name / self.home_subdir

    def container_for(self, name: str) -> Path:
        """The directory holding every runtime home for one profile."""
        return self.root / name

    def active(self) -> str | None:
        """The selection the person's config file records, where it records one."""
        return self.config.load().profile

    def select(self, name: str) -> None:
        """Record which profile answers for a caller naming none."""
        self.config.select_profile(name)


class TreeProfileNames(ProfileNames):
    """Read which accounts the profile directories hold."""

    def __init__(self, folders: ProfileFolders) -> None:
        self.folders = folders

    def names(self) -> list[str]:
        return self.folders.names()

    def config_dir_for(self, name: str) -> Path:
        if name not in self.folders.names():
            raise KeyError(name)
        return self.folders.home_for(name)

    def active_profile(self) -> str | None:
        return self.folders.active()


class TreeProfileRegistrar(ProfileRegistrar):
    """Start and select profile directories, and refuse to forget one."""

    def __init__(self, folders: ProfileFolders) -> None:
        self.folders = folders

    def add_profile(self, name: str, config_dir: Path | None = None) -> Path:
        """Start a profile directory, for a login to fill in.

        Where its configuration home sits is derived from the name, so a
        caller naming one elsewhere is asking for something a directory
        profile cannot be rather than for a variation on one. An account
        whose home already exists elsewhere is reached by making that path a
        symlink, which resolves like any other — except onto the runtime's
        default home, which the directory refuses however it is reached,
        because naming no profile is what selects that account.

        The first profile a person starts becomes their selection: someone
        with exactly one account should not also have to say so.
        """
        home = self.folders.home_for(name)
        if config_dir is not None and config_dir != home:
            raise ValueError(
                f"a directory profile keeps its configuration home at {home}, "
                f"derived from the name — {config_dir} cannot be one; symlink "
                "that path to point this profile at a home already elsewhere, "
                "other than the runtime's default home, which naming no profile "
                "already selects"
            )
        home.mkdir(parents=True, exist_ok=True)
        if self.folders.active() is None:
            self.folders.select(name)
        return home

    def set_active(self, name: str) -> None:
        if name not in self.folders.names():
            raise KeyError(name)
        self.folders.select(name)

    def remove_profile(self, name: str) -> None:
        """Refuse, because forgetting one here would mean deleting it.

        Nothing registers a directory profile, so there is no registration to
        drop: the directory is the profile, and it holds the login that
        account earned. Answered as a ``ValueError`` whose message is the
        explanation, which is what a command tree renders in place of one.

        Where that profile is the selection, the line recording it is named
        too: removed alone, the directory leaves every launch naming none
        refused for a profile that no longer exists, told to add it back.
        """
        selected = (
            f", and the `profile` line in {self.folders.config.path()}, which "
            "selects it"
            if self.folders.active() == name
            else ""
        )
        raise ValueError(
            f"a directory profile is {self.folders.root / name}, which holds "
            f"its login — remove that directory to remove the profile{selected}"
        )


class TreeProfileStateLocations(ProfileStateLocations):
    """Keep auxiliary state beside every runtime home under one profile."""

    def __init__(self, folders: ProfileFolders) -> None:
        self.folders = folders

    def container_for(self, name: str) -> Path:
        if name not in self.folders.names():
            raise KeyError(name)
        return self.folders.container_for(name)


def user_profile_directory(
    login: ProviderLogin, config: UserConfigFile | None = None
) -> ProfileDirectory:
    """One runtime's side of the accounts a person keeps, as a directory to curate.

    The one origin a name resolves against — a launch, the usage display, a
    resolver run, a declaration's ``profile`` — so a name opens the same
    account wherever it is spelled. Which runtime's homes it reads is the
    ``login``'s to say, through the subdirectory each takes inside a profile.
    ``config`` is the person's lup config home, read from the environment
    unless a caller names another.
    """
    folders = ProfileFolders(config or UserConfigFile(), login.home_subdir)
    return ProfileDirectory(
        TreeProfileNames(folders),
        TreeProfileRegistrar(folders),
        login,
        TreeProfileStateLocations(folders),
    )


def profile_environment(
    login: ProviderLogin, name: str | None, config: UserConfigFile | None = None
) -> EnvVars:
    """The environment a declaration naming ``profile=name`` runs under.

    What an agent's ``profile`` field resolves to, the same way a launch
    naming that profile does: the account's home for this runtime, exported
    through the variable the runtime reads. A name the person keeps no
    profile under is refused listing the ones they do, and one whose home is
    the runtime's default is refused as a launch refuses it.

    Naming none exports nothing, rather than the person's selection: a
    declaration opened inside a session stays on the account that session was
    started under, which a launch already chose from that selection.
    """
    if name is None:
        return {}
    return user_profile_directory(login, config).account(name).variables
