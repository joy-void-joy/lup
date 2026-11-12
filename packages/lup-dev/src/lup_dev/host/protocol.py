"""The host service's control requests and replies, typed.

One request per connection, its JSON read to the end, and one JSON reply. A request
is a model told apart by its `kind`, which names the handler that answers it
(`host/service.py`); a reply is told apart by its own. The kinds here are the
service's own: a launch's registration, its end, listing the launches served,
and stopping the service. A module declares its own kinds beside the handler it
registers for them. Any of them can also be watched, on the service's watch
socket (`host/watch.py`).
"""

from datetime import datetime
from pathlib import Path, PurePath, PurePosixPath
from typing import Annotated, ClassVar, Literal, Unpack, get_args

from pydantic import AfterValidator, ConfigDict

from lup.blocks import Drawer, FoldKind, Tone, Verb
from lup.rooms.container import AbsolutePath
from lup.types import Model
from lup_dev.errors import LupDevError
from lup_ledger.parties import Conversation


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
"""A launch's name: how the operator, lup's commands and the session themselves call it.

Unique among the launches the service serves, and changeable while it runs;
nothing is kept by it, so a rename takes effect wherever the name is next used.
The launch's id stays the same."""

type Action = Literal[
    "fetch",
    "push",
    "force-push",
    "delete-merged",
    "delete-ref",
    "read-issues",
    "file-issue",
    "edit-issue",
    "close-issue",
    "comment",
    "edit-comment",
    "draft-pull-request",
]
"""What the host can do with the operator's credentials for a launch, by name.

Each names a handler lup carries out on the host (`docs/credentials.md`):
fetching from one of the repository's remotes;
pushing to one, a push that isn't a fast-forward being `force-push`, one
removing a branch whose commits are all in a gated branch on the remote
`delete-merged`, and one removing any branch or tag `delete-ref`; reading
issues and pull requests, the repository's own or another's the operator's
login can read; filing an issue, editing its title, body and labels, and
closing or reopening it; commenting on an issue or pull request, and editing a
comment; and opening a draft pull request.
The handlers arrive with GitHub's tools and git's remote helper.
"""


def actions() -> list[Action]:
    """List every action, in the order `Action` names them.

    >>> "force-push" in actions()
    True
    """
    return list(get_args(Action.__value__))


def branch_name(value: str) -> str:
    """Return `value` if it can name a branch in a declaration: its short name, neither empty nor read as one of git's options, without the whitespace and characters no ref holds.

    It reaches git's and `gh`'s command lines, and a full ref would be read as
    `refs/heads/refs/heads/…`.

    >>> branch_name("release/2")
    'release/2'
    >>> branch_name("refs/heads/dev")
    Traceback (most recent call last):
    ...
    ValueError: a branch is named by its short name, as `dev` is, not 'refs/heads/dev'
    """
    wrong = (
        not value
        or value.startswith(("-", "refs/"))
        or any(each.isspace() or each in "~^:?*[\\" for each in value)
    )
    if wrong:
        message = f"a branch is named by its short name, as `dev` is, not {value!r}"
        raise ValueError(message)
    return value


type BranchName = Annotated[str, AfterValidator(branch_name)]
"""A branch, as a declaration names it: `dev`, never `refs/heads/dev`."""


class Branches(Model):
    """The two branches a repository's work moves between, by the names its approved declaration gives them (`docs/trust.md`, *Which branch*).

    Plain names, kept with the approval (`Approval.branches`), so whatever reads
    them on the host runs no project code. These defaults are what's read
    before the first approval, and in a record from before approvals kept them.
    """

    integration: BranchName = "dev"
    """What branches start from, where accepting one merges it, and what a pull
    request targets: `Core.integration`."""
    running: BranchName = "dev"
    """What the host runs, what trust reads and what `land` lands on:
    `Versions.running`, else the integration branch."""

    @property
    def integration_ref(self) -> str:
        """Return the integration branch by its ref's full name.

        >>> Branches(integration="trunk").integration_ref
        'refs/heads/trunk'
        """
        return f"refs/heads/{self.integration}"

    @property
    def running_ref(self) -> str:
        """Return the running branch by its ref's full name.

        >>> Branches(running="live").running_ref
        'refs/heads/live'
        """
        return f"refs/heads/{self.running}"


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
    (`remote/helper.py`), the host checking nothing of that; and only where what
    it lands asks the operator nothing they haven't approved, which the host
    reads from its diff (`Remotes.asking`, `remote/protocol.py`). Branches land
    there: `delete-merged` deletes a branch whose commits are all in a gated one
    on the remote, but a running branch the host computes, whose history holds
    what's on trial (`Remotes.trying`), and never a gated one."""

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
    """A control request: its `kind` names it, and the handler that answers it.

    Each kind says whether it only reads, a keyword of its class with no
    default (`class ListLaunches(Request, reads=True)`), so a kind declared
    without it fails as its module is imported. One that reads changes nothing
    in answering, and a room is served it for its own repository alone
    (`Reading`, `host/service.py`); one that writes never reaches a room from
    the control socket.
    """

    kind: str
    reads: ClassVar[bool]
    """Whether answering it changes nothing, as its class says."""

    def __init_subclass__(cls, *, reads: bool, **kwargs: Unpack[ConfigDict]) -> None:
        """Keep whether the kind only reads, as its class says, with pydantic's own keywords passed on."""
        super().__init_subclass__(**kwargs)
        cls.reads = reads

    @classmethod
    def named(cls) -> str:
        """Return the kind this model's requests carry, its `kind` field's default.

        A model built without validation holds its defaults, so a request's kind is
        read from its model rather than spelled again where it's routed.
        """
        return cls.model_construct().kind


