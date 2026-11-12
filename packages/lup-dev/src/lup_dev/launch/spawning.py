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
  (`Register.repository`), never a path the call names. The launcher takes it
  as given (`HeldLaunch.repository`, `located` in `cli.py`), never finding it
  through the worktree, whose `.git` file a room writes, and refuses a worktree
  that repository doesn't name back.
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
  the concerns of the spawner's repository alone.
- **How many:** at most `limit` sessions an agent spawned run at once on the
  host, and `each` of one repository's, counted from those served, those whose
  launcher started and hasn't registered yet, and the spawns under way: against
  a loop of spawns, not a budget.
- **Nothing a room can slow holds the service, or another room's spawn.** git
  on the host reads refs a room writes, any of which it can make a pipe
  nothing writes: it runs in the repository's own threads, off the service's
  loop (`threaded`), killed past `reading`, and a branch's free number is
  read in one call, `numbers` at most tried. `podman exec` running the room's
  own git to make the worktree is killed past `making`, with what it started
  (`executed`). Nothing is held across either: a spawn is counted, and takes
  its branch, at once, between two awaits (`reserved`).

What isn't covered: another repository, which the call can't name yet; and a
spawn whose launcher fails after an approval restarted the service, which the
spawner isn't told of, the service started since not knowing that launcher.
"""

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

from pydantic import Field, JsonValue

import lup
from lup.programs import ProgramError, Ran
from lup.tools.serving import Answer
from lup.tools.tool import Accepted, AgentTool, ToolSpec
from lup.tools.tool import Refused as Rejected
from lup.types import Model, MutableModel
from lup_dev.git import Git, GitError, threaded
from lup_dev.host.held import HeldLaunch, Launchers, Spawning
from lup_dev.host.protocol import Register, Spawner, branch_name, segment
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
            "A concern to hand over with it: an existing one's name or number, "
            "or a new title, which opens one under the one you work in. It "
            "holds it and works in it, its reports land there, and the "
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
          whole, wakes you, and returns your `wait_inbox`, and it ends there.
          `send` reaches it by its name, resuming it with all it knew, its
          answer coming back the same way.
        - **A concern handed over** (`concern`): it holds it and works in it,
          what it says lands there, the operator talks with it directly, and
          it lands its own branch. You hear, in a line, when it says the
          concern is done and when it ends, not its reports, which you read in
          the concern. Once handed, it's theirs.

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


class Reserved(Model):
    """A spawn under way: its repository's git directory, and the branch it took, once it took one."""

    token: str
    repository: Path
    branch: str | None = None


