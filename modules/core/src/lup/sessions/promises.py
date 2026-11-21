"""Sessions' promises: what the operator, and a session's agent, can count on of the sessions lup starts and holds itself, each in a room of its own.

Each is checked through the harness, the machine's parts started as the
machine's own (`machine=True`), a project open, and every program they run
stood in for as the promise scripts it: podman, git's store, uv, curl fetching
each runtime's CLI, and each session's holder, run by the machine's own Python,
so the gate checks what lup asks of each without running any (`README.md` here,
*Promises*). A session's hooks reach the machine as its room's socket carries
them, by the session's agent, each payload as Claude Code gives it.

The machine's sweep runs beside each promise, on the harness's clock, its timer
firing wherever hypothesis picks: a promise holds whenever it looks.
"""

import asyncio
import csv
import hashlib
import io
import json
import sys
import tarfile
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, get_args
lazy from collections.abc import AsyncGenerator

from pydantic import Field, JsonValue

import lup
import lup.testing
from lup import Agent, Codebase, Machine, Model, MutableModel, Operator, Part
from lup.testing import (
    Accepted,
    Answering,
    Guidance,
    ProgramRun,
    Refused,
    Responding,
    Scripted,
    Section,
    Started,
    Testing,
)


def home(kept: Path, *settings: str) -> str:
    """Return the home repository's declaration, as lup's own declares it, its rooms keeping what they share across sessions in `kept`, the sessions' module given `settings` beside it, each a field as a declaration writes it."""
    given = ", ".join([f"kept=Path({str(kept)!r})", *settings])
    return f"""
from datetime import timedelta
from pathlib import Path

from lup import Modules, Project
from lup.hosting.module import Hosting
from lup.sessions.part import Sessions

project = Project(modules=Modules.default().add(Hosting(), Sessions({given})))
"""


REPOSITORY = "harmon"
"""The project the promises open, which every session starts in."""

HOLDER = "lup.environment.sessions.holder"
"""The holder's module, which the machine's Python runs."""


class Stored(Model):
    """An object of git's store: its id, and its content as git hashes it."""

    id: str
    content: bytes

    @classmethod
    def of(cls, kind: str, content: bytes) -> Stored:
        """Return the object of `kind` holding `content`, named by its id, as git names one in a repository of SHA-1."""
        framed = b"".join([f"{kind} {len(content)}".encode(), b"\0", content])
        return cls(
            id=hashlib.sha1(framed, usedforsecurity=False).hexdigest(),
            content=content,
        )


TREE = Stored.of("tree", b"")
"""An empty tree: the commit the operator approves holds no file."""

COMMIT = Stored.of(
    "commit",
    f"tree {TREE.id}\nauthor a <a> 0 +0000\ncommitter a <a> 0 +0000\n\nm\n".encode(),
)
"""The commit of the project the operator approves."""


