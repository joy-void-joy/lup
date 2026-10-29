"""An approval's types, read on the host once it's in the inbox, after the reading of its files' parse it was asked with.

`docs/trust.md`. Trust asks an approval with each file read
from its parse alone, which costs a parse, so the question comes at once,
before a type check that takes seconds (`Approval.typing`). The judgement with
types follows here, on the host, whoever asked: a launch's terminal, which may be
gone by then, or a push. Each approval waiting with its first reading is read
once, off the event loop: its files are kept again with their whole reading, and
the item kept again, which the watches see, so the dashboard asks for its files
anew. Where the judge fails, the files keep the reading of their parse, and the
summary's last line says why. One whose reading a stop cut short is read again
by the next service.
"""

import asyncio
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import override

from lup.types import MutableModel
from lup_dev.host.service import Companion
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import Approval, ChangedFile, InboxError, Item, cited
from lup_ledger.parties import Operator


class TypeReader(MutableModel, Companion, arbitrary_types_allowed=True):
    """Reads the types of each approval waiting with the reading of its files' parse alone, in the background, from the service's start to its stop."""

    delivery: Delivery
    read: Callable[[Approval, Path, list[ChangedFile]], list[ChangedFile]]
    """Reads an approval's files wholly, types and lup's rules included, in the
    worktree it was asked from, raising what the judge raises: trust's
    (`Trust.typed`, through `cli.py`). It runs in a thread of its own."""
    say: Callable[[str], None]
    """Where what it read, and what failed, is said: the service's log."""
    running: dict[int, asyncio.Task[None]] = {}
    """Each reading under way, by its approval's number."""
    watching: asyncio.Task[None] | None = None

    @override
    async def begin(self) -> None:
        self.watching = asyncio.create_task(self.watch())

    @override
    async def end(self) -> None:
        for task in [self.watching, *self.running.values()]:
            if task is not None:
                task.cancel()

    async def watch(self) -> None:
        """Start a reading for each approval waiting with its first reading: those there as the service starts, then each as it comes."""
        changes = self.delivery.inbox.changes
        self.started()
        if changes is None:
            return
        seen = changes.count
        while True:
            seen = await changes.after(seen)
            self.started()

    def started(self) -> None:
        """Start reading each approval waiting with its first reading that isn't being read."""
        for item in self.delivery.inbox.waiting(Operator()):
            match item:
                case Item(number=number, reason=Approval(typing=True) as approval) if (
                    number not in self.running
                ):
                    task = asyncio.create_task(
                        self.typed(number, approval, item.worktree)
                    )
                    self.running = {**self.running, number: task}
                case _:
                    pass

    async def typed(
        self, number: int, approval: Approval, worktree: Path | None
    ) -> None:
        """Read approval `number`'s files wholly and keep them, or say in its summary why they couldn't be; either way, its reading is over."""
        try:
            await self.kept(number, approval, worktree)
        except Exception as failure:
            self.over(number, str(failure))
            told = "".join(traceback.format_exception(failure))
            self.say(f"{cited(number)}: its types couldn't be read:\n{told}")
            return
        self.over(number, "")
        self.say(f"{cited(number)}: its types are read")

    async def kept(
        self, number: int, approval: Approval, worktree: Path | None
    ) -> None:
        """Read approval `number`'s files wholly, in the worktree it was asked from, and keep them beside it."""
        if worktree is None:
            message = f"{cited(number)} names no worktree to read its files in"
            raise InboxError(message)
        inbox = self.delivery.inbox
        files = await asyncio.to_thread(inbox.files, number)
        read = await asyncio.to_thread(self.read, approval, worktree, files)
        await asyncio.to_thread(inbox.filed, number, read)

    def over(self, number: int, why: str) -> None:
        """End approval `number`'s reading: the item kept as read, its summary's last line saying `why` its types couldn't be read, where they couldn't."""
        inbox = self.delivery.inbox
        item = inbox.item(number)
        match item.reason:
            case Approval(summary=summary) as approval:
                said = (
                    f"{summary}\nThe judge couldn't read the change's types, so the "
                    f"review reads each file by its parse alone: {why}"
                    if why
                    else summary
                )
                read = approval.model_copy(update={"typing": False, "summary": said})
                inbox.kept(item.model_copy(update={"reason": read}))
            case _:
                pass
        self.running = {
            each: task for each, task in self.running.items() if each != number
        }
