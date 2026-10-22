"""Landing a branch: `land`, the tool that moves a gated branch on the remote once the operator approved what was flagged on what it lands.

`docs/judging-writes.md`, *Landing a branch*. A flagged write lands in its
worktree and holds no one (`lup_dev.policy.flags`); the landing of its branch is
where it waits for the operator. `git push` runs in the agent's shell, which ends
a command within minutes, so a push can't wait hours for them; a call to one of
lup's tools can, as `ask` with `wait` does (`docs/inbox.md`, *Holding a call*).
So `land`, a tool the host service serves each launched session, moves the
gated branch, `dev` by default, to a local branch's tip:
1. the gated branch's tip on the remote is fetched, and the tip landed must hold
   it: a landing is a fast-forward;
2. the gate must have passed on the tip's files, as the room's gate recorded it
   (`lup_dev.gate`, `Passes`): the gate needs the project's environment, which
   the host doesn't run, so `land` reads the pass and never runs the gate. The
   room writes the passes, so this steers and guards nothing;
3. each file the landing changes that's flagged on a branch it lands, and not
   approved, is a hold in the operator's inbox, one item a file covering every
   flag on it (`AtLanding`), its diff from the version of the file the operator
   last saw there to the tip's; the call waits until each is answered. Approved,
   each flag it covers is approved with it; a comment without approval, or a
   decline, sends the operator's words to the conversation landing, and nothing
   is pushed (`Delivery.held_back`, `Delivery.landing_decided`);
4. the push goes the remote helper's way (`PushHandler`): held to the launch's
   limits, through the `publishing` moment, and told to `Remotes.landed`, which
   asks trust's approval where it moved the integration branch;
5. each branch it landed is cleaned up after: its copy on the remote deleted,
   as `delete-merged` deletes one (`Remotes.merged`); its worktree removed where
   it's clean and nobody works in it; then the local branch deleted.

**Which branches it lands:** of the local branches in the history of the tip and
not in that of the gated branch's tip on the remote, those the landing merged
(`landed_branches`): the branch landed, and each whose tip is a parent beyond the
first of a merge on the first-parent line from the tip down to the remote's. A
branch whose tip is one of that line's own commits, just made from the
integration branch say, has nothing of its own in the landing: it's left alone,
its worktree with it, holds the landing on no flag, and the answer names it, so
the session landing isn't surprised to find it there. A flag keeps the branch
its worktree had checked out (`Flagged.branch`): one on a branch renamed or
deleted since holds nothing, and a stale one on a branch name used again holds
that branch's landing.

**The version a hold starts from** is the latest the operator saw of the file on
the branches landed: a flagged write or a hold at landing they approved, read or
commented on, so a hold after a comment shows what changed in answer to it.
Where they saw none, it's the file at the gated branch's tip on the remote,
which the tip holds, so the integration branch's own changes don't show. One
they saw before the integration branch changed the file too, merged since,
shows that change as well.

**A worktree is removed in the room,** never on the host: through `podman exec` in
the launch's container, `git worktree remove` without `--force`, so git itself
keeps one with changes or untracked files, and what it ignores (its `.venv`, its
scratch) goes with it. Removed on the host, the path would be the one
`<git directory>/worktrees/<name>/gitdir` names, which the room writes, and the
host's recursive delete could be aimed outside the repository. Left alone, and
said: the repository's main worktree, one where the conversation landing works,
and one where a conversation of a launch still served works, as the judge's
session index has it (`Holding.works`); the local branch it has checked out
stays with it.

The tool's docstring's first line is its summary, 50 characters at most, which
the guidance lists (`launch/guidance.py`); the rest is its description. It
answers in words, as `content`.
"""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime
from itertools import batched
from pathlib import Path
from typing import override

from pydantic import Field, JsonValue, ValidationError