class Store(Model, Responding):
    """git's object store as the promises stand it in, holding the approved commit: answering `git cat-file --batch=%(objectsize)` as git does."""

    objects: list[Stored] = [COMMIT, TREE]

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer a `cat-file` run, each object asked on its own line: its size on a line, its content, then a newline."""
        if "cat-file" not in arguments or given is None:
            return None
        held = {each.id: each.content for each in self.objects}

        def told(asked: str) -> bytes:
            content = held.get(asked)
            if content is None:
                return f"{asked} missing\n".encode()
            return b"".join([f"{len(content)}\n".encode(), content, b"\n"])

        return Answering(
            output=b"".join(told(each) for each in given.decode().splitlines())
        )


PLAN: JsonValue = {"format": 1, "parts": [], "tools": [], "files": []}
"""The project's plan: no part of its own, so opening it starts no container,
and a room runs none of its parts."""

GUIDANCE = Guidance(
    sections=[Section(module="core", method="told", text="Work in your worktree.")]
)
"""What a session of the project is told at its start, as its declaration
renders it."""


class Podman(MutableModel, Responding, arbitrary_types_allowed=True):
    """podman as the promises stand it in: images there, the project's plan and guidance rendered, every start and stop succeeding, and each container asked to stop heard."""

    stops: list[str] = []
    """Each container asked to stop, by its name, in order."""
    heard: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set each time a container's asked to stop."""

    async def stopped(self, name: str) -> None:
        """Wait until the container named `name` is asked to stop."""
        while name not in self.stops:
            self.heard.clear()
            await self.heard.wait()

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer each run as podman would."""
        del given
        match arguments:
            case ["version", *_]:
                return Answering(output="6.1.0\n")
            case ["image", "exists", *_]:
                return Answering()
            case ["run", "--interactive", *_] if (
                f"--name=lup-plan-{REPOSITORY}" in arguments
            ):
                return Answering(output=json.dumps(PLAN))
            case ["run", "--interactive", *_] if (
                f"--name=lup-told-{REPOSITORY}" in arguments
            ):
                return Answering(output=GUIDANCE.model_dump_json())
            case ["run", "--detach", *_]:
                return Answering()
            case ["stop", *_, name]:
                self.stops = [*self.stops, name]
                self.heard.set()
                return Answering()
            case ["ps", *_]:
                return Answering(output="[]")
            case _:
                return None


UV = Scripted(answers=[Answering(when=["python", "dir"], output="/srv/python\n")])
"""uv as the promises stand it in: saying the machine keeps Python at
`/srv/python`."""


def packed(files: dict[str, bytes]) -> bytes:
    """Return a gzipped tar archive holding `files`, by their paths in it."""
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o755
            tar.addfile(member, io.BytesIO(content))
    return archive.getvalue()


class Vendors(Model):
    """What each runtime's vendor publishes, as the promises stand it in: one version of each CLI, its manifest or release saying its checksum."""

    claude: str = "https://downloads.claude.ai/claude-code-releases"
    claude_version: str = "2.1.300"
    claude_cli: bytes = b"#!/bin/sh\n"
    codex: str = "https://releases.openai.com/codex"
    codex_version: str = "0.200.0"
    codex_target: str = "x86_64-unknown-linux-musl"
    codex_archive: str = "https://example.invalid/codex-package.tar.gz"

    def codex_package(self) -> bytes:
        """Return Codex's package, its manifest and its program."""
        manifest = {
            "version": self.codex_version,
            "target": self.codex_target,
            "entrypoint": "bin/codex",
        }
        return packed(
            {
                "codex-package.json": json.dumps(manifest).encode(),
                "bin/codex": b"#!/bin/sh\n",
            }
        )

    def published(self) -> dict[str, bytes]:
        """Return what each URL answers: each runtime's newest version, its manifest or release, and its CLI."""
        package = self.codex_package()
        release = json.dumps(
            {
                "tag_name": f"rust-v{self.codex_version}",
                "assets": [
                    {
                        "name": f"codex-package-{self.codex_target}.tar.gz",
                        "browser_download_url": self.codex_archive,
                        "digest": f"sha256:{hashlib.sha256(package).hexdigest()}",
                    }
                ],
            }
        ).encode()
        manifest = json.dumps(
            {
                "platforms": {
                    "linux-x64": {
                        "checksum": hashlib.sha256(self.claude_cli).hexdigest()
                    }
                }
            }
        ).encode()
        claude = f"{self.claude}/{self.claude_version}"
        return {
            f"{self.claude}/latest": f"{self.claude_version}\n".encode(),
            f"{claude}/manifest.json": manifest,
            f"{claude}/linux-x64/claude": self.claude_cli,
            f"{self.codex}/channels/latest": release,
            f"{self.codex}/releases/{self.codex_version}/release.json": release,
            self.codex_archive: package,
        }


class Curl(Model, Responding):
    """curl as the promises stand it in: what a vendor publishes at the URL asked for written where it's asked to, any other URL failing as an HTTP error does."""

    published: dict[str, bytes] = Field(default_factory=lambda: Vendors().published())

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Write what the URL asked for answers into the file `--output` names."""
        del given
        into = Path(arguments[arguments.index("--output") + 1])
        content = self.published.get(arguments[-1])
        if content is None:
            return Answering(status=22, error="The requested URL returned error: 404")
        into.write_bytes(content)
        return Answering()


class Holding(Model):
    """What a holder is started with, of which the promises read the socket it listens on for the room's first program."""

    room: Path


