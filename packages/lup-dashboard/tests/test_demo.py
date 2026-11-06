"""The stand-in demo over the host's own handlers: what it shows, each of its stand-ins answered as the host answers it, and what comes to it later."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import override

import pytest

from lup_dashboard.demo import FIX_CLOCK, Demo
from lup_dev.clock import Clock
from lup_dev.host.protocol import Listed, ListLaunches, Refused
from lup_dev.inbox.protocol import (
    Context,
    Conversed,
    Files,
    Items,
    ListInbox,
    SendItem,
    ShowContext,
    ShowConversation,
    ShowFiles,
)
from lup_dev.inbox.store import Decided, Waiting
from lup_dev.inbox.threaded import ListThreads, ThreadRead, ThreadsRead
from lup_dev.policy.since import (
    ReviewSince,
    ShowSince,
    Since,
    SinceReviewed,
    ViewedFile,
)
from lup_dev.policy.waits import LandingsWaiting, ShowLandings
from lup_dev.switching import CopiesListed, CopySwitching, ListCopies, SwitchCopy
from lup_ledger.parties import Conversation

LUP = Path("/home/op/lup.git")
PARSER = Conversation(repository=LUP, runtime="claude", session="s1", agent="a02")
CLOCK = PARSER.model_copy(update={"agent": FIX_CLOCK})


class Fixed(Clock):
    """A clock at one moment."""

    @override
    def now(self) -> datetime:
        return datetime(2026, 10, 1, 12, tzinfo=UTC)

    @override
    def sleep(self, seconds: float) -> None:
        del seconds


def threads(demo: Demo) -> dict[str, ThreadRead]:
    """Return each thread as the review reads it, by its name."""
    listed = asyncio.run(demo.ask(ListThreads()))
    assert isinstance(listed, ThreadsRead)
    return {each.thread.name: each for each in listed.threads}


def since(demo: Demo, conversation: Conversation) -> Since:
    """Return what `conversation`'s branches changed, as their drawer shows it."""
    shown = asyncio.run(demo.ask(ShowSince(conversation=conversation)))
    assert isinstance(shown, Since)
    return shown


def test_the_demo_lists_its_launches_as_the_host_lists_those_it_serves() -> None:
    listed = asyncio.run(Demo(clock=Fixed(), size=0).ask(ListLaunches()))

    assert isinstance(listed, Listed)
    assert [each.name for each in listed.launches] == [
        "lup-impl",
        "guidance-voice",
        "main",
        "magpie-search",
    ]
    assert [each.path for each in listed.talkers["a1f0"]] == [
        "lup-impl",
        "lup-impl/explore-auth",
        "lup-impl/parser",
        "lup-impl/parser/grep-tokens",
        "lup-impl/survey-legacy",
        "lup-impl/probe-meta",
        "lup-impl/nest-probe",
        "lup-impl/fix-clock",
    ]
    assert [each.path for each in listed.talkers["c3d2"]] == [
        "main",
        "main/render_frames",
    ]
    assert listed.talkers["d4c3"] == []
    assert listed.sessions == {
        "s1": "lup-impl",
        "s2": "guidance-voice",
        "s3": "main",
    }


def test_a_message_to_a_launch_whose_session_hasnt_started_is_refused_as_the_host_refuses_it() -> (
    None
):
    answered = asyncio.run(
        Demo(clock=Fixed(), size=0).ask(SendItem(launch="d4c3", text="Hello?"))
    )

    assert isinstance(answered, Refused)
    assert "no session of launch `d4c3` has reached lup" in answered.error


@pytest.mark.parametrize("size", [0, 6])
def test_each_item_an_agent_s_call_made_has_its_moment_read_from_their_record(
    size: int,
) -> None:
    demo = Demo(clock=Fixed(), size=size)
    asyncio.run(demo.ask(ListInbox()))
    made = [each for each in demo.host.inbox.items.values() if each.call is not None]

    assert made
    for item in made:
        moment = asyncio.run(demo.ask(ShowContext(number=item.number)))
        assert isinstance(moment, Context), item.number
        anchored = moment.entries[moment.anchor]
        assert getattr(anchored, "id", None) == item.call


