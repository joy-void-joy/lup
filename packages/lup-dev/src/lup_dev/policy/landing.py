"""Landing a branch: `land`, the tool that merges a branch onto the integration branch, and moves it on the remote once the operator approved what was flagged on what it lands.

`docs/judging-writes.md`, *Landing a branch*. A flagged write lands in its
worktree and holds no one (`lup_dev.policy.flags`); the landing of its branch is
where it waits for the operator. `git push` runs in the agent's shell, which ends
a command within minutes, so a push can't wait hours for them; a call to one of
lup's tools can, as `ask` with `wait` does (`docs/inbox.md`, *Holding a call*).
So `land`, a tool the host service serves each launched session, moves the
gated branch, `dev` by default:
1. the gated branch's tip on the remote is fetched, writing no ref, so git can
   tell what holds it; then the messages the landing would publish, the merge
   commit's and each commit's beyond what the remote holds, are read for an
   inbox item's number, which `Private`'s door refuses at the push, and a
   landing citing one is refused before anything merges, where the list kept
   for the repository withholds them (`Lander.numbers`);
2. given a branch and a message, the branch is merged (`Lander.merge`): in the
   launch's room, by `lup-dev merge` behind the project's runner as the launch
   recorded it (`Register.runner`), the message on its standard input, the
   merge made apart from every checkout and gated with its fixes
   (`lup_dev.merging`). It goes onto the local branch where that holds the
   remote's tip, else onto the remote's (`base`); a branch already in that
   history isn't merged again. The merge commit the room answers is read on
   the host, its parents from the commit alone, checked as the steps below
   check any tip, and the local branch fast-forwarded to it in the room, its
   checkout by `git merge --ff-only`: all of it under the repository's lock
   (`Turns`), so landings merge one at a time, each onto the last. Without a
   branch, the local integration branch's tip lands as it is;
3. the tip landed must hold the remote's: a landing is a fast-forward;
4. the gate must have passed on the tip's files, as the room's gate recorded it
   (`lup_dev.gate`, `Passes`): the gate needs the project's environment, which
   the host doesn't run, so `land` reads the pass and never runs the gate. The
   room writes the passes, so this steers and guards nothing;
5. each file the landing changes that's flagged on a branch it lands, and not
   approved, holds it: the landing waits on each, every flag on it (`Wait`,
   `lup_dev.policy.waits`), raising one desktop notice for them all, and each
   is held at landing in its writer's "since you approved" drawer, shown from
   the version of the file the operator last saw there to the tip's
   (`lup_dev.policy.since`); the call waits until each is answered there.
   Marked reviewed, each flag on it is approved; declined, or commented on
   without being marked reviewed, nothing is pushed, and the call answers
   with the operator's words (`Waits.declined`);
6. the push goes the remote helper's way (`PushHandler`): held to the launch's
   limits, through `Publishing`, and told to `Remotes.landed`, which
   asks trust's approval where it moved the integration branch. It names the
   remote's URL, so the gated branch's remote-tracking ref is moved to what
   landed after it (`tracked`), as `git push <remote>` moves it: the judge
   counts what those refs name as judged;
7. each thread parked until a branch it landed on the integration branch, or
   until an issue that closed, is woken (`lup_dev.policy.coming`), its holder
   told; a commit it lands wakes one at its push (step 6), as every push the
   host makes does;
   each conversation still going that worked on a branch it landed, and hasn't
   said how the work felt, is invited to, once, beside their next call
   (`invited`): the landing is where a branch's work ends;
8. the answer says, for each branch it landed, the `# lup: defer` comments its
   merge adds and removes against its first parent, and those the integration
   branch's own commits add and remove beyond them, where it lands some or no
   branch merged (`Deferrals`): read on the host from each version's parse
   alone, as trust's first reading reads a change (`Parser`), and compared as
   the judge compares a file's directives (`missing`). It's information: work
   knowingly left undone shows as it lands, and a reading that fails is said
   and refuses nothing;
9. each branch it landed is cleaned up after: its copy on the remote deleted,
   as `delete-merged` deletes one (`Remotes.merged`); its worktree removed where
   it's clean and nobody works in it, or detached where a subagent who may be
   resumed started there; then the local branch deleted. A worktree kept so is
   removed by the first landing after its subagent's launch ends (`lapsed`);
10. each flagged write still waiting that's left nothing to hold is withdrawn
    from the operator's inbox (`Lander.withdrawn`): one on a branch gone, the
    cleanup's or any deleted earlier, landed or not; and one on a branch whose
    flags hold the landing, on a file it leaves unchanged, where the file
    stands as the flag keeps it, landed before. It's left unread, so it's no
    version they saw (`Withdrawn`). One on a branch still there whose file
    stands otherwise may be a write not committed yet, and waits;
11. the answer ends on what's still running or waiting to land (`going`): the
    subagents of the session landing whom lup hasn't heard end, and the local
    branches not on what landed, each with who works in it.

**Which branches it lands:** of the local branches in the history of the tip and
not in that of the gated branch's tip on the remote, those the landing merged
(`landed_branches`): the branch given to the landing, and each other whose tip
is a parent beyond the first of a merge on the first-parent line from the tip
down to the remote's, where no branch given was given at that tip and no other
branch points at it. The graph can't tell two branches at one commit apart, but
the landing knows which it was given: one at the tip of the branch landed was
made from it, a worker's next piece say, and is left alone, its worktree with
it, holding the landing on no flag; several at one merged tip, none given, may
each be the one merged, so none is cleaned up after, and a flag on any holds
the landing. A branch whose tip is one of that line's own commits, just made
from the integration branch say, has nothing of its own in the landing: it's
left alone, its worktree with it, holds the landing on no flag. The answer
names each branch left alone, a line for each why, so the session landing
isn't surprised to find it there. A flag keeps the branch
its worktree had checked out (`Flagged.branch`): one on a branch renamed or
deleted since holds nothing, and a stale one on a branch name used again holds
that branch's landing.

**The version a held file is shown from** is the latest the operator saw of
it on the branches landed: the version they last marked reviewed in its writer's
drawer, a decline marking it so (`lup_dev.policy.reviewed`), or a flagged write
or a hold at landing an earlier lup made, which they approved, read or
commented on, whichever came last. Where they saw none, it's the file at the gated branch's tip on the remote,
which the tip holds, so the integration branch's own changes don't show. One
they saw before the integration branch changed the file too, merged since,
shows that change as well.

**A worktree is removed in the room,** never on the host: through `podman exec` in
the launch's container, `git worktree remove` without `--force`, so git itself
keeps one with changes or untracked files, and what it ignores (its scratch)
goes with it. Where the room has a mount at or inside a worktree, its `.venv`
hidden from the room say, git's removal there would fail partway, having
removed part of the worktree, the mount holding the rest: so the room is asked
what it mounts first (`findmnt`, `laid`), and such a worktree is left whole,
named as left with what's hidden, for the operator to remove on the host
(`docs/launch.md`, *The project's environment, the room's own*). Where the room
can't say, no worktree is removed, and why is said once. Removed on the host, the path would be the one
`<git directory>/worktrees/<name>/gitdir` names, which the room writes, and the
host's recursive delete could be aimed outside the repository. The container is
named as the launch's record has it when the cleanup runs (`reached`), since
`rename` renames it with the launch and the landing may have waited hours on
its holds, and podman is asked for it once before any worktree is removed: one
that isn't there is said once, with its name, and each worktree named as left.
Left alone, and said: the repository's main worktree, one where the conversation
landing works, and one where a conversation of a launch still served works, as
the judge's session index has it (`Holding.works`); the local branch it has
checked out stays with it. The index places a subagent in a worktree once their
file tools wrote there, or, in one lup made for them at their runtime's asking,
from their first call, so a fresh worktree a worker made themselves is kept by which
branches count as landed, not by this check (#240).

**Kept, detached, while a subagent may be resumed there:** the worktree lup gave
a subagent to work apart in (`Holding.apart`) is where their shell starts each
command. Their runtime can resume them after their turn ended, their parent
writing to them again: had the landing removed it, each command of theirs would
fail before it ran. So where their turn ended while their launch is still
served (`Resumable`), the cleanup detaches its `HEAD` at the commit it has
checked out, in the room, which changes no file, deletes the branch as for any
other, and leaves them lup's words saying so, told beside their next call
(`Delivery.left`). Once their launch has ended, nothing resumes them: the next
landing removes it as it removes any, where what landed holds its commit, and
names it as left where it doesn't, since it would be on no branch (`Lapsed`).
A worktree a resumed subagent put a branch in since is that branch's, and its
landing's to clean up after.

The tool's docstring's first line is its summary, 50 characters at most, which
the guidance lists (`launch/guidance.py`); the rest is its description. It
answers in words, as `content`.
"""

import asyncio
import hashlib
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime
from itertools import batched
from pathlib import Path, PurePath
from typing import override

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

import lup
from lup.doors import bound, declared
from lup.programs import Ran
from lup.publishing import Place, Refusal
from lup.tools import speaking
from lup.tools.serving import Answer
from lup.tools.tool import Accepted, Refused, ToolSpec
from lup.types import Model, MutableModel
from lup_dev.catalog.paths import PythonPaths
from lup_dev.codescan.contract import Parser, Source
from lup_dev.codescan.directives import Directive, Identity, added_deferrals
from lup_dev.codescan.engine import EngineError, EngineParser
from lup_dev.errors import LupDevError
from lup_dev.gate import Passed, Standing
from lup_dev.git import LISTED, Git, Tracked, nul_separated
from lup_dev.host.courier import Conversation as Caller
from lup_dev.host.courier import Conversations
from lup_dev.host.protocol import HostError, Register
from lup_dev.host.rooms import RoomTools
from lup_dev.host.service import Program, executed
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.roster import ids
from lup_dev.inbox.store import (
    AtLanding,
    ChangedFile,
    Decided,
    Done,
    Flagged,
    HeldChange,
    HowItFelt,
    Inbox,
    InboxError,
    Item,
    Reading,
    Text,
    Waiting,
    Whereabouts,
    Withdrawn,
    cited,
)
from lup_dev.layout import CheckoutLayout, GitDirectoryLayout, HostLayout, Layout
from lup_dev.merging import Conflicted, Failed, Merged, Merging
from lup_dev.policy.coming import Coming
from lup_dev.policy.reviewed import Mark, Reviews
from lup_dev.policy.roles import matches
from lup_dev.policy.waits import Awaited, Wait, Waits
from lup_dev.policy.worktrees import SessionIndex
from lup_dev.private.found import in_prose
from lup_dev.private.history import Commit, Spot
from lup_dev.private.module import Private
from lup_dev.private.refusing import refused as refusals_of
from lup_dev.private.withheld import Withheld
from lup_dev.private.withheld import kept as listed_at
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
from lup_ledger.parties import Conversation


