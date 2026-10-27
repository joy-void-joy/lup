"""A module's view, as the dashboard asks the host for one: answered by its repository's process, and watched while the page shows it.

`docs/host.md`, *The views the dashboard shows*. The page asks for a view of
one of a repository's modules (`Viewing`, naming the repository), and the host
puts it to that repository's process with no launch, as the operator's
(`RepositoryAsking`), starting the process from the copy approved for the
repository where none runs. It's the operator's alone: a room reads a view with
its module's command, in its own process, from the worktree's declaration.

Watched, a view is answered at once, then again only at its triggers, which
its answer carries (`Watching`): at the events of the agent it's of that its
door names, at an item of the inbox that agent sent or was sent changing, and
`longest` apart at most. Each answer asks the repository's process, so a view
isn't answered again at every change anywhere, as the service's own kinds are.
Its answer goes out whole, and only where it differs from the one sent last
(`Dispatcher.watching`); each one past `large` bytes or `slow` is said in the
service's output, so a view growing too long or too slow to send whole shows
there. While it's watched, the watch holds the repository's process
(`Holder.watching`), so it doesn't end between answers.
"""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, override

from pydantic import Field

from lup.types import Model
from lup_dev.clock import Clock, SystemClock
from lup_dev.host.protocol import HostError, Reply
from lup_dev.host.service import Reading
from lup_dev.host.watch import Changes, Touched
from lup_dev.host.workers import RepositoryAsking, Viewed, Viewing, Watching

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


class ModuleViews(Model, Reading[Viewing], arbitrary_types_allowed=True):
    """Answers `Viewing` for the operator, through each repository's process, and watches it at its own triggers; refuses a room."""

    asking: RepositoryAsking
    changes: Changes
    """Told where what the service holds may have changed, and which
    conversations each change touched: a watch waits on its agent's."""
    say: Callable[[str], None]
    clock: Clock = Field(default_factory=SystemClock)
    """How long each answer took; a test gives its own."""
    large: int = 100_000
    """The most bytes an answer takes before it's said: past it, sending it
    whole at each change it differs is worth looking at again."""
    slow: timedelta = timedelta(seconds=1)
    """The longest an answer takes before it's said."""

    @override
    def request(self) -> type[Viewing]:
        return Viewing

    @override
    async def answer(self, request: Viewing) -> Reply:
        return await self.viewed(request)

    @override
    async def scoped(self, request: Viewing, repository: Path) -> Reply:
        message = (
            "a view the host answers is the operator's: a room reads one with its "
            "module's command, `lup-dev <module> <view>`"
        )
        raise HostError(message)

    async def viewed(self, request: Viewing) -> Viewed:
        """Answer the view from its repository's process, saying an answer past `large` or `slow`.

        Raise `HostError` where it names a launch, as a room's would, where its
        process can't answer it, or where it answers what isn't a view's.
        """
        if request.launch is not None:
            message = "a view the host answers is the operator's, asked with no launch"
            raise HostError(message)
        started = self.clock.now()
        reply = await self.asking.asked(request.repository, request)
        took = self.clock.now() - started
        if not isinstance(reply, Viewed):
            message = f"the repository's process answered a view with {reply.kind}"
            raise HostError(message)
        size = len(reply.model_dump_json())
        if size > self.large or took > self.slow:
            self.say(
                f"{request.repository}: `{request.module}`'s view `{request.view}` "
                f"answered {size:,} bytes in {took.total_seconds():.2f} s, past "
                f"{self.large:,} bytes or {self.slow.total_seconds():g} s: each "
                "answer that differs is sent whole"
            )
        return reply

    async def watched(self, request: Viewing) -> AsyncGenerator[Reply]:
        """Yield the view's answer at once, then again at each of its triggers after the answer before, its repository's process held meanwhile.

        Raise `HostError` where nothing is approved for its repository, or
        where an answer can't be had.
        """
        async with self.asking.watching(request.repository):
            while True:
                seen = self.changes.count
                reply = await self.viewed(request)
                yield reply
                await self.triggered(request.repository, reply.watch, seen)

    async def triggered(self, repository: Path, watch: Watching, seen: int) -> None:
        """Wait for the first of a view's triggers since the count `seen`: a change touching the agent it's of, at one of the events it names or by an item; or `longest` gone by. A view of no agent and no `longest` waits for ever."""
        of = watch.of
        wanted = (
            []
            if of is None
            else [
                Touched(
                    repository=repository,
                    runtime=of.runtime,
                    session=of.session,
                    agent=of.agent,
                    by=by,
                )
                for by in ["item", *watch.on]
            ]
        )
        waits: list[asyncio.Task[int | None]] = [
            asyncio.ensure_future(self.changes.touching(wanted, seen))
        ]
        if watch.longest is not None:
            waits.append(
                asyncio.ensure_future(asyncio.sleep(watch.longest.total_seconds()))
            )
        try:
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for each in waits:
                each.cancel()