from lup.programs import Ran
from lup.tools.serving import Answer
from lup.tools.tool import Accepted, Refused, ToolSpec, bound, declared, lup_tool
from lup.types import Model
from lup_dev.errors import LupDevError
from lup_dev.gate import Passed, Standing
from lup_dev.git import LISTED, Git, Tracked, nul_separated
from lup_dev.host.courier import Conversation as Caller
from lup_dev.host.protocol import HostError, Register
from lup_dev.host.rooms import RoomTools
from lup_dev.host.service import Program, executed
from lup_dev.inbox.delivery import Delivery, who
from lup_dev.inbox.store import (
    AtLanding,
    ChangedFile,
    Conversation,
    Decided,
    Done,
    Flagged,
    HeldChange,
    InboxError,
    Item,
    Reading,
    Superseded,
    Text,
    Waiting,
    Whereabouts,
    cited,
)
from lup_dev.layout import CheckoutLayout, GitDirectoryLayout, Layout
from lup_dev.policy.holds import unified
from lup_dev.policy.worktrees import SessionIndex
from lup_dev.remote.protocol import (
    Pushed,
    PushHandler,
    Pushing,
    Ref,
    RemoteName,
    Remotes,
    Update,
    Wanted,
    matching,
    oneline,
    require,
)
from lup_dev.stored import read_model


class Landing(Model):
    """A branch to land."""

    branch: str | None = Field(
        default=None,
        description=(
            "The local branch whose tip lands, by its name, as `git branch` lists "
            "it. Left out, the integration branch's own, `dev`, where you merged."
        ),
    )
    onto: str | None = Field(
        default=None,
        description=(
            "The branch it lands on, on the remote, by its name: one the project's "
            "declaration gates (`Core.credentials`). Left out, the integration "
            "branch, `dev`."
        ),
    )
    remote: RemoteName = Field(
        default="origin",
        description="The remote, by its name in the repository's `config`.",
    )


class Flag(Model):
    """A flagged write as a landing reads it: its item's number, and what it flagged."""

    number: int
    flagged: Flagged


class Seen(Model):
    """An item of a file the operator saw, and when they settled it."""

    item: Item
    at: datetime


class Held(Model):
    """A hold at landing as `land` waits on it: its item, and the file it holds."""

    number: int
    path: Path


class Outcome(Model):
    """How the operator answered one hold at landing."""

    held: Held
    approved: bool
    said: str
    """How, in a few words: `approved`, `declined`."""


class Waited(Model):
    """What a landing's wait on its holds came to: what reached the conversation meanwhile, told whole, and how each hold was answered."""

    told: str
    outcomes: list[Outcome]


class Worktree(Model):
    """One worktree of the repository, as `git worktree list` gives it: its root, and the branch it has checked out, by its ref's full name."""

    root: Path
    branch: str | None = None


class Worker(Model):
    """A worktree a conversation works in, and who, as a landing's cleanup says why it leaves it."""

    root: Path
    why: str


class Cleaned(Model):
    """What a landing's cleanup did, and what it left with why, a line each."""

    done: list[str] = []
    left: list[str] = []

    @classmethod
    def joined(cls, parts: list[Cleaned]) -> Cleaned:
        """Return `parts` as one, each's lines in order."""
        return cls(
            done=[line for part in parts for line in part.done],
            left=[line for part in parts for line in part.left],
        )


def short(ref: str) -> str:
    """Return a branch's name from its ref's full name.

    >>> short("refs/heads/dev")
    'dev'
    """
    return ref.removeprefix("refs/heads/")


class Branches(Model):
    """The local branches in a landing's history and not in the remote's: those it lands, each ref's full name with its tip, and those it leaves alone, having merged none of them."""

    landed: dict[str, str] = {}
    alone: list[str] = []


def landed_branches(git: Git, tip: str, old: str | None, source: str) -> Branches:
    """Return the local branches a landing of `tip`, the branch `source`'s, lands, and those it leaves alone.

    Of the local branches in `tip`'s history and not in `old`'s, the gated
    branch's tip on the remote where it has one, it lands those the landing
    merged: `source` itself, and each whose tip is a parent beyond the first
    of a merge on the first-parent line from `tip` down to `old`. The rest
    have nothing of their own in it, their tip being one of that line's own
    commits: a branch just made from the integration branch, say, whose
    worktree a session may be about to work in.
    """
    excluded = [] if old is None else [f"^{old}"]
    walked = git.text("rev-list", "--first-parent", "--parents", tip, *excluded)
    # Each tip merged on the line, with the merge that merged it.
    merged = {
        parent: merge
        for line in walked.splitlines()
        for merge, *parents in [line.split()]
        for parent in parents[1:]
    }
    listed = git.run(
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
        f"--merged={tip}",
        *([] if old is None else [f"--no-merged={old}"]),
        "refs/heads/",
    )
    found = dict(nul_separated(line) for line in listed.output.splitlines())
    return Branches(
        landed={
            ref: commit
            for ref, commit in found.items()
            if ref == source or commit in merged
        },
        alone=[
            ref
            for ref, commit in found.items()
            if ref != source and commit not in merged
        ],
    )