class Ordered(Model):
    """An order a holder is told, of which the promises read its kind."""

    order: str


def ordered(run: ProgramRun, kind: str) -> bool:
    """Say whether `run` told a holder an order of `kind`."""
    return (
        HOLDER in run.arguments
        and "order" in run.arguments
        and run.given is not None
        and Ordered.model_validate_json(run.given).order == kind
    )


class Holder(MutableModel, Responding, arbitrary_types_allowed=True):
    """Each session's holder as the promises stand it in: it starts at once, answers every order with where its session stands, connected, ready and idle, and hears each order, in order."""

    holds: list[Holding] = []
    """What each holder started was given, in order."""
    orders: list[Ordered] = []
    """Each order told a holder, in order."""
    heard: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set each time an order is told."""

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer a holder's start, or an order told one, saying where its session stands."""
        if HOLDER not in arguments or given is None:
            return None
        standing = json.dumps({"connected": True, "up": True, "busy": False})
        match arguments[arguments.index(HOLDER) + 1]:
            case "start":
                self.holds = [*self.holds, Holding.model_validate_json(given)]
                return Answering(output=standing)
            case "order":
                self.orders = [*self.orders, Ordered.model_validate_json(given)]
                self.heard.set()
                return Answering(output=standing)
            case _:
                return None

    def kinds(self) -> list[str]:
        """Return the kind of each order told, in order."""
        return [each.order for each in self.orders]

    async def told(self, kind: str) -> None:
        """Wait until a holder is told an order of `kind`."""
        while kind not in self.kinds():
            self.heard.clear()
            await self.heard.wait()


class Listed(Model):
    """A session as the machine lists it, of which the promises read lup's id for it and its name."""

    session: str
    name: str


class Listing(Model):
    """Every session the machine lists."""

    sessions: list[Listed] = []


class Vouched(Model):
    """A call as the machine carries it, of which the promises read whom it's by."""

    by: JsonValue


class Carried(Model):
    """Where a call come in on a socket goes, of which the promises read the call as carried."""

    call: Vouched


class Specific(Model):
    """What Claude Code reads of a hook's answer for its hook alone: what the agent's told beside it, and what a call's given in place of what it was."""

    told: str | None = Field(default=None, alias="additionalContext")
    updated: dict[str, JsonValue] | None = Field(default=None, alias="updatedInput")


class Printed(Model):
    """What a hook prints for Claude Code to read."""

    specific: Specific = Field(default_factory=Specific, alias="hookSpecificOutput")


class Spoken(Model):
    """What a hook answers its runtime: what it prints, and the status it ends with."""

    output: str
    status: int = 0

    def printed(self) -> Specific:
        """Return what it prints for its hook alone, as Claude Code reads it."""
        return Printed.model_validate_json(self.output).specific


class Telling(Model):
    """How many times one item was told to one party, as the inbox says it."""

    item: int
    party: str
    times: int


class Inboxed(Model):
    """The project's inbox as data, of which the promises read what's new to the operator and what's been told whom."""

    new: list[int] = []
    told: list[Telling] = []


class Inside(Model):
    """Where lup's things land in a room, as the promises check them."""

    sockets: Path = Path("/run/lup")
    """The room's directory of sockets."""


