"""Flags: a write that landed flagged, put in the operator's inbox as an item that holds no one.

What the declaration flags (by default a new file, a file written whole and a
change to the public API) lands as an allow would, and is put before the
operator too (`flagged`; `docs/judging-writes.md`, *Asking the operator*): an
item of their inbox showing its file as a held change shows its files, its diff
and the judge's reading of it. They read it, or comment on it, the comment
reaching the agent with their review ("yes, but"); it never waits for them.

A later flagged write to the same file by the same conversation joins the item
while the operator hasn't read it (`Inbox.gathering`), the file judged whole
since the item was made (`gathered`), so ten edits to one new module read as
one item. Where the operator holds each flagged write of a conversation, its
writes are held instead (`Judge.holding`), and none is flagged.

A write lands whatever fails here: what couldn't be put before the operator is
said to the agent, to pass on.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, override

from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.errors import LupDevError
from lup_dev.host.client import Detached, HostClient
from lup_dev.inbox.protocol import AskFlag, Gathering, ShowGathering, Shown
from lup_dev.inbox.store import ChangedFile, Conversation, Flagged, Text
from lup_dev.layout import HostLayout
from lup_dev.policy.holds import unified
from lup_dev.policy.judge import Change, Judge, Judgement

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class Landed(Model):
    """A write that landed flagged, as the judge judged it, and whose it is."""

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


def asking(landed: Landed, root: Path, sender: Conversation) -> AskFlag:
    """Return the request putting `landed` before the operator, its file whole as its change has it, from `sender`, in the worktree at `root`."""
    change = landed.change
    path = change.path
    judgement = landed.judgement
    brought = "" if landed.commit is None else f" with commit {landed.commit}"
    summary = "\n".join(ask.reason for ask in [*judgement.asks, *judgement.flags])
    return AskFlag(
        flagged=Flagged(
            text=f"{path} landed{brought}, flagged for the operator's review.",
            summary=summary,
            worktree=root,
            path=path,
            commit=landed.commit,
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


def flagged(
    flagging: Flagging,
    judge: Judge,
    runtime: str,
    repository: Path,
    landed: list[Landed],
) -> list[str]:
    """Put each write that landed flagged before the operator, from its conversation of `runtime` in `repository`, judged whole since the item it joins was made; `judge` judged them, in their worktree.

    Return what couldn't be put there, a line each, for the agent to pass on:
    the write landed all the same.
    """
    root = judge.root

    def unsaid() -> Iterator[str]:
        for each in landed:
            path = each.change.path
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
                request = asking(whole or each, root, sender)
                joining = None if whole is None else found.number
                flagging.flagged(request.model_copy(update={"joining": joining}))
            except LupDevError as failure:
                yield (
                    f"lup couldn't put the flagged write to {root / path} before "
                    f"the operator ({failure}). It landed all the same: tell the "
                    "operator."
                )

    return list(unsaid())