def changed_files(git: Git, old: str | None, tip: str) -> list[Path]:
    """Return the files a landing of `tip` changes, from the repository's root: those differing from `old`'s, or every one of `tip`'s where the remote has no `old`."""
    if old is None:
        listed = git.run("ls-tree", "-r", "-z", "--name-only", "--full-tree", tip)
    else:
        listed = git.run("diff", "--name-only", "-z", "--no-renames", old, tip)
    return [Path(each) for each in nul_separated(listed.output)]


def blob(git: Git, commit: str, path: Path) -> bytes | None:
    """Return the file at `path` in `commit`, or none where `commit` has no file there."""
    listed = git.run(
        "ls-tree", "-z", "--full-tree", f"--format={LISTED}", commit, "--", str(path)
    )
    entries = [
        Tracked.model_validate(
            {"mode": mode, "kind": kind, "object": found, "path": named}
        )
        for mode, kind, found, named in batched(
            nul_separated(listed.output), 4, strict=True
        )
    ]
    match [each.object for each in entries if each.kind == "blob"]:
        case [found]:
            [content] = git.contents([found])
            return content
        case _:
            return None


def worktrees(git: Git) -> list[Worktree]:
    """Return the repository's worktrees, its main one first, as `git worktree list` gives them, each with the branch it has checked out."""
    fields = nul_separated(git.run("worktree", "list", "--porcelain", "-z").output)
    starts = [at for at, field in enumerate(fields) if field.startswith("worktree ")]
    records = [
        fields[start:end]
        for start, end in zip(starts, [*starts[1:], len(fields)], strict=True)
    ]
    return [
        Worktree(
            root=Path(record[0].removeprefix("worktree ")),
            branch=next(
                (
                    field.removeprefix("branch ")
                    for field in record
                    if field.startswith("branch ")
                ),
                None,
            ),
        )
        for record in records
    ]


def passed(kept: Path) -> bool:
    """Say whether a pass of the gate is recorded at `kept`: a file, never a link, that reads as one.

    The room writes the passes, so one that doesn't read counts as none, and
    what's wrong with it isn't said.
    """
    if kept.is_symlink() or not kept.is_file():
        return False
    try:
        return read_model(kept, Passed) is not None
    except OSError, ValidationError:
        return False


def text(found: bytes | None) -> str | None:
    """Return a file's bytes as text for its diff, or none where it has none or they aren't text."""
    if found is None:
        return None
    try:
        return found.decode()
    except UnicodeDecodeError:
        return None


def settled_at(item: Item) -> datetime | None:
    """Return when the operator settled `item`, read, commented on, approved or declined; none where they haven't."""
    match item.state:
        case Done(at=at) | Decided(at=at):
            return at
        case _:
            return None


def outcome(held: Held, item: Item) -> Outcome:
    """Say how the operator answered hold `held`, its item `item` as it stands."""
    match item.state:
        case Decided(approved=True):
            return Outcome(held=held, approved=True, said="approved")
        case Decided():
            return Outcome(held=held, approved=False, said="declined")
        case Done():
            return Outcome(held=held, approved=False, said="commented on, not approved")
        case Superseded(by=by):
            said = f"superseded by {cited(by)}, another landing's hold on the file"
            return Outcome(held=held, approved=False, said=said)
        case _:
            return Outcome(
                held=held, approved=False, said="still waiting for the operator"
            )


def flagged_on(path: Path, landed: list[str], item: Item) -> bool:
    """Say whether `item` is of the file at `path` on one of the branches `landed`: a flagged write there, or a hold at landing on it covering one."""
    match item.reason:
        case Flagged(path=flagged, branch=str() as branch):
            return flagged == path and branch in landed
        case HeldChange(landing=AtLanding() as held):
            return held.path == path and any(each in landed for each in held.branches)
        case _:
            return False


