"""The host service's control requests and replies, typed.

One request per connection, its JSON read to the end, and one JSON reply. A request
is a model told apart by its `kind`, which names the handler that answers it
(`host/service.py`); a reply is told apart by its own. The kinds here are the
service's own: a launch's registration, its end, listing the launches served, and
stopping the service. A module declares its own kinds beside the handler it
registers for them.
"""

from pathlib import Path, PurePath, PurePosixPath
from typing import Annotated, Literal, get_args

from pydantic import AfterValidator

from lup.rooms.container import AbsolutePath
from lup.types import Model
from lup_dev.errors import LupDevError


class HostError(LupDevError):
    """The host service refused a request, or couldn't be reached."""


def segment(launch: str) -> str:
    """Return a launch's id if it can name a directory: one path segment, not `..`.

    >>> segment("a1b2")
    'a1b2'
    """
    if not launch or launch == ".." or PurePath(launch).name != launch:
        message = f"a launch's id names its directory, so it's one path segment, not {launch!r}"
        raise ValueError(message)
    return launch


type LaunchId = Annotated[str, AfterValidator(segment)]
"""A launch's id: unique among the launches the service serves, it names their directory."""


def handle(name: str, longest: int = 64) -> str:
    """Return `name` if a launch can take it: letters, digits, `-`, `_` and `.`, not starting with `-`, at most `longest` long.

    >>> handle("gate-on-push")
    'gate-on-push'
    >>> handle("two words")
    Traceback (most recent call last):
    ...
    ValueError: a launch's name is letters, digits, `-`, `_` and `.`, not starting with `-`, at most 64 long: not 'two words'
    """
    allowed = all(each.isalnum() or each in "-_." for each in name)
    if not name or not allowed or name.startswith("-") or len(name) > longest:
        message = (
            "a launch's name is letters, digits, `-`, `_` and `.`, not starting with "
            f"`-`, at most {longest} long: not {name!r}"
        )
        raise ValueError(message)
    return name


type Name = Annotated[str, AfterValidator(handle)]
"""A launch's name: how the operator, lup's commands and the session itself call it.

Unique among the launches the service serves, and changeable while it runs;
nothing is kept by it, so a rename takes effect wherever the name is next used.
The launch's id stays the same."""

type Action = Literal[
    "fetch",
    "push",
    "force-push",
    "delete-ref",
    "read-issues",
    "file-issue",
    "comment",
    "draft-pull-request",
]
"""What the host can do with the operator's credentials for a launch, by name.

Each names a handler lup carries out on the host (`docs/host-tools.md`,
*Credentials on the host*): fetching from one of the repository's remotes;
pushing to one, a push that isn't a fast-forward being `force-push`, and one
removing a branch or tag `delete-ref`; reading issues and pull requests, the
repository's own or another's the operator's login can read; filing an issue;
commenting on one; and opening a draft pull request.
The handlers arrive with GitHub's tools and git's remote helper.
"""


def actions() -> list[Action]:
    """List every action, in the order `Action` names them.

    >>> "force-push" in actions()
    True
    """
    return list(get_args(Action.__value__))


class Limits(Model):
    """What the host does with the operator's credentials for a launch without asking.

    The project's declaration says it (`Core`'s `credentials`), resolved at the
    commit the operator approved. The host's handlers hold each action to it,
    refusing one beyond it and saying why, as they arrive.
    """

    actions: list[Action]
    """The actions allowed, in the order `Action` names them."""
    protected: list[str]
    """Patterns over full ref names, such as `refs/tags/*`: the refs no push
    updates."""
    gated: list[str] = []
    """Patterns over full ref names: the refs a push from the room updates only
    once the gate passed on its commit, which the room's git helper runs first
    (`remote/helper.py`); the host checks nothing of it."""

    def refusal(self, action: Action) -> str | None:
        """Say why the host doesn't do `action` for the launch, where these limits leave it out; none where they allow it.

        >>> print(Limits(actions=["fetch"], protected=[]).refusal("comment"))
        the project's declaration doesn't allow `comment` with the operator's credentials (`Core.credentials`), and allowing it is the operator's call
        """
        if action in self.actions:
            return None
        return (
            f"the project's declaration doesn't allow `{action}` with the operator's "
            "credentials (`Core.credentials`), and allowing it is the operator's call"
        )


