"""Profiles: the whole setting a person's rooms run with, in every repository (`docs/declaration.md`, *Profiles*).

A profile names the account its sessions log in with, one for every runtime or
one per runtime; the directories it lends every launch; each runtime's session
defaults; a section of guidance of its own; whether the operator's own runtime
configuration is the layer below the profile's own; and optionally a layer on
each repository's project. An account is a login per runtime, kept by its name
under lup's data (`AccountsLayout`), so every room on it shares one login.

The person declares them in their profiles file, `~/.config/lup/profiles.py`,
binding `profiles`, a `Profiles` written as a layer on lup's own, which holds
`default` alone: account `default`, the operator's own runtime configuration
and nothing lent, so a person who never writes the file runs on it. The file
is Python the host runs, so trust on launch approves it by its content, as it
does the person's own layer, and a launch runs the copy approved, never the
file (`docs/trust.md`, *Trusted by its content*), with no import path of its
own (`lup_dev.declaration.load.declared_profiles`).

A launch's profile is `--profile`'s, else the one the repository's person's
layer chooses (`Project.profile`), else `default`; its account for the runtime
it launches is `--account`'s, else the profile's (`chosen`).
"""

from pathlib import Path
from typing import Annotated, Literal, Self, override

from pydantic import AfterValidator, model_validator

from lup.types import Model
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Edit, Layer, Named, Placed, listed
from lup_dev.declaration.project import Project

DEFAULT = "default"
"""The profile a launch runs on where neither `--profile` nor the person's layer names one, and the account a profile logs in with where it names none."""


def directory_named(name: str) -> str:
    """Refuse a name that can't be a directory's of its own: letters, digits, `-`, `_` and `.`, not starting with `.`.

    A profile keeps its configuration, and an account its logins, in a
    directory by its name, so a name holding `/`, or `..`, would place it
    elsewhere.

    >>> directory_named("work-2")
    'work-2'
    >>> directory_named("../work")
    Traceback (most recent call last):
    ...
    ValueError: `../work` can't name a profile or an account: a name is letters, digits, `-`, `_` and `.`, not starting with `.`
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
    """A directory a profile lends every launch on it, at its host path, as `--mount` lends one to a launch.

    >>> Lend(path=Path("~/notes")).writable
    False
    """

    path: Path
    """The directory on the host: absolute, or from the operator's home with a leading `~`."""
    writable: bool = False
    """Whether the room may write it, as `--mount-rw` lends one; read-only otherwise."""


class Lending(Named[Lend]):
    """The directories a profile lends every launch on it, each named by its path as written."""

    @override
    def named(self, entry: Lend) -> str:
        return str(entry.path)


class RuntimeDefaults(Model, extra="forbid"):
    """One runtime's defaults for a session on a profile, spelled as that runtime spells them: neither its models nor its efforts are another's.

    >>> RuntimeDefaults(model="opus").effort is None
    True
    """

    model: str | None = None
    """The model, by the runtime's id or alias for it; none leaves it to the runtime's own settings."""
    effort: str | None = None
    """How hard the model works, in the runtime's own levels; none leaves it to the runtime's own settings."""


class Profile(Layer, extra="forbid"):
    """The whole setting a room runs with: its account, what it lends, its sessions' defaults, its guidance and its runtime configuration.

    A layer on the profile of its name, where one is below (`Profiles.edit`):
    the fields it sets change that one's, as a module's do.

    >>> Profile(name="work", account="work").accounts
    {}
    >>> Profile(name="work", layer=Project(profile="home"))
    Traceback (most recent call last):
    ...
    lup_dev.declaration.errors.ProjectError: Profile `work`'s layer chooses the profile `home`: a profile is chosen by `--profile` or the person's own layer, never by another profile
    """

    name: DirectoryName
    """How `--profile`, the person's own layer and `Profiles`' verbs name it."""
    account: DirectoryName = DEFAULT
    """The account every runtime's sessions on it log in with, unless `accounts` names another for the runtime."""
    accounts: dict[str, DirectoryName] = {}
    """Per runtime, by its name as `lup-dev launch` takes it, the account its
    sessions log in with in place of `account`. A launch refuses a runtime's
    name no runtime has."""
    # lup: defer(issue=324, why="a launch's lending reads the profile's directories (profile-settings)")
    lent: Lending = Lending()
    """The directories lent to every launch on it, each at its host path and
    listed in the guidance as `--mount`'s are."""
    # lup: defer(issue=324, why="each runtime's terminal takes the profile's model and effort, once it's settled whether they sit below or above the operator's own (profile-settings)")
    defaults: dict[str, RuntimeDefaults] = {}
    """Per runtime, by its name, the defaults its sessions on it start with:
    the model and effort."""
    # lup: defer(issue=324, why="the launch's guidance renders the profile's section (profile-settings)")
    guidance: Path | None = None
    """A section of guidance of its own, after the person's `AGENTS.local.md`,
    on both runtimes: the file holding its text, from the profile's own
    directory (`~/.config/lup/profiles/<name>/`), or absolute; none for none."""
    operator_configuration: bool = True
    """Whether the operator's own runtime configuration is the layer below the
    profile's own (`~/.config/lup/profiles/<name>/<runtime>/`), credentials left
    out; off, the profile's own is the whole of it. What a session saves of their
    preferences is carried back into the profile's own."""
    rooms_home: Literal["project", "global"] = "project"
    """Where its rooms keep their history and state: in a home of each
    project's own, which the project's rooms share across worktrees and
    profiles (`project`), or in one home the rooms of every project share,
    whichever profile chooses it (`global`)."""
    # lup: defer(issue=324, why="a launch layers the profile's project over the person's, once it's settled whether that changes what trust approves (profile-settings)")
    layer: Project | None = None
    """A layer on each repository's project for its launches on the profile,
    over the person's own layer, in the same grammar; none for none."""

    @model_validator(mode="after")
    def chosen_elsewhere(self) -> Self:
        """Refuse a layer choosing a profile: a profile is chosen for a launch, never by one."""
        if self.layer is not None and self.layer.profile is not None:
            message = (
                f"Profile `{self.name}`'s layer chooses the profile "
                f"`{self.layer.profile}`: a profile is chosen by `--profile` or "
                "the person's own layer, never by another profile"
            )
            raise ProjectError(message)
        return self

    def account_for(self, runtime: str) -> str:
        """Return the account runtime `runtime`'s sessions on it log in with, by the runtime's name.

        >>> Profile(name="split", account="work", accounts={"second": "home"}).account_for("first")
        'work'
        """
        return self.accounts.get(runtime, self.account)

    def runtimes(self) -> list[str]:
        """List the runtimes it names, by the names it gives them, each once.

        >>> Profile(name="x", accounts={"first": "a"}, defaults={"first": RuntimeDefaults()}).runtimes()
        ['first']
        """
        return list(dict.fromkeys([*self.accounts, *self.defaults]))