def shown_from(onto: str, since: int | None, old: str | None) -> str:
    """Say which version of the file a hold's diff starts from: the item `since`, the gated branch `onto`'s tip on the remote, `old`, or none."""
    if since is not None:
        return f"Shown since {cited(since)}, the version of it you last saw."
    if old is not None:
        return (
            f"Shown from `{onto}`'s tip on the remote, {old}: you've seen none of it."
        )
    return f"Shown whole: `{onto}` isn't on the remote yet."


class Lander(Model, arbitrary_types_allowed=True):
    """One conversation of a launch landing a branch: the tool's function, bound to it."""

    delivery: Delivery
    """The inbox, where each hold is put and answered."""
    remotes: Remotes
    """git on the host for the launch's room, which pushes the landing."""
    layout: Layout
    """lup's state on the host: the judge's session index, the launches served."""
    launch: Register
    caller: Caller
    call: str | None = None
    """The runtime's id for the call, which each hold it makes keeps."""
    integration: str
    """The integration branch's name: what lands, and where, unless the call says."""
    run: Callable[[Program], Awaitable[Ran]] = executed
    """Runs one program on the host: `podman exec` into the launch's room."""

    @property
    def party(self) -> Conversation:
        """Return the inbox's party for the conversation landing."""
        return Delivery.party(self.launch, self.caller)

    @lup_tool(idempotent=True)
    async def land(self, landing: Landing) -> str:
        """Land a branch on the integration branch.

        Puts your local `branch`'s tip on the remote's integration branch,
        `dev`, as `git push origin dev` would, once it's a fast-forward of the
        remote's, the gate passed on its files (`uv run lup-dev check`, with
        everything committed, records the pass), and the operator approved
        each file the landing changes that was flagged on a branch it lands: a
        new file, a file written whole, a change to the public API. Each such
        file is a hold in the operator's inbox, showing what changed since they
        last saw it, and this call waits for their answers, which may take
        hours. Approved, it lands. Where they comment without approving, or
        decline, it returns their words and lands nothing: answer them,
        commit, and call it again; what they approved stays approved. Once
        landed, it cleans up after each branch it landed: deletes its copy on
        the remote, removes its worktree where it's clean and nobody works in
        it, and deletes the local branch; what it leaves, it says, and why.
        """
        try:
            return await self.landed(landing)
        except LupDevError as refused:
            return f"Not landed: {refused}"

    def onto(self, landing: Landing) -> str:
        """Return the gated branch `landing` lands on, by its ref's full name, or say it isn't gated."""
        ref = f"refs/heads/{landing.onto or self.integration}"
        if not matching(ref, self.launch.limits.gated):
            message = (
                f"`{short(ref)}` isn't a branch the project's declaration gates "
                "(`Core.credentials`), where branches land: push any other with git"
            )
            raise HostError(message)
        return ref

    async def landed(self, landing: Landing) -> str:
        """Land `landing`'s branch, waiting on its holds, and clean up after it: what the agent reads."""
        onto = self.onto(landing)
        source = landing.branch or self.integration
        remote = landing.remote
        git = Git.pinned(self.launch.repository)
        tip = await asyncio.to_thread(git.commit, f"refs/heads/{source}")
        if tip is None:
            message = f"this repository has no local branch `{source}`"
            raise HostError(message)
        require("push", self.launch)
        refs = await self.remotes.listed(self.launch, remote, push=True)
        old = next((ref.object for ref in refs if ref.name == onto), None)
        if old == tip:
            return (
                f"Nothing to land: `{short(onto)}` on `{remote}` is at {tip} already."
            )
        refused = await self.forward(remote, onto, source, tip, old)
        if refused is not None:
            return refused
        unpassed = await asyncio.to_thread(self.unpassed, git, tip, source)
        if unpassed is not None:
            return unpassed
        branches = await asyncio.to_thread(
            landed_branches, git, tip, old, f"refs/heads/{source}"
        )
        holds = await self.holds(git, onto, tip, old, branches.landed)
        waited = await self.waited(holds)
        if not all(each.approved for each in waited.outcomes):
            return unapproved(waited)
        reply = await PushHandler(remotes=self.remotes).answer(
            Pushing(remote=remote, updates=[Update(source=tip, destination=onto)]),
            self.launch,
        )
        if not isinstance(reply, Pushed):
            message = f"the push answered {reply.kind}"
            raise HostError(message)
        [update] = reply.updates
        if update.error is not None:
            kept = " What the operator approved stays approved." if holds else ""
            refusals = f"\n{reply.said}" if reply.said else ""
            return f"Not landed: {update.error}.{kept}{refusals}"
        cleaned = await self.cleaned(git, remote, refs, branches.landed, onto)
        was = "new there" if old is None else f"which was at {old}"
        return "\n".join(
            [
                f"Landed {tip} on `{short(onto)}` at `{remote}`, {was}.",
                *approvals(waited),
                *said(cleaned),
                *left_alone(source, branches.alone),
            ]
        )

    async def forward(
        self, remote: str, onto: str, source: str, tip: str, old: str | None
    ) -> str | None:
        """Say why `tip` doesn't land on `onto`, at `old` on `remote`, where it isn't a fast-forward of it; none where it is, or `onto` isn't there yet.

        `old` is fetched into the store first, writing no ref, so git can tell.
        """
        if old is None:
            return None
        wanted = [Wanted(object=old, name=onto)]
        if await self.remotes.fetched(self.launch, remote, wanted, push=True):
            message = (
                f"`{short(onto)}` moved on `{remote}` while lup read it: land again"
            )
            raise HostError(message)
        if await self.remotes.descends(self.launch, tip, old):
            return None
        return (
            f"Not landed: `{short(onto)}` on `{remote}` is at {old}, which `{source}` "
            f"doesn't hold: merge it into `{source}`, run the gate on the result, and "
            "land again."
        )

    def unpassed(self, git: Git, tip: str, source: str) -> str | None:
        """Say why `tip` doesn't land for want of a pass of the gate on its files, or none where one is recorded.

        Its files are named as the room's gate names them: the commit's tree,
        and the digest of the person's own layer of the declaration, beside the
        declaration in the repository's main worktree (`person_layer`), found
        here through git pinned to the repository.
        """
        tree = git.text("rev-parse", f"{tip}^{{tree}}")
        local = CheckoutLayout(root=git.main_worktree()).local_declaration
        layer = (
            hashlib.sha256(local.read_bytes()).hexdigest() if local.is_file() else None
        )
        files = Standing(tree=tree, layer=layer)
        passes = GitDirectoryLayout(common=self.launch.repository).passes
        if passed(passes / f"{files.name}.json"):
            return None
        return (
            f"Not landed: the gate has no pass on {tip}'s files (tree `{tree}`). "
            f"Run `uv run lup-dev check` where `{source}` is checked out, with "
            "everything committed, so it passes on exactly what lands; then call "
            "`land` again."
        )

    async def holds(
        self,
        git: Git,
        onto: str,
        tip: str,
        old: str | None,
        branches: dict[str, str],
    ) -> list[Held]:
        """Put a hold in the operator's inbox for each file the landing changes that's flagged on a branch it lands and not approved, covering every such flag on it, and return them."""
        names = [short(ref) for ref in branches]
        changed = await asyncio.to_thread(changed_files, git, old, tip)
        flags = [
            Flag(number=item.number, flagged=item.reason)
            for item in self.delivery.inbox.about(self.launch.repository)
            if isinstance(item.reason, Flagged)
            and item.reason.branch in names
            and item.reason.path in changed
            and not (isinstance(item.state, Decided) and item.state.approved)
        ]
        paths = list(dict.fromkeys(each.flagged.path for each in flags))
        return [
            await self.hold(
                git,
                [each for each in flags if each.flagged.path == path],
                AtLanding(onto=onto, tip=tip, path=path, branches=[], flags=[]),
                landed=names,
                old=old,
            )
            for path in paths
        ]

    async def hold(
        self,
        git: Git,
        flags: list[Flag],
        held: AtLanding,
        *,
        landed: list[str],
        old: str | None,
    ) -> Held:
        """Put the hold on `held`'s file in the operator's inbox, covering `flags` on it, its diff from the version of it the operator last saw on the branches `landed` to the tip's, and return it."""
        path = held.path
        landing = held.model_copy(
            update={
                "branches": list(
                    dict.fromkeys(
                        each.flagged.branch for each in flags if each.flagged.branch
                    )
                ),
                "flags": [each.number for each in flags],
            }
        )
        seen = self.seen(path, landed)
        kept = None if seen is None else await asyncio.to_thread(self.after, seen, path)
        since = None if seen is None or kept is None else seen.number
        before = (
            kept
            if kept is not None or old is None
            else await asyncio.to_thread(blob, git, old, path)
        )
        after = await asyncio.to_thread(blob, git, landing.tip, path)
        latest = max(flags, key=lambda each: each.number)
        reading = await asyncio.to_thread(self.reading, latest, after)
        asks = dict.fromkeys(
            line for each in flags for line in each.flagged.summary.splitlines()
        )
        onto = short(landing.onto)
        named = ", ".join(f"`{each}`" for each in landing.branches)
        change = HeldChange(
            text=(
                f"Let `{path}` land on `{onto}`? It's flagged on {named}, and the "
                f"landing of {landing.tip} waits on your approval."
            ),
            summary="\n".join([*asks, shown_from(onto, since, old)]),
            worktree=latest.flagged.worktree,
            landing=landing.model_copy(update={"since": since}),
        )
        diff = unified(path, text(before), text(after))
        file = ChangedFile.of(path, before, after, reading)
        item = await self.delivery.held_at_landing(
            change, self.party, diff, [file], call=self.call
        )
        return Held(number=item.number, path=path)

    def seen(self, path: Path, landed: list[str]) -> Item | None:
        """Return the latest item of the file at `path` on the branches `landed` that the operator saw: a flagged write or a hold at landing they approved, read or commented on, the last they settled; none where they saw none."""
        seen = [
            Seen(item=item, at=at)
            for item in self.delivery.inbox.about(self.launch.repository)
            if flagged_on(path, landed, item) and (at := settled_at(item)) is not None
        ]
        latest = max(seen, key=lambda each: each.at, default=None)
        return None if latest is None else latest.item

    def after(self, item: Item, path: Path) -> bytes | None:
        """Return the version of `path` kept beside `item`, what it changed it to; none where none is kept as text."""
        try:
            files = self.delivery.inbox.files(item.number)
        except InboxError:
            return None
        found = next((each for each in files if each.path == path), None)
        if found is None or not isinstance(found.after, Text):
            return None
        return found.after.text.encode()

    def reading(self, flag: Flag, after: bytes | None) -> Reading | None:
        """Return the judge's reading of the file as `flag`, the latest on it, kept it: its lines and findings kept only where the tip holds the file as that flag left it."""
        try:
            files = self.delivery.inbox.files(flag.number)
        except InboxError:
            return None
        found = next((each for each in files if each.path == flag.flagged.path), None)
        if found is None or found.reading is None:
            return None
        if isinstance(found.after, Text) and found.after.text.encode() == after:
            return found.reading
        return Reading(
            role=found.reading.role,
            asks=[
                each.model_copy(update={"line": None}) for each in found.reading.asks
            ],
        )

    async def waited(self, holds: list[Held]) -> Waited:
        """Hold the call until no hold of `holds` waits for the operator, and return what reached the conversation meanwhile, told, and how each was answered; at once, telling nothing, where there's none."""
        if not holds:
            return Waited(told="", outcomes=[])
        inbox = self.delivery.inbox

        def answered() -> bool:
            return not any(
                isinstance(inbox.item(each.number).state, Waiting) for each in holds
            )

        told = await self.delivery.held(self.party, answered)
        return Waited(
            told=told,
            outcomes=[outcome(each, inbox.item(each.number)) for each in holds],
        )

    async def cleaned(
        self,
        git: Git,
        remote: str,
        refs: list[Ref],
        branches: dict[str, str],
        onto: str,
    ) -> Cleaned:
        """Clean up after each branch the landing landed but those gated or protected: its copy on `remote`, which listed `refs` before the push; its worktree; its local branch."""
        limits = self.launch.limits
        landed = {
            ref: commit
            for ref, commit in branches.items()
            if ref != onto
            and not matching(ref, limits.gated)
            and not matching(ref, limits.protected)
        }
        if not landed:
            return Cleaned()
        listed = [ref.name for ref in refs]
        trees = await asyncio.to_thread(worktrees, git)
        places = list(self.delivery.inbox.whereabouts.values())
        working = await asyncio.to_thread(self.working, places)
        main = trees[0].root if trees else None
        return Cleaned.joined(
            [
                await self.branch_cleaned(
                    git,
                    remote,
                    ref,
                    commit,
                    on_remote=ref in listed,
                    roots=[each.root for each in trees if each.branch == ref],
                    left={
                        **(
                            {}
                            if main is None
                            else {main: "the repository's main worktree"}
                        ),
                        **working,
                    },
                )
                for ref, commit in landed.items()
            ]
        )

    async def branch_cleaned(
        self,
        git: Git,
        remote: str,
        ref: str,
        commit: str,
        *,
        on_remote: bool,
        roots: list[Path],
        left: dict[Path, str],
    ) -> Cleaned:
        """Clean up after the branch `ref`, landed at `commit`: its copy on `remote` where it's there, each worktree of `roots` having it checked out but those `left` names, and the local branch where none still has it."""
        deleted = await self.remote_deleted(remote, ref) if on_remote else Cleaned()
        trees = [await self.worktree_removed(root, left.get(root)) for root in roots]
        kept = [root for root, each in zip(roots, trees, strict=True) if each.left]
        branch = (
            await asyncio.to_thread(local_deleted, git, ref, commit)
            if not kept
            else Cleaned(
                left=[f"the local branch `{short(ref)}`, checked out in {kept[0]}"]
            )
        )
        return Cleaned.joined([deleted, *trees, branch])

    async def remote_deleted(self, remote: str, ref: str) -> Cleaned:
        """Delete `ref` on `remote` as a push from the room would, `delete-merged` checking its commits are in a gated branch there, and say how it went."""
        try:
            reply = await PushHandler(remotes=self.remotes).answer(
                Pushing(remote=remote, updates=[Update(source=None, destination=ref)]),
                self.launch,
            )
        except LupDevError as refused:
            return Cleaned(left=[f"`{short(ref)}` on `{remote}`: {refused}"])
        if not isinstance(reply, Pushed):
            return Cleaned(left=[f"`{short(ref)}` on `{remote}`: {reply.kind}"])
        [update] = reply.updates
        if update.error is not None:
            return Cleaned(left=[f"`{short(ref)}` on `{remote}`: {update.error}"])
        return Cleaned(done=[f"deleted `{short(ref)}` on `{remote}`"])

    async def worktree_removed(self, root: Path, why: str | None) -> Cleaned:
        """Remove the worktree at `root` in the launch's room, as its session would, unless `why` says why it's left; say how it went.

        `git worktree remove` without `--force` keeps a worktree with changes or
        untracked files, saying so, and takes what git ignores with it.
        """
        if why is not None:
            return Cleaned(left=[f"the worktree {root}: {why}"])
        container = self.launch.container
        if container is None:
            return Cleaned(left=[f"the worktree {root}: lup can't reach your room"])
        ran = await self.run(
            Program(
                command=[
                    "podman",
                    "exec",
                    "--workdir",
                    str(self.launch.worktree),
                    container,
                    "git",
                    "worktree",
                    "remove",
                    str(root),
                ],
                payload="",
                directory=self.launch.repository,
            )
        )
        if ran.status != 0:
            said = oneline(ran.said()) or f"it ended with status {ran.status}"
            return Cleaned(left=[f"the worktree {root}: `git worktree remove`: {said}"])
        return Cleaned(done=[f"removed the worktree {root}"])

    def working(self, places: list[Whereabouts]) -> dict[Path, str]:
        """Return the worktrees a conversation works in, each with who, as the cleanup leaves it: the conversation landing, then each launch still served of this repository where it started, then each of its conversations still going where the judge's session index has it work (`Holding.works`), each by the first found."""
        index = SessionIndex(layout=self.layout)
        host = self.layout.host
        # Each launch's conversations are kept beside its record, and aren't a record.
        records = [
            recorded(path)
            for path in sorted(host.launches.glob("*.json"))
            if path != host.conversations(path.stem.removesuffix(".conversations"))
        ]
        live = {
            record.launch: record
            for record in records
            if record is not None and record.repository == self.launch.repository
        }
        own = index.read(self.caller.session)
        mine = [
            *([] if self.caller.agent is not None else [self.launch.worktree]),
            *([] if own is None else own.works(self.caller.agent or "")),
        ]
        going = [
            place
            for place in places
            if place.launch in live
            and place.ended is None
            and place.conversation.repository == self.launch.repository
        ]
        workers = [
            *(Worker(root=root, why="you work there") for root in mine),
            *(
                Worker(
                    root=record.worktree,
                    why=f"launch `{record.name or record.launch}` started there",
                )
                for record in live.values()
            ),
            *(
                Worker(root=root, why=f"{who(place.conversation)} works there")
                for place in going
                if (held := index.read(place.conversation.session)) is not None
                for root in held.works(place.conversation.agent or "")
            ),
        ]
        return {each.root: each.why for each in reversed(workers)}


