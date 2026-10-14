"""git's pushes and fetches on the host for a launch's room: the remote helper's requests, and their handlers.

`docs/host-tools.md`, *git through a remote helper*. The room's helper
(`remote/helper.py`) sends one request per batch git hands it, on the launch's
`request.sock`, and the service answers with the launch it knows by the socket
(`host/rooms.py`). Where git runs, and to which remote, is the host's word:
- git runs in the repository's own git directory, which the launcher found
  before the room started (`Register.repository`), named explicitly, never
  discovered from a directory the room writes;
- the remote is one the repository's `config` names, which the room can't
  write, and its URL is git's for it there (`git remote get-url`). Anything else
  is refused: a URL, or a name only a file of the room's defines, since git
  still reads a remote from `remotes/` or `branches/` in the git directory;
- each update is held to the launch's limits (`Register.limits`) before git
  runs: a forced one (`+`, `option force`, a lease), a deletion, or one to a
  protected ref is refused where the declaration doesn't allow it, saying why;
- each is pushed by object id, one at a time (together where git asked for an
  atomic push), forced only where the limits allow it and git asked, so the
  forge refuses a push that isn't a fast-forward too. The objects are already in
  the repository's store, which the room shares;
- a fetch brings the names asked for into that store, writing no ref, after
  which each object asked for must be there; the room's git writes its own refs;
- neither runs unless the store is self-contained: no `objects/info/alternates`
  or `objects/info/http-alternates`, and no symbolic link anywhere under
  `objects/`, through which the room could have git read, and send, another
  repository's objects (`docs/field-notes.md`, *Host-side git in a repository
  the room writes*).

git runs with replace refs ignored, automatic maintenance, hooks and
`core.fsmonitor` off, and submodules never followed, each spawned through
asyncio and awaited on the service's event loop, as each judge is
(`host/service.py`, `judged`). The operator's credentials are the service's
environment. Each push and fetch is said in the service's log, with git's
standard error once.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Annotated, Literal, override

from pydantic import AfterValidator

from lup.types import Model
from lup_dev.host.protocol import Action, HostError, Register, Reply, Request
from lup_dev.host.rooms import RoomHandler, RoomRoute
from lup_dev.host.service import Asked, Judged, judged

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def object_id(value: str) -> str:
    """Return `value` if it's a whole object id: 40 hexadecimal digits, or 64 in a SHA-256 repository.

    >>> object_id("ab" * 20) == "ab" * 20
    True
    """
    try:
        digits = bytes.fromhex(value)
    except ValueError as unread:
        message = f"an object id is hexadecimal digits, not {value!r}"
        raise ValueError(message) from unread
    if len(value) != 2 * len(digits) or len(digits) not in [20, 32]:
        message = f"an object id is 40 or 64 hexadecimal digits, not {value!r}"
        raise ValueError(message)
    return value


type ObjectId = Annotated[str, AfterValidator(object_id)]
"""A whole object id, as git names an object."""


def full_ref(value: str) -> str:
    """Return `value` if it's a ref's full name: git would read a short one as whichever of the remote's refs it matches.

    >>> full_ref("refs/heads/main")
    'refs/heads/main'
    """
    if not value.startswith("refs/"):
        message = f"a destination is a ref's full name, `refs/…`, not {value!r}"
        raise ValueError(message)
    return value


type RefName = Annotated[str, AfterValidator(full_ref)]
"""A ref's full name, such as `refs/heads/main`."""


def listed_name(value: str) -> str:
    """Return `value` if it names a ref as a remote lists it: `HEAD`, or a full name holding no `:`.

    A `:` would make a fetch's refspec write a ref.

    >>> listed_name("HEAD")
    'HEAD'
    """
    if value != "HEAD" and not value.startswith("refs/"):
        message = f"a ref a remote lists is `HEAD` or `refs/…`, not {value!r}"
        raise ValueError(message)
    if ":" in value:
        message = f"a ref's name holds no `:`, unlike {value!r}"
        raise ValueError(message)
    return value


type ListedName = Annotated[str, AfterValidator(listed_name)]
"""A ref's name as a remote lists it: `HEAD`, or a full name."""


def remote_name(value: str) -> str:
    """Return `value` if it can name a remote: not empty, and not read as one of git's options.

    >>> remote_name("origin")
    'origin'
    """
    if not value or value.startswith("-"):
        message = f"a remote's name isn't empty and doesn't start with `-`: {value!r}"
        raise ValueError(message)
    return value


type RemoteName = Annotated[str, AfterValidator(remote_name)]
"""A remote, by its name in the repository's `config`."""