class SpawnTools(MutableModel, RoomTools, arbitrary_types_allowed=True):
    """The `spawn` tool, as the host service serves it to each launched session; what's under way changes as calls come and go."""

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
    """Runs one program on the host: `podman exec` into the spawner's room,
    killed past its `within` with what it started, which ends with status
    124."""
    limit: int = 32
    """How many sessions agents spawned may run at once on the host, every
    repository's: against a loop of spawns, each about 300 MB of a held runtime
    while it runs."""
    each: int = 16
    """How many of those may be one repository's, so one room's loop leaves
    the other repositories theirs."""
    longest: int = 48
    """How long a branch's name made from a spawn's `name` may be, so a number
    added where it's taken keeps it within a launch's name (`handle`)."""
    numbers: int = 100
    """How many numbers a branch's name takes, `-2` to this, before the spawn
    is refused: a room can make as many `tree/<name>-<n>` as it likes."""
    reading: timedelta = timedelta(seconds=30)
    """How long git on the host may take to read refs, before it's killed, as
    long as `Git.limit` gives any: a room can make a ref a pipe nothing
    writes."""
    making: timedelta = timedelta(minutes=2)
    """How long the spawner's room's git may take to make the worktree, a
    checkout of the whole tree, before `podman exec` is killed with what it
    started and the spawn refused."""
    heard: int = 16 * 1024
    """The most of what the room's git prints that's kept, its end, which a
    refusal quotes: the room chooses that git, which could print without end
    into the service's memory (`Program.kept`)."""
    reserved: list[Reserved] = []
    """Each spawn under way, from its count against the limits to its
    launcher's start, with the branch it took once it took one: counted, so
    two calls at once can't both pass a limit, and no two take one branch.
    Nothing is held across what a room can slow."""

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
        launcher started, the concern handed, and the brief sent, the spawn
        counted against the limits from the first await until its launcher has
        started.
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
        reserved = self.limited(launch.repository)
        try:
            return await self.started(bound, spawn, wanted, session, reserved)
        finally:
            self.reserved = [
                each for each in self.reserved if each.token != reserved.token
            ]

    async def started(
        self,
        bound: SpawnCall,
        spawn: Spawn,
        wanted: str,
        session: str,
        reserved: Reserved,
    ) -> str:
        """Start the session `spawn` asks for, of `bound`'s conversation, counted as `reserved`, its branch named `wanted` or the next number free, its session `session`; raise `SpawnError` where it can't be."""
        launch, party = bound.launch, bound.party
        repository = launch.repository
        git = Git.pinned(repository)
        start = spawn.start or self.starting(repository)
        commit = await started_at(git, start, self.reading)
        concerns = self.delivery.concerns()
        if spawn.concern is not None:
            found = concerns.found(repository, spawn.concern)
            numbered = spawn.concern.strip().removeprefix("@").isdigit()
            if (found is None and numbered) or (
                found is not None and not isinstance(found, Thread)
            ):
                message = f"`{spawn.concern}` names no concern of this repository"
                raise SpawnError(message)
        taken = await branches(git, wanted, self.reading)
        made = await self.worktree(
            launch, self.claimed(reserved, wanted, taken), commit
        )
        try:
            thread = (
                None
                if spawn.concern is None
                else concerns.addressed(party, spawn.concern)
            )
        except InboxError as unopened:
            message = f"{unopened}{await self.unmade(launch, made)}"
            raise SpawnError(message) from unopened
        child = Conversation(
            repository=repository, runtime=launch.runtime, session=session
        )
        spawner = Spawner(
            launch=launch.launch,
            conversation=party,
            concern=None if thread is None else thread.number,
        )
        try:
            starting = await self.spawning.started(
                lambda minted: HeldLaunch(
                    launch=minted,
                    runtime=launch.runtime,
                    worktree=made.root,
                    session=session,
                    repository=repository,
                    spawner=spawner,
                    arguments=modelled(launch.model),
                )
            )
        except (ProgramError, OSError) as unstarted:
            message = (
                f"its launcher didn't start: {unstarted}"
                f"{await self.unmade(launch, made)}{opened(thread)}"
            )
            raise SpawnError(message) from unstarted
        try:
            handed = None if thread is None else concerns.handed(party, thread, child)
            brief = Message(kind="note", text=spawn.brief)
            sent = await self.delivery.posted(
                brief, party, child, launch.worktree, call=bound.call
            )
            await self.delivery.copied(
                brief, child, party, launch.worktree, call=bound.call, thread=handed
            )
        except (InboxError, OSError) as unsent:
            # A session up with no brief would wait on nobody: its launcher is
            # ended before it starts one.
            await asyncio.to_thread(
                self.launchers.started[starting.launch].end, self.making
            )
            message = (
                f"its brief wasn't sent, so its launcher was ended: {unsent}"
                f"{await self.unmade(launch, made)}{opened(thread)}"
            )
            raise SpawnError(message) from unsent
        if handed is None:
            kept = self.layout.side_job(session)
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_text(self.launchers.specs[starting.launch].model_dump_json())
        return said(made, start, sent.number, starting.log, handed)

    async def resumed(
        self, side: Conversation, spawner: Conversation, launch: Register
    ) -> str:
        """Resume `side`, a side job `spawner`, of `launch`, spawned, that ended at its report, its session held again in its worktree with its context, as `lup-dev spawn --resume` holds one, the message they just sent it waiting for its call-up; say how it went, after `send`'s answer, or nothing where it's no ended side job of theirs.

        What it was started with is kept by the host as it's spawned
        (`Layout.side_job`), by the session's id lup minted, so nothing a room
        says names its worktree; its spawner is recorded again as the
        conversation that sent, of the launch they send from. It counts
        against the limits as a spawn does.
        """
        try:
            kept = self.layout.side_job(segment(side.session))
            spec = HeldLaunch.model_validate_json(kept.read_text())
        except ValueError, OSError:
            return ""
        if spec.spawner is None or spec.spawner.conversation != spawner:
            return ""
        if any(each.session == side.session for each in self.served()):
            return ""
        if not spec.worktree.is_dir():
            return (
                f" It ended at its report, and its worktree, {spec.worktree}, is "
                "gone, so it isn't resumed."
            )
        try:
            reserved = self.limited(spec.repository or launch.repository)
        except SpawnError as limited:
            return f" It ended at its report, and isn't resumed: {limited}"
        try:
            starting = await self.spawning.started(
                lambda minted: spec.model_copy(
                    update={
                        "launch": minted,
                        "session": None,
                        "resume": side.session,
                        "spawner": Spawner(launch=launch.launch, conversation=spawner),
                        "arguments": modelled(launch.model),
                    }
                )
            )
        except (ProgramError, OSError) as unstarted:
            return (
                f" It ended at its report, and its launcher didn't start: {unstarted}"
            )
        finally:
            self.reserved = [
                each for each in self.reserved if each.token != reserved.token
            ]
        return (
            f" It ended at its report: it's resumed held in {spec.worktree}, with "
            "all it knew, your message its first turn once it's up; its launcher "
            f"writes to {starting.log}."
        )

    async def unmade(self, launch: Register, made: Made) -> str:
        """Remove a spawn's worktree and branch, which nothing ran in yet, by the spawner's room's own git, stopped past `making`, and say how it went, to follow a refusal's reason."""
        container = launch.container
        if container is None:
            return f"; its worktree, {made.root}, and branch `{made.branch}` stay"
        steps = [
            ["worktree", "remove", "--force", str(made.root)],
            ["branch", "-D", made.branch],
        ]
        for step in steps:
            program = Program(
                command=[
                    "podman",
                    "exec",
                    "--workdir",
                    str(launch.repository),
                    container,
                    "git",
                    "--git-dir",
                    str(launch.repository),
                    *step,
                ],
                payload="",
                directory=launch.repository,
                within=self.making,
                kept=self.heard,
            )
            ran = await self.run(program)
            if ran.status != 0:
                return f"; its worktree, {made.root}, and branch `{made.branch}` stay"
        return "; its worktree and branch were removed"

    def limited(self, repository: Path) -> Reserved:
        """Count a spawn in `repository` against the limits, the host's and the repository's, and return it counted; refuse it past either, naming those that run.

        Those counted are the launches served that an agent spawned, those
        whose launcher started and hasn't registered, and the spawns under way.
        Read and counted at once, with nothing awaited between, so two calls
        can't both pass.
        """
        running = {
            each.launch: (each.repository, each.name or each.launch)
            for each in self.served()
            if each.spawner is not None
        }
        starting = {
            each.launch: (each.repository or repository, each.worktree.name)
            for each in self.launchers.spawning(self.layout)
            if each.launch not in running
        }
        under_way = {
            each.token: (each.repository, each.branch or "a spawn under way")
            for each in self.reserved
        }
        counted = {**running, **starting, **under_way}
        theirs = {
            key: name for key, (where, name) in counted.items() if where == repository
        }
        for limit, among, whose in [
            (self.limit, {key: name for key, (_, name) in counted.items()}, ""),
            (self.each, theirs, " of this repository"),
        ]:
            if len(among) >= limit:
                names = ", ".join(f"`{each}`" for each in sorted(among.values()))
                runs = (
                    f"session agents spawned{whose} runs"
                    if len(among) == 1
                    else f"sessions agents spawned{whose} run"
                )
                message = (
                    f"{len(among)} {runs} already, the most that may at once, "
                    f"against loops of spawns: {names}. One ends with `lup-dev "
                    "spawn end`, which is the operator's"
                )
                raise SpawnError(message)
        reserved = Reserved(token=secrets.token_hex(8), repository=repository)
        self.reserved = [*self.reserved, reserved]
        return reserved

    def claimed(self, reserved: Reserved, wanted: str, taken: list[str]) -> str:
        """Take for `reserved` the first of `wanted`, `wanted-2`, `wanted-3` up to `numbers` that's no branch `taken` names, no path in the repository's `tree/`, and no other spawn's under way; refuse where none is.

        Read and taken at once, with nothing awaited between.
        """
        others = [
            each.branch
            for each in self.reserved
            if each.repository == reserved.repository and each.token != reserved.token
        ]
        candidates = [wanted, *(f"{wanted}-{n}" for n in range(2, self.numbers + 1))]
        free = next(
            (
                each
                for each in candidates
                if each not in taken
                and each not in others
                and not made_root(reserved.repository, each).exists(
                    follow_symlinks=False
                )
            ),
            None,
        )
        if free is None:
            message = (
                f"`{wanted}` and `{wanted}-2` to `{wanted}-{self.numbers}` are each a "
                "branch or a worktree already: name it otherwise"
            )
            raise SpawnError(message)
        self.reserved = [
            each.model_copy(update={"branch": free})
            if each.token == reserved.token
            else each
            for each in self.reserved
        ]
        return free

    async def worktree(self, launch: Register, branch: str, commit: str) -> Made:
        """Make the spawn's worktree at `tree/<branch>` in the repository's git directory, on the branch `branch`, at `commit`, by the spawner's room's own git, stopped past `making`; raise `SpawnError` where the room can't be reached, or git fails or runs past it, saying why."""
        repository = launch.repository
        root = made_root(repository, branch)
        container = launch.container
        if container is None:
            message = "your launch names no room to make its worktree in"
            raise SpawnError(message)
        program = Program(
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
            within=self.making,
            kept=self.heard,
        )
        made = Made(root=root, branch=branch, commit=commit)
        ran = await self.run(program)
        if ran.status == 124:  # `executed` killed it past `within`
            # Killing `podman exec` may leave the room's git running, which
            # can make the worktree after all: it's removed all the same.
            message = (
                f"its worktree, {root}, wasn't made in your room within "
                f"{self.making}, so its git was stopped"
                f"{await self.unmade(launch, made)}"
            )
            raise SpawnError(message)
        if ran.status != 0:
            said = ran.said() or f"it ended with status {ran.status}"
            message = f"its worktree, {root}, wasn't made in your room: {said}"
            raise SpawnError(message)
        return made

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
        # Not what the log says: it can name what's no room's to read, as
        # another repository's paths.
        text = (
            f"lup: the session spawned in {spec.worktree} never came up, so it "
            f"isn't running. Its launcher's log, the operator's to read, is {log}."
        )
        await self.delivery.posted(
            Message(kind="problem", text=text),
            child,
            self.delivery.reaching(spawner.conversation),
            None,
        )


