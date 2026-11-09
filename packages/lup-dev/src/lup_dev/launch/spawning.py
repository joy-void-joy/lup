"""An agent's `spawn`: a session of its own, held with no terminal, in a room and a worktree of its own (`docs/launch.md`, *An agent's spawn*).

The tool is the host service's, served each launched session on its
`mcp.sock` beside the inbox's. One call starts what `lup-dev spawn` starts for
the operator, through the same launcher (`Spawning.started`), and returns at
once; the launch's setup runs behind it. Two kinds, told apart by what's
given rather than by a kind: with a `concern`, it's a concern handed over to
build, which the session spawned holds, and where what it says lands, the
operator talking with it directly; without, a side job for the spawner, whose
report, its turn's end, comes back to them whole (`Delivery.reported`).

**Why a room can't make more of it than that.** A room asks the host to start
something outside it, so what the call can name, and what reaches a command
line, a path or git, is held to this:
- **Who asks** is the conversation lup's hook stamped on the call, of the
  launch whose `mcp.sock` it came on (`LaunchTools`): the socket says the launch,
  never the room. The spawner recorded with the launch (`Spawner`) is that
  launch and that conversation, so the parent link is the host's, not the
  room's word.
- **The repository** is the one the host recorded for the spawner's launch
  (`Register.repository`), never a path the call names. The launcher refuses a
  worktree whose git leads elsewhere (`HeldLaunch.repository`, `spawned_in` in
  `cli.py`), since a room writes every worktree's `.git` file and could lead
  one to another repository approved on this machine.
- **The worktree** is made at `tree/<branch>` in that repository's git
  directory (`made_root`), inside what the spawner's room mounts, by the
  spawner's room's own git through `podman exec` (as `land` removes worktrees),
  never by the host's git on what a room committed: a checkout runs filters
  and hooks the room's commits choose. The command is a list, no shell: `git`,
  the git directory from the host's record, `worktree add`, the branch, the
  root and a commit's id.
- **The branch** is the call's `name` in a branch's shape (`branch_named`):
  ASCII letters, digits and `-`, never starting with `-`, so neither git nor a
  path reads it as anything else; a branch or a worktree that's there already
  takes the next number.
- **What it starts from** is a local branch by its short name, held to a
  branch's shape (`branch_name`, then git's own `check-ref-format` on
  `refs/heads/<it>`, which expands no `@{-1}` as `--branch` would), read by
  git pinned to the common directory (`Git.pinned`, hooks off, no replace
  objects, no commit graph) as `refs/heads/<it>`, peeled to a commit; only
  that commit's id reaches the room's git.
- **The runtime** is the spawner's, and only one with a session held with no
  terminal; the call names none, nor any of its arguments, a profile or an
  account: the launch runs on its repository's default profile, as
  `lup-dev spawn` with none named does.
- **The brief** is text in the inbox alone: an item from the spawner to the
  session spawned, which reaches it as its first turn through its launcher, as
  the operator's words do (`Delivery.called_up`). `concern` is resolved through
  the threads of the spawner's repository alone.
- **How many:** at most `limit` sessions an agent spawned run at once on the
  host, every repository's, counted from those served and those whose launcher
  started and hasn't registered yet: against a loop of spawns, not a budget.

What isn't covered: another repository, which the call can't name yet; and a
spawn whose launcher fails after an approval restarted the service, which the
spawner isn't told of, the service started since not knowing that launcher.
"""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, override

from pydantic import Field, JsonValue

import lup
from lup.programs import Ran
from lup.tools.serving import Answer
from lup.tools.tool import Accepted, AgentTool, ToolSpec
from lup.tools.tool import Refused as Rejected
from lup.types import Model
from lup_dev.git import Git, GitError
from lup_dev.host.held import HeldLaunch, Launchers, Spawning, tail
from lup_dev.host.protocol import Register, Spawner, branch_name
from lup_dev.host.rooms import RoomTools
from lup_dev.host.service import Program, executed
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import InboxError, Message
from lup_dev.layout import Layout
from lup_dev.policy.worktrees import branch_named, made_root
from lup_ledger.parties import Conversation
from lup_ledger.threads import Thread

if TYPE_CHECKING:
    from lup_dev.host.courier import Conversation as Caller