class Machined(Model, arbitrary_types_allowed=True):
    """The machine's parts as a promise starts them: a project open, each program stood in for, and where the project's git directory is."""

    started: Started
    podman: Podman
    holder: Holder
    common: Path
    """The project's common git directory on the machine."""

    async def session(self, name: str, runtime: str = "claude") -> Accepted | Refused:
        """Start a session called `name` on `runtime`, in a worktree of its own, as the operator does, and say what came of it."""
        return await self.started.run(
            "sessions",
            "start",
            {
                "repository": REPOSITORY,
                "runtime": runtime,
                "name": name,
                "worktree": str(self.common / "tree" / name),
            },
            Operator(),
        )

    async def begun(self, name: str, runtime: str = "claude") -> str:
        """Start a session called `name` on `runtime`, which must start, and return lup's id for it."""
        started = await self.session(name, runtime)
        assert isinstance(started, Accepted), started
        known = await self.started.serve("known", {}, Machine())
        assert isinstance(known, Accepted), known
        listing = Listing.model_validate_json(known.answer())
        [session] = [each.session for each in listing.sessions if each.name == name]
        return session

    def room(self, session: str) -> list[str]:
        """Return podman's arguments starting the room of the session lup knows as `session`, which must have started once."""
        [command] = [
            each
            for each in self.started.ran("podman")
            if "--detach" in each and f"--name=lup-{REPOSITORY}-{session}" in each
        ]
        return command

    async def hooked(
        self, session: str, hook: str, payload: dict[str, JsonValue]
    ) -> Accepted | Refused:
        """Send one of a Claude Code session's hooks from its room, as its hook command does, by the session's agent the room vouches for."""
        given: dict[str, JsonValue] = {
            "hook_event_name": hook,
            "session_id": session,
            "cwd": str(self.common / "tree"),
            **payload,
        }
        return await self.started.serve(
            "hooked",
            {"hook": hook, "payload": json.dumps(given)},
            Agent.of(session),
        )

    async def routed(self, directory: Path) -> Accepted | Refused:
        """Carry a call to one of lup's tools come in on the socket in `directory`, as the machine does, which says it's the operator's."""
        call: JsonValue = {
            "format": 1,
            "kind": "tool",
            "tool": "note",
            "given": {},
            "by": {"party": "operator"},
        }
        return await self.started.serve(
            "routed", {"directory": str(directory), "call": call}, Machine()
        )

    async def inboxed(self) -> Inboxed:
        """Return the project's inbox as data, as its code reads it."""
        read = await self.started.serve("standing", {}, Codebase(repository=REPOSITORY))
        assert isinstance(read, Accepted), read
        return Inboxed.model_validate_json(read.answer())

    async def told(self, name: str, text: str) -> int:
        """Tell the agent called `name` `text`, as the operator does, and return the number of the item it's told in."""
        before = await self.inboxed()
        sent = await self.started.run(
            "core",
            "tell",
            {"repository": REPOSITORY, "to": name, "text": text},
            Operator(),
        )
        assert isinstance(sent, Accepted), sent
        after = await self.inboxed()
        [number] = [
            each.item
            for each in after.told
            if each.party == f"@{name}" and each not in before.told
        ]
        return number

    async def times(self, name: str, item: int) -> int:
        """Return how many times the item numbered `item` was told to the agent called `name`."""
        inbox = await self.inboxed()
        return sum(
            each.times
            for each in inbox.told
            if each.party == f"@{name}" and each.item == item
        )


def placed(place: Path) -> Path:
    """Make the project's common git directory in `place`, its configuration and its worktrees' directory, as a room mounts them, and return it."""
    common = place / f"{REPOSITORY}.git"
    (common / "tree").mkdir(parents=True)
    (common / "config").touch()
    return common


async def machine_started(
    by: Testing, settings: list[str], kept: Path, podman: Podman, holder: Holder
) -> Started:
    """Start the machine's parts as the machine's own, the sessions' module given `settings`, its rooms keeping what they share in `kept`, never where the operator's are, podman stood in for by `podman` and each session's holder by `holder`."""
    return await by.started(
        lup.testing.Repository(declaration=home(kept, *settings)),
        programs={
            "podman": podman,
            "git": Store(),
            "uv": UV,
            "curl": Curl(),
            sys.executable: holder,
        },
        machine=True,
    )


