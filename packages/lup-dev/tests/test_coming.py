"""Parked threads woken where what they wait for comes: a time, a conversation's end, a condition the gate found holding, a branch or a commit landing, an issue closing."""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

import pytest

from lup import events
from lup.programs import run
from lup_dev import cli
from lup_dev.codescan.contract import Due
from lup_dev.errors import LupDevError
from lup_dev.forge.github import GitHubError
from lup_dev.host.courier import Conversation as Caller
from lup_dev.host.courier import Heard
from lup_dev.host.names import Names
from lup_dev.host.protocol import Limits, Register
from lup_dev.host.pushes import Pushes
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.reading import Narrowing, Reader
from lup_dev.inbox.store import KINDS, Inbox
from lup_dev.inbox.tools import Parking, Speaker, ThreadedRemark, Threading
from lup_dev.layout import GitDirectoryLayout, Layout
from lup_dev.policy.coming import Coming, hashed
from lup_dev.remote.protocol import Update
from lup_dev.stored import write_model
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Lup
from lup_ledger.threads import Parked, Reopened, Thread

if TYPE_CHECKING:
    from conftest import FakeClock

    from lup_dev.codescan.directives import IssueRef


class Silent(Notices):
    """Raises nothing."""

    @override
    async def notify(self, summary: str, body: str) -> None:
        pass


class World:
    """A delivery over an inbox, the threads of one repository on it, and what wakes them."""

    def __init__(self, tmp_path: Path, clock: FakeClock) -> None:
        self.repository = tmp_path / "work" / ".git"
        self.repository.mkdir(parents=True)
        self.delivery = Delivery(
            inbox=Inbox.opened(
                Ledger.opened(LedgerLayout(home=tmp_path / "ledger"), KINDS)
            ),
            waker=cli.Wakers(adapters=cli.Adapters(known=cli.adapters())),
            pushes=Pushes(),
            layout=Layout(state=tmp_path / "state", runtime=tmp_path / "run").host,
            notices=Silent(),
            clock=clock,
            say=lambda _: None,
        )
        self.said: list[str] = []
        self.closed: list[int] = []
        self.asked: list[str] = []
        self.coming = Coming(
            delivery=self.delivery,
            integration="dev",
            say=self.said.append,
            states=self.state,
        )
        self.register = self.launched(
            "dev", "s1", Limits(actions=["read-issues"], protected=[])
        )
        asyncio.run(self.speaker(self.main("s1")).note(ThreadedRemark(remark="Go.")))

    async def state(
        self, launch: Register, issue: IssueRef
    ) -> Literal["open", "closed"]:
        assert launch == self.register
        self.asked.append(str(issue))
        if issue.number == 99:
            message = "`gh` on the host has no GitHub login"
            raise GitHubError(message)
        return "closed" if issue.number in self.closed else "open"

    def launched(self, name: str, session: str, limits: Limits) -> Register:
        """Serve a launch named `name`, its session `session` heard in it."""
        register = Register(
            launch=name,
            runtime="claude",
            worktree=self.repository.parent,
            repository=self.repository,
            judge=Path("/judge/lup-dev"),
            limits=limits,
            github=None,
        )
        record = self.delivery.layout.record(name)
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(register.model_dump_json())
        Names(path=self.delivery.layout.names).keep(session, name)
        self.delivery.heard_in(self.main(session), register, None)
        return register

    def main(self, session: str) -> Conversation:
        return Conversation(
            repository=self.repository, runtime="claude", session=session
        )

    def spawned(self, agent: str, name: str) -> Conversation:
        party = self.main("s1").model_copy(update={"agent": agent})
        self.delivery.heard_in(party, self.register, self.main("s1"), name)
        return party

    def speaker(self, party: Conversation) -> Speaker:
        return Speaker(delivery=self.delivery, launch=self.register, party=party)

    def parked(self, name: str, parking: Parking, holder: Conversation) -> Thread:
        """Open thread `name`, handed to `holder`, and park it as `parking` says."""
        said = asyncio.run(
            self.speaker(self.main("s1")).thread(
                Threading(name=name, title=f"About {name}", park=parking)
            )
        ).text
        assert "is parked until" in said, said
        if holder != self.main("s1"):
            hand = self.delivery.roster().own(holder)
            asyncio.run(
                self.speaker(self.main("s1")).thread(Threading(name=name, hand=hand))
            )
        self.told(holder)
        return self.thread(name)

    def thread(self, name: str) -> Thread:
        return self.delivery.concerns().named(self.repository, name)

    def status(self, name: str) -> object:
        return self.delivery.concerns().standing(self.thread(name)).status

    def told(self, party: Conversation) -> list[str]:
        return self.delivery.taken_words(party)