def recorded(path: Path) -> Register | None:
    """Return the launch recorded at `path`, or none where it doesn't read as one."""
    try:
        return read_model(path, Register)
    except OSError, ValidationError:
        return None


def local_deleted(git: Git, ref: str, commit: str) -> Cleaned:
    """Delete the local branch `ref` where it's still at `commit`, the tip it landed at, and say how it went."""
    try:
        git.run("update-ref", "-d", ref, commit)
    except LupDevError as kept:
        return Cleaned(left=[f"the local branch `{short(ref)}`: {kept}"])
    return Cleaned(done=[f"deleted the local branch `{short(ref)}`"])


def unapproved(waited: Waited) -> str:
    """Say that a landing didn't land, the operator not having approved each hold: how they answered each, then what reached the conversation meanwhile, their words among it."""
    lines = [
        f"- {cited(each.held.number)} (`{each.held.path}`): {each.said}"
        for each in waited.outcomes
    ]
    told = [waited.told] if waited.told else []
    return "\n".join(
        [
            "Not landed: the operator didn't approve each file it waits on.",
            *lines,
            (
                "What they approved stays approved. Answer what they said, commit, "
                "and call `land` again: each file left is held again, shown from "
                "the version they last saw."
            ),
            *told,
        ]
    )


def approvals(waited: Waited) -> list[str]:
    """Say which holds the operator approved for a landing that landed, then what reached the conversation meanwhile, their comments among it; nothing where none held it."""
    if not waited.outcomes:
        return []
    named = ", ".join(
        f"{cited(each.held.number)} (`{each.held.path}`)" for each in waited.outcomes
    )
    return [
        f"The operator approved {named}.",
        *([waited.told] if waited.told else []),
    ]


