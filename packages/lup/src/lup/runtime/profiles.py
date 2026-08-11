"""Where a project's named configuration homes come from, and the surface over them.

What a profile name means is the application's to decide: a personal registry
file listing accounts by hand, or a directory the project already keeps one
account per entry in. :class:`ProfileStore` is the engine answering for one
such origin, and :class:`ProfileDirectory` is the concrete surface a command
tree and a launcher hold over whichever engine an application supplied.

Nothing here names a provider. A directory carries the :class:`ProviderLogin`
of the runtime whose homes it holds, so reporting whether one is signed in —
and telling a caller how to sign it in — is answered in that runtime's own
words rather than in words this module would have to choose.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.runtime.login import ProviderLogin


class ProfileStore(ABC):
    """One origin of named configuration homes.

    Injected into :class:`ProfileDirectory` and never held by a consumer
    directly, so an application supplies its own origin without any caller
    above learning where profiles are kept.
    """

    @abstractmethod
    def names(self) -> list[str]:
        """Every profile name this origin knows, in display order."""

    @abstractmethod
    def config_dir_for(self, name: str) -> Path:
        """The configuration home that name selects, or ``KeyError``."""

    @abstractmethod
    def active_profile(self) -> str | None:
        """The name that answers for a caller naming none."""

    @abstractmethod
    def add_profile(self, name: str, config_dir: Path | None = None) -> Path:
        """Register name at ``config_dir``, or where this origin puts one."""

    @abstractmethod
    def set_active(self, name: str) -> None:
        """Make name answer for callers naming none, or ``KeyError``."""

    @abstractmethod
    def remove_profile(self, name: str) -> None:
        """Forget name, if this origin knows it."""


class Profile(BaseModel):
    """One profile, resolved far enough for a caller to act on it."""

    model_config = ConfigDict(frozen=True)

    name: str
    config_dir: Path
    active: bool
    logged_in: bool
    """Whether that home already holds a completed login, so a listing can
    say which profile a launch would drop into a sign-in prompt."""


class ProfileDirectory:
    """Resolve, list, and curate profiles over whichever origin holds them."""

    def __init__(self, store: ProfileStore, login: ProviderLogin) -> None:
        self.store = store
        self.login = login

    def profile(self, name: str) -> Profile:
        """Resolve one name against the origin, login state included."""
        config_dir = self.store.config_dir_for(name)
        return Profile(
            name=name,
            config_dir=config_dir,
            active=name == self.store.active_profile(),
            logged_in=self.login.logged_in(config_dir),
        )

    def entries(self) -> list[Profile]:
        """Every known profile, in the origin's own display order."""
        return [self.profile(name) for name in self.store.names()]

    def active(self) -> Profile | None:
        """The profile answering for a caller naming none, where there is one."""
        name = self.store.active_profile()
        return None if name is None else self.profile(name)

    def launch_home(self, name: str | None) -> Path | None:
        """The configuration home a launch exports, or None to inherit.

        Naming none while no profile is active is not an error: it leaves
        whatever home the surrounding environment already selected, which is
        both what a project with no profiles expects and what keeps a session
        launched from inside another one on the account it was started under.
        """
        selected = name or self.store.active_profile()
        if selected is None:
            return None
        return self.store.config_dir_for(selected)

    def add(self, name: str, config_dir: Path | None = None) -> Profile:
        """Register a profile and resolve what registering it produced."""
        self.store.add_profile(name, config_dir)
        return self.profile(name)

    def use(self, name: str) -> Profile:
        """Make one profile the active selection, and resolve it."""
        self.store.set_active(name)
        return self.profile(name)

    def remove(self, name: str) -> Profile:
        """Forget a profile, resolving it first so a caller can report it."""
        removed = self.profile(name)
        self.store.remove_profile(name)
        return removed
