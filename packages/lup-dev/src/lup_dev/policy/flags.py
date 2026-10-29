"""Flags: a write that landed flagged, put in the operator's inbox as an item that holds no one.

What the declaration flags (by default a new file, a file written whole and a
change to the public API) lands as an allow would, and is put before the
operator too (`flagged`; `docs/judging-writes.md`, *Asking the operator*): an
item of their inbox showing its file as a held change shows its files, its diff
and the judge's reading of it. They read it, or comment on it, the comment
reaching the agent with their review ("yes, but"); it never waits for them.

A later write to the same file by the same conversation joins the item while
the operator hasn't read it (`Inbox.gathering`), the file judged whole since
the item was made (`gathered`), so ten edits to one new module read as one
item, showing the file as it stands. One that flags nothing of its own joins it
too, refreshing it, and makes none where the operator has read it; it asks the
inbox only for a file the session's record says an item may gather
(`Session.flagging`), so a write to any other file costs nothing. Where the
operator holds each flagged write of a conversation, their writes are held
instead (`Judge.holding`), and none is flagged.

Each flag keeps the branch its worktree has checked out (`Flagged.branch`), and
says so: the landing of that branch waits on it until the operator approves it.
A landing withdraws it once it's left nothing to hold, its branch gone or its
file left unchanged as the flag keeps it (`lup_dev.policy.landing`).

A write lands whatever fails here: what couldn't be put before the operator is
said to the agent, to pass on.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import override

from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.errors import LupDevError
from lup_dev.git import Git
from lup_dev.host.client import Detached, HostClient
from lup_dev.inbox.protocol import AskFlag, Gathering, ShowGathering, Shown
from lup_dev.inbox.store import ChangedFile, Conversation, Flagged, Text
from lup_dev.layout import HostLayout
from lup_dev.policy.holds import unified
from lup_dev.policy.judge import Change, Judge, Judgement


class Landed(Model):
    """A write that landed flagged, or to a file an item of its conversation's may gather, as the judge judged it, and whose it is."""

    change: Change
    judgement: Judgement
    session: str
    agent: str | None = None
    """The runtime's id for the subagent whose call made it; none for the
    session's own conversation, and for what a move of `HEAD` brought."""
    call: str | None = None
    """The runtime's id for the call that made it, or whose finish found it."""
    commit: str | None = None
    """The commit a move of `HEAD` reached, where the write came with it; none
    where a conversation's call made it."""


class Flagging(ABC):
    """Where a write that landed flagged is put before the operator: their inbox, which gathers a conversation's flagged writes to one file into one item."""

    @abstractmethod
    def gathering(self, asked: ShowGathering) -> Gathering:
        """Return the item a flagged write would join, with its file whole as it's kept; none where it would make one."""

    @abstractmethod
    def flagged(self, asking: AskFlag) -> None:
        """Put a flagged write before the operator: joining the item it names where that item still gathers, else as an item of its own."""


class InboxFlagging(Model, Flagging, arbitrary_types_allowed=True):
    """Flagged writes put in the operator's inbox through the host service."""

    layout: HostLayout
    clock: Clock

    @override
    def gathering(self, asked: ShowGathering) -> Gathering:
        host = HostClient(layout=self.layout, clock=self.clock, starter=Detached())
        return host.ask(asked, Gathering)

    @override
    def flagged(self, asking: AskFlag) -> None:
        host = HostClient(layout=self.layout, clock=self.clock, starter=Detached())
        host.ask(asking, Shown)


def gathered(judge: Judge, landed: Landed, gathering: Gathering) -> Landed | None:
    """Return `landed` judged whole since the item it joins was made: from what the file held before that item's first write, as `gathering` keeps it, to what this write makes it; none where it joins none, or the file kept isn't text.

    A file one of the item's writes wrote whole stays written whole.
    """
    match gathering.file:
        case ChangedFile(before=Text(text=text), reading=reading):
            earlier: str | None = text
        case ChangedFile(before=None, reading=reading):
            earlier = None
        case _:
            return None
    written = reading is not None and any(
        each.name == "whole-file" for each in reading.asks
    )
    change = landed.change.model_copy(
        update={"before": earlier, "whole": landed.change.whole or written}
    )
    [judgement] = judge.judge([change], inform=False)
    return landed.model_copy(update={"change": change, "judgement": judgement})


