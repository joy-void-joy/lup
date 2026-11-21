"""`Remotes`: each project's part pushing and fetching for its rooms, with the operator's credentials, within what its declaration allows.

It runs in a container of its own, from the commit the operator approved,
holding the project's git directory and the operator's SSH agent alone
(`GitDirectory`, `SshAgent`), so what it reads of a store a room wrote reaches
one project's directory. A room's git reaches it through `git-remote-lup`,
which turns each batch git hands a remote helper into one call here
(`README.md` here):
- **Where it pushes is the repository's word,** never the room's: a remote the
  repository's `config` names, which no room writes, each of its push URLs; a
  URL from the room, or a name only a file of the room's defines, is refused.
- **Each update is held to the declaration's limits** before git runs: a forced
  one, a deletion, the integration branch, the release branch, a protected ref.
- **What it publishes is told first** (`Publishing`): each commit the remote
  lacks, one event each, and the ref's name; a refusal there keeps it from
  leaving.
- **It pushes by object id** from a store holding its own objects alone, never
  forcing an update git didn't force.
"""

import difflib
from typing import Annotated

from pydantic import AfterValidator

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Agent, Machine
from lup.doors.parts import Declared, GitDirectory, Part, Program, SshAgent
from lup.landing.module import Landing
from lup.programs.git.answers import nul_separated, tab_separated
from lup.programs.git.running import Git
from lup.programs.git.stores import Store
from lup.publishing.events import Changed, Commit, Line, Publishing, Push
from lup.types import Model
lazy from lup.remote.module import Remote


def object_id(value: str) -> str:
    """Return `value` where it's a whole object id: 40 hexadecimal digits, or 64 in a SHA-256 repository.

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


def full_ref(value: str) -> str:
    """Return `value` where it's a ref's full name: git would read a short one as whichever of the remote's refs it matches.

    >>> full_ref("refs/heads/feat")
    'refs/heads/feat'
    """
    if not value.startswith("refs/"):
        message = f"a ref is named in full, `refs/…`, not {value!r}"
        raise ValueError(message)
    return value


def listed_name(value: str) -> str:
    """Return `value` where it names a ref as a remote lists it: `HEAD`, or a full name holding no `:`, which would make a fetch write a ref.

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


def remote_name(value: str) -> str:
    """Return `value` where it can name a remote: not empty, and not read as one of git's options.

    >>> remote_name("origin")
    'origin'
    """
    if not value or value.startswith("-"):
        message = f"a remote's name isn't empty and doesn't start with `-`: {value!r}"
        raise ValueError(message)
    return value


type ObjectId = Annotated[str, AfterValidator(object_id)]
"""A whole object id, as git names an object."""
type RefName = Annotated[str, AfterValidator(full_ref)]
"""A ref's full name, such as `refs/heads/feat`."""
type ListedName = Annotated[str, AfterValidator(listed_name)]
"""A ref's name as a remote lists it: `HEAD`, or a full name."""
type RemoteName = Annotated[str, AfterValidator(remote_name)]
"""A remote, by its name in the repository's `config`."""


class Listing(Model):
    """A remote's refs, asked for: git's `list` to a remote helper, or `list for-push` before a push."""

    remote: RemoteName
    for_push: bool = False
    """Asked before a push: listed from the remote's push URL; otherwise from
    its URL."""


class Ref(Model):
    """One ref a remote lists: the object it names, and its name."""

    object: ObjectId
    name: str


class Listed(Model):
    """A remote's refs, as it lists them."""

    refs: list[Ref] = []


class Update(Model):
    """One ref a push updates: the object it's to name, none for a deletion, and whether git was asked to force it."""

    source: ObjectId | None
    destination: RefName
    forced: bool = False
    """Its refspec began with `+`."""


class Lease(Model):
    """`--force-with-lease` on one ref: the object it must name on the remote for the push to replace it, all zeros where it mustn't be there yet."""

    ref: RefName
    expected: ObjectId


class Updates(Model):
    """One batch of updates git asked a remote helper to push, with the options it set for them."""

    remote: RemoteName
    updates: list[Update]
    force: bool = False
    """git's `option force`: every update forced."""
    leases: list[Lease] = []
    """git's `option cas`, one for each ref leased."""
    dry_run: bool = False
    atomic: bool = False
    """Every update, or none."""
    push_options: list[str] = []
    """Each `--push-option`, for the remote."""