def test_an_item_no_call_made_has_no_moment_as_the_host_says() -> None:
    answered = asyncio.run(Demo(clock=Fixed(), size=0).ask(ShowContext(number=54)))

    assert answered == Refused(error="@54 was made by no agent's call")


def test_each_change_keeps_its_files_on_the_ledger_as_the_host_keeps_them() -> None:
    demo = Demo(clock=Fixed())
    for number in [54, 55, 59, 60, 68, 69, demo.first_worked + 2 * demo.workers]:
        shown = asyncio.run(demo.ask(ShowFiles(number=number)))
        assert isinstance(shown, Files), number
        assert shown.files, number
    note = asyncio.run(demo.ask(ShowFiles(number=52)))
    assert isinstance(note, Refused)
    assert "which changes no file" in note.error


def test_the_parser_s_conversation_grows_each_time_it_s_read() -> None:
    demo = Demo(clock=Fixed(), size=0)
    asked = ShowConversation(runtime="claude", session="s1", agent="a02")

    first = asyncio.run(demo.ask(asked))
    second = asyncio.run(demo.ask(asked))

    assert isinstance(first, Conversed)
    assert isinstance(second, Conversed)
    assert second.total == first.total + 1
    assert first.tasks


def test_the_late_question_arrives_as_the_page_first_asks_for_the_inbox_in_the_thread_its_asker_works_in() -> (
    None
):
    demo = Demo(clock=Fixed(), size=0, arrives=timedelta(0))

    async def arriving() -> tuple[Items, Items]:
        before = await demo.ask(ListInbox())
        assert isinstance(before, Items)
        for _ in range(100):
            if 61 in demo.host.inbox.items:
                break
            await asyncio.sleep(0)
        after = await demo.ask(ListInbox())
        assert isinstance(after, Items)
        return before, after

    before, after = asyncio.run(arriving())

    assert 61 not in [each.number for each in before.items]
    assert 61 in [each.number for each in after.items]
    assert [each.node for each in threads(demo)["transcript-reader"].asks] == [
        51,
        311,
        61,
    ]
    moment = asyncio.run(demo.ask(ShowContext(number=61)))
    assert isinstance(moment, Context)


def test_the_two_writes_come_to_the_parser_s_branch_the_flag_on_each_waiting() -> None:
    demo = Demo(clock=Fixed(), size=0)
    asyncio.run(demo.ask(ListInbox()))
    before = since(demo, PARSER)

    demo.wrote()

    after = since(demo, PARSER)
    assert after.version != before.version
    [was] = before.places
    [now] = after.places
    assert [each.flags for each in was.files] == [[59], []]
    assert [each.flags for each in now.files] == [[59], [], [60]]


def held_file(demo: Demo) -> ViewedFile:
    """Return the file the stand-in landing waits on, as the fix-clock subagent's drawer shows it, held there."""
    [first, _] = since(demo, CLOCK).places
    [file] = first.files
    assert file.held is not None
    assert file.flags == [68]
    return ViewedFile(path=file.path, version=file.version)