def asking(
    landed: Landed, root: Path, sender: Conversation, branch: str | None = None
) -> AskFlag:
    """Return the request putting `landed` before the operator, its file whole as its change has it, from `sender`, in the worktree at `root`, which has `branch` checked out.

    Its summary is what that change asks, a line each; where a later write took
    out all it flagged, it says so. Its text says the branch's landing waits on
    it, where there's a branch.
    """
    change = landed.change
    path = change.path
    judgement = landed.judgement
    brought = "" if landed.commit is None else f" with commit {landed.commit}"
    asks = [ask.reason for ask in [*judgement.asks, *judgement.flags]]
    summary = "\n".join(asks) or f"{path}'s whole change flags nothing any more"
    holding = (
        ""
        if branch is None
        else f" It holds at landing: `{branch}` lands once they approve it."
    )
    return AskFlag(
        flagged=Flagged(
            text=f"{path} landed{brought}, flagged for the operator's review.{holding}",
            summary=summary,
            worktree=root,
            path=path,
            commit=landed.commit,
            branch=branch,
        ),
        sender=sender,
        diff=unified(path, change.before, change.after),
        file=ChangedFile.of(
            path,
            None if change.before is None else change.before.encode(),
            None if change.after is None else change.after.encode(),
            judgement.reading(),
        ),
        call=landed.call,
    )


class Put(Model):
    """What putting landed writes before the operator came to."""

    unsaid: list[str] = []
    """What couldn't be put there, a line each, for the agent to pass on: the
    write landed all the same."""
    read: list[Path] = []
    """The files of writes that would only have refreshed an item, which the
    operator has read since, so it gathers them no more: a later write to one
    asks the inbox nothing."""


def flagged(
    flagging: Flagging,
    judge: Judge,
    runtime: str,
    repository: Path,
    landed: list[Landed],
) -> Put:
    """Put each write that landed before the operator, from its conversation of `runtime` in `repository`, judged whole since the item it joins was made; `judge` judged them, in their worktree.

    A write its judgement flags joins the item gathering its conversation's
    writes to its file, or makes one. One it flags nothing in only refreshes
    that item, so it shows the file as it stands: where none gathers them, the
    operator having read it, it makes none, and says so (`Put.read`). Each
    keeps the branch the worktree has checked out (`Flagged.branch`): where git
    can't say it, the flag holds no landing.
    """
    root = judge.root
    try:
        branch = Git(cwd=root).branch() if landed else None
    except LupDevError:
        branch = None

    def one(each: Landed) -> Put:
        path = each.change.path
        refreshing = not each.judgement.flags
        sender = Conversation(
            repository=repository,
            runtime=runtime,
            session=each.session,
            agent=each.agent,
        )
        try:
            found = flagging.gathering(
                ShowGathering(sender=sender, worktree=root, path=path)
            )
            whole = gathered(judge, each, found)
            if refreshing and whole is None:
                return Put(read=[path] if found.number is None else [])
            request = asking(whole or each, root, sender, branch)
            joining = None if whole is None else found.number
            flagging.flagged(
                request.model_copy(
                    update={"joining": joining, "refreshing": refreshing}
                )
            )
        except LupDevError as failure:
            unsaid = (
                f"lup couldn't bring the operator's item on {root / path} to "
                f"your write ({failure}). It landed all the same."
                if refreshing
                else f"lup couldn't put the flagged write to {root / path} before "
                f"the operator ({failure}). It landed all the same: tell the "
                "operator."
            )
            return Put(unsaid=[unsaid])
        return Put()

    puts = [one(each) for each in landed]
    return Put(
        unsaid=[line for put in puts for line in put.unsaid],
        read=[path for put in puts for path in put.read],
    )