class Spawner(Model):
    """Who started a launch through lup's `spawn`, as the host recorded it from their call, never as a room names it: their launch, their conversation, and the concern they handed over with it (`docs/launch.md`, *An agent's spawn*)."""

    launch: LaunchId
    """The launch whose session called `spawn`, as the host served it."""
    conversation: Conversation
    """The conversation that called it, as the inbox keys them: the spawned
    session's parent, who hears of it as a parent hears of a subagent."""
    concern: int | None = None
    """The thread handed to the spawned session with it, by its number, which it
    holds and works in, and where its reports land: a concern handed over to
    build. None for a side job, whose report comes back to its spawner."""


class Behind(Model):
    """The host code a launch an agent spawned runs, where the running branch's tip holds another nobody approved, which it asked nothing about (`Trust.asking`): the commit of each."""

    running: str
    """The commit of the copy approved, which judges its session."""
    tip: str
    """The commit of the tip's host zone, unapproved."""


class Register(Request, reads=False):
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
    container: str | None = None
    """The name of the launch's container, which tells the sweep whether its
    session still runs: none in a launcher's request, which the service names
    after the launch's repository and name (`container_name`) and renames with
    it, where podman has it there to rename."""
    limits: Limits
    """What the host does with the operator's credentials for the launch
    without asking, from the declaration at the commit the operator approved:
    recorded with the launch, so a service started again keeps them."""
    github: GitHubRepository | None
    """The repository on GitHub, as `gh` named it from the repository's own
    remote, in its git directory, when the launch started: the one repository
    lup's GitHub tools act on for the launch, never one the room names. None
    where it couldn't be named, which the launch said."""
    runner: list[str] | None = None
    """What the room puts before a tool of the project's environment, as the
    declaration at the commit the operator approved runs one
    (`Runner.command([])`): `land` runs `lup-dev merge` behind it in the room.
    None in a record from before launches kept it, which `land` merges nothing
    for."""
    environments: AbsolutePath | None = None
    """The launch's own environments, one per worktree, outside the repository,
    where its room has environments of its own (`docs/launch.md`, *The
    project's environment, the room's own*): the judge reads each worktree's
    there, for the launch's hooks, rather than where the runner names the
    host's (`Runner.venv`). None where the room has none, and in a record from
    before launches had them."""
    home: AbsolutePath | None = None
    """The history its runtime's sessions share with the other rooms given it
    (`docs/launch.md`, *A home of the rooms' own*): where the host reads a
    launched session's record, and what a path a hook names under the launch's
    own runtime directory (`own`) is read in. None in a record from before
    launches kept it."""
    own: AbsolutePath | None = None
    """The runtime's own directory for the launch, which the room writes, links
    into `home` among it: a path a hook names inside it is read as the same
    place in `home`, never through it (`lup_dev.host.homes.translated`)."""
    name: Name | None = None
    """Its name, as it stands: the one asked at registration, made unique
    (`exact`), and each rename since. None in a record from before launches
    had names, which the service names after its worktree."""
    exact: bool = False
    """Whether the name was asked for as it is (`--name`), so registering
    refuses where another launch holds it; otherwise `-2`, `-3` is added until
    it's free."""
    held: bool = False
    """Whether its session is held by its launcher with no terminal
    (`docs/launch.md`, *A session held with no terminal*): the host wakes it
    through its launcher's socket, which an interrupt and its end go through
    too, and the sweep stops its room once its launcher is gone. False for a
    session in a terminal, and in a record from before launches were held."""
    spawner: Spawner | None = None
    """Who started it through lup's `spawn`, as the host recorded it from their
    call: its session's own conversation is theirs, as a subagent is their
    parent's. None for a launch the operator started, and in a record from
    before agents spawned."""
    model: str | None = None
    """The model its runtime's arguments named (`--model`), as its launcher was
    given them, never the room: what the sessions it spawns run on. None where
    they named none, the profile's then choosing."""
    session: str | None = None
    """The runtime's id for a held launch's session, which its launcher named
    up front: the one session its hooks may name, so a room's hook can't speak
    as another session of the repository's, a spawner among them. None for a
    terminal's, whose session the operator may clear and the runtime names."""
    behind: Behind | None = None
    """Where an agent spawned the launch, and the tip's host zone isn't the one
    approved: the copy approved it runs, which its session is told as it
    starts, so an agent needing the newer can ask the operator for it. None
    where it runs the tip's."""


class Rename(Request, reads=False):
    """Rename a launch the service serves, refused where another holds the name."""

    kind: Literal["rename"] = "rename"
    launch: LaunchId
    name: Name