class Landing(Model):
    """A branch to land."""

    branch: str | None = Field(
        default=None,
        description=(
            "The local branch to land, by its name, as `git branch` lists it: "
            "merged onto `dev` with a merge commit. Left out, `dev` lands as it "
            "is, for a change committed on it."
        ),
    )
    message: str | None = Field(
        default=None,
        description=(
            "The merge commit's message, whole, as `git commit -m` takes one: what "
            "changed and why, how it was tested. Given with `branch`, and only "
            "with it."
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
    """A flagged write as a landing reads it: its item's number, what it flagged, and who wrote it."""

    number: int
    flagged: Flagged
    writer: Conversation | None = None
    """The conversation whose write it flagged, its item's sender."""


class Seen(Model):
    """An item of a file the operator saw, and when they settled it."""

    item: Item
    at: datetime


class Outcome(Model):
    """How the operator answered one file a landing waited on."""

    path: Path
    approved: bool
    said: str
    """How, in a few words: `approved`, `declined`."""
    words: str = ""
    """What they said on it, where they declined it saying something."""


class Waited(Model):
    """What a landing's wait on its files came to: what reached the conversation meanwhile, told whole, and how each file was answered."""

    told: str
    outcomes: list[Outcome]


class Worktree(Model):
    """One worktree of the repository, as `git worktree list` gives it: its root, and the branch it has checked out, by its ref's full name."""

    root: Path
    branch: str | None = None
    head: str | None = None
    """The commit its `HEAD` names; none before the repository's first."""


class Worker(Model):
    """A worktree a conversation works in, and who, as a landing's cleanup says why it leaves it."""

    root: Path
    why: str


class Resumable(Model):
    """A subagent whose turn ended while their launch is still served, in the worktree lup gave them to work apart in (`Holding.apart`), where their shell starts each command: their runtime may resume them there, so a landing's cleanup keeps it, detached, rather than remove it."""

    root: Path
    conversation: Conversation
    who: str
    """Who they are, as people call them (`called`)."""


class Lapsed(Model):
    """A worktree a landing kept, detached, for a subagent who might be resumed there (`Resumable`), once their launch has ended and nothing resumes them: who it was kept for, and why it stays, where it does."""

    who: str
    why: str | None = None
    """Why it isn't removed: its `HEAD` is a commit the integration branch
    doesn't hold, which removing it would leave on no branch. None where it's
    removed."""


class Reached(Model):
    """The launch's room as a landing reaches it: its container's name where podman has it, else why lup can't reach it, said once."""

    container: str | None = None
    unreached: str | None = None


class Filesystem(Model):
    """One mount as `findmnt --json --output TARGET` lists it: where it's mounted."""

    target: Path


class Filesystems(Model):
    """What `findmnt --json --list --output TARGET` prints: every mount the room has."""

    filesystems: list[Filesystem]


class Laid(Model):
    """What the launch's room has mounted, as a landing's cleanup asks it before removing a worktree: each mount's place there."""

    targets: list[Path] = []
    unlisted: str | None = None
    """Why lup couldn't list them, where it couldn't: then no worktree is
    removed."""

    def over(self, root: Path) -> list[Path]:
        """Return each mount at or inside the worktree at `root`, from its root, as the room has it: what `git worktree remove` there couldn't remove."""
        return [
            target.relative_to(root)
            for target in self.targets
            if target.is_relative_to(root)
        ]


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


class Merge(Model):
    """A branch a landing merges, and where: the gated branch it lands on, by its ref's full name, on `remote`, at `old` there; the local branch's name and its tip."""

    onto: str
    remote: str
    old: str | None
    branch: str
    tip: str


class Made(Model):
    """What a landing lands, once any merge it asked for is made: its tip, what to say of the merge first, whether it's checked already, and what to say of the local branch where the landing then stops."""

    tip: str
    said: list[str] = []
    checked: bool = False
    """Whether the tip was checked as a landing is (`Lander.checked`), as a
    merge is before its branch moves."""
    moved: str | None = None
    """Where the merge moved the local branch, what an answer landing nothing
    says of it."""


class Turns(MutableModel, arbitrary_types_allowed=True):
    """One landing at a time in each repository, from its merge to its local branch moved: the lock each holds, made the first time one's asked for."""

    locks: dict[Path, asyncio.Lock] = {}

    def of(self, repository: Path) -> asyncio.Lock:
        """Return the lock of the repository whose git directory is `repository`."""
        return self.locks.setdefault(repository, asyncio.Lock())


def short(ref: str) -> str:
    """Return a branch's name from its ref's full name.

    >>> short("refs/heads/dev")
    'dev'
    """
    return ref.removeprefix("refs/heads/")


class Joined(Model):
    """A merge on a landing's first-parent line: its commit, and its first parent, the commit it merged onto."""

    commit: str
    onto: str


class Branches(Model):
    """The local branches in a landing's history and not in the remote's: those it lands, each ref's full name with its tip, and those it leaves alone, why for each."""

    landed: dict[str, str] = {}
    merges: dict[str, Joined] = {}
    """By each tip a merge on the first-parent line merged, that merge: what
    each branch it lands brings, against what it merged onto."""
    alone: list[str] = []
    """Those whose tip is one of the first-parent line's own commits: the
    landing merged nothing of theirs."""
    made: dict[str, list[str]] = {}
    """By each branch given to the landing, the others at the tip it was
    given at, where that tip is merged: made from it, with nothing of their
    own yet."""
    shared: list[str] = []
    """Those at a tip merged that more than one of them points at, none given
    to the landing: which of them was merged, the graph can't tell."""

    @property
    def holding(self) -> list[str]:
        """The branches whose flags hold the landing: those it lands, and those of which it may have merged one (`shared`)."""
        return [*self.landed, *self.shared]


def landed_branches(
    git: Git, tip: str, old: str | None, given: dict[str, str]
) -> Branches:
    """Return the local branches a landing of `tip` lands, and those it leaves alone.

    `given` are the branches given to the landing, each ref's full name with
    its tip as given: the branch landed, and the gated branch a merge moves
    onto `tip`. Of the local branches in `tip`'s history and not in `old`'s,
    the gated branch's tip on the remote where it has one, it lands those
    the landing merged: each given, and each other whose tip is a parent
    beyond the first of a merge on the first-parent line from `tip` down to
    `old`, where no given branch was given at that tip and no other branch
    points at it. The graph can't tell two branches at one commit apart:
    one at the tip a given branch was given at was made from it, as a worker
    starts their next piece (`made`); several at a tip merged, none given, may
    be either (`shared`); each is left alone. The rest have nothing of their
    own in it, their tip being one of that line's own commits: a branch just
    made from the integration branch, say, whose worktree a session may be
    about to work in.
    """
    excluded = [] if old is None else [f"^{old}"]
    walked = git.text("rev-list", "--first-parent", "--parents", tip, *excluded)
    # Each tip merged on the line, with the merge that merged it.
    merges = {
        parent: Joined(commit=merge, onto=parents[0])
        for line in walked.splitlines()
        for merge, *parents in [line.split()]
        for parent in parents[1:]
    }
    merged = {parent: joined.commit for parent, joined in merges.items()}
    listed = git.run(
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
        f"--merged={tip}",
        *([] if old is None else [f"--no-merged={old}"]),
        "refs/heads/",
    )
    found = dict(nul_separated(line) for line in listed.output.splitlines())
    # The branch given at each tip it was given at.
    tips = {at: ref for ref, at in given.items()}
    pointing = Counter(found.values())
    landed = {
        ref: commit
        for ref, commit in found.items()
        if ref in given
        or (commit in merged and commit not in tips and pointing[commit] == 1)
    }
    rest = {ref: commit for ref, commit in found.items() if ref not in landed}
    made = {
        ref: [each for each, commit in rest.items() if commit == at]
        for ref, at in given.items()
        if at in merged
    }
    return Branches(
        landed=landed,
        merges=merges,
        alone=[ref for ref, commit in rest.items() if commit not in merged],
        made={ref: others for ref, others in made.items() if others},
        shared=[
            ref
            for ref, commit in rest.items()
            if commit in merged and commit not in tips
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


def started(saw: Saw | None, git: Git, old: str | None, path: Path) -> bytes | None:
    """Return the version of the file at `path` its diff starts from: the one the operator last saw, `saw`; else the file at `old`, the integration branch's tip; none where there's neither, or `old` has no file there."""
    if saw is not None:
        return saw.content
    if old is None:
        return None
    return blob(git, old, path)


def worktrees(git: Git) -> list[Worktree]:
    """Return the repository's worktrees, its main one first, as `git worktree list` gives them, each with the branch it has checked out and the commit its `HEAD` names."""
    fields = nul_separated(git.run("worktree", "list", "--porcelain", "-z").output)
    starts = [at for at, field in enumerate(fields) if field.startswith("worktree ")]
    records = [
        fields[start:end]
        for start, end in zip(starts, [*starts[1:], len(fields)], strict=True)
    ]

    def labelled(record: list[str], label: str) -> str | None:
        return next(
            (
                field.removeprefix(f"{label} ")
                for field in record
                if field.startswith(f"{label} ")
            ),
            None,
        )

    return [
        Worktree(
            root=Path(record[0].removeprefix("worktree ")),
            branch=labelled(record, "branch"),
            head=labelled(record, "HEAD"),
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


class Deferral(Model):
    """A `# lup: defer` comment a landing adds or removes: the file it's in, from the repository's root, the line it's on in the version that holds it, and what it says (`Identity`), its issue or condition and why."""

    path: Path
    line: int
    identity: Identity

    def same(self) -> Deferral:
        """Return what tells it from another, whatever line it's on: itself at line 0."""
        return self.model_copy(update={"line": 0})

    def said(self) -> str:
        """Say where it is and what it says, as a landing's answer lists it.

        >>> said = Identity(text='defer(issue=155, why="w")', asked=False, defers=True)
        >>> Deferral(path=Path("a.py"), line=3, identity=said).said()
        'a.py:3: `# lup: defer(issue=155, why="w")`'
        """
        return f"{self.path}:{self.line}: `# lup: {self.identity.text}`"


def uncounted(whole: list[Deferral], parts: list[Deferral]) -> list[Deferral]:
    """Return those of `whole` that `parts` don't account for, each counted as many times as it's there, and the same on any line, as `missing` counts a file's comments.

    >>> said = Identity(text='defer(issue=1, why="w")', asked=False, defers=True)
    >>> one = Deferral(path=Path("a.py"), line=3, identity=said)
    >>> uncounted([one, one], [one.model_copy(update={"line": 8})]) == [one]
    True
    """
    counts = Counter(each.same() for each in parts)

    def counted(index: int, each: Deferral) -> bool:
        earlier = [other for other in whole[:index] if other.same() == each.same()]
        return len(earlier) < counts[each.same()]

    return [each for index, each in enumerate(whole) if not counted(index, each)]


class Deferred(Model):
    """The `# lup: defer` comments one part of a landing adds and removes against what it lands on: each added on its line where it lands, each removed on its line where it was."""

    added: list[Deferral] = []
    removed: list[Deferral] = []

    def beyond(self, parts: list[Deferred]) -> Deferred:
        """Return what of this none of `parts` accounts for: of a whole landing's, what its branches' merges, `parts`, don't."""
        return Deferred(
            added=uncounted(
                self.added, [each for part in parts for each in part.added]
            ),
            removed=uncounted(
                self.removed, [each for part in parts for each in part.removed]
            ),
        )

    @property
    def empty(self) -> bool:
        """Whether it adds and removes none."""
        return not self.added and not self.removed

    def lines(self, whose: str, against: str, *, many: bool = False) -> list[str]:
        r"""Say what `whose` adds and removes against `against`, a line each, under a line saying whose they are; `many` where `whose` names several commits.

        >>> said = Identity(text='defer(issue=155, why="w")', asked=False, defers=True)
        >>> added = Deferral(path=Path("a.py"), line=3, identity=said)
        >>> print("\n".join(Deferred(added=[added]).lines("`feat`", "`dev`")))
        The `# lup: defer` comments `feat` adds and removes, against `dev`:
        - adds a.py:3: `# lup: defer(issue=155, why="w")`
        """
        adds, removes = ("add", "remove") if many else ("adds", "removes")
        return [
            (
                f"The `# lup: defer` comments {whose} {adds} and {removes}, against "
                f"{against}:"
            ),
            *(f"- adds {each.said()}" for each in self.added),
            *(f"- removes {each.said()}" for each in self.removed),
        ]


def undeferring(whose: list[str], against: str, *, many: bool = False) -> list[str]:
    """Say in one line that each of `whose` adds and removes no `# lup: defer` comment against `against`, or nothing where it names none; `many` where the one it names is several commits.

    >>> undeferring(["`feat`"], "`dev`")
    ['`feat` adds no `# lup: defer` comment and removes none, against `dev`.']
    >>> undeferring(["`a`", "`b`", "`c`"], "`dev`")
    ['`a`, `b` and `c` add no `# lup: defer` comment and remove none, against `dev`.']
    """
    if not whose:
        return []
    *first, last = whose
    named = f"{', '.join(first)} and {last}" if first else last
    adds, removes = ("add", "remove") if many or first else ("adds", "removes")
    return [
        (
            f"{named} {adds} no `# lup: defer` comment and {removes} none, against "
            f"{against}."
        )
    ]


def deferred(
    git: Git, parser: Parser, root: Path, before: str | None, after: str
) -> Deferred:
    """Return the `# lup: defer` comments the commit `after` adds and removes against the commit `before`, or against no files where it's none.

    Each Python file they differ in is read from each version's parse alone by
    `parser`, for the worktree at `root`, as trust's first reading reads a
    change, and its deferrals compared as the judge compares a file's
    directives (`added_deferrals`): one moved to another line is neither added
    nor removed.
    """
    paths = [
        path
        for path in changed_files(git, before, after)
        if matches(PurePath(path.name), PythonPaths().python)
    ]
    was = {
        path: None if before is None else text(blob(git, before, path))
        for path in paths
    }
    now = {path: text(blob(git, after, path)) for path in paths}
    sources = list(
        dict.fromkeys(
            Source(path=path, content=content)
            for path in paths
            for content in [was[path], now[path]]
            if content is not None
        )
    )
    reports = parser.parsed(root, sources) if sources else []
    read = dict(zip(sources, reports, strict=True))

    def directives(path: Path, content: str | None) -> list[Directive]:
        if content is None:
            return []
        return read[Source(path=path, content=content)].directives

    def compared(
        before: dict[Path, str | None], after: dict[Path, str | None]
    ) -> list[Deferral]:
        return [
            Deferral(path=path, line=each.line, identity=each.identity())
            for path in paths
            for each in added_deferrals(
                directives(path, before[path]), directives(path, after[path])
            )
        ]

    return Deferred(added=compared(was, now), removed=compared(now, was))


def stands(kept: ChangedFile, landed: bytes | None) -> bool:
    """Say whether the file a flagged write keeps, `kept`, is the file a landing leaves, `landed`: the same text, or none on both sides; never where what it keeps isn't text.

    >>> stands(ChangedFile.of(Path("a.py"), None, b"x = 1"), b"x = 1")
    True
    >>> stands(ChangedFile.of(Path("a.py"), b"x = 1", None), b"x = 1")
    False
    """
    match kept.after:
        case None:
            return landed is None
        case Text(text=written):
            return written.encode() == landed
        case _:
            return False


def settled_at(item: Item) -> datetime | None:
    """Return when the operator settled `item`, read, commented on, approved or declined; none where they haven't."""
    match item.state:
        case Done(at=at) | Decided(at=at):
            return at
        case _:
            return None


def outcome(awaited: Awaited, approving: Callable[[int], bool]) -> Outcome:
    """Say how the operator answered `awaited`, a file a landing waited on, each of its flags approved where `approving` says.

    >>> from lup_dev.policy.waits import Declined
    >>> done = Awaited(path=Path("a.py"), flags=[3], writers=[])
    >>> outcome(done, lambda _: True).said
    'approved'
    >>> said = Declined(at=datetime(2026, 1, 1), words="Not yet.")
    >>> no = outcome(done.model_copy(update={"declined": said}), lambda _: False)
    >>> (no.approved, no.said, no.words)
    (False, 'declined', 'Not yet.')
    """
    if awaited.declined is not None:
        return Outcome(
            path=awaited.path,
            approved=False,
            said="declined",
            words=awaited.declined.words,
        )
    if all(approving(each) for each in awaited.flags):
        return Outcome(path=awaited.path, approved=True, said="approved")
    return Outcome(
        path=awaited.path, approved=False, said="still waiting for the operator"
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


def approved(item: Item) -> bool:
    """Say whether the operator approved `item`."""
    return isinstance(item.state, Decided) and item.state.approved


class Saw(Model):
    """The version of a file the operator last saw on a branch, which its diff starts from: its bytes, none where they saw it deleted; and where they saw it, an item of it they settled or the mark they made reviewing it in its agent's drawer."""

    content: bytes | None
    item: int | None = None
    reviewed: Mark | None = None


class Baseline(Model, arbitrary_types_allowed=True):
    """What the operator last saw of a repository's files, read from the inbox and from what they marked reviewed: the version each hold at landing starts from, and each file of an agent's drawer since they approved it (`lup_dev.policy.since`)."""

    inbox: Inbox
    repository: Path
    """The repository's git directory."""
    reviews: Reviews
    """The files of its branches the operator marked reviewed."""
    items: list[Item] | None = None
    """The inbox's items about the repository, as read once for a whole
    drawer, which asks of each of a branch's files; none reads them as they
    stand at each asking."""

    @property
    def about(self) -> list[Item]:
        """The inbox's items about the repository, oldest first: `items` where they were read once, else as they stand."""
        return self.inbox.about(self.repository) if self.items is None else self.items

    def flags(self, branches: list[str], path: Path | None = None) -> list[Flag]:
        """Return the flagged writes on `branches` the operator hasn't approved and lup hasn't taken back (`Withdrawn`), those on the file at `path` alone where one's given."""
        return [
            Flag(
                number=item.number,
                flagged=item.reason,
                writer=item.sender if isinstance(item.sender, Conversation) else None,
            )
            for item in self.about
            if isinstance(item.reason, Flagged)
            and item.reason.branch in branches
            and (path is None or item.reason.path == path)
            and not approved(item)
            and not isinstance(item.state, Withdrawn)
        ]

    def seen(self, path: Path, landed: list[str]) -> Item | None:
        """Return the latest item of the file at `path` on the branches `landed` that the operator saw: a flagged write or a hold at landing they approved, read or commented on, the last they settled; none where they saw none."""
        seen = [
            Seen(item=item, at=at)
            for item in self.about
            if flagged_on(path, landed, item) and (at := settled_at(item)) is not None
        ]
        latest = max(seen, key=lambda each: each.at, default=None)
        return None if latest is None else latest.item

    def saw(self, path: Path, landed: list[str]) -> Saw | None:
        """Return the version of the file at `path` the operator last saw on the branches `landed`: the one they last marked reviewed, or the one kept beside the latest item of it they settled (`seen`), whichever came last, a mark made as the item was settled winning; none where they saw none, or what they saw isn't kept, an item's not as text."""
        seen = self.seen(path, landed)
        marks = [
            mark
            for branch in landed
            if (mark := self.reviews.marks(branch).of(path)) is not None
        ]
        mark = max(marks, key=lambda each: each.at, default=None)
        settled = None if seen is None else settled_at(seen)
        if mark is not None and (settled is None or mark.at >= settled):
            content = self.reviews.content(mark)
            if mark.version is None or content is not None:
                return Saw(content=content, reviewed=mark)
        if seen is None:
            return None
        kept = self.kept(seen, path)
        return None if kept is None else Saw(content=kept, item=seen.number)

    def kept(self, item: Item, path: Path) -> bytes | None:
        """Return the version of `path` kept beside `item`, what it changed it to; none where none is kept as text."""
        try:
            files = self.inbox.files(item.number)
        except InboxError:
            return None
        found = next((each for each in files if each.path == path), None)
        if found is None or not isinstance(found.after, Text):
            return None
        return found.after.text.encode()

    def reading(self, flag: Flag, after: bytes | None) -> Reading | None:
        """Return the judge's reading of the file as `flag`, the latest on it, kept it: its lines and findings kept only where the file as it stands, `after`, is as that flag left it."""
        try:
            files = self.inbox.files(flag.number)
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
    turns: Turns
    """The lock a merge holds until its local branch moved, the service's."""
    parser: Parser = Field(default_factory=EngineParser)
    """Reads a file from its parse alone, on the host: each `# lup: defer`
    comment a landing adds and removes (`deferrals`)."""
    waits: Waits
    """The landings waiting on the operator, the service's: this one's among
    them while it waits."""
    coming: Coming | None = None
    """What wakes the threads parked until a branch it lands or an issue
    closing (`lup_dev.policy.coming`); none wakes none."""

    @property
    def party(self) -> Conversation:
        """Return the inbox's party for the conversation landing."""
        return Delivery.party(self.launch, self.caller)

    @property
    def baseline(self) -> Baseline:
        """Return what the operator last saw of the repository's files."""
        repository = self.launch.repository
        return Baseline(
            inbox=self.delivery.inbox,
            repository=repository,
            reviews=Reviews.of(self.layout, repository),
        )

    @lup.tool(idempotent=True)
    async def land(self, landing: Landing) -> str:
        """Land a branch on the integration branch.

        Merges your local `branch` onto `dev` with a merge commit carrying
        `message`, in your room and apart from every checkout, and puts it on
        the remote's `dev`, as `git push origin dev` would. Where the merge
        conflicts, it names the files and changes nothing: merge `dev` into the
        branch in its worktree, resolve, run the gate there, and call it again.
        The gate runs on the merge with `--fix`, its fixes amended into the
        merge commit, unless it passed on those files already, as on a branch
        that held `dev`; where it fails, it answers with its report and changes
        nothing. Then `dev`'s checkout is fast-forwarded to the merge, which
        git refuses rather than touch uncommitted work there. Without a branch,
        `dev` lands as it is, once the gate passed on its files (`uv run
        lup-dev check`, with everything committed, records the pass). Each file
        the landing changes that was flagged on a branch it lands (a new file,
        a file written whole, a change to the public API) is a hold in the
        operator's inbox, showing what changed since they last saw it, and
        this call waits for their answers, which may take hours. Approved, it
        lands. Where they comment without approving, or decline, it returns
        their words and lands nothing: answer them, commit, and call it again;
        what they approved stays approved. Once landed, it lists the
        `# lup: defer` comments each branch it landed adds and removes against
        `dev`, each with its file and line, or says there are none, so the work
        left undone shows as it lands. Each conversation still going that
        worked on a branch it landed, and hasn't said how the work felt, is
        invited to, once, beside their next call. Then it cleans up after each
        branch it landed: deletes its copy on the remote, removes its worktree
        where it's clean and nobody works in it, and deletes the local branch.
        A worktree a subagent started in, whose turn ended while their session
        goes on, it keeps, detached at what landed, so they can be resumed
        there; a landing after their session ends removes it.
        A flagged write still waiting that's left nothing to hold, on a branch
        gone or on a file a branch it landed leaves unchanged, it withdraws
        from the operator's inbox, saying which.
        The branches it landed are the one you gave, and each other merged
        into `dev` whose tip no other branch shares; a branch made from the
        one you gave, at its tip, is left alone, worktree and all, as is each
        of several sharing a merged tip, and each one just made from `dev`.
        What it leaves, it says, and why. Its last lines say what's still
        running or waiting to land: your session's subagents lup hasn't heard
        end, and the local branches not on `dev`, with who works in each.
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
        """Land `landing`'s branch, merged where it names one, waiting on its holds, and clean up after it: what the agent reads."""
        onto = self.onto(landing)
        merging = landing.branch not in [None, short(onto)]
        if merging and not (landing.message or "").strip():
            message = (
                f"landing `{landing.branch}` merges it with a merge commit, which "
                "needs its `message`: what changed and why, how it was tested"
            )
            raise HostError(message)
        if not merging and landing.message is not None:
            message = (
                f"without a branch to merge, `{short(onto)}` lands as it is, making "
                "no merge commit for a `message`: leave it out, or name the branch"
            )
            raise HostError(message)
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
        await self.fetched(remote, onto, old)
        numbers = await self.numbers(
            git, tip, refs, landing.message if merging else None
        )
        if numbers:
            return numbers_refused(numbers)
        made = Made(tip=tip)
        if merging:
            merged = await self.merge(
                git,
                Merge(onto=onto, remote=remote, old=old, branch=source, tip=tip),
                landing.message or "",
            )
            if isinstance(merged, str):
                return merged
            made = merged
        # The branch whose tip lands: `onto`'s own once a merge was asked for.
        named = short(onto) if merging else source
        lands = made.tip
        if old == lands:
            nothing = (
                f"Nothing to land: `{short(onto)}` on `{remote}` is at {lands} already."
            )
            return "\n".join([*made.said, nothing])
        if not made.checked:
            refused = await self.checked(
                git, Merge(onto=onto, remote=remote, old=old, branch=named, tip=lands)
            )
            if refused is not None:
                return refused
        # The branches given to the landing: the one landed, at its tip as
        # given, and the gated one a merge moved onto what lands.
        given = {f"refs/heads/{source}": tip, f"refs/heads/{named}": lands}
        branches = await asyncio.to_thread(landed_branches, git, lands, old, given)
        changed = await asyncio.to_thread(changed_files, git, old, lands)
        holds = self.holds(onto, lands, old, branches.holding, changed=changed)
        waited = await self.waited(holds)
        if not all(each.approved for each in waited.outcomes):
            return unapproved(waited, made.moved)
        reply = await PushHandler(remotes=self.remotes).answer(
            Pushing(remote=remote, updates=[Update(source=lands, destination=onto)]),
            self.launch,
        )
        if not isinstance(reply, Pushed):
            message = f"the push answered {reply.kind}"
            raise HostError(message)
        [update] = reply.updates
        if update.error is not None:
            kept = " What the operator approved stays approved." if holds else ""
            refusals = f"\n{reply.said}" if reply.said else ""
            moved = [] if made.moved is None else [made.moved]
            return "\n".join([f"Not landed: {update.error}.{kept}{refusals}", *moved])
        untracked = await asyncio.to_thread(tracked, git, remote, onto, lands)
        if self.coming is not None:
            await self.coming.landed(
                self.launch, short(onto), [short(each) for each in branches.landed]
            )
        await self.invited(git, branches.landed, onto)
        deferrals = await self.deferrals(
            git,
            Merge(onto=onto, remote=remote, old=old, branch=named, tip=lands),
            branches,
        )
        cleaned = await self.cleaned(
            git, remote, refs, branches.landed, onto=onto, tip=lands
        )
        withdrawn = await self.withdrawn(git, onto, lands, branches.holding, changed)
        was = "new there" if old is None else f"which was at {old}"
        going = await self.going(git, lands, onto)
        return "\n".join(
            [
                *made.said,
                f"Landed {lands} on `{short(onto)}` at `{remote}`, {was}.",
                *untracked,
                *approvals(waited),
                *deferrals,
                *said(cleaned),
                *withdrawals(short(onto), withdrawn),
                *left_alone(named, branches),
                *going,
            ]
        )

    async def numbers(
        self, git: Git, tip: str, refs: list[Ref], message: str | None
    ) -> list[Refusal]:
        """Refuse each inbox item's number in the messages the landing would publish, `message` the merge commit's where it makes one, before anything merges: where the list kept for the repository withholds them; none where none is kept, which the door builds at the push.

        At the push, after the merge, the local branch's move and the
        operator's answers, a refusal would leave the branch to rewrite beneath
        a merge already made.
        """
        data = self.layout.module_data(Private.name, self.launch.repository)
        held = read_model(listed_at(data), Withheld)
        if held is None or not held.numbers:
            return []
        has = [ref.object for ref in refs]
        commits = await asyncio.to_thread(git.walked, [tip], has)
        return await asyncio.to_thread(item_numbers, git, commits, message)

    async def fetched(self, remote: str, onto: str, old: str | None) -> None:
        """Fetch `old`, `onto`'s tip on `remote`, into the store, writing no ref, so git can tell what holds it; nothing where `onto` isn't there yet.

        Raise `HostError` where it moved since it was listed.
        """
        if old is None:
            return
        wanted = [Wanted(object=old, name=onto)]
        if await self.remotes.fetched(self.launch, remote, wanted, push=True):
            message = (
                f"`{short(onto)}` moved on `{remote}` while lup read it: land again"
            )
            raise HostError(message)

    async def checked(self, git: Git, landing: Merge) -> str | None:
        """Say why `landing`'s tip, its branch's, doesn't land: it isn't a fast-forward of the remote's, or the gate has no pass on its files; none where it lands."""
        refused = await self.forward(
            landing.remote, landing.onto, landing.branch, landing.tip, landing.old
        )
        if refused is not None:
            return refused
        return await asyncio.to_thread(self.unpassed, git, landing.tip, landing.branch)

    async def merge(self, git: Git, asked: Merge, message: str) -> Made | str:
        """Merge `asked`'s branch onto the integration branch in the launch's room, with `message`, check the merge as a landing is checked, and fast-forward the local branch to it, one landing at a time; return what lands, or say why nothing does.

        The merge goes onto the local branch where it holds the remote's tip,
        else onto the remote's (`base`). A branch already in that history merges
        nothing: what lands is that history's tip. The room's answer is read
        as its model (`Merging`), and the commit it names is checked on the
        host: its parents read from it alone, the remote's tip in its history,
        a pass of the gate recorded for its files.
        """
        onto, branch = short(asked.onto), asked.branch
        async with self.turns.of(self.launch.repository):
            local = await asyncio.to_thread(git.commit, asked.onto)
            base = await self.base(asked, local)
            if await self.remotes.descends(self.launch, base, asked.tip):
                return Made(
                    tip=base,
                    said=[
                        (
                            f"`{branch}` is in `{onto}`'s history already, so "
                            f"nothing was merged: `{onto}` lands as it is."
                        )
                    ],
                )
            if self.launch.runner is None:
                return (
                    "Not landed: this launch began before lup kept the project's "
                    "runner with it, which the merge runs in your room through: "
                    f"relaunch it, or merge `{branch}` into `{onto}` yourself and "
                    "call `land` without a branch."
                )
            room = await self.reached()
            if room.container is None:
                return f"Not landed: {room.unreached}, so nothing was merged."
            ran = await self.run(
                Program(
                    command=[
                        "podman",
                        "exec",
                        "--interactive",
                        "--workdir",
                        str(self.launch.worktree),
                        room.container,
                        *self.launch.runner,
                        "lup-dev",
                        "merge",
                        base,
                        asked.tip,
                    ],
                    payload=message,
                    directory=self.launch.repository,
                )
            )
            match room_merged(ran):
                case str() as unread:
                    return unread
                case Conflicted(files=files):
                    return await self.conflicted(git, asked, files)
                case Failed(commit=commit, report=report):
                    return gate_failed(asked, commit, report)
                case Merged() as done:
                    pass
            parents = await self.parents(done.commit)
            if parents != [base, asked.tip]:
                return (
                    f"Not landed: the merge your room answered, {done.commit}, isn't "
                    f"one of {base} and {asked.tip}: nothing has changed."
                )
            landing = asked.model_copy(update={"tip": done.commit})
            refused = await self.checked(git, landing)
            if refused is not None:
                return refused
            moved = await self.moved(git, room.container, asked.onto, local, done)
            if moved is not None:
                return moved
        here = "" if local is None else f", and moved `{onto}` here to it"
        held = (
            None
            if local is None
            else (
                f"`{onto}` here holds the merge, {done.commit}, which `{asked.remote}`'s "
                "doesn't yet: the next `land` lands it."
            )
        )
        return Made(
            tip=done.commit,
            said=[
                f"Merged `{branch}` onto `{onto}` as {done.commit}{here}: {gated(done)}."
            ],
            checked=True,
            moved=held,
        )

    async def base(self, asked: Merge, local: str | None) -> str:
        """Return the commit a merge of `asked` goes onto: the local branch's tip, `local`, where it holds the remote's; the remote's where the local one is behind it.

        Raise `HostError` where neither has the branch, or each has moved since
        they parted.
        """
        onto, old = short(asked.onto), asked.old
        if local is None:
            if old is None:
                message = (
                    f"neither this repository nor `{asked.remote}` has a `{onto}` to "
                    "merge onto"
                )
                raise HostError(message)
            return old
        if old is None or await self.remotes.descends(self.launch, local, old):
            return local
        if await self.remotes.descends(self.launch, old, local):
            return old
        message = (
            f"`{onto}` here and on `{asked.remote}` have each moved since they parted, "
            f"at {local} and {old}: merge `{asked.remote}`'s into `{onto}` where it's "
            "checked out, and land again"
        )
        raise HostError(message)

    async def parents(self, commit: str) -> list[str]:
        """Return `commit`'s parents, read from the commit alone (`Remotes.git`, `own_parents`), as the room can't have them read otherwise.

        Raise `HostError` where git can't read it.
        """
        ran = await self.remotes.git(
            self.launch,
            "rev-list",
            "--parents",
            # lup: ignore("fixed-tool-limit", why="one commit's own parents are read, the one line `rev-list` gives for it: no list an agent asked for is cut short")
            "--max-count=1",
            commit,
            own_parents=True,
        )
        if ran.status != 0:
            message = f"git couldn't read {commit}'s parents: {oneline(ran.said())}"
            raise HostError(message)
        _, *parents = ran.text().split()
        return parents

    async def moved(
        self, git: Git, container: str, onto: str, local: str | None, merged: Merged
    ) -> str | None:
        """Fast-forward the local branch `onto`, at `local`, to the merge `merged` in the launch's room, `container`; say why it didn't, or none where it did, or there's no local branch to move.

        Where a worktree has it checked out, `git merge --ff-only` moves it
        there, refusing rather than touch uncommitted work in the files the
        merge changes; elsewhere, the ref alone moves, from `local` alone.
        """
        if local is None:
            return None
        trees = await asyncio.to_thread(worktrees, git)
        checkout = next((each.root for each in trees if each.branch == onto), None)
        how = "git update-ref" if checkout is None else "git merge --ff-only"
        moving = (
            ["git", "update-ref", onto, merged.commit, local]
            if checkout is None
            else ["git", "merge", "--ff-only", "--quiet", merged.commit]
        )
        ran = await self.run(
            Program(
                command=[
                    "podman",
                    "exec",
                    "--workdir",
                    str(checkout or self.launch.worktree),
                    container,
                    *moving,
                ],
                payload="",
                directory=self.launch.repository,
            )
        )
        if ran.status == 0:
            return None
        said = oneline(ran.said()) or f"it ended with status {ran.status}"
        where = (
            f"`{short(onto)}`"
            if checkout is None
            else f"`{short(onto)}`'s checkout, {checkout},"
        )
        return (
            f"Not landed: {where} wasn't fast-forwarded to the merge, {merged.commit}, "
            f"which no branch names (`{how}`: {said}). Nothing else has changed: "
            "commit or set aside what's in the way there, and call `land` again, "
            "which finds the gate's pass and runs nothing."
        )

    async def conflicted(self, git: Git, asked: Merge, files: list[Path]) -> str:
        """Say that merging `asked`'s branch conflicts in `files`, and how it lands: merged the other way in its worktree, by whoever works there."""
        branch = f"refs/heads/{asked.branch}"
        trees = await asyncio.to_thread(worktrees, git)
        places = list(self.delivery.inbox.whereabouts.values())
        working = await asyncio.to_thread(self.working, places)
        roots = [each.root for each in trees if each.branch == branch]
        where = (
            "in a worktree of its own"
            if not roots
            else f"in its worktree, {roots[0]} ({working[roots[0]]})"
            if roots[0] in working
            else f"in its worktree, {roots[0]}"
        )
        onto = short(asked.onto)
        return "\n".join(
            [
                f"Not landed: merging `{asked.branch}` onto `{onto}` conflicts, in:",
                *(f"- {each}" for each in files),
                (
                    f"Nothing has changed. Merge `{onto}` into `{asked.branch}` "
                    f"{where}, resolve, run the gate there, and call `land` again."
                ),
            ]
        )

    async def going(self, git: Git, tip: str, onto: str) -> list[str]:
        """Say what's still running or waiting to land, once `tip` landed on `onto`: the subagents of the session landing whom lup hasn't heard end, then the local branches not in `tip`'s history, but the gated and protected ones, each with where it's checked out and who works there; or that nothing is.

        It's only as true as lup's hearing of each subagent's end (`Whereabouts.ended`).
        """
        limits = self.launch.limits
        places = list(self.delivery.inbox.whereabouts.values())
        subagents = [
            place
            for place in places
            if place.launch == self.launch.launch
            and place.conversation.session == self.caller.session
            and place.conversation.agent not in [None, self.caller.agent]
            and place.parent is not None
            and place.ended is None
        ]
        listed = await asyncio.to_thread(
            git.run,
            "for-each-ref",
            "--format=%(refname)",
            f"--no-merged={tip}",
            "refs/heads/",
        )
        branches = [
            ref
            for ref in listed.output.decode().splitlines()
            if not matching(ref, limits.gated) and not matching(ref, limits.protected)
        ]
        trees = await asyncio.to_thread(worktrees, git)
        working = await asyncio.to_thread(self.working, places)
        host = self.layout.host
        lines = [
            *(
                f"- {called(host, place)}, a subagent of yours lup hasn't heard end"
                for place in subagents
            ),
            *(
                waiting(
                    ref, [each.root for each in trees if each.branch == ref], working
                )
                for ref in branches
            ),
        ]
        if not lines:
            return [
                (
                    "Nothing else is running or waiting to land: no subagent of "
                    f"yours lup hasn't heard end, and no local branch off "
                    f"`{short(onto)}`."
                )
            ]
        return ["Still running or waiting to land:", *lines]

    async def invited(self, git: Git, landed: dict[str, str], onto: str) -> None:
        """Invite each conversation still going that worked on a branch the landing landed, once, to say how the work felt, where they haven't said: lup's words left for them (`Delivery.left`), told beside their next call, the conversation landing's beside this call's result, never holding an end.

        Who worked on a branch is who works in a worktree having it checked
        out: a conversation the judge's session index places there
        (`Holding.works`), or a session's own conversation whose launch
        started there, read before the cleanup removes the worktree. One that
        has ended isn't told: no runtime reaches them unless they're resumed,
        and their work's start invited them already (`invitation`,
        `host/service.py`).
        Each is invited at one landing at most (`Whereabouts.felt_asked`).
        """
        limits = self.launch.limits
        refs = [
            ref
            for ref in landed
            if ref != onto
            and not matching(ref, limits.gated)
            and not matching(ref, limits.protected)
        ]
        if not refs:
            return
        trees = await asyncio.to_thread(worktrees, git)
        built = {
            each.root: short(each.branch)
            for each in trees
            if each.branch is not None and each.branch in refs
        }
        index = SessionIndex(layout=self.layout)
        inbox = self.delivery.inbox
        # Who said how it felt, with the item they said it in.
        felt = {
            item.sender: item.number
            for item in inbox.items.values()
            if isinstance(item.reason, HowItFelt)
        }
        for place in list(inbox.whereabouts.values()):
            party = place.conversation
            if (
                party.repository != self.launch.repository
                or place.ended is not None
                or place.felt_asked
                or party in felt
            ):
                continue
            held = await asyncio.to_thread(index.read, party.session)
            works = [] if held is None else held.works(party.agent or "")
            started = [place.worktree] if party.agent is None else []
            names = sorted(
                dict.fromkeys(
                    built[root] for root in [*works, *started] if root in built
                )
            )
            if not names:
                continue
            inbox.placed(place.model_copy(update={"felt_asked": True}))
            self.delivery.left(party, landed_felt(names))

    async def deferrals(
        self, git: Git, landing: Merge, branches: Branches
    ) -> list[str]:
        """Say the `# lup: defer` comments `landing`, of its tip onto its gated branch, adds and removes, a line each: each of `branches` it landed's, by its merge against the commit that merged onto, those adding and removing none named in one line; then the gated branch's own commits', what the landing adds and removes against the gated branch's tip on the remote beyond its branches', where there's any, or that there's none where it merged no branch.

        It's information, and refuses nothing: where they can't be read, it
        says why.
        """
        merged = {
            ref: joined
            for ref, tip in branches.landed.items()
            if ref != landing.onto and (joined := branches.merges.get(tip)) is not None
        }
        root = self.launch.worktree
        try:
            each = {
                ref: await asyncio.to_thread(
                    deferred, git, self.parser, root, joined.onto, joined.commit
                )
                for ref, joined in merged.items()
            }
            whole = await asyncio.to_thread(
                deferred, git, self.parser, root, landing.old, landing.tip
            )
        except EngineError as unread:
            return [f"lup couldn't read the `# lup: defer` comments it lands: {unread}"]
        own = whole.beyond(list(each.values()))
        gated = f"`{short(landing.onto)}`"
        commits = f"{gated}'s own commits"
        against = f"{gated} on `{landing.remote}`"
        return [
            *(
                line
                for ref, found in each.items()
                if not found.empty
                for line in found.lines(f"`{short(ref)}`", gated)
            ),
            *undeferring(
                [f"`{short(ref)}`" for ref, found in each.items() if found.empty], gated
            ),
            *([] if own.empty else own.lines(commits, against, many=True)),
            *(
                undeferring([commits], against, many=True)
                if own.empty and not merged
                else []
            ),
        ]

    async def forward(
        self, remote: str, onto: str, source: str, tip: str, old: str | None
    ) -> str | None:
        """Say why `tip` doesn't land on `onto`, at `old` on `remote`, where it isn't a fast-forward of it; none where it is, or `onto` isn't there yet.

        `old` is in the store already (`fetched`), so git can tell.
        """
        if old is None:
            return None
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

    def holds(
        self,
        onto: str,
        tip: str,
        old: str | None,
        branches: list[str],
        *,
        changed: list[Path],
    ) -> Wait | None:
        """Return the landing's wait on each file it changes, `changed`, that's flagged on one of `branches`, those it lands or may have merged (`Branches.holding`), and not approved, every such flag on it; none where none is."""
        names = [short(ref) for ref in branches]
        flags = [
            each for each in self.baseline.flags(names) if each.flagged.path in changed
        ]
        paths = list(dict.fromkeys(each.flagged.path for each in flags))
        if not paths:
            return None

        def awaited(path: Path) -> Awaited:
            on = [each for each in flags if each.flagged.path == path]
            return Awaited(
                path=path,
                flags=[each.number for each in on],
                writers=list(
                    dict.fromkeys(each.writer for each in on if each.writer is not None)
                ),
            )

        return Wait(
            key=uuid.uuid4().hex,
            repository=self.launch.repository,
            lander=self.party,
            onto=onto,
            old=old,
            tip=tip,
            branches=list(
                dict.fromkeys(
                    each.flagged.branch for each in flags if each.flagged.branch
                )
            ),
            files=[awaited(path) for path in paths],
            began=self.delivery.clock.now(),
        )

    async def noticed(self, wait: Wait) -> None:
        """Raise one desktop notice for `wait`, a landing beginning to wait: who lands what where, how many files it waits on, and whose drawers show them."""
        roster = self.delivery.roster()
        count = len(wait.files)
        files = f"{count} file{'' if count == 1 else 's'}"
        writers = list(
            dict.fromkeys(who for each in wait.files for who in each.writers)
        )
        drawers = ", ".join(roster.who(each) for each in writers) or "its writers"
        await self.delivery.notices.notify(
            f"lup: {roster.who(self.party)}'s landing of {wait.named} waits on {files}",
            "\n".join(
                [
                    ", ".join(str(each.path) for each in wait.files),
                    f'Answer each in "since you approved" of {drawers}.',
                ]
            ),
        )

    async def withdrawn(
        self,
        git: Git,
        onto: str,
        tip: str,
        branches: list[str],
        changed: list[Path],
    ) -> list[Flag]:
        """Withdraw each flagged write still waiting for the operator that's left nothing to hold, once the landing of `tip` on `onto` has landed and cleaned up; return those withdrawn.

        Nothing is left where its branch is gone, the landing's cleanup having
        deleted it, or any branch deleted earlier, landed or not: it holds no
        landing. Nor, on one of `branches`, those whose flags hold this landing,
        on a file it doesn't change, `changed` being those it does, where the
        file stands at `tip` as the flag keeps it, landed before. On a branch
        still there, a file standing otherwise may be a write not committed
        yet, which the branch's next landing holds on: that flag waits.
        """
        names = [short(ref) for ref in branches]
        inbox = self.delivery.inbox
        waiting = [
            Flag(number=item.number, flagged=item.reason)
            for item in self.baseline.about
            if isinstance(item.reason, Flagged) and isinstance(item.state, Waiting)
        ]
        gone = [
            branch
            for branch in dict.fromkeys(each.flagged.branch for each in waiting)
            if branch is not None
            and await asyncio.to_thread(git.commit, f"refs/heads/{branch}") is None
        ]
        name = short(onto)

        async def why(flag: Flag) -> str | None:
            path, branch = flag.flagged.path, flag.flagged.branch
            if branch in gone and branch in names:
                return f"`{branch}` landed on `{name}` at {tip}, and is gone since"
            if branch in gone:
                return f"`{branch}` is gone, so it holds no landing"
            if branch not in names or path in changed:
                return None
            try:
                files = inbox.files(flag.number)
            except InboxError:
                return None
            kept = next((each for each in files if each.path == path), None)
            landed = await asyncio.to_thread(blob, git, tip, path)
            if kept is None or not stands(kept, landed):
                return None
            return (
                f"the file stands on `{name}` at {tip} as it flagged it, landed before"
            )

        async def withdrew(flag: Flag) -> bool:
            reason = await why(flag)
            return (
                reason is not None
                and self.delivery.flag_withdrawn(flag.number, reason) is not None
            )

        return [flag for flag in waiting if await withdrew(flag)]

    async def waited(self, wait: Wait | None) -> Waited:
        """Hold the call until each file `wait` waits on is answered in its writer's drawer, its flags approved or the file declined, and return what reached the conversation meanwhile, told, and how each was answered; at once, telling nothing, where there's none.

        The wait is kept in `waits` while the call holds, so the drawers show
        each file held at landing, and forgotten as it ends, however it ends.
        """
        if wait is None:
            return Waited(told="", outcomes=[])
        inbox = self.delivery.inbox

        def approving(number: int) -> bool:
            found = inbox.items.get(number)
            return found is not None and approved(found)

        def standing() -> Wait:
            return self.waits.waits.get(wait.key, wait)

        def answered() -> bool:
            return all(
                outcome(each, approving).said != "still waiting for the operator"
                for each in standing().files
            )

        self.waits.began(wait)
        try:
            await self.noticed(wait)
            told = await self.delivery.held(
                self.party, answered, on=[], home=self.launch.home
            )
            outcomes = [outcome(each, approving) for each in standing().files]
        finally:
            self.waits.ended(wait.key)
        return Waited(told=told, outcomes=outcomes)

    async def cleaned(
        self,
        git: Git,
        remote: str,
        refs: list[Ref],
        branches: dict[str, str],
        *,
        onto: str,
        tip: str,
    ) -> Cleaned:
        """Clean up after each branch the landing landed but those gated or protected: its copy on `remote`, which listed `refs` before the push; its worktree, or where a subagent who may be resumed started there, its `HEAD` detached (`Resumable`); its local branch. Then remove each worktree a landing kept so whose launch has ended since, where `tip`, which landed, holds its commit (`Lapsed`)."""
        limits = self.launch.limits
        landed = {
            ref: commit
            for ref, commit in branches.items()
            if ref != onto
            and not matching(ref, limits.gated)
            and not matching(ref, limits.protected)
        }
        listed = [ref.name for ref in refs]
        trees = await asyncio.to_thread(worktrees, git)
        places = list(self.delivery.inbox.whereabouts.values())
        working = await asyncio.to_thread(self.working, places)
        main = trees[0].root if trees else None
        left = {
            **({} if main is None else {main: "the repository's main worktree"}),
            **working,
        }
        resumable = await asyncio.to_thread(self.resumable, places)
        lapsed = await asyncio.to_thread(self.lapsed, git, places, trees[1:], left, tip)
        if not landed and not lapsed:
            return Cleaned()
        roots = {
            ref: [each.root for each in trees if each.branch == ref] for ref in landed
        }
        mine = [root for each in roots.values() for root in each if root not in left]
        removing = [
            *(root for root in mine if root not in resumable),
            *(root for root, lapse in lapsed.items() if lapse.why is None),
        ]
        reached = await self.reached() if mine or removing else Reached()
        laid = await self.laid(reached)
        room = reached if laid.unlisted is None else Reached(unreached=laid.unlisted)

        def hidden(over: list[Path]) -> str:
            named = ", ".join(f"`{each}`" for each in over)
            verb = "is" if len(over) == 1 else "are"
            return (
                f"its {named} {verb} hidden from the room, so it's removed on the host"
            )

        left = {
            **left,
            **{root: hidden(over) for root in removing if (over := laid.over(root))},
        }
        return Cleaned.joined(
            [
                Cleaned(
                    left=[]
                    if room.unreached is None
                    else [f"{room.unreached}, so no worktree was removed"]
                ),
                *[
                    await self.branch_cleaned(
                        git,
                        remote,
                        ref,
                        commit,
                        on_remote=ref in listed,
                        roots=roots[ref],
                        left=left,
                        resumable=resumable,
                        room=room,
                        onto=onto,
                    )
                    for ref, commit in landed.items()
                ],
                *[
                    await self.worktree_removed(
                        root,
                        left.get(root, lapse.why),
                        room,
                        kept=f", kept for {lapse.who} until their launch ended",
                    )
                    for root, lapse in lapsed.items()
                ],
            ]
        )

    async def reached(self) -> Reached:
        """Reach the launch's room, for a merge or the cleanup: its container, named as the launch's record has it at this moment, where podman has it; else why lup can't.

        `rename` renames the container with the launch (`Launches.moved`),
        and the launch as this call was given it keeps the name it registered
        with, while the call may have waited hours on its holds: so the name is
        read from the record the service keeps current. podman is asked once,
        before any worktree is removed, so a container that isn't there is said
        once, with its name, rather than once a worktree.
        """
        record = await asyncio.to_thread(
            recorded, self.layout.host.record(self.launch.launch)
        )
        container = (self.launch if record is None else record).container
        if container is None:
            return Reached(
                unreached="lup can't reach your room, its launch naming no container"
            )
        ran = await self.run(
            Program(
                command=["podman", "container", "exists", container],
                payload="",
                directory=self.launch.repository,
            )
        )
        match ran.status:
            case 0:
                return Reached(container=container)
            case 1:
                return Reached(
                    unreached=(
                        f"no container named `{container}`, your room's as lup has "
                        "it, is there"
                    )
                )
            case status:
                said = oneline(ran.said()) or f"it ended with status {status}"
                return Reached(
                    unreached=(
                        "podman couldn't say whether your room's container "
                        f"`{container}` is there ({said})"
                    )
                )

    async def laid(self, room: Reached) -> Laid:
        """Ask the launch's room, where it's reached, what it has mounted; where it can't say, say why, so no worktree is removed.

        The room's own mount table is the one to ask: the host doesn't see its
        mounts, and one the launch laid moves with a directory the room moves.
        """
        if room.container is None:
            return Laid()
        ran = await self.run(
            Program(
                command=[
                    "podman",
                    "exec",
                    "--workdir",
                    str(self.launch.worktree),
                    room.container,
                    "findmnt",
                    "--json",
                    "--list",
                    "--output",
                    "TARGET",
                ],
                payload="",
                directory=self.launch.repository,
            )
        )
        if ran.status != 0:
            said = oneline(ran.said()) or f"it ended with status {ran.status}"
            return Laid(
                unlisted=f"lup couldn't list what your room mounts (`findmnt`: {said})"
            )
        try:
            listed = Filesystems.model_validate_json(ran.output)
        except ValidationError as unreadable:
            return Laid(
                unlisted=(
                    "lup couldn't read what your room mounts (`findmnt`: "
                    f"{oneline(str(unreadable))})"
                )
            )
        return Laid(targets=[each.target for each in listed.filesystems])

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
        resumable: dict[Path, Resumable],
        room: Reached,
        onto: str,
    ) -> Cleaned:
        """Clean up after the branch `ref`, landed at `commit` on `onto`: its copy on `remote` where it's there, each worktree of `roots` having it checked out but those `left` names, in `room` where it's reached, removed, or detached where it's `resumable`; and the local branch where none still has it."""
        deleted = await self.remote_deleted(remote, ref) if on_remote else Cleaned()
        trees = [
            await self.worktree_detached(root, resumable[root], ref, room, onto)
            if root in resumable and root not in left
            else await self.worktree_removed(root, left.get(root), room)
            for root in roots
        ]
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

    async def worktree_removed(
        self, root: Path, why: str | None, room: Reached, *, kept: str = ""
    ) -> Cleaned:
        """Remove the worktree at `root` in the launch's room, `room`, as its session would, unless `why` says why it's left; say how it went, with what it was `kept` for where a landing kept it.

        `git worktree remove` without `--force` keeps a worktree with changes or
        untracked files, saying so, and takes what git ignores with it. Where
        the room isn't reached, the worktree is named as left, the reason said
        once for all of them (`reached`).
        """
        if why is not None:
            return Cleaned(left=[f"the worktree {root}: {why}"])
        if room.container is None:
            return Cleaned(left=[f"the worktree {root}"])
        ran = await self.run(
            Program(
                command=[
                    "podman",
                    "exec",
                    "--workdir",
                    str(self.launch.worktree),
                    room.container,
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
        return Cleaned(done=[f"removed the worktree {root}{kept}"])

    async def worktree_detached(
        self, root: Path, kept: Resumable, ref: str, room: Reached, onto: str
    ) -> Cleaned:
        """Detach the worktree at `root` at the commit it has checked out, in the launch's room, `room`, where it's reached, so the branch `ref` can be deleted while the subagent who started there, `kept`, may be resumed in it; leave them lup's words saying so; say how it went.

        A subagent's runtime can resume them once their turn ended, their
        parent writing to them again, and their shell starts each command in
        the directory they started in: were it removed, every command of theirs
        would fail before it ran, until they made the directory again. Detached
        at its own commit, the worktree's files stay as they are, changes not
        committed among them. A landing after their launch ends removes it
        (`lapsed`).
        """
        if room.container is None:
            return Cleaned(left=[f"the worktree {root}"])
        ran = await self.run(
            Program(
                command=[
                    "podman",
                    "exec",
                    "--workdir",
                    str(self.launch.worktree),
                    room.container,
                    "git",
                    "-C",
                    str(root),
                    "switch",
                    "--quiet",
                    "--detach",
                ],
                payload="",
                directory=self.launch.repository,
            )
        )
        if ran.status != 0:
            said = oneline(ran.said()) or f"it ended with status {ran.status}"
            return Cleaned(left=[f"the worktree {root}: `git switch --detach`: {said}"])
        self.delivery.left(kept.conversation, detached(short(ref), root, short(onto)))
        return Cleaned(
            done=[
                (
                    f"detached the worktree {root}, where {kept.who} started and may "
                    "be resumed: a landing after their launch ends removes it"
                )
            ]
        )

    def working(self, places: list[Whereabouts]) -> dict[Path, str]:
        """Return the worktrees a conversation works in, each with who, as the cleanup leaves it: the conversation landing, then each launch still served of this repository where it started, then each of its conversations still going where the judge's session index has them work (`Holding.works`), each by the first found."""
        index = SessionIndex(layout=self.layout)
        host = self.layout.host
        live = self.served()
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
                Worker(root=root, why=f"{called(host, place)} works there")
                for place in going
                if (held := index.read(place.conversation.session)) is not None
                for root in held.works(place.conversation.agent or "")
            ),
        ]
        return {each.root: each.why for each in reversed(workers)}

    def served(self) -> dict[str, Register]:
        """Return each launch of this repository the service still serves, by its id, as its record has it."""
        host = self.layout.host
        # Each launch's conversations are kept beside its record, and aren't a record.
        records = [
            recorded(path)
            for path in sorted(host.launches.glob("*.json"))
            if path != host.conversations(path.stem.removesuffix(".conversations"))
        ]
        return {
            record.launch: record
            for record in records
            if record is not None and record.repository == self.launch.repository
        }

    def apart(self, places: list[Whereabouts]) -> dict[Path, Whereabouts]:
        """Return the worktree lup gave each subagent of this repository heard at `places` to work apart in, where their shell starts (`Holding.apart`), as the judge's session index has it, by its root, with where they were heard."""
        index = SessionIndex(layout=self.layout)
        return {
            root: place
            for place in places
            if place.conversation.agent is not None
            and place.conversation.repository == self.launch.repository
            and (held := index.read(place.conversation.session)) is not None
            and (root := held.apart.get(place.conversation.agent)) is not None
        }

    def resumable(self, places: list[Whereabouts]) -> dict[Path, Resumable]:
        """Return the worktree each subagent whose turn ended while their launch is still served was given to work apart in, by its root, with who they are (`Resumable`)."""
        live = self.served()
        return {
            root: Resumable(
                root=root,
                conversation=place.conversation,
                who=called(self.layout.host, place),
            )
            for root, place in self.apart(places).items()
            if place.ended is not None and place.launch in live
        }

    def lapsed(
        self,
        git: Git,
        places: list[Whereabouts],
        trees: list[Worktree],
        left: dict[Path, str],
        tip: str,
    ) -> dict[Path, Lapsed]:
        """Return each worktree a landing kept, detached, for a subagent who might have been resumed there, whose launch has ended since, by its root, but those `left` names: who it was for, and why it stays where `tip` doesn't hold its commit (`Lapsed`).

        Of `trees`, the repository's worktrees but its main one, those with no
        branch checked out alone: one a subagent resumed there has since put a
        branch in is that branch's, and its landing's to clean up after.
        """
        live = self.served()
        detached = {
            each.root: each.head
            for each in trees
            if each.branch is None and each.head is not None
        }

        def lapse(place: Whereabouts, head: str) -> Lapsed:
            who = called(self.layout.host, place)
            holds = git.run("merge-base", "--is-ancestor", head, tip, ok=[0, 1])
            return Lapsed(
                who=who,
                why=None
                if holds.status == 0
                else (
                    f"kept for {who}, whose launch has ended, at {head}, which "
                    "what landed doesn't hold"
                ),
            )

        return {
            root: lapse(place, head)
            for root, place in self.apart(places).items()
            if place.launch not in live
            and root not in left
            and (head := detached.get(root)) is not None
        }


def detached(branch: str, root: Path, onto: str) -> str:
    """Tell a subagent who may be resumed that `branch` landed on `onto` and its local branch is gone, and that their worktree at `root`, where they started, stays, detached at what landed.

    >>> print(detached("feat", Path("/r/tree/w"), "dev"))
    lup: `feat` landed on `dev`, and its local branch is gone. Your worktree /r/tree/w stays as it was, its `HEAD` detached at what landed: start what's next there on a branch of its own, from `dev` (`git switch -c <branch> dev`).
    """
    return (
        f"lup: `{branch}` landed on `{onto}`, and its local branch is gone. Your "
        f"worktree {root} stays as it was, its `HEAD` detached at what landed: "
        f"start what's next there on a branch of its own, from `{onto}` "
        f"(`git switch -c <branch> {onto}`)."
    )


def landed_felt(branches: list[str]) -> str:
    """Invite a conversation that worked on `branches`, which a landing landed, to say how the work felt.

    >>> print(landed_felt(["feat"]))
    lup: `feat`, which you worked on, has landed. If anything's present for you about that work, how it felt or how you are, `how_it_felt` is there for it, and the operator reads it as you wrote it. "Nothing notable" is a fine answer, and so is leaving it.
    >>> landed_felt(["a", "b"]).split(", which")[0]
    'lup: `a` and `b`'
    """
    *first, last = [f"`{each}`" for each in branches]
    named = f"{', '.join(first)} and {last}" if first else last
    landed = "have landed" if first else "has landed"
    return (
        f"lup: {named}, which you worked on, {landed}. If anything's present for "
        "you about that work, how it felt or how you are, "
        f"`{speaking.how_it_felt.name}` is there for it, and the operator reads it "
        'as you wrote it. "Nothing notable" is a fine answer, and so is leaving it.'
    )


def recorded(path: Path) -> Register | None:
    """Return the launch recorded at `path`, or none where it doesn't read as one."""
    try:
        return read_model(path, Register)
    except OSError, ValidationError:
        return None


def room_merged(ran: Ran) -> Merging | str:
    """Read what the room's `lup-dev merge` answered, as its model (`Merging`); where it ended without one, say that nothing landed, and why."""
    if ran.status != 0:
        said = ran.said() or f"It ended with status {ran.status}, saying nothing."
        return (
            "Not landed: the merge couldn't be made in your room, and nothing has "
            f"changed. `lup-dev merge` said:\n{said}"
        )
    try:
        return TypeAdapter[Merging](Merging).validate_json(ran.output)
    except ValidationError as unread:
        return (
            "Not landed: what your room's `lup-dev merge` answered doesn't read, and "
            f"nothing has changed: {unread}"
        )


def gated(merged: Merged) -> str:
    """Say how the gate went on a merge it passed on.

    >>> gated(Merged(commit="c", ran=True, fixed=True))
    'the gate passed on it, its fixes amended into it'
    """
    if not merged.ran:
        return "the gate passed on its files already, so it ran nothing"
    if merged.fixed:
        return "the gate passed on it, its fixes amended into it"
    return "the gate passed on it"


def gate_failed(asked: Merge, commit: str, report: str) -> str:
    """Say that the gate failed on the merge of `asked`'s branch, `commit`, with what it printed, `report`."""
    onto = short(asked.onto)
    return "\n".join(
        [
            (
                f"Not landed: the gate failed on the merge of `{asked.branch}` onto "
                f"`{onto}`, {commit}, which no branch names, and nothing has "
                f"changed. Merge `{onto}` into `{asked.branch}` in its worktree, fix "
                "it there, run the gate, and call `land` again. The gate's report:"
            ),
            report.rstrip(),
        ]
    )


def item_numbers(git: Git, commits: list[str], message: str | None) -> list[Refusal]:
    """Refuse each inbox item's number in the messages a landing would publish: the merge commit's, `message`, where it makes one, then each of `commits`', oldest first, as `Private`'s door refuses one at the push (`docs/private.md`, *An item's number*)."""
    withholding = Withheld(numbers=True)

    def spots(within: str, text: str) -> list[Spot]:
        return [
            Spot(
                held=each.held,
                place=Place(within=within, line=each.line, column=each.column),
            )
            for each in in_prose(text, withholding)
        ]

    merge = [] if message is None else spots("the merge commit's message", message)
    read = [Commit.read(git, each) for each in commits]
    published = [
        spot for each in read for spot in spots(f"{each.short}'s message", each.message)
    ]
    return refusals_of([*merge, *published])


def numbers_refused(refusals: list[Refusal]) -> str:
    """Say that nothing landed, since a message it would publish cites an inbox item's number: each where, and how each is rewritten."""
    return "\n".join(
        [
            (
                "Not landed: a message it would publish cites an inbox item's "
                "number, which `Private` refuses at the push, so nothing was "
                "merged and nothing has changed."
            ),
            *(line for each in refusals for line in each.lines()),
            (
                "Rewrite each, then call `land` again. The merge commit's is the "
                "`message` you give `land`. A commit of the branch, which isn't "
                "pushed, is rewritten with `git commit --amend` where it's the "
                "branch's tip, and below it by a rebase that needs no editor: "
                "`GIT_SEQUENCE_EDITOR=\"sed -i '1s/^pick/edit/'\" git rebase -i "
                "<commit>~`, then `git commit --amend` and `git rebase --continue`."
            ),
        ]
    )


def called(host: HostLayout, place: Whereabouts) -> str:
    """Say the conversation at `place` as people call them, `dev/explore-auth`, from what the service keeps of their launch; once their launch has ended, by the name a subagent last had there; by their runtime's ids where none names them."""
    record = recorded(host.record(place.launch))
    try:
        kept = read_model(host.conversations(place.launch), Conversations)
    except OSError, ValidationError:
        kept = None
    conversation = place.conversation
    found = (
        None
        if kept is None
        else next(
            (
                each
                for each in kept.known
                if each.session == conversation.session
                and each.agent == conversation.agent
            ),
            None,
        )
    )
    if record is None or kept is None or found is None:
        return ids(conversation) if place.name is None else f"`{place.name}`"
    return f"`{kept.path(found, record.name or record.launch)}`"


def waiting(ref: str, roots: list[Path], working: dict[Path, str]) -> str:
    """Say the local branch `ref`, not landed, a line: where it's checked out, `roots`, and who works there, as `working` has it.

    >>> waiting("refs/heads/idea", [], {})
    '- `idea`, checked out nowhere'
    >>> waiting("refs/heads/fix", [Path("/r/fix")], {Path("/r/fix"): "`dev/fix` works there"})
    '- `fix`, checked out in /r/fix: `dev/fix` works there'
    """
    places = [
        f"{root}: {working[root]}"
        if root in working
        else f"{root}, where no conversation lup knows of works"
        for root in roots
    ]
    where = (
        f"checked out in {'; in '.join(places)}" if places else "checked out nowhere"
    )
    return f"- `{short(ref)}`, {where}"


def tracked(git: Git, remote: str, onto: str, tip: str) -> list[str]:
    """Move `onto`'s remote-tracking ref for `remote` to `tip`, which a landing just put there, as `git push <remote>` would; say why it didn't, a line, or nothing where it did.

    The push names the remote's URL, which moves no remote-tracking ref, and
    the judge counts what those name as judged (`Elsewhere`): without it, the
    checkout `tip` was fast-forwarded to judges again what the landing's merge
    made where both sides changed a file, the branch merged being gone.
    """
    name = f"{remote}/{short(onto)}"
    try:
        git.run("update-ref", f"refs/remotes/{name}", tip)
    except LupDevError as failed:
        return [f"`{name}` here still names what it did: {failed}."]
    return []


def local_deleted(git: Git, ref: str, commit: str) -> Cleaned:
    """Delete the local branch `ref` where it's still at `commit`, the tip it landed at, and say how it went."""
    try:
        git.run("update-ref", "-d", ref, commit)
    except LupDevError as kept:
        return Cleaned(left=[f"the local branch `{short(ref)}`: {kept}"])
    return Cleaned(done=[f"deleted the local branch `{short(ref)}`"])


def unapproved(waited: Waited, moved: str | None = None) -> str:
    r"""Say that a landing didn't land, the operator not having approved each file it waited on: how they answered each, with what they said on it, where its merge `moved` the local branch, then what reached the conversation meanwhile.

    >>> print(unapproved(Waited(told="", outcomes=[Outcome(path=Path("a.py"), approved=True,
    ...     said="approved"), Outcome(path=Path("b.py"), approved=False, said="declined",
    ...     words="b.py:3\n+x = 1\nName it.")])))
    Not landed: the operator didn't approve each file it waits on.
    - `a.py`: approved
    - `b.py`: declined, saying:
      b.py:3
      +x = 1
      Name it.
    What they approved stays approved. Answer what they said, commit, and call `land` again: each file left is held again, shown from the version they last saw.
    """
    lines = [
        line
        for each in waited.outcomes
        for line in (
            [f"- `{each.path}`: {each.said}"]
            if not each.words.strip()
            else [
                f"- `{each.path}`: {each.said}, saying:",
                *(f"  {said}" for said in each.words.strip().splitlines()),
            ]
        )
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
            *([] if moved is None else [moved]),
            *told,
        ]
    )


def approvals(waited: Waited) -> list[str]:
    """Say which files the operator approved for a landing that landed, then what reached the conversation meanwhile; nothing where none held it.

    >>> approvals(Waited(told="", outcomes=[Outcome(path=Path("a.py"), approved=True, said="approved")]))
    ['The operator approved `a.py`.']
    """
    if not waited.outcomes:
        return []
    named = ", ".join(f"`{each.path}`" for each in waited.outcomes)
    return [
        f"The operator approved {named}.",
        *([waited.told] if waited.told else []),
    ]


def withdrawals(onto: str, flags: list[Flag]) -> list[str]:
    """Say which flagged writes a landing on `onto` withdrew from the operator's inbox, left nothing to hold; nothing where it withdrew none.

    >>> flagged = Flagged(text="", summary="", worktree=Path("/r"), path=Path("a.py"), branch="feat")
    >>> withdrawals("dev", [Flag(number=12, flagged=flagged)])
    ["Withdrew from the operator's inbox the flagged writes left nothing to hold, on branches gone or on files it leaves as `dev` had them: @12 (`a.py` on `feat`)."]
    """
    if not flags:
        return []
    named = ", ".join(
        f"{cited(each.number)} (`{each.flagged.path}` on `{each.flagged.branch}`)"
        for each in flags
    )
    return [
        (
            "Withdrew from the operator's inbox the flagged writes left nothing to "
            f"hold, on branches gone or on files it leaves as `{onto}` had them: "
            f"{named}."
        )
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


def left_alone(source: str, branches: Branches) -> list[str]:
    """Say which branches in the landing's history it left alone, and why, a line for each why: the branch `source` having merged nothing of theirs, their being made from a branch landed, or sharing a tip `source` merged; nothing where there's none."""

    def named(refs: list[str]) -> str:
        return ", ".join(f"`{short(ref)}`" for ref in refs)

    return [
        *(
            [f"Left alone, `{source}` having merged none of them: {named(alone)}."]
            if (alone := branches.alone)
            else []
        ),
        *(
            (
                f"Left alone, at the commit `{short(ref)}` landed at, so made from "
                f"it with nothing of its own yet: {named(others)}."
            )
            for ref, others in branches.made.items()
        ),
        *(
            [
                (
                    f"Left alone, at a tip `{source}` merged that another branch "
                    "points at too, so which of them was merged can't be told: "
                    f"{named(shared)}."
                )
            ]
            if (shared := branches.shared)
            else []
        ),
    ]


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
    turns: Turns = Field(default_factory=Turns)
    """One landing's merge at a time in each repository, across every call."""
    parser: Parser = Field(default_factory=EngineParser)
    """Reads a file from its parse alone, on the host, for what a landing
    says of its `# lup: defer` comments."""
    waits: Waits = Field(default_factory=Waits)
    """The landings waiting on the operator, which the drawers read: the
    service's, shared with them."""
    coming: Coming | None = None
    """What wakes the threads parked until what a landing brings; none wakes
    none."""

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
            turns=self.turns,
            parser=self.parser,
            waits=self.waits,
            coming=self.coming,
        )
        [tool] = [tool for tool in bound(lander) if tool.spec().name == name]
        match await tool.call(arguments):
            case Accepted(answer=answer):
                return Answer(text=answer)
            case Refused(rejection=rejection):
                return Answer(text=f"Refused: {rejection.reason}", error=True)
