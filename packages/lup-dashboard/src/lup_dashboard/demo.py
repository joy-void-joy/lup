"""The dashboard over stand-in data: the real page, every view populated, with no host service or session behind it.

`lup-dashboard demo` serves it, for looking at a view while it's built (a session
in a room screenshots it headless) and for the operator to try one before it
lands. Its data are the host's own models, so it shows what the page would show.
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

from lup.types import Model
from lup_dashboard.host import Host
from lup_dev.clock import Clock, SystemClock
from lup_dev.host.protocol import (
    Activity,
    Limits,
    Listed,
    ListLaunches,
    Refused,
    Register,
    Talker,
)
from lup_dev.inbox.protocol import Items, ListInbox
from lup_dev.inbox.store import (
    Conversation,
    Decision,
    Item,
    Message,
    Operator,
    Question,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from lup_dashboard.api import Asked, Replied


class Demo(Model, Host, arbitrary_types_allowed=True):
    """A host serving stand-in launches, conversations and items, as of the clock's time; what it can't answer it refuses, saying it's a demo."""

    clock: Clock = SystemClock()
    # lup: ignore("runtime-mention", why="stand-in data: the runtimes the demo's launches show, not a feature built for one")
    runtimes: list[str] = ["claude", "codex"]
    """The runtimes the demo's launches run, by name: the first for most, the second for one."""

    @override
    async def ask(self, request: Asked) -> Replied:
        match request:
            case ListLaunches():
                return self.listed()
            case ListInbox():
                return self.items()
            case _:
                return Refused(error=f"the demo doesn't answer `{request.kind}`")

    @override
    async def watch(self, request: Asked) -> AsyncGenerator[Replied]:
        yield await self.ask(request)
        await asyncio.Event().wait()

    def ago(self, minutes: float) -> datetime:
        """Return the moment `minutes` before the clock's."""
        return self.clock.now() - timedelta(minutes=minutes)

    def listed(self) -> Listed:
        """Return four launches over three repositories: one with subagents working, asking and ended; one idle; one on the second runtime; one whose session hasn't started."""
        first, second = self.runtimes
        lup = launch("a1f0", "lup-impl", first, Path("/home/op/lup.git/tree/dev"))
        voice = launch(
            "b2e1",
            "guidance-voice",
            first,
            Path("/home/op/lup.git/tree/guidance-voice"),
        )
        adlib = launch("c3d2", "main", second, Path("/home/op/adlib.git/tree/main"))
        waiting = launch(
            "d4c3", "nori-search", first, Path("/home/op/nori.git/tree/main")
        )
        calling = Activity(state="calling", since=self.ago(0.4), tool="Bash")
        ended = [
            talker(
                name,
                "s1",
                Activity(state="ended", since=self.ago(minutes)),
                agent=f"a0{at + 4}",
                kind="Explore",
                parent="lup-impl",
                depth=1,
            )
            for at, (name, minutes) in enumerate(
                [("survey-legacy", 52), ("probe-meta", 40), ("nest-probe", 33)]
            )
        ]
        talkers = {
            "a1f0": [
                talker("lup-impl", "s1", calling),
                talker(
                    "explore-auth",
                    "s1",
                    Activity(state="calling", since=self.ago(1.5), tool="Grep"),
                    agent="a01",
                    kind="Explore",
                    parent="lup-impl",
                    depth=1,
                ),
                talker(
                    "parser",
                    "s1",
                    Activity(
                        state="calling",
                        since=self.ago(4),
                        tool="mcp__lup__ask",
                        lups=True,
                    ),
                    agent="a02",
                    kind="general-purpose",
                    parent="lup-impl",
                    depth=1,
                ),
                talker(
                    "grep-tokens",
                    "s1",
                    Activity(state="idle", since=self.ago(0.2)),
                    agent="a03",
                    kind="general-purpose",
                    parent="lup-impl/parser",
                    depth=2,
                ),
                *ended,
            ],
            "b2e1": [
                talker(
                    "guidance-voice", "s2", Activity(state="idle", since=self.ago(12))
                )
            ],
            "c3d2": [
                talker(
                    "main",
                    "s3",
                    Activity(state="calling", since=self.ago(2), tool="exec_command"),
                ),
                talker(
                    "render_frames",
                    "s3",
                    Activity(state="calling", since=self.ago(0.7), tool="exec_command"),
                    agent="th-7",
                    kind="default",
                    parent="main",
                    depth=1,
                ),
            ],
        }
        return Listed(
            launches=[lup, voice, adlib, waiting],
            sessions={"s1": "lup-impl", "s2": "guidance-voice", "s3": "main"},
            talkers=talkers,
        )

    def items(self) -> Items:
        """Return what waits for the operator: a question of numbered decisions from a subagent, and a note."""
        first, _ = self.runtimes
        parser = Conversation(
            repository=Path("/home/op/lup.git"),
            runtime=first,
            session="s1",
            agent="a02",
        )
        voice = Conversation(
            repository=Path("/home/op/lup.git"), runtime=first, session="s2"
        )
        question = Question(
            text="Which parser for the transcript reader?",
            decisions=[
                Decision(
                    text="Read each record with pydantic, one model per line kind",
                    lean="yes",
                ),
                Decision(
                    text="Fold every tool call to one line",
                    lean="yes, its name and status",
                ),
            ],
        )
        note = Message(kind="note", text="I assumed transcripts are UTF-8 throughout.")
        return Items(
            items=[
                Item(
                    number=51,
                    reason=question,
                    sender=parser,
                    recipient=Operator(),
                    worktree=Path("/home/op/lup.git/tree/dev"),
                    made=self.ago(4),
                ),
                Item(
                    number=52,
                    reason=note,
                    sender=voice,
                    recipient=Operator(),
                    worktree=Path("/home/op/lup.git/tree/guidance-voice"),
                    made=self.ago(12),
                ),
            ]
        )


def launch(id_: str, name: str, runtime: str, worktree: Path) -> Register:
    """Return a stand-in launch of `runtime` in `worktree`, named `name`."""
    repository = worktree.parent.parent
    return Register(
        launch=id_,
        runtime=runtime,
        worktree=worktree,
        repository=repository,
        judge=Path("/home/op/.local/bin/lup-dev"),
        container=f"lup-{id_}",
        limits=Limits(actions=["fetch", "push"], protected=["refs/heads/main"]),
        github=None,
        name=name,
    )


def talker(
    own: str,
    session: str,
    activity: Activity,
    *,
    agent: str | None = None,
    kind: str | None = None,
    parent: str | None = None,
    depth: int = 0,
) -> Talker:
    """Return a stand-in conversation, `depth` spawns below its session's own: its own name, under `parent`'s path where it has one."""
    path = own if parent is None else f"{parent}/{own}"
    return Talker(
        path=path,
        own=own,
        session=session,
        agent=agent,
        kind=kind,
        parent=parent,
        depth=depth,
        activity=activity,
    )