class SetHolding(Request, reads=False):
    """Turn the operator's switch for one conversation on or off: whether each flagged write of theirs is held."""

    kind: Literal["set-holding"] = "set-holding"
    launch: LaunchId
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's own conversation."""
    on: bool


class ShowHolding(Request, reads=True):
    """Say whether the operator holds each flagged write of one conversation, as the judge asks."""

    kind: Literal["show-holding"] = "show-holding"
    runtime: str
    session: str
    agent: str | None = None


class Unregister(Request, reads=False):
    """End a launch: its sockets closed, its directory and record removed."""

    kind: Literal["unregister"] = "unregister"
    launch: LaunchId


class ListLaunches(Request, reads=True):
    """List the launches the service serves."""

    kind: Literal["list"] = "list"


class Stop(Request, reads=False):
    """Stop the service; the launches it serves stay recorded, for the next to serve."""

    kind: Literal["stop"] = "stop"


class Reply(Model):
    """The service's answer to one request, told apart by its `kind`."""

    kind: str


class Registered(Reply):
    """The launch is served: its socket directory, which its room mounts, the name it took, and its container's."""

    kind: Literal["registered"] = "registered"
    directory: Path
    name: Name
    container: str
    """The name its launcher runs its container by."""


class Holding(Reply):
    """Whether the operator holds each flagged write of a conversation."""

    kind: Literal["holding"] = "holding"
    on: bool


class Renamed(Reply):
    """The launch is renamed: as it stands."""

    kind: Literal["renamed"] = "renamed"
    launch: Register


class Activity(Model):
    """What a conversation is doing, as their latest hook said, and since when."""

    state: Literal["calling", "idle", "ended"]
    """Running a call; between calls, their turn running or ended; or ended, a
    subagent whose conversation is over."""
    since: datetime
    tool: str | None = None
    """The tool their running call calls, by their runtime's name; none between calls."""
    lups: bool = False
    """Whether their running call is to one of lup's tools, which may hold it
    until the operator answers."""


class Talker(Model):
    """A conversation of a launch, as the operator is shown them: how they're called, the runtime's ids, their kind, their parent and what they're doing."""

    path: str
    """Their launch's name, then each subagent's down to them
    (`dev/explore-auth`); an unnamed subagent by their kind and id."""
    own: str
    """Their own part of `path`: their launch's name for the session's own
    conversation, a subagent's name, or their kind and id."""
    session: str
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's own conversation."""
    kind: str | None = None
    parent: str | None = None
    """Their parent's path; none for the session's own conversation."""
    depth: int = 0
    """How many spawns below their session's own conversation they are: 0 for that
    conversation, 1 for a subagent it spawned."""
    activity: Activity | None = None
    """None until one of their hooks is heard."""
    holding: bool = False
    """Whether the operator holds each flagged write of theirs."""


class Drawn(Model):
    """A view a module places in a drawer, with its module: what the page lists under each agent's banner."""

    module: str
    """The module's name."""
    view: str
    """The view's name: its method's, which the drawer's fold kind is named for."""
    place: Drawer


class Bannered(Model):
    """A view a module places on each agent's banner, with its module: a part of the banner's line (`lup.Banner`)."""

    module: str
    """The module's name."""
    view: str
    """The view's name: its method's."""


class Looks(Model):
    """How a repository's modules' views look: their fold kinds, their tones, the drawers they place, and the parts of the banner, the core's first."""

    folds: list[FoldKind] = []
    tones: list[Tone] = []
    drawers: list[Drawn] = []
    """In the order the page lays them under a banner."""
    banners: list[Bannered] = []
    """In the order the page says them on a banner, after what the core says
    of the agent."""
    verbs: list[Verb] = []
    """The verbs the review's keys say, Space and a key, the core's first."""


class Listed(Reply):
    """The launches the service serves, each as it stands, the name each session of theirs last had, and each launch's conversations."""

    kind: Literal["listed"] = "listed"
    launches: list[Register]
    sessions: dict[str, Name] = {}
    """By the runtime's id for each session the service has heard start, the
    name of its launch as it last stood: how the operator's inbox names who
    sent an item."""
    talkers: dict[str, list[Talker]] = {}
    """By launch id, its latest session's conversations: the session's own
    first, then each subagent under their parent."""
    running: dict[str, bool] | None = None
    """By launch id, whether its container runs, as the host's podman says: for
    a room, which has no podman to ask; none for the operator's terminal, which
    asks podman itself."""
    looks: dict[Path, Looks] = {}
    """By repository's git directory, how its modules' views look, as its
    process said when it last started: the page draws their fold kinds, tones
    and drawers from them. A repository whose process hasn't started since the
    service did has none yet: `standing` stands in for it."""
    standing: Looks = Looks()
    """How the views of lup's default declaration look, as the host's own lup
    resolves it: what the page draws a repository's by until its process says
    its own, as after each start of the service."""


class Done(Reply):
    """The request is carried out, with nothing more to say."""

    kind: Literal["done"] = "done"


class Refused(Reply):
    """The request wasn't carried out, and why."""

    kind: Literal["refused"] = "refused"
    error: str