class Updated(Model):
    """How one update ended: its ref, and why it wasn't made, in one line, where it wasn't."""

    destination: str
    error: str | None = None


class Pushed(Model):
    """How each update of a push ended, in the order asked, and what the room is told beside them: each refusal at `Publishing`, whole."""

    updates: list[Updated]
    said: str = ""
    """What git's standard error shows before each ref's line, since git
    shows one line a ref."""


class Wanted(Model):
    """One object a fetch is for, and the ref the remote listed it as."""

    object: ObjectId
    name: ListedName


class Fetching(Model):
    """The objects git asked a remote helper to fetch, as the remote's refs name them."""

    remote: RemoteName
    wanted: list[Wanted]


class Fetched(Model):
    """Every object asked for is in the repository's store."""


class Verdict(Model):
    """What came of holding one update to the limits and telling what it publishes: why it's refused, none where it isn't, and what a part hearing `Publishing` said refusing it."""

    why: str | None = None
    said: str = ""


class Remotes(Part):
    """Each project's part pushing and fetching for its rooms, with the operator's credentials: a room's git reaches it through `git-remote-lup`."""

    module: Remote
    repository: GitDirectory
    agent: SshAgent
    declared: Declared
    git: Program = Program(
        name="git",
        optional=True,
        why="pushes and fetches for the project's rooms",
        install="https://git-scm.com",
    )
    ssh: Program = Program(
        name="ssh",
        optional=True,
        package="openssh",
        why="reaches a remote through the operator's SSH agent, as git runs it",
        install="https://www.openssh.com",
    )
    quiet: list[str] = [
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
        "-c",
        "submodule.recurse=false",
        "-c",
        "fetch.recurseSubmodules=false",
    ]
    """What git is given before a push or a fetch: no maintenance started that
    would outlive it, and no submodule followed, whose `config` a room
    writes."""

    def store(self) -> Store:
        """Return the project's store, git pinned to it, reaching remotes through the operator's agent."""
        git = Git(through=self.git)
        variables = {**git.variables, **self.agent.variables()}
        return Store(
            git=git.model_copy(update={"variables": variables}),
            common=self.repository.path,
        )

    def landing(self) -> Landing | None:
        """Return the project's landing, which names the integration branch and the release branch; none where it lands nothing."""
        return next(
            (each for each in self.declared.modules if isinstance(each, Landing)), None
        )

    def require(self, action: str) -> None:
        """Refuse `action` where the declaration doesn't allow it, saying that allowing it is the operator's call."""
        if action not in self.module.allowed():
            message = (
                f"the project's declaration doesn't allow `{action}` with the "
                "operator's credentials (`Remote.actions`), and allowing it is "
                "the operator's call"
            )
            raise RefusedError(message)

    async def urls(self, remote: str, *, push: bool) -> list[str]:
        """Return where `remote` is pushed to, each of its push URLs, or fetched from, its first URL, as the repository's own `config` names them, never a file of the room's.

        Raise `RefusedError` where the `config` names no such remote.
        """
        store = self.store()

        async def values(key: str) -> list[str]:
            ran = await store.ran("config", "--local", "-z", "--get-all", key)
            return nul_separated(ran.output) if ran.status == 0 else []

        urls = await values(f"remote.{remote}.url")
        if not urls:
            message = (
                f"`{remote}` isn't one of the remotes the repository's `config` names, "
                "so lup pushes and fetches nothing there: name one of them, as "
                "`git push origin` does"
            )
            raise RefusedError(message)
        if not push:
            return [urls[0]]
        return await values(f"remote.{remote}.pushurl") or urls

    async def refs_at(self, url: str) -> list[Ref]:
        """List the refs of the remote at `url`, as it lists them.

        Raise `RefusedError` where git can't.
        """
        ran = await self.store().done("ls-remote", url, within=Git().crossing)
        refs: list[Ref] = []
        for row in tab_separated(ran.text()):
            match row:
                case [named, name]:
                    refs = [*refs, Ref(object=named, name=name)]
                case _:
                    message = f"git ls-remote listed {row!r}, not an object and a ref"
                    raise RefusedError(message)
        return refs

    @lup.service
    async def listed(self, listing: Listing, by: Agent | Machine) -> Listed:
        """List a remote's refs, as git asks a remote helper to: from its push URL before a push, else from its URL."""
        del by
        self.require("push" if listing.for_push else "fetch")
        [url, *_] = await self.urls(listing.remote, push=listing.for_push)
        return Listed(refs=await self.refs_at(url))

    @lup.service
    async def fetched(self, fetching: Fetching, by: Agent | Machine) -> Fetched:
        """Fetch the objects a remote's refs name into the repository's store, writing no ref, as git asks a remote helper to: the room's git writes its own.

        Refused where the store reads objects from outside it, or a ref moved
        on the remote since it was listed, so what's asked isn't there.
        """
        del by
        self.require("fetch")
        store = self.store()
        if not store.self_contained():
            raise RefusedError(UNCONTAINED)
        [url] = await self.urls(fetching.remote, push=False)
        names = list(dict.fromkeys(each.name for each in fetching.wanted))
        await store.done(
            *self.quiet,
            "fetch",
            "--no-recurse-submodules",
            "--no-write-fetch-head",
            "--no-tags",
            "--quiet",
            url,
            *names,
            within=Git().crossing,
        )
        missing = [
            each
            for each in fetching.wanted
            if (await store.ran("cat-file", "-e", each.object)).status != 0
        ]
        if missing:
            moved = ", ".join(f"`{each.name}`" for each in missing)
            message = (
                f"{moved} moved on `{fetching.remote}` since it was listed: fetch again"
            )
            raise RefusedError(message)
        return Fetched()

    @lup.service
    async def pushed(self, updates: Updates, by: Agent | Machine) -> Pushed:
        """Push each update the declaration allows, by object id, to each of the remote's push URLs, and say how each ended.

        Before anything leaves, each update is held to the limits, a deletion
        of a branch that hasn't landed refused, and what it publishes told at
        `Publishing`, where a refusal keeps it from leaving. An atomic push
        with an update refused pushes none.
        """
        self.require("push")
        store = self.store()
        if not store.self_contained():
            raise RefusedError(UNCONTAINED)
        urls = await self.urls(updates.remote, push=True)
        held = await self.refs_at(urls[0])

        async def verdict(update: Update) -> Verdict:
            why = await self.refusal(update, updates, by, held)
            if why is not None:
                return Verdict(why=why)
            if update.source is None:
                return Verdict()
            said = await self.published(update, updates.remote, held)
            if said is None:
                return Verdict()
            return Verdict(
                why=(
                    "refused by lup: it would publish what isn't published, at the "
                    "places said above"
                ),
                said=said,
            )

        verdicts = [await verdict(each) for each in updates.updates]
        refused = {
            update.destination: each.why
            for update, each in zip(updates.updates, verdicts, strict=True)
            if each.why is not None
        }
        said = "\n".join(each.said for each in verdicts if each.said)
        allowed = [each for each in updates.updates if each.destination not in refused]
        if refused and (updates.atomic or not allowed):
            first = next(iter(refused))
            held_back = f"not pushed: the push is atomic, and `{first}` was refused"
            return Pushed(
                updates=[
                    Updated(
                        destination=each.destination,
                        error=refused.get(each.destination, held_back),
                    )
                    for each in updates.updates
                ],
                said=said,
            )
        leased = {
            **{
                each.destination: Lease(
                    ref=each.destination, expected=landed_tip(each, held)
                )
                for each in allowed
                if each.source is None
            },
            **{each.ref: each for each in updates.leases},
        }
        batches = [allowed] if updates.atomic else [[each] for each in allowed]
        errors = {
            each.destination: await self.sent(store, urls, updates, leased, batch)
            for batch in batches
            for each in batch
        }
        return Pushed(
            updates=[
                Updated(
                    destination=each.destination,
                    error=refused.get(each.destination, errors.get(each.destination)),
                )
                for each in updates.updates
            ],
            said=said,
        )

    async def refusal(
        self, update: Update, updates: Updates, by: Agent | Machine, held: list[Ref]
    ) -> str | None:
        """Say why the declaration refuses `update`, or none where it allows it: a ref git doesn't take, a protected one, the integration branch from a room, the release branch, a forced update, or a deletion of a branch that hasn't landed."""
        destination = update.destination
        checked = await self.store().ran("check-ref-format", destination)
        if checked.status != 0:
            return f"`{destination}` isn't a ref's name git takes"
        landing = self.landing()
        protected = self.module.holding(destination)
        if protected is not None:
            return (
                f"`{destination}` is protected by the project's declaration "
                f"(`Remote.protected`, `{protected}`): updating it is the operator's"
            )
        if landing is not None and destination == f"refs/heads/{landing.released}":
            return (
                f"`{destination}` is the release branch (`Landing.released`): only the "
                "operator merges into it"
            )
        if (
            landing is not None
            and isinstance(by, Agent)
            and destination == f"refs/heads/{landing.integration}"
        ):
            return (
                f"`{destination}` is the integration branch (`Landing.integration`), "
                "which moves only when the operator accepts a landing: land your "
                "branch with `land`"
            )
        forced = (
            updates.force
            or update.forced
            or any(each.ref == destination for each in updates.leases)
        )
        if (
            update.source is not None
            and forced
            and "force-push" not in self.module.allowed()
        ):
            return (
                f"a forced update of `{destination}` (`+`, `--force` or "
                "`--force-with-lease`): the project's declaration doesn't allow "
                "`force-push` with the operator's credentials (`Remote.actions`), "
                "and allowing it is the operator's call. A fast-forward pushes"
            )
        if update.source is None:
            return await self.undeletable(update, updates, held)
        return None

    async def undeletable(
        self, update: Update, updates: Updates, held: list[Ref]
    ) -> str | None:
        """Say why deleting `update`'s branch is refused, or none where it's allowed: by `delete-any` whatever it holds, or by `delete-landed` where its tip on the remote is in the integration branch's history there, both fetched into the store first, so nothing goes with it."""
        allowed = self.module.allowed()
        destination = update.destination
        if "delete-any" in allowed:
            return None
        anyway = (
            "deleting it anyway is `delete-any`, which the project's declaration "
            "doesn't allow with the operator's credentials (`Remote.actions`), and "
            "allowing it is the operator's call"
        )
        if "delete-landed" not in allowed:
            return f"deleting `{destination}`: {anyway}"
        landing = self.landing()
        if landing is None or not destination.startswith("refs/heads/"):
            return (
                f"deleting `{destination}`: `delete-landed` deletes a branch once the "
                f"integration branch holds it; {anyway}"
            )
        integration = f"refs/heads/{landing.integration}"
        tip = next((each.object for each in held if each.name == destination), None)
        onto = next((each.object for each in held if each.name == integration), None)
        if tip is None:
            return f"deleting `{destination}`: `{updates.remote}` doesn't hold it"
        if onto is None:
            return (
                f"deleting `{destination}`: `{updates.remote}` holds no "
                f"`{integration}`, so nothing there says it has landed; {anyway}"
            )
        leased = next(
            (each for each in updates.leases if each.ref == destination), None
        )
        if leased is not None and leased.expected != tip:
            return (
                f"deleting `{destination}`: `{updates.remote}` holds it at {tip}, not "
                f"{leased.expected} as leased"
            )
        await self.fetched(
            Fetching(
                remote=updates.remote,
                wanted=[
                    Wanted(object=tip, name=destination),
                    Wanted(object=onto, name=integration),
                ],
            ),
            Machine(),
        )
        if not await self.store().holds(tip, onto):
            return (
                f"deleting `{destination}`: its commits on `{updates.remote}` aren't "
                f"all in `{integration}` there, so deleting it would lose them; {anyway}"
            )
        return None

    async def published(
        self, update: Update, remote: str, held: list[Ref]
    ) -> str | None:
        """Tell what `update` would publish at `Publishing`, each commit the remote lacks in an event of its own, or its ref's name alone where it publishes none, and return what a part hearing it said refusing it; none where nothing refuses."""
        store = self.store()
        asked = "".join([f"{update.source}\n", *(f"^{each.object}\n" for each in held)])
        listed = await store.done(
            "rev-list", "--ignore-missing", "--reverse", "--stdin", given=asked
        )
        commits = [row[0] for row in tab_separated(listed.text())]
        told = [await self.commit(store, each) for each in commits] or [None]
        for commit in told:
            heeded = await lup.heeded(
                Publishing(
                    published=Push(remote=remote, ref=update.destination, commit=commit)
                )
            )
            if heeded.refused is not None:
                return heeded.refused
        return None

    async def commit(self, store: Store, commit: str) -> Commit:
        """Return what `commit` publishes: its message, and each file it adds or changes against every parent, with the lines it adds against each, or its bytes where it isn't text."""
        message = (await store.done("show", "-s", "--format=%B", commit)).text()
        parents = [
            row[0]
            for row in tab_separated(
                (await store.done("rev-parse", f"{commit}^@")).text()
            )
        ]
        files = {each.path: each for each in await store.held(commit)}
        before = [
            {each.path: each for each in await store.held(parent)} for parent in parents
        ]
        changed = [
            entry
            for entry in files.values()
            if entry.kind == "blob"
            and all(
                (other := each.get(entry.path)) is None or other.object != entry.object
                for each in before
            )
        ]
        contents = await store.verified("blob", [each.object for each in changed])
        earlier = {
            entry.path: await store.verified(
                "blob",
                [
                    other.object
                    for each in before
                    if (other := each.get(entry.path)) is not None
                    and other.kind == "blob"
                ],
            )
            for entry in changed
        }
        return Commit(
            id=commit,
            message=message,
            changed=[
                changed_file(str(entry.path), content, earlier[entry.path])
                for entry, content in zip(changed, contents, strict=True)
            ],
        )

    async def sent(
        self,
        store: Store,
        urls: list[str],
        updates: Updates,
        leased: dict[str, Lease],
        batch: list[Update],
    ) -> str | None:
        """Push `batch` to each of `urls` by object id, with the leases on its refs and the options git set, forcing only an update git forced, and say why it failed, in one line, where it did on any; none where it pushed everywhere."""
        refspecs = [
            ("+" if each.forced or updates.force else "")
            + f"{each.source or ''}:{each.destination}"
            for each in batch
        ]
        leases = [
            f"--force-with-lease={lease.ref}:{lease.expected}"
            for each in batch
            if (lease := leased.get(each.destination)) is not None
        ]
        failures: list[str] = []
        for url in urls:
            ran = await store.ran(
                *self.quiet,
                "-c",
                "push.recurseSubmodules=no",
                "push",
                "--recurse-submodules=no",
                "--porcelain",
                *(["--atomic"] if updates.atomic else []),
                *(["--dry-run"] if updates.dry_run else []),
                *(f"--push-option={each}" for each in updates.push_options),
                *leases,
                url,
                *refspecs,
                within=Git().crossing,
            )
            if ran.status != 0:
                failures = [*failures, f"{url}: {' '.join(ran.said().split())}"]
        return "; ".join(failures) or None