class Listing(Request):
    """List a remote's refs: what git asks a helper with `list`, or with `list for-push` before a push."""

    kind: Literal["remote-list"] = "remote-list"
    remote: RemoteName
    for_push: bool = False
    """Asked before a push: listed from the remote's push URL, and allowed by
    `push`; otherwise from its URL, and allowed by `fetch`."""


class Ref(Model):
    """One ref a remote lists: its name, and the object it names."""

    object: ObjectId
    name: str


class Advertised(Reply):
    """A remote's refs, as `git ls-remote` lists them."""

    kind: Literal["remote-advertised"] = "remote-advertised"
    refs: list[Ref]


class Update(Model):
    """One ref a push updates: the object it's to name, and whether git was asked to force it."""

    source: ObjectId | None
    """The object, as the room resolved what git named; none for a deletion."""
    destination: RefName
    forced: bool = False
    """Its refspec began with `+`."""


class Lease(Model):
    """`--force-with-lease` for one ref: the object it must name on the remote for the push to replace it."""

    ref: RefName
    expected: ObjectId
    """All zeros where the ref mustn't exist yet."""


class Pushing(Request):
    """Push one batch of updates to a remote, with the options git set for it."""

    kind: Literal["remote-push"] = "remote-push"
    remote: RemoteName
    updates: list[Update]
    force: bool = False
    """git's `option force`: every update forced."""
    leases: list[Lease] = []
    """git's `option cas`, one per ref leased."""
    dry_run: bool = False
    atomic: bool = False
    """Every update or none."""
    push_options: list[str] = []
    """Each `--push-option`, for the forge."""


class Updated(Model):
    """How one update ended: its ref, and why it wasn't made, where it wasn't."""

    destination: str
    error: str | None = None
    """Why, in one line: lup's reason where the limits refused it, git's own
    words where git did."""


class Pushed(Reply):
    """How each update of a push ended, in the order asked."""

    kind: Literal["remote-pushed"] = "remote-pushed"
    updates: list[Updated]


class Wanted(Model):
    """One object a fetch is for, and the ref the remote listed it as."""

    object: ObjectId
    name: ListedName


class Fetching(Request):
    """Fetch the objects git asked for into the repository's store, as the remote's refs name them."""

    kind: Literal["remote-fetch"] = "remote-fetch"
    remote: RemoteName
    wanted: list[Wanted]


class Fetched(Reply):
    """Every object asked for is in the repository's store."""

    kind: Literal["remote-fetched"] = "remote-fetched"


def stray(objects: Path) -> list[Path]:
    """List what has the object store at `objects` read objects from elsewhere: its alternates files, and every symbolic link in it.

    One look covers every way measured: alternates absolute, relative or nested,
    and a pack linked in from another repository with no alternates at all.
    """
    if objects.is_symlink():
        return [objects]
    alternates = [
        path
        for path in [
            objects / "info" / "alternates",
            objects / "info" / "http-alternates",
        ]
        if path.exists() or path.is_symlink()
    ]
    linked = [
        directory / name
        for directory, folders, files in objects.walk()
        for name in [*folders, *files]
        if (directory / name).is_symlink()
    ]
    return [*alternates, *linked]


def denied(action: Action, launch: Register) -> str | None:
    """Say why `launch`'s limits don't allow `action`, or none where they do."""
    if action in launch.limits.actions:
        return None
    return (
        f"`{action}` isn't among the actions the project's declaration allows "
        "(`Core.credentials`): it's the operator's"
    )


def refusal(update: Update, *, forced: bool, launch: Register) -> str | None:
    """Say why `launch`'s limits refuse `update`, or none where they allow it.

    `forced` is whether it's forced: its own `+`, git's `option force`, or a
    lease on its ref. A protected ref's pattern is read as git's own glob, `*`
    spanning `/`, case and all.
    """
    protected = [
        pattern
        for pattern in launch.limits.protected
        if fnmatchcase(update.destination, pattern)
    ]
    if protected:
        return (
            f"`{update.destination}` is protected by the project's declaration "
            f"(`Core.credentials`, `{protected[0]}`): updating it is the operator's"
        )
    if update.source is None:
        denial = denied("delete-ref", launch)
        return None if denial is None else f"deleting `{update.destination}`: {denial}"
    if forced:
        denial = denied("force-push", launch)
        return (
            None
            if denial is None
            else (
                f"a forced update of `{update.destination}` (`+`, `--force` or "
                f"`--force-with-lease`): {denial}. A fast-forward pushes"
            )
        )
    return None


def oneline(said: str) -> str:
    r"""Return what git said as one line, its words as it wrote them.

    >>> oneline("error: failed\nhint: pull first\n")
    'error: failed hint: pull first'
    """
    return " ".join(said.split())