class Spawn(Model):
    """A session to start: its name, its brief, and the concern handed with it, where one is."""

    name: str = Field(
        description=(
            "What it's for, in a few words, which names it and its branch: "
            "`measure the gate`, `fix-tabs`."
        )
    )
    brief: str = Field(
        description=(
            "Its brief, whole: what to do, what you know already, and what to "
            "say back. It's your message to it, its first turn."
        )
    )
    concern: str | None = Field(
        default=None,
        description=(
            "A concern to hand over with it: an existing thread's name or "
            "number, or a new title, which opens one under the thread you work "
            "in. It holds it and works in it, its reports land there, and the "
            "operator talks with it directly: once handed, it's theirs. Left "
            "out, it's a side job for you, its report coming back to you."
        ),
    )
    start: str | None = Field(
        default=None,
        description=(
            "The local branch its worktree starts from, by its short name. Left "
            "out, the branch work starts from, as the declaration names it."
        ),
    )


class Made(Model):
    """A worktree made for a spawn: where, on which branch, at which commit."""

    root: Path
    branch: str
    commit: str


class SpawnError(InboxError):
    """A spawn that can't be made, and why."""


class SpawnCall(Model, arbitrary_types_allowed=True):
    """One conversation of a launch spawning a session: the tool's function, bound to it."""

    tools: SpawnTools
    launch: Register
    party: Conversation
    call: str | None = None

    async def spawn(self, spawn: Spawn) -> str:
        """Start an agent in a room and worktree of its own.

        A session of its own, as yours is, held by lup with no terminal, in a
        worktree lup makes on a branch named after `name`, from the branch
        `start` names or the one work starts from, its environment made as
        its room starts. Your brief is its first turn. The call returns at
        once, while its room starts.

        Two kinds, by whether you hand it a concern:
        - **A side job for you** (no `concern`), such as a search or a
          measurement: its report, what it ends its turn saying, reaches you
          whole, wakes you, and returns your `wait_inbox`. `send` reaches it
          by its name, and its answer comes back the same way, with all it
          knew. It ends when your session does.
        - **A concern handed over** (`concern`): it holds it and works in it,
          what it says lands there, the operator talks with it directly, and
          it lands its own branch. You hear when it ends, in a line, not its
          reports, which you read in the concern. Once handed, it's theirs.

        The runtime is yours. How many run at once has a high limit, against
        loops of spawns.
        """
        try:
            return await self.tools.spawned(self, spawn)
        except InboxError as refused:
            return f"Not spawned: {refused}"

    def tools_bound(self) -> list[AgentTool]:
        """Return the tool, bound to this conversation."""
        return [lup.tool(self.spawn)]