UNCONTAINED = (
    "the repository's object store reads objects from outside it (`objects/info/"
    "alternates`, or a link under `objects/`), through which a push would send "
    "another repository's objects with the operator's credentials: lup pushes and "
    "fetches nothing from it"
)
"""Why a push or a fetch from a store that isn't self-contained is refused."""


def landed_tip(update: Update, held: list[Ref]) -> str:
    """Return the object `update`'s ref names on the remote, as listed, which its deletion is leased on, so it fails where the ref moved since; all zeros where it isn't listed."""
    return next(
        (each.object for each in held if each.name == update.destination), "0" * 40
    )


def changed_file(path: str, content: bytes, earlier: list[bytes]) -> Changed:
    r"""Return a file a commit publishes at `path`, holding `content`, against what each parent held there, `earlier`: the lines it adds against every one of them, or its bytes where it isn't text.

    >>> [each.text for each in changed_file("a", b"x\ny\nz\n", [b"x\nz\n"]).added]
    ['y']
    >>> changed_file("logo.png", b"\x89PNG", []).content
    b'\x89PNG'
    """
    try:
        lines = content.decode().splitlines()
        before = [each.decode().splitlines() for each in earlier]
    except UnicodeDecodeError:
        return Changed(path=path, content=content)
    added = [
        dict.fromkeys(
            number
            for tag, _, _, first, last in difflib.SequenceMatcher(
                None, old, lines, autojunk=False
            ).get_opcodes()
            if tag in ["insert", "replace"]
            for number in range(first, last)
        )
        for old in before
    ]
    return Changed(
        path=path,
        added=[
            Line(number=number + 1, text=text)
            for number, text in enumerate(lines)
            if all(number in each for each in added)
        ],
    )