async def started_at(git: Git, start: str, within: timedelta) -> str:
    """Return the commit the local branch `start` is at, read by git pinned to the repository's common directory, in the repository's own threads (`threaded`), stopped past `within`; raise `SpawnError` where `start` isn't a branch's short name, names no branch there, or git can't read it in time."""
    repository = git.where()
    try:
        branch_name(start)
        await threaded(
            repository,
            git.run,
            "check-ref-format",
            f"refs/heads/{start}",
            within=within,
        )
    except (ValueError, GitError) as unnamed:
        message = f"`{start}` isn't a branch's short name"
        raise SpawnError(message) from unnamed
    try:
        found = await threaded(
            repository,
            git.run,
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            f"refs/heads/{start}^{{commit}}",
            ok=[0, 1],
            within=within,
        )
    except GitError as unread:
        message = f"`{start}` couldn't be read: {unread}"
        raise SpawnError(message) from unread
    commit = found.output.decode().strip()
    if found.status != 0 or not commit:
        message = f"no local branch `{start}` is there to start from"
        raise SpawnError(message)
    return commit


async def branches(git: Git, wanted: str, within: timedelta) -> list[str]:
    """Return the branches of the repository named `wanted` or `wanted-<anything>`, by their short names, read in one go by git pinned to its common directory, in the repository's own threads (`threaded`), stopped past `within`; raise `SpawnError` where git can't read them in time."""
    try:
        found = await threaded(
            git.where(),
            git.run,
            "for-each-ref",
            "--format=%(refname:lstrip=2)",
            f"refs/heads/{wanted}",
            f"refs/heads/{wanted}-*",
            within=within,
        )
    except GitError as unread:
        message = f"the branches named `{wanted}` couldn't be read: {unread}"
        raise SpawnError(message) from unread
    return found.output.decode().splitlines()


def opened(thread: Thread | None) -> str:
    """Say the concern a refused spawn named stays, where it named one, to follow the refusal's reason."""
    return "" if thread is None else f"; @{thread.name} stays as it is"


def modelled(model: str | None) -> list[str]:
    """Return the runtime's arguments a spawned session runs with: the spawner's launch's model, where its arguments named one, so the agents it spawns run on the model it does, the trial's cheap one among them.

    >>> modelled("haiku"), modelled(None)
    (['--model', 'haiku'], [])
    """
    return [] if model is None else ["--model", model]


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
            "whole, wakes you, and returns your `wait_inbox`, and it ends there. "
            f"`send` to `{made.branch}` resumes it, with all it knew."
        )
    return (
        f"{where} @{handed.name} is theirs now: what it says lands there, where you "
        "can read it, and the operator talks with it directly. You'll hear in a "
        "line when it says it's done, and when it ends."
    )