class SpawnTools(Model, RoomTools, arbitrary_types_allowed=True):
    """The `spawn` tool, as the host service serves it to each launched session."""

    delivery: Delivery
    layout: Layout
    spawning: Spawning
    """Starts a launcher apart from the service, as `lup-dev spawn` does."""
    launchers: Launchers
    served: Callable[[], list[Register]]
    """The launches the service serves, as their records stand."""
    mint: Callable[[str], str | None]
    """Mints a new session's id for the runtime named; none where it has no
    session held with no terminal."""
    starting: Callable[[Path], str]
    """The branch work starts from in the repository at the git directory
    given, as the declaration approved names it."""
    run: Callable[[Program], Awaitable[Ran]] = executed
    """Runs one program on the host: `podman exec` into the spawner's room."""
    limit: int = 32
    """How many sessions agents spawned may run at once on the host, every
    repository's: against a loop of spawns, each about 300 MB of a held runtime
    while it runs."""
    longest: int = 48
    """How long a branch's name made from a spawn's `name` may be, so a number
    added where it's taken keeps it within a launch's name (`handle`)."""
    one: asyncio.Lock = Field(default_factory=asyncio.Lock)
    """Held from a spawn's count against the limit to its launcher's start, so
    two calls at once can't both pass it, nor take one branch."""

    @override
    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in SpawnCall.model_construct().tools_bound()]

    @override
    async def call(
        self,
        name: str,
        arguments: JsonValue,
        launch: Register,
        caller: Caller,
        call: str | None,
    ) -> Answer:
        """Run `spawn` for `caller`, a conversation of `launch`; arguments that don't validate are refused, saying why."""
        party = Conversation(
            repository=launch.repository,
            runtime=launch.runtime,
            session=caller.session,
            agent=caller.agent,
        )
        bound = SpawnCall(tools=self, launch=launch, party=party, call=call)
        [tool] = [tool for tool in bound.tools_bound() if tool.spec().name == name]
        match await tool.call(arguments):
            case Accepted(answer=answer):
                return Answer(text=str(answer))
            case Rejected(rejection=rejection):
                return Answer(text=f"Refused: {rejection.reason}", error=True)

    async def spawned(self, bound: SpawnCall, spawn: Spawn) -> str:
        """Start the session `spawn` asks for, of `bound`'s conversation, and say what it is; raise `SpawnError` where it can't be, having made nothing where that's known before.

        Everything the call names is read first: the runtime, the name, the
        limit, what it starts from, the concern. Then the worktree is made in
        the spawner's room, the concern opened where it's a new title, the
        launcher started, the concern handed, and the brief sent, one spawn at
        a time from its count against the limit.
        """
        launch = bound.launch
        session = self.mint(launch.runtime)
        if session is None:
            message = (
                f"{launch.runtime} has no session lup holds with no terminal yet, so "
                "a session of yours spawns none"
            )
            raise SpawnError(message)
        wanted = branch_named(spawn.name)
        if not wanted:
            message = f"`{spawn.name}` holds no letter or digit to name it by"
            raise SpawnError(message)
        if len(wanted) > self.longest:
            message = (
                f"`{spawn.name}` is long for a name: a few words, its branch "
                f"`{wanted}` {self.longest} characters at most"
            )
            raise SpawnError(message)
        if not spawn.brief.strip():
            message = "its brief is empty: it would start with nothing to do"
            raise SpawnError(message)
        async with self.one:
            return await self.started(bound, spawn, wanted, session)

    async def started(
        self, bound: SpawnCall, spawn: Spawn, wanted: str, session: str
    ) -> str:
        """Start the session `spawn` asks for, of `bound`'s conversation, its branch named `wanted` or the next number free, its session `session`, past the limit and what it starts from; raise `SpawnError` where it can't be."""
        launch, party = bound.launch, bound.party
        self.limited()
        repository = launch.repository
        git = Git.pinned(repository)
        start = spawn.start or self.starting(repository)
        commit = started_at(git, start)
        concerns = self.delivery.concerns()
        if spawn.concern is not None:
            found = concerns.found(repository, spawn.concern)
            numbered = spawn.concern.strip().removeprefix("@").isdigit()
            if (found is None and numbered) or (
                found is not None and not isinstance(found, Thread)
            ):
                message = f"`{spawn.concern}` names no thread of this repository"
                raise SpawnError(message)
        made = await self.worktree(launch, git, wanted, commit)
        thread = (
            None if spawn.concern is None else concerns.addressed(party, spawn.concern)
        )
        child = Conversation(
            repository=repository, runtime=launch.runtime, session=session
        )
        spawner = Spawner(
            launch=launch.launch,
            conversation=party,
            concern=None if thread is None else thread.number,
        )
        starting = await self.spawning.started(
            lambda minted: HeldLaunch(
                launch=minted,
                runtime=launch.runtime,
                worktree=made.root,
                session=session,
                repository=repository,
                spawner=spawner,
            )
        )
        handed = None if thread is None else concerns.handed(party, thread, child)
        brief = Message(kind="note", text=spawn.brief)
        sent = await self.delivery.posted(
            brief, party, child, launch.worktree, call=bound.call
        )
        await self.delivery.copied(
            brief, child, party, launch.worktree, call=bound.call, thread=handed
        )
        return said(made, start, sent.number, starting.log, handed)

    def limited(self) -> None:
        """Refuse a spawn past the limit, naming those that run."""
        running = {
            each.launch: each.name or each.launch
            for each in self.served()
            if each.spawner is not None
        }
        starting = {
            each.launch: each.name or each.worktree.name
            for each in self.launchers.spawning()
            if each.launch not in running
        }
        counted = {**running, **starting}
        if len(counted) >= self.limit:
            names = ", ".join(f"`{each}`" for each in sorted(counted.values()))
            runs = (
                "session agents spawned runs"
                if len(counted) == 1
                else ("sessions agents spawned run")
            )
            message = (
                f"{len(counted)} {runs} already, the most that may at once, against "
                f"loops of spawns: {names}. One ends with `lup-dev spawn end`, which "
                "is the operator's"
            )
            raise SpawnError(message)

    async def worktree(
        self, launch: Register, git: Git, wanted: str, commit: str
    ) -> Made:
        """Make the spawn's worktree at `tree/<branch>` in the repository's git directory, on a branch named `wanted`, or the first of `wanted-2`, `wanted-3` free, at `commit`, by the spawner's room's own git; raise `SpawnError` where the room can't be reached or git fails, saying why."""
        repository = launch.repository
        branch = free(git, repository, wanted)
        root = made_root(repository, branch)
        container = launch.container
        if container is None:
            message = "your launch names no room to make its worktree in"
            raise SpawnError(message)
        ran = await self.run(
            Program(
                command=[
                    "podman",
                    "exec",
                    "--workdir",
                    str(repository),
                    container,
                    "git",
                    "--git-dir",
                    str(repository),
                    "worktree",
                    "add",
                    "--quiet",
                    "-b",
                    branch,
                    str(root),
                    commit,
                ],
                payload="",
                directory=repository,
            )
        )
        if ran.status != 0:
            said = ran.said() or f"it ended with status {ran.status}"
            message = f"its worktree, {root}, wasn't made in your room: {said}"
            raise SpawnError(message)
        return Made(root=root, branch=branch, commit=commit)

    async def lost(self, spec: HeldLaunch) -> None:
        """Tell the agent who spawned `spec`'s launch that its session never came up, with the end of what its launcher wrote, as a problem from it: loud, so a spawner waiting on its report hears instead."""
        spawner = spec.spawner
        if spawner is None or spec.session is None:
            return
        log = self.layout.launch(spec.launch).log
        child = Conversation(
            repository=spawner.conversation.repository,
            runtime=spec.runtime,
            session=spec.session,
        )
        text = (
            f"lup: the session spawned in {spec.worktree} never came up, so it "
            f"isn't running. The end of what its launcher wrote ({log}):\n\n"
            f"{tail(log)}"
        )
        await self.delivery.posted(
            Message(kind="problem", text=text), child, spawner.conversation, None
        )