class Profiles(Named[Profile]):
    """The person's profiles, each named by its name: lup's `default`, and their own.

    `Profiles()` starts from lup's, `default` alone; `.add(Profile(…))` adds
    one; `.edit(Profile(name="default", …))` changes the one of that name,
    field by field.

    >>> Profiles().edit(Profile(name="default", account="work")).operations[0].verb
    'edit'
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


LUPS = Profiles.of(Profile(name=DEFAULT))
"""lup's own profiles, below the person's: `default` alone."""


def resolved_profiles(profiles: Profiles) -> list[Profile]:
    """Return the profiles `profiles` gives as a layer on lup's, in order.

    Raise `ProjectError` where it leaves `default` out.

    >>> [each.name for each in resolved_profiles(Profiles().add(Profile(name="work")))]
    ['default', 'work']
    """
    placed = profiles.over(LUPS).resolve(LUPS.given(), LUPS.given())
    found = profiles.ordered(placed)
    if DEFAULT not in [each.name for each in found]:
        message = (
            f"`Profiles` leaves out `{DEFAULT}`, which a launch choosing no profile "
            f'runs: `.edit(Profile(name="{DEFAULT}", …))` changes it'
        )
        raise ProjectError(message)
    return found


class Chosen(Model):
    """The profile a launch runs on, and the account its runtime logs in with."""

    profile: Profile
    account: DirectoryName
    """The account the launched runtime's sessions log in with: `--account`'s, else the profile's."""

    def said(self) -> str | None:
        """Say which profile and account the launch runs on, where either isn't the default; none otherwise.

        >>> Chosen(profile=Profile(name="work", account="work"), account="work").said()
        'This launch runs on the profile `work`, with the account `work`.'
        >>> Chosen(profile=Profile(name=DEFAULT), account=DEFAULT).said() is None
        True
        """
        if self.profile.name == DEFAULT and self.account == DEFAULT:
            return None
        return (
            f"This launch runs on the profile `{self.profile.name}`, with the "
            f"account `{self.account}`."
        )


def chosen(
    profiles: list[Profile],
    runtime: str,
    runtimes: list[str],
    *,
    profile: str | None,
    account: str | None,
) -> Chosen:
    """Choose a launch's profile and its runtime's account.

    The profile is `profile`, `--profile`'s or else the person's layer's, or
    `default` where it's none; the account `account`, `--account`'s, else the
    profile's for `runtime`. Raise `ProjectError` where the profile isn't among
    `profiles`, naming those that are, where `account` can't name one, or where
    the profile names a runtime that isn't among `runtimes`, as their adapters
    name them.

    >>> chosen([Profile(name=DEFAULT)], "first", ["first"], profile=None, account="work").account
    'work'
    """
    wanted = profile or DEFAULT
    by_name = {each.name: each for each in profiles}
    if wanted not in by_name:
        message = (
            f"no profile is called `{wanted}`: the profiles are {listed(list(by_name))}"
        )
        raise ProjectError(message)
    found = by_name[wanted]
    unknown = [each for each in found.runtimes() if each not in runtimes]
    if unknown:
        message = (
            f"Profile `{wanted}` names {listed(unknown)}, which no runtime is "
            f"called: the runtimes are {listed(runtimes)}"
        )
        raise ProjectError(message)
    if account is not None:
        try:
            directory_named(account)
        except ValueError as malformed:
            message = f"`--account {account}`: {malformed}"
            raise ProjectError(message) from malformed
    return Chosen(profile=found, account=account or found.account_for(runtime))