def test_the_landing_waits_on_its_file_until_it_s_marked_reviewed_which_approves_its_flag() -> (
    None
):
    demo = Demo(clock=Fixed(), size=0, lands=timedelta(hours=1))
    asyncio.run(demo.ask(ListInbox()))
    file = held_file(demo)
    waiting = asyncio.run(demo.ask(ShowLandings()))
    assert isinstance(waiting, LandingsWaiting)
    assert [each.named for each in waiting.waiting] == ["`fix-clock` on `dev`"]
    listed = asyncio.run(demo.ask(ListInbox()))
    assert isinstance(listed, Items)
    # What the host's listing says of a flag a landing waits on, from what the host holds of it.
    assert listed.landings == {68: "`fix-clock` on `dev`"}

    reviewed = asyncio.run(
        demo.ask(ReviewSince(conversation=CLOCK, branch="fix-clock", files=[file]))
    )

    assert isinstance(reviewed, SinceReviewed)
    assert reviewed.approved == [68]
    state = demo.host.inbox.item(68).state
    assert isinstance(state, Decided)
    assert state.approved
    demo.landed()
    done = asyncio.run(demo.ask(ShowLandings()))
    assert isinstance(done, LandingsWaiting)
    assert done.waiting == []
    [first, _] = since(demo, CLOCK).places
    [settled] = first.files
    assert settled.held is None
    assert settled.reviewed is not None


def test_a_declined_landing_says_so_in_its_file_its_flag_left_waiting_until_it_s_done_waiting() -> (
    None
):
    demo = Demo(clock=Fixed(), size=0, lands=timedelta(hours=1))
    asyncio.run(demo.ask(ListInbox()))
    file = held_file(demo)

    reviewed = asyncio.run(
        demo.ask(
            ReviewSince(
                conversation=CLOCK, branch="fix-clock", files=[file], decline=True
            )
        )
    )

    assert isinstance(reviewed, SinceReviewed)
    assert reviewed.approved == []
    assert reviewed.declined == [file.path]
    assert isinstance(demo.host.inbox.item(68).state, Waiting)
    [first, _] = since(demo, CLOCK).places
    [declined] = first.files
    assert declined.held is not None
    assert declined.held.declined
    demo.landed()
    [after, _] = since(demo, CLOCK).places
    assert after.files[0].held is None


def test_a_hook_call_changes_what_a_worker_does_and_comes_again() -> None:
    demo = Demo(clock=Fixed(), hooks=60)

    async def hooked() -> tuple[Listed, Listed]:
        first = await demo.ask(ListLaunches())
        assert isinstance(first, Listed)
        assert demo.hooking is not None
        demo.hook()
        second = await demo.ask(ListLaunches())
        assert isinstance(second, Listed)
        assert demo.hooking is not None
        demo.hooking.cancel()
        return first, second

    first, second = asyncio.run(hooked())

    assert demo.hooked == 1
    assert first.talkers["a1f0"] != second.talkers["a1f0"]


def test_the_demo_keeps_copies_and_switches_between_them_moving_nothing_else() -> None:
    demo = Demo(clock=Fixed())
    listed = asyncio.run(demo.ask(ListCopies()))
    assert isinstance(listed, CopiesListed)
    [running, before, never] = listed.copies
    assert running.running
    assert not before.running
    assert never.answered is None
    assert listed.last is None
    switching = asyncio.run(demo.ask(SwitchCopy(commit=before.commit)))
    assert isinstance(switching, CopySwitching)
    assert switching.commit == before.commit
    after = asyncio.run(demo.ask(ListCopies()))
    assert isinstance(after, CopiesListed)
    assert {each.commit: each.running for each in after.copies} == {
        running.commit: False,
        before.commit: True,
        never.commit: False,
    }
    assert after.last is not None
    assert after.last.answered
    assert demo.host.withheld.switched == [before.commit]


def test_the_demo_refuses_a_switch_as_the_host_does() -> None:
    demo = Demo(clock=Fixed())
    listed = asyncio.run(demo.ask(ListCopies()))
    assert isinstance(listed, CopiesListed)
    running = next(each for each in listed.copies if each.running)
    already = asyncio.run(demo.ask(SwitchCopy(commit=running.commit)))
    assert isinstance(already, Refused)
    assert "already" in already.error
    unknown = asyncio.run(demo.ask(SwitchCopy(commit="none")))
    assert isinstance(unknown, Refused)
    assert "no copy kept" in unknown.error
    assert demo.host.withheld.switched == []