def started_at(git: Git, start: str) -> str:
    """Return the commit the local branch `start` is at, read by git pinned to the repository's common directory; raise `SpawnError` where `start` isn't a branch's short name, or names no branch there."""
    try:
        branch_name(start)
        git.run("check-ref-format", f"refs/heads/{start}")
    except (ValueError, GitError) as unnamed:
        message = f"`{start}` isn't a branch's short name"
        raise SpawnError(message) from unnamed
    found = git.run(
        "rev-parse",
        "--verify",
        "--quiet",
        "--end-of-options",
        f"refs/heads/{start}^{{commit}}",
        ok=[0, 1],
    )
    commit = found.output.decode().strip()
    if found.status != 0 or not commit:
        message = f"no local branch `{start}` is there to start from"
        raise SpawnError(message)
    return commit


def free(git: Git, repository: Path, wanted: str) -> str:
    """Return `wanted`, or the first of `wanted-2`, `wanted-3` that's neither a branch of the repository nor a worktree's place there."""

    def taken(branch: str) -> bool:
        found = git.run(
            "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", ok=[0, 1]
        )
        return found.status == 0 or made_root(repository, branch).exists()

    if not taken(wanted):
        return wanted
    number = 2
    while taken(f"{wanted}-{number}"):
        number += 1
    return f"{wanted}-{number}"


def said(made: Made, start: str, brief: int, log: Path, handed: Thread | None) -> str:
    """Say what a spawn started: its name, where it works, which kind it is and where what it says goes."""
    where = (
        f"`{made.branch}` is starting, in {made.root} on its branch `{made.branch}`, "
        f"from `{start}`, at {made.commit}; its brief is @{brief}, its first "
        f"turn, and its launcher writes to {log}."
    )
    if handed is None:
        return (
            f"{where} A side job for you: what it ends its turn saying reaches you "
            "whole, wakes you, and returns your `wait_inbox`. `send` reaches it by "
            f"`{made.branch}`, and it ends when your session does."
        )
    return (
        f"{where} @{handed.name} is theirs now: what it says lands there, where you "
        "can read it, and the operator talks with it directly. You'll hear in a "
        "line when it ends."
    )