@pytest.fixture
def world(tmp_path: Path, clock: FakeClock) -> World:
    return World(tmp_path, clock)


def test_a_parked_thread_woken_is_reopened_by_lup_and_whoever_answers_for_it_is_told(
    world: World,
) -> None:
    worker = world.spawned("a1", "fixer")
    world.parked(
        "release", Parking(branch="build-x", why="release once (4) lands"), worker
    )
    world.parked("later", Parking(branch="other"), world.main("s1"))

    woken = asyncio.run(world.coming.landed(world.register, "dev", ["build-x"]))

    status = world.status("release")
    assert [each.name for each in woken] == ["release"]
    assert isinstance(status, Reopened)
    assert (status.by, status.why) == (Lup(), "`build-x` landed")
    assert world.told(worker) == [
        (
            "lup: @release came due: `build-x` landed. It was parked until "
            "`build-x` landing: release once (4) lands."
        )
    ]
    assert isinstance(world.status("later"), Parked)
    assert world.told(world.main("s1")) == []
    standing = asyncio.run(
        world.speaker(world.main("s1")).thread(Threading(name="release"))
    ).text
    assert standing.endswith("working; came due: `build-x` landed.")


def test_a_thread_whose_holder_ended_is_told_to_the_holder_above_as_it_comes_due(
    world: World,
) -> None:
    worker = world.spawned("a1", "fixer")
    world.parked("release", Parking(branch="build-x"), worker)
    world.delivery.inbox.placed(
        world.delivery.inbox.whereabouts[worker.key()].model_copy(
            update={"ended": world.delivery.clock.now()}
        )
    )

    asyncio.run(world.coming.landed(world.register, "dev", ["build-x"]))

    reader = Reader(delivery=world.delivery, reader=world.main("s1"))
    read = reader.read(
        world.delivery.inbox.about(world.repository), Narrowing(thread="release")
    ).text
    assert world.told(world.main("s1")) == [
        "lup: @release came due: `build-x` landed. It was parked until `build-x` landing."
    ]
    assert "held by nobody: working; came due: `build-x` landed." in read


def test_a_branch_wakes_only_where_it_lands_on_the_integration_branch(
    world: World,
) -> None:
    world.parked("release", Parking(branch="build-x"), world.main("s1"))

    elsewhere = asyncio.run(world.coming.landed(world.register, "main", ["build-x"]))
    other = asyncio.run(world.coming.landed(world.register, "dev", ["build-y"]))

    assert (elsewhere, other) == ([], [])
    assert isinstance(world.status("release"), Parked)


def test_the_sweep_wakes_a_thread_whose_time_came(
    world: World, clock: FakeClock
) -> None:
    world.parked("soon", Parking(at=clock.now() + timedelta(hours=1)), world.main("s1"))

    early = world.coming.swept()
    clock.sleep(3600)
    late = world.coming.swept()
    again = world.coming.swept()

    assert early == []
    assert [each.name for each in late] == ["soon"]
    assert again == []
    status = world.status("soon")
    assert isinstance(status, Reopened)
    assert status.why == "2026-10-01 13:00 UTC came"