def said(cleaned: Cleaned) -> list[str]:
    """Say what a landing's cleanup did, then what it left and why, a line each."""
    done = (
        ["Cleaned up after it:", *(f"- {line}" for line in cleaned.done)]
        if cleaned.done
        else []
    )
    left = ["Left:", *(f"- {line}" for line in cleaned.left)] if cleaned.left else []
    return [*done, *left]


def left_alone(source: str, alone: list[str]) -> list[str]:
    """Say which branches in the landing's history it left alone, the branch `source` having merged none of them, in a line; nothing where there's none."""
    if not alone:
        return []
    named = ", ".join(f"`{short(ref)}`" for ref in alone)
    return [f"Left alone, `{source}` having merged none of them: {named}."]


class LandingTools(Model, RoomTools, arbitrary_types_allowed=True):
    """`land`, as the host service serves it to each launched session, beside the inbox's and the judge's tools."""

    delivery: Delivery
    remotes: Remotes
    layout: Layout
    """lup's state on the host."""
    integration: str
    """The integration branch's name."""
    run: Callable[[Program], Awaitable[Ran]] = executed
    """Runs one program on the host: `podman exec` into a launch's room."""

    @override
    def specs(self) -> list[ToolSpec]:
        return list(declared(Lander).values())

    @override
    async def call(
        self,
        name: str,
        arguments: JsonValue,
        launch: Register,
        caller: Caller,
        call: str | None,
    ) -> Answer:
        """Run the tool `name` for `caller`, a conversation of `launch`: its arguments validated, its answer in words.

        Arguments that don't validate are refused, saying why, as the library's
        tools refuse them. A hold the call makes keeps `call`, its moment in
        the conversation's record.
        """
        lander = Lander(
            delivery=self.delivery,
            remotes=self.remotes,
            layout=self.layout,
            launch=launch,
            caller=caller,
            call=call,
            integration=self.integration,
            run=self.run,
        )
        [tool] = [tool for tool in bound(lander) if tool.spec().name == name]
        match await tool.call(arguments):
            case Accepted(answer=answer):
                return Answer(text=answer)
            case Refused(rejection=rejection):
                return Answer(text=f"Refused: {rejection.reason}", error=True)