@asynccontextmanager
async def machined(by: Testing, *settings: str) -> AsyncGenerator[Machined]:
    """Start the machine's parts as the machine's own, the sessions' module given `settings`, and open the project the operator approved a commit of, in a directory of the promise's own, removed once the parts have stopped."""
    with tempfile.TemporaryDirectory(prefix="lup-sessions-") as directory:
        place = await asyncio.to_thread(Path(directory).resolve)
        common = await asyncio.to_thread(placed, place)
        podman, holder = Podman(), Holder()
        started = await machine_started(
            by, list(settings), place / "kept", podman, holder
        )
        approved = await started.run(
            "hosting",
            "approve",
            {"project": REPOSITORY, "commit": COMMIT.id},
            Operator(),
        )
        assert isinstance(approved, Accepted), approved
        opened = await started.serve(
            "opened", {"repository": REPOSITORY, "common": str(common)}, Machine()
        )
        assert isinstance(opened, Accepted), opened
        try:
            yield Machined(started=started, podman=podman, holder=holder, common=common)
        finally:
            await started.stopped()


def mounted(command: list[str], destination: Path) -> list[list[str]]:
    """Return each mount among podman's arguments `command` landing at `destination`, as its fields."""
    mounts = [
        next(csv.reader([each.removeprefix("--mount=")]))
        for each in command
        if each.startswith("--mount=")
    ]
    return [each for each in mounts if f"destination={destination}" in each]


def source_of(mount: list[str]) -> Path:
    """Return the directory of the machine's a mount's fields say it mounts."""
    [source] = [
        each.removeprefix("source=") for each in mount if each.startswith("source=")
    ]
    return Path(source)


def spoken(answered: Accepted | Refused) -> Specific:
    """Return what a hook's answer has Claude Code read for its hook alone, which the hook must have answered."""
    assert isinstance(answered, Accepted), answered
    return Spoken.model_validate_json(answered.answer()).printed()


type Wall = Literal[
    "--rm",
    "--init",
    "--pull=never",
    "--userns=keep-id",
    "--cap-drop=all",
    "--security-opt=no-new-privileges",
]
"""What every container lup starts stands behind, as podman's options."""


class Named(Model):
    """What a session is called, as the operator names one."""

    name: Literal["reader", "harmon-bot", "story.teller", "writer_2"]


class Runtimed(Model):
    """A runtime a session runs on, by lup's name for it."""

    runtime: Literal["claude", "codex"]


class Called(Model):
    """A call a session's conversation is about to make, as its hook says it: to one of lup's own tools or another, by the session's own conversation or a subagent's."""

    tool: Literal["mcp__lup__note", "mcp__lup__send", "Bash", "Read", "mcp__other__lup"]
    conversation: Literal["a1b2c3", "agent-7", "x"] | None = None
    """The subagent's id, as Claude Code names one; none for the session's own."""
    given: dict[Literal["text", "to", "command", "path"], str] = {}
    """What the tool's given."""

    def payload(self) -> dict[str, JsonValue]:
        """Return what Claude Code's `PreToolUse` is given of it."""
        return {
            "tool_name": self.tool,
            "tool_input": {str(key): value for key, value in self.given.items()},
            "tool_use_id": "toolu_1",
            **({} if self.conversation is None else {"agent_id": self.conversation}),
        }


class Words(Model):
    """Words someone says: an agent's last words of a turn, or the operator's to an agent."""

    text: str = Field(min_length=1, max_length=200)


class Next(Model):
    """The hook a session's own conversation runs at its next prompt or call, which tells them what waits."""

    hook: Literal["UserPromptSubmit", "PreToolUse"]

    def payload(self) -> dict[str, JsonValue]:
        """Return what the hook is given."""
        if self.hook == "UserPromptSubmit":
            return {"prompt": "go on"}
        return {
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_use_id": "toolu_2",
        }


class Most(Model):
    """The most sessions a promise's machine runs at once."""

    most: int = Field(ge=1, le=3)