def test_a_subagent_s_end_wakes_a_thread_parked_until_it_as_the_host_hears_it(
    world: World,
) -> None:
    worker = world.spawned("a1", "fixer")
    world.spawned("a2", "reviewer")
    world.parked("after-fixer", Parking(ended="fixer"), world.main("s1"))
    world.parked("after-reviewer", Parking(ended="reviewer"), world.main("s1"))

    asyncio.run(
        world.delivery.ended(
            worker,
            world.register,
            Caller(id="c2", session="s1", agent="a1", name="fixer"),
            Heard(
                fits=10_000,
                event=events.ConversationEnded(),
                session="s1",
                agent="a1",
                judged=False,
            ),
        )
    )

    status = world.status("after-fixer")
    assert isinstance(status, Reopened)
    assert status.why == "`dev/fixer` ended"
    assert isinstance(world.status("after-reviewer"), Parked)


def test_the_sweep_wakes_a_thread_parked_until_a_session_whose_launch_ended(
    world: World,
) -> None:
    other = world.launched("voice", "s2", Limits(actions=["read-issues"], protected=[]))
    world.parked("after-voice", Parking(ended="voice"), world.main("s1"))

    going = world.coming.swept()
    world.delivery.layout.record(other.launch).unlink()
    gone = world.coming.swept()

    assert going == []
    assert [each.name for each in gone] == ["after-voice"]


def test_the_sweep_wakes_a_thread_parked_until_a_condition_the_gate_found_holding(
    world: World,
) -> None:
    world.parked("ttl", Parking(when="sdk_reports_ttl"), world.main("s1"))
    world.parked("py", Parking(when="python_315"), world.main("s1"))
    due = GitDirectoryLayout(common=world.repository).due

    unkept = world.coming.swept()
    write_model(due, Due(held=["sdk_reports_ttl"]))
    held = world.coming.swept()
    due.write_text("not json")
    unread = world.coming.swept()

    assert unkept == []
    assert [each.name for each in held] == ["ttl"]
    assert unread == []
    assert world.said[-1].startswith("The gate's record of what came due in")
    assert isinstance(world.status("py"), Parked)