class Remotes(Model, arbitrary_types_allowed=True):
    """git on the host for each launch's room: in its repository's own git directory, to that repository's own remotes."""

    say: Callable[[str], None]
    """Where each push and fetch is said: the service's log."""
    run: Callable[[Asked], Awaitable[Judged]] = judged
    """Runs one git command to its end on the service's event loop."""

    async def git(self, launch: Register, *arguments: str) -> Judged:
        """Run git in `launch`'s repository's own git directory, named, with what it could be led into turned off."""
        repository = str(launch.repository)
        return await self.run(
            Asked(
                command=[
                    "git",
                    "-C",
                    repository,
                    f"--git-dir={repository}",
                    "--no-replace-objects",
                    "-c",
                    "gc.auto=0",
                    "-c",
                    "maintenance.auto=false",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    f"core.hooksPath={os.devnull}",
                    *arguments,
                ],
                payload="",
            )
        )

    async def url(self, launch: Register, remote: str, *, push: bool) -> str:
        """Return the URL of the remote named `remote` in `launch`'s repository, as git reads it there for a push or a fetch.

        Raise `HostError` where the repository's `config` names no such remote.
        """
        named = await self.git(
            launch, "config", "--local", "--get-all", f"remote.{remote}.url"
        )
        if named.status != 0:
            message = (
                f"`{remote}` isn't one of the remotes {launch.repository}'s `config` "
                "names, so lup pushes and fetches nothing there: name one of them, "
                "as `git push origin` does"
            )
            raise HostError(message)
        found = await self.git(
            launch, "remote", "get-url", *(["--push"] if push else []), remote
        )
        if found.status != 0:
            message = f"git couldn't say `{remote}`'s URL: {oneline(found.error)}"
            raise HostError(message)
        return found.output.strip()

    async def contained(self, launch: Register) -> None:
        """Refuse to go on, with `HostError`, unless `launch`'s repository's object store is self-contained."""
        found = await asyncio.to_thread(stray, launch.repository / "objects")
        if found:
            named = ", ".join(str(each) for each in found)
            message = (
                "lup pushes and fetches nothing while the repository's object store "
                f"reads objects from outside it ({named}): a room could have git "
                "send another repository's objects through them, with your "
                "credentials. A repository sharing its store through alternates "
                "can't push or fetch from a room"
            )
            raise HostError(message)

    def told(self, launch: Register, what: str, ran: Judged) -> None:
        """Say what one git command did for `launch`, with what git wrote to its standard error, once."""
        outcome = "done" if ran.status == 0 else f"failed (status {ran.status})"
        said = ran.error.strip()
        self.say(
            f"{launch.launch}: {what}: {outcome}"
            + (f". git said:\n{said}" if said else "")
        )


class ListHandler(Model, RoomHandler[Listing]):
    """Answers `Listing`: the remote's refs, by `git ls-remote` on its URL."""

    remotes: Remotes

    @override
    def request(self) -> type[Listing]:
        return Listing

    @override
    async def answer(self, request: Listing, launch: Register) -> Reply:
        denial = denied("push" if request.for_push else "fetch", launch)
        if denial is not None:
            raise HostError(denial)
        url = await self.remotes.url(launch, request.remote, push=request.for_push)
        ran = await self.remotes.git(launch, "ls-remote", "--end-of-options", url)
        if ran.status != 0:
            self.remotes.told(launch, f"listing `{request.remote}` ({url})", ran)
            message = f"git couldn't list `{request.remote}`: {oneline(ran.error)}"
            raise HostError(message)

        def read() -> Iterator[Ref]:
            for line in ran.output.splitlines():
                match line.split():
                    case [listed, name]:
                        yield Ref(object=listed, name=name)
                    case _:
                        message = (
                            f"git ls-remote listed {line!r}, not an object and a "
                            "ref's name"
                        )
                        raise HostError(message)

        return Advertised(refs=list(read()))