class GitHubRepository(Model):
    """A repository on GitHub, by its owner's login and its own name.

    >>> str(GitHubRepository(owner="joy-void-joy", name="lup"))
    'joy-void-joy/lup'
    """

    owner: str
    name: str

    @classmethod
    def read(cls, written: str) -> GitHubRepository:
        """Read a repository written as `gh --repo` takes it: `owner/name`.

        Raise `ValueError` where it isn't two names, neither `..`, apart by one
        `/`.

        >>> GitHubRepository.read("someone/atlas")
        GitHubRepository(owner='someone', name='atlas')
        >>> GitHubRepository.read("/atlas")
        Traceback (most recent call last):
        ...
        ValueError: a repository on GitHub is `owner/name`, not '/atlas'
        """
        path = PurePosixPath(written)
        plain = str(path) == written and not path.is_absolute()
        match path.parts:
            case [owner, name] if plain and ".." not in path.parts:
                return cls(owner=owner, name=name)
            case _:
                message = f"a repository on GitHub is `owner/name`, not {written!r}"
                raise ValueError(message)

    def __str__(self) -> str:
        """Spell it as `gh --repo` takes it: `owner/name`."""
        return f"{self.owner}/{self.name}"


class Request(Model):
    """A control request: its `kind` names it, and the handler that answers it."""

    kind: str

    @classmethod
    def named(cls) -> str:
        """Return the kind this model's requests carry, its `kind` field's default.

        A model built without validation holds its defaults, so a request's kind is
        read from its model rather than spelled again where it's routed.
        """
        return cls.model_construct().kind


class Register(Request):
    """Serve a launch: its socket directory, the hook socket inside, its record."""

    kind: Literal["register"] = "register"
    launch: LaunchId
    runtime: str
    """The runtime the launch runs, by its name: whose hooks its judge answers."""
    worktree: Path
    """The worktree the launch started in."""
    repository: AbsolutePath
    """The repository's git directory on the host, which the launcher found
    before the room started: where the host acts for the launch, never a path
    the room names."""
    judge: AbsolutePath
    """The command of the launch's repository's approved copy of `lup-dev`: each
    of its hooks runs `<judge> hook <runtime>`, so it's judged by the code
    approved for its repository."""
    container: str
    """The name of the launch's container, which tells a later launch whether
    this one is gone."""
    limits: Limits
    """What the host does with the operator's credentials for the launch
    without asking, from the declaration at the commit the operator approved:
    recorded with the launch, so a service started again keeps them."""
    github: GitHubRepository | None
    """The repository on GitHub, as `gh` named it from the repository's own
    remote, in its git directory, when the launch started: the one repository
    lup's GitHub tools act on for the launch, never one the room names. None
    where it couldn't be named, which the launch said."""
    name: Name | None = None
    """Its name, as it stands: the one asked at registration, made unique
    (`exact`), and each rename since. None in a record from before launches
    had names, which the service names after its worktree."""
    exact: bool = False
    """Whether the name was asked for as it is (`--name`), so registering
    refuses where another launch holds it; otherwise `-2`, `-3` is added until
    it's free."""


class Rename(Request):
    """Rename a launch the service serves, refused where another holds the name."""

    kind: Literal["rename"] = "rename"
    launch: LaunchId
    name: Name


class Unregister(Request):
    """End a launch: its sockets closed, its directory and record removed."""

    kind: Literal["unregister"] = "unregister"
    launch: LaunchId


class ListLaunches(Request):
    """List the launches the service serves."""

    kind: Literal["list"] = "list"


class Stop(Request):
    """Stop the service; the launches it serves stay recorded, for the next to serve."""

    kind: Literal["stop"] = "stop"


class Reply(Model):
    """The service's answer to one request, told apart by its `kind`."""

    kind: str


class Registered(Reply):
    """The launch is served: its socket directory, which its room mounts, and the name it took."""

    kind: Literal["registered"] = "registered"
    directory: Path
    name: Name


class Renamed(Reply):
    """The launch is renamed: as it stands."""

    kind: Literal["renamed"] = "renamed"
    launch: Register


class Listed(Reply):
    """The launches the service serves, each as it stands, and the name each session of theirs last had."""

    kind: Literal["listed"] = "listed"
    launches: list[Register]
    sessions: dict[str, Name] = {}
    """By the runtime's id for each session the service has heard start, the
    name of its launch as it last stood: how the operator's inbox names who
    sent an item."""


class Done(Reply):
    """The request is carried out, with nothing more to say."""

    kind: Literal["done"] = "done"


class Refused(Reply):
    """The request wasn't carried out, and why."""

    kind: Literal["refused"] = "refused"
    error: str