def test_a_push_moving_the_integration_branch_wakes_a_thread_parked_until_a_commit_in_its_history(
    world: World,
) -> None:
    root = world.repository.parent
    for arguments in [
        ["init", "-q", "-b", "dev"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
        ["config", "commit.gpgsign", "false"],
    ]:
        run("git", *arguments, cwd=root)

    def committed(name: str) -> str:
        (root / name).write_text(name)
        run("git", "add", "-A", cwd=root)
        run("git", "commit", "-q", "-m", name, cwd=root)
        return run("git", "rev-parse", "HEAD", cwd=root).text().strip()

    first = committed("a")
    second = committed("b")
    run("git", "checkout", "-q", "-b", "side", first, cwd=root)
    aside = committed("c")
    world.parked("first", Parking(commit=first[:8]), world.main("s1"))
    world.parked("aside", Parking(commit=aside), world.main("s1"))
    world.parked("odd", Parking(commit="--output=x"), world.main("s1"))

    feature = asyncio.run(
        world.coming.pushed(
            world.register, [Update(source=second, destination="refs/heads/feat")]
        )
    )
    landed = asyncio.run(
        world.coming.pushed(
            world.register, [Update(source=second, destination="refs/heads/dev")]
        )
    )

    assert feature == []
    assert [each.name for each in landed] == ["first"]
    status = world.status("first")
    assert isinstance(status, Reopened)
    assert status.why == f"commit {first[:8]} landed"
    assert isinstance(world.status("aside"), Parked)
    assert isinstance(world.status("odd"), Parked)


def test_a_commit_is_read_as_a_hash_alone() -> None:
    assert hashed("C6576E49")
    assert not hashed("HEAD")
    assert not hashed("a" * 65)


def test_an_issue_closing_is_asked_of_github_once_each_as_a_session_starts_and_at_a_landing(
    world: World,
) -> None:
    world.parked("twelve", Parking(issue=12), world.main("s1"))
    world.parked("also-twelve", Parking(issue=12, branch="never"), world.main("s1"))
    world.parked("elsewhere", Parking(issue="owner/name#13"), world.main("s1"))
    world.parked("unreachable", Parking(issue=99), world.main("s1"))
    world.parked("unreadable", Parking(issue="lup 7"), world.main("s1"))

    async def starting() -> None:
        await world.delivery.telling(
            world.register,
            Caller(id="c1", session="s1"),
            None,
            Heard(
                fits=10_000,
                event=events.SessionStarted(),
                session="s1",
                judged=False,
            ),
            10_000,
        )
        await asyncio.gather(*world.delivery.looks)

    world.delivery.starting = world.coming.started
    asyncio.run(starting())
    open_still = [world.status(each) for each in ["twelve", "also-twelve"]]
    world.closed = [12, 13]
    world.asked = []
    landed = asyncio.run(world.coming.landed(world.register, "dev", []))

    assert all(isinstance(each, Parked) for each in open_still)
    assert [each.name for each in landed] == ["twelve", "also-twelve", "elsewhere"]
    assert world.asked == ["#12", "owner/name#13", "#99"]
    assert any("issue #99 closed" in each for each in world.said)
    assert any("`lup 7` closes, which names no issue" in each for each in world.said)
    assert isinstance(world.status("unreachable"), Parked)


def test_no_issue_is_asked_where_none_waits_or_the_launch_s_limits_refuse_reading_them(
    world: World,
) -> None:
    refused = world.launched("bare", "s3", Limits(actions=[], protected=[]))
    nothing = asyncio.run(world.coming.closed(world.register))
    world.parked("twelve", Parking(issue=12), world.main("s1"))
    world.closed = [12]

    woken = asyncio.run(world.coming.closed(refused))

    assert (nothing, woken) == ([], [])
    assert world.asked == []
    assert "doesn't allow `read-issues`" in world.said[-1]


class Failing(Coming):
    """Fails at the sweep, as a ledger gone would."""

    @override
    def swept(self) -> list[Thread]:
        message = "the ledger is gone"
        raise OSError(message)


def test_each_sweep_beside_the_host_service_wakes_what_came_and_says_a_failure(
    world: World, clock: FakeClock
) -> None:
    world.parked("now", Parking(at=clock.now()), world.main("s1"))
    said: list[str] = []
    sweeping = cli.Sweeping.model_construct(coming=world.coming, say=said.append)
    failing = cli.Sweeping.model_construct(
        coming=Failing(delivery=world.delivery, integration="dev", say=said.append),
        say=said.append,
    )

    sweeping.woken()
    failing.woken()

    assert isinstance(world.status("now"), Reopened)
    assert said[0].startswith("Waking the threads parked until what came failed:")
    assert "OSError: the ledger is gone" in said[0]


def test_what_fails_waking_threads_is_said_and_the_moment_goes_on(
    world: World,
) -> None:
    world.parked("twelve", Parking(issue=12), world.main("s1"))

    async def broken(launch: Register, issue: IssueRef) -> Literal["open", "closed"]:
        message = "the inbox refused it"
        raise LupDevError(message)

    coming = world.coming.model_copy(update={"states": broken})

    asyncio.run(coming.started(world.register))
    woken = asyncio.run(coming.landed(world.register, "dev", []))

    assert woken == []
    assert world.said == [
        (
            "dev: the threads parked until what came at a session's start weren't "
            "woken: the inbox refused it"
        ),
        (
            "dev: the threads parked until what came at a landing weren't woken: "
            "the inbox refused it"
        ),
    ]