class SessionsPromises(Part):
    """What the operator, and a session's agent, can count on of the sessions lup starts and holds."""

    @lup.promise
    async def a_session_starts_held_in_a_room_of_its_own(self, by: Testing) -> None:
        """Starting a session starts its holder, then its room: behind the walls every container stands behind, its first program the one connecting its runtime to its holder, over the socket the holder listens on in the room's own directory of sockets, mounted at `/run/lup`, then its runtime; a call from that directory is by the session's own agent, whatever it says."""
        named, runtime = by.any(Named).name, by.any(Runtimed).runtime
        inside = Inside()
        async with machined(by) as machine:
            session = await machine.begun(named, runtime)
            runs = machine.started.heard.runs
            command = machine.room(session)
            holding = next(
                index
                for index, each in enumerate(runs)
                if HOLDER in each.arguments and "start" in each.arguments
            )
            rooming = next(
                index for index, each in enumerate(runs) if each.arguments == command
            )
            assert holding < rooming
            assert all(wall in command for wall in get_args(Wall.__value__))
            assert any(each.startswith("--pids-limit=") for each in command)
            tag = next(
                index
                for index, each in enumerate(command)
                if each.startswith("localhost/lup:")
            )
            program = command[tag + 1 :]
            assert program.index("lup.environment.sessions.connected") == 3
            assert program.index("-m") == 2
            separator = program.index("--")
            assert program[separator + 1] == runtime
            [sockets] = mounted(command, inside.sockets)
            assert "ro=true" not in sockets
            directory = source_of(sockets)
            [holds] = machine.holder.holds
            connecting = Path(program[separator - 1])
            assert holds.room.parent == directory
            assert connecting.parent == inside.sockets
            assert holds.room.name == connecting.name
            routed = await machine.routed(directory)
            assert isinstance(routed, Accepted), routed
            carried = Carried.model_validate_json(routed.answer())
            assert carried.call.by == Agent.of(session).model_dump(mode="json")

    @lup.promise
    async def a_subagents_call_to_lups_tools_is_stamped(self, by: Testing) -> None:
        """A call about to run, as a session's hook says it, is read with the session's runtime: a subagent's call to one of lup's own tools is answered with what it's given and lup's stamp of their conversation beside it; the session's own conversation's call, or a call to another tool, runs as it is, unstamped; a hook from the room of a session lup never started is refused."""
        called, stranger = by.any(Called), by.any(Agent)
        async with machined(by) as machine:
            session = await machine.begun(by.any(Named).name)
            answered = await machine.hooked(session, "PreToolUse", called.payload())
            updated = spoken(answered).updated
            if called.conversation is None or not called.tool.startswith("mcp__lup__"):
                assert updated is None
            else:
                assert updated is not None
                assert called.given.items() <= updated.items()
                [stamp] = [
                    value for key, value in updated.items() if key not in called.given
                ]
                assert stamp == called.conversation
            refused = await machine.started.serve(
                "hooked",
                {"hook": "PreToolUse", "payload": json.dumps(called.payload())},
                stranger,
            )
            assert isinstance(refused, Refused)

    @lup.promise
    async def what_waits_is_told_at_the_next_hook_once(self, by: Testing) -> None:
        """What waits in the inbox for a session's own agent, mid-turn, is told them at their next prompt or call, once: the hooks after tell them nothing of it."""
        named, words = by.any(Named).name, by.any(Words).text
        first, then = by.any(Next), by.any(Next)
        async with machined(by) as machine:
            session = await machine.begun(named)
            began = await machine.hooked(
                session, "UserPromptSubmit", {"prompt": "start"}
            )
            assert spoken(began).told is None
            item = await machine.told(named, words)
            telling = spoken(await machine.hooked(session, first.hook, first.payload()))
            assert telling.told is not None
            assert f'item="{item}"' in telling.told
            again = await machine.hooked(session, then.hook, then.payload())
            assert spoken(again).told is None
            assert await machine.times(named, item) == 1

    @lup.promise
    async def a_turns_last_words_are_kept_as_its_end(self, by: Testing) -> None:
        """A session's own conversation ending their turn, as its `Stop` hook says, has their last words kept in the inbox as their turn's end, in their buffer, new to the operator."""
        named, words = by.any(Named).name, by.any(Words).text
        async with machined(by) as machine:
            session = await machine.begun(named)
            before = await machine.inboxed()
            stopped = await machine.hooked(
                session, "Stop", {"last_assistant_message": words}
            )
            assert isinstance(stopped, Accepted), stopped
            after = await machine.inboxed()
            [new] = [each for each in after.new if each not in before.new]
            buffer = await machine.started.view(
                "core",
                "party",
                {"repository": REPOSITORY, "name": named},
                Operator(),
            )
            assert isinstance(buffer, Accepted), buffer
            assert isinstance(buffer.output, lup.Blocks)
            [heading] = [
                each
                for each in buffer.output.blocks
                if isinstance(each, lup.Line) and each.id == f"item-{new}"
            ]
            [text] = [
                each
                for each in buffer.output.blocks
                if isinstance(each, lup.Markdown) and each.id == f"item-{new}-text"
            ]
            assert any("turn-end" in span.text for span in heading.spans)
            assert text.text == words

    @lup.promise
    async def ending_a_session_ends_its_holder_and_room(self, by: Testing) -> None:
        """Ending a session tells its holder to end, then stops its room; a call from its room is refused from then on."""
        named = by.any(Named).name
        async with machined(by) as machine:
            session = await machine.begun(named)
            room = f"lup-{REPOSITORY}-{session}"
            [sockets] = mounted(machine.room(session), Inside().sockets)
            ended = await machine.started.run(
                "sessions", "end", {"name": named}, Operator()
            )
            assert isinstance(ended, Accepted), ended
            runs = machine.started.heard.runs
            [ending] = [
                index for index, each in enumerate(runs) if ordered(each, "end")
            ]
            stopping = [
                index
                for index, each in enumerate(runs)
                if each.program == "podman"
                and each.arguments[0] == "stop"
                and each.arguments[-1] == room
            ]
            assert stopping
            assert ending < min(stopping)
            gone = await machine.routed(source_of(sockets))
            assert isinstance(gone, Refused)

    @lup.promise
    async def past_the_most_sessions_running_a_start_is_refused(
        self, by: Testing
    ) -> None:
        """Past `Sessions.most` sessions running, a start is refused before its holder or room starts; one ended makes room for another."""
        most, ending = by.any(Most).most, by.any(bool)
        async with machined(by, f"most={most}") as machine:
            names = [f"reader-{each}" for each in range(most)]
            for name in names:
                await machine.begun(name)
            if ending:
                ended = await machine.started.run(
                    "sessions", "end", {"name": names[0]}, Operator()
                )
                assert isinstance(ended, Accepted), ended

            def rooms() -> int:
                return len(
                    [
                        each
                        for each in machine.started.ran("podman")
                        if "--detach" in each
                    ]
                )

            holders, started = len(machine.holder.holds), rooms()
            past = await machine.session("writer")
            assert isinstance(past, Accepted) == ending
            assert (len(machine.holder.holds) == holders) != ending
            assert (rooms() == started) != ending

    @lup.promise
    async def an_idle_session_with_something_for_it_is_woken(self, by: Testing) -> None:
        """A session idle, its own agent told something in the inbox, is woken by the sweep: its holder told to start a turn on what waits, which is told once, never again at its hooks."""
        named, words, later = by.any(Named).name, by.any(Words).text, by.any(Next)
        async with machined(by) as machine:
            session = await machine.begun(named)
            item = await machine.told(named, words)
            await machine.holder.told("turn")
            assert await machine.times(named, item) == 1
            after = await machine.hooked(session, later.hook, later.payload())
            assert spoken(after).told is None

    @lup.promise
    async def a_session_idle_past_its_time_is_ended(self, by: Testing) -> None:
        """A session idle past `Sessions.idle` is ended by the sweep: its holder told to end, then its room stopped."""
        named = by.any(Named).name
        async with machined(by, "idle=timedelta(0)") as machine:
            session = await machine.begun(named)
            room = f"lup-{REPOSITORY}-{session}"
            await machine.podman.stopped(room)
            runs = machine.started.heard.runs
            ending = [index for index, each in enumerate(runs) if ordered(each, "end")]
            stopping = next(
                index
                for index, each in enumerate(runs)
                if each.program == "podman"
                and each.arguments[0] == "stop"
                and each.arguments[-1] == room
            )
            assert ending
            assert min(ending) < stopping
