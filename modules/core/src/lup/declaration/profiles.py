"""Profiles and accounts: the setting a repository's sessions run with, declared in its layers (`README.md` here, *Profiles and accounts*).

An account is a login per runtime, kept by its name, so every room on it shares
one login. A profile names the account its sessions log in with, one for every
runtime or one per runtime, the directories it lends every session, each
runtime's defaults, and where its rooms keep their history. `Core` holds the
profiles (`Core.profiles`) and the one a repository's sessions run on
(`Core.profile`), so they're declared where any of a module's settings are: a
profile in a repository's declaration or its own local layer applies to that
repository, and one in the machine's layer to every repository on this machine.
"""

from pathlib import Path
from typing import Annotated, Literal, Self, override

from pydantic import AfterValidator

from lup.declaration.errors import ProjectError
from lup.declaration.grammar import Edit, Layer, Named, Placed, listed
from lup.types import Model

DEFAULT = "default"
"""The profile sessions run on where nothing chooses another, and the account a
profile logs in with where it names none."""


def directory_named(name: str) -> str:
    """Refuse a name that can't name a directory of its own: letters, digits, `-`, `_` and `.`, not starting with `.`.

    A profile keeps its configuration, and an account its logins, in a
    directory by its name, so a name holding `/`, or `..`, would place it
    elsewhere.

    >>> directory_named("work-2")
    'work-2'
    """
    shaped = all(char.isascii() and (char.isalnum() or char in "-_.") for char in name)
    if not shaped or name == "" or name.startswith("."):
        message = (
            f"`{name}` can't name a profile or an account: a name is letters, "
            "digits, `-`, `_` and `.`, not starting with `.`"
        )
        raise ValueError(message)
    return name


type DirectoryName = Annotated[str, AfterValidator(directory_named)]
"""A profile's or an account's name, which names a directory of its own."""


class Lend(Model, extra="forbid"):
    """A directory a profile lends every session on it, at its path on the machine.

    >>> Lend(path=Path("~/notes")).writable
    False
    """

    path: Path
    """The directory on the machine: absolute, or from the operator's home with a
    leading `~`."""
    writable: bool = False
    """Whether the room may write it; read-only otherwise."""


class Lending(Named[Lend]):
    """The directories a profile lends every session on it, each named by its path as written."""

    @override
    def named(self, entry: Lend) -> str:
        return str(entry.path)


class RuntimeDefaults(Model, extra="forbid"):
    """One runtime's defaults for a session on a profile, spelled as that runtime spells them, since neither its models nor its efforts are another's."""

    model: str | None = None
    """The model, by the runtime's id or alias for it; none leaves it to the
    runtime's own settings."""
    effort: str | None = None
    """How hard the model works, in the runtime's own levels; none leaves it to
    the runtime's own settings."""


class Profile(Layer, extra="forbid"):
    """The setting a repository's sessions run with: their account, what's lent them, their defaults and where their rooms keep their history.

    A layer on the profile of its name where one is below (`Profiles.edit`): the
    fields it sets change that one's, as a module's do.

    >>> Profile(name="work", account="work").account_for("codex")
    'work'
    """

    name: DirectoryName
    """How `Core.profile` and `Profiles`' verbs name it."""
    account: DirectoryName = DEFAULT
    """The account every runtime's sessions on it log in with, unless `accounts`
    names another for the runtime."""
    accounts: dict[str, DirectoryName] = {}
    """Per runtime, by its name, the account its sessions log in with in place of
    `account`."""
    lent: Lending = Lending()
    """The directories lent to every session on it, each at its path on the
    machine."""
    defaults: dict[str, RuntimeDefaults] = {}
    """Per runtime, by its name, the defaults its sessions start with: the model
    and effort."""
    operator_configuration: bool = True
    """Whether the operator's own runtime configuration is the layer below the
    profile's own; off, the profile's own is the whole of it."""
    rooms_home: Literal["project", "global"] = "project"
    """Where its rooms keep their history and state: a home of each repository's
    own, which that repository's rooms share across worktrees and profiles
    (`project`), or one home the rooms of every repository share (`global`)."""

    def account_for(self, runtime: str) -> str:
        """Return the account `runtime`'s sessions on it log in with, by the runtime's name."""
        return self.accounts.get(runtime, self.account)


class Profiles(Named[Profile]):
    """The profiles a repository's sessions may run on, each named by its name: lup's `default`, and those its layers declare.

    `.add(Profile(…))` adds one; `.edit(Profile(name="default", …))` changes the
    one of that name, field by field.
    """

    @override
    def named(self, entry: Profile) -> str:
        return entry.name

    def edit(self, profile: Profile, why: str | None = None) -> Self:
        """Put `profile` as a layer on the profile of its name, which must be there."""
        return self.then(Edit(entry=profile, why=why))

    @override
    def edited(self, below: Placed[Profile], layer: Placed[Profile]) -> Placed[Profile]:
        """Return the profile `below` with `layer`'s profile on it, where it was."""
        return below.model_copy(update={"entry": layer.entry.over(below.entry)})

    def resolved(self) -> list[Profile]:
        """Return the profiles this selection gives, in order.

        Raise `ProjectError` where it leaves out `default`, which sessions run on
        where nothing chooses another, or where a name its verbs give isn't there.
        """
        found = self.ordered(self.resolve([], []))
        if DEFAULT not in [each.name for each in found]:
            message = (
                f"the profiles leave out `{DEFAULT}`, which sessions run on where "
                f'nothing chooses another: `.edit(Profile(name="{DEFAULT}", …))` '
                "changes it"
            )
            raise ProjectError(message, about=[DEFAULT])
        return found


class Chosen(Model):
    """The profile a session runs on, and the account its runtime logs in with."""

    profile: Profile
    account: DirectoryName


def chosen(
    profiles: Profiles,
    runtime: str,
    *,
    profile: str,
    account: str | None = None,
) -> Chosen:
    """Return the profile named `profile` among `profiles`, and the account `runtime`'s session logs in with on it: `account` where it's given, else the profile's for the runtime.

    Raise `ProjectError` where no profile has that name, naming those there are.
    """
    found = profiles.resolved()
    named = {each.name: each for each in found}
    if profile not in named:
        message = f"no profile is named `{profile}`; there are {listed(list(named))}"
        raise ProjectError(message, about=[profile])
    picked = named[profile]
    return Chosen(
        profile=picked,
        account=picked.account_for(runtime) if account is None else account,
    )