class PushHandler(Model, RoomHandler[Pushing]):
    """Answers `Pushing`: each update held to the launch's limits, then pushed by object id to the remote's push URL."""

    remotes: Remotes

    @override
    def request(self) -> type[Pushing]:
        return Pushing

    @override
    async def answer(self, request: Pushing, launch: Register) -> Reply:
        """Push each update the limits allow, and say how each ended.

        An atomic push with an update refused pushes none of them.
        """
        denial = denied("push", launch)
        if denial is not None:
            raise HostError(denial)
        leases = {lease.ref: lease for lease in request.leases}

        async def why(update: Update) -> str | None:
            checked = await self.remotes.git(
                launch, "check-ref-format", update.destination
            )
            if checked.status != 0:
                return f"`{update.destination}` isn't a ref's name git accepts"
            forced = request.force or update.forced or update.destination in leases
            return refusal(update, forced=forced, launch=launch)

        reasons = [await why(update) for update in request.updates]
        refused = {
            update.destination: reason
            for update, reason in zip(request.updates, reasons, strict=True)
            if reason is not None
        }
        for destination, reason in refused.items():
            self.remotes.say(
                f"{launch.launch}: refused a push to `{destination}` on "
                f"`{request.remote}`: {reason}"
            )
        allowed = [each for each in request.updates if each.destination not in refused]
        if refused and (request.atomic or not allowed):
            first = next(iter(refused))
            held = f"not pushed: the push is atomic, and `{first}` was refused"
            return Pushed(
                updates=[
                    Updated(
                        destination=each.destination,
                        error=refused.get(each.destination, held),
                    )
                    for each in request.updates
                ]
            )
        await self.remotes.contained(launch)
        url = await self.remotes.url(launch, request.remote, push=True)
        batches = [allowed] if request.atomic else [[each] for each in allowed]
        errors = [
            await self.pushed(request, launch, url, leases, batch) for batch in batches
        ]
        pushed = {
            each.destination: error
            for batch, error in zip(batches, errors, strict=True)
            for each in batch
        }
        return Pushed(
            updates=[
                Updated(
                    destination=each.destination,
                    error=refused.get(each.destination, pushed.get(each.destination)),
                )
                for each in request.updates
            ]
        )

    async def pushed(
        self,
        request: Pushing,
        launch: Register,
        url: str,
        leases: dict[str, Lease],
        batch: list[Update],
    ) -> str | None:
        """Push `batch` in one `git push`, and return why it failed, or none where it didn't."""

        def refspec(update: Update) -> str:
            forced = (
                request.force or update.forced
            ) and update.destination not in leases
            source = update.source or ""
            return f"{'+' if forced else ''}{source}:{update.destination}"

        held = [
            leases[each.destination] for each in batch if each.destination in leases
        ]
        ran = await self.remotes.git(
            launch,
            "push",
            "--no-verify",
            "--no-recurse-submodules",
            *(["--dry-run"] if request.dry_run else []),
            *(["--atomic"] if request.atomic else []),
            *(f"--push-option={option}" for option in request.push_options),
            *(f"--force-with-lease={lease.ref}:{lease.expected}" for lease in held),
            "--end-of-options",
            url,
            *(refspec(each) for each in batch),
        )
        updates = ", ".join(
            f"{each.source or 'deletion'} to {each.destination}" for each in batch
        )
        self.remotes.told(
            launch, f"pushing {updates} on `{request.remote}` ({url})", ran
        )
        if ran.status == 0:
            return None
        return oneline(ran.error) or f"git push ended with status {ran.status}"


class FetchHandler(Model, RoomHandler[Fetching]):
    """Answers `Fetching`: the names asked for fetched from the remote's URL into the repository's store, writing no ref."""

    remotes: Remotes

    @override
    def request(self) -> type[Fetching]:
        return Fetching

    @override
    async def answer(self, request: Fetching, launch: Register) -> Reply:
        denial = denied("fetch", launch)
        if denial is not None:
            raise HostError(denial)
        await self.remotes.contained(launch)
        url = await self.remotes.url(launch, request.remote, push=False)
        names = list(dict.fromkeys(each.name for each in request.wanted))
        ran = await self.remotes.git(
            launch,
            "fetch",
            "--no-write-fetch-head",
            "--no-tags",
            "--no-recurse-submodules",
            "--end-of-options",
            url,
            *names,
        )
        wanted = ", ".join(f"{each.object} as {each.name}" for each in request.wanted)
        self.remotes.told(
            launch, f"fetching {wanted} from `{request.remote}` ({url})", ran
        )
        if ran.status != 0:
            message = (
                f"git couldn't fetch from `{request.remote}`: {oneline(ran.error)}"
            )
            raise HostError(message)
        missing = [
            each
            for each in request.wanted
            if (await self.remotes.git(launch, "cat-file", "-e", each.object)).status
            != 0
        ]
        if missing:
            moved = ", ".join(each.name for each in missing)
            message = (
                f"{moved} moved on `{request.remote}` since git listed it, so the "
                "object it named isn't fetched: fetch again"
            )
            raise HostError(message)
        return Fetched()


def routes(remotes: Remotes) -> list[RoomRoute]:
    """Return the routes of git's remote helper on each launch's `request.sock`: listing, pushing and fetching."""
    return [
        RoomRoute.to(ListHandler(remotes=remotes)),
        RoomRoute.to(PushHandler(remotes=remotes)),
        RoomRoute.to(FetchHandler(remotes=remotes)),
    ]
