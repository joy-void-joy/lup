"""The stand-in demo over the host's own handlers: what it shows, each of its stand-ins answered as the host answers it, and what comes to it later."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup_dashboard.demo import FIX_CLOCK, ON_DEV, Demo
from lup_dev.clock import Clock
from lup_dev.host.on_trial import CopySwitching, SwitchCopy
from lup_dev.host.protocol import Listed, ListLaunches, Refused
from lup_dev.host.workers import Acted, Acting, ActionAnswer, Viewed, Viewing
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
from lup_dev.switching import CopiesListed, ListCopies
from lup_ledger.parties import Conversation

LUP = Path("/home/op/lup.git")
PARSER = Conversation(repository=LUP, runtime="claude", session="s1", agent="a02")
CLOCK = PARSER.model_copy(update={"agent": FIX_CLOCK})

if TYPE_CHECKING:
    from pydantic import JsonValue


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
    # The docs session's name outlives their launch, as the host keeps it.
    assert listed.sessions == {
        "s1": "lup-impl",
        "s2": "guidance-voice",
        "s3": "main",
        "s4": "docs-pass",
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
    assert [each.node for each in threads(demo)["transcript-reader"].asks] == [51, 61]
    moment = asyncio.run(demo.ask(ShowContext(number=61)))
    assert isinstance(moment, Context)


def test_a_script_driving_the_demo_brings_the_late_question_once() -> None:
    said: list[str] = []
    demo = Demo(clock=Fixed(), size=0, say=said.append)
    asyncio.run(demo.ask(ListInbox()))
    assert 61 not in demo.host.inbox.items

    demo.told("arrive\n")
    demo.told("arrive\n")
    demo.told("land\n")

    assert [each.node for each in threads(demo)["transcript-reader"].asks] == [
        51,
        311,
        61,
    ]
    assert said == [
        "`land` names nothing a stand-in agent does: `arrive` brings the late question"
    ]


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


def what_runs(demo: Demo) -> str:
    """Return what the demo's `Versions` says runs, in its text form."""
    viewing = Viewing(
        repository=demo.lup_session().repository,
        module="versions",
        view="what_runs",
        argument={},
    )
    viewed = asyncio.run(demo.ask(viewing))
    assert isinstance(viewed, Viewed)
    return viewed.blocks.text()


def act(demo: Demo, action: str, *arguments: JsonValue) -> list[ActionAnswer]:
    """Run one of the demo's `Versions`' actions, as Ctrl+Enter does, and return what came of each mark."""
    acting = Acting(
        repository=demo.lup_session().repository,
        module="versions",
        action=action,
        arguments=list(arguments),
    )
    acted = asyncio.run(demo.ask(acting))
    assert isinstance(acted, Acted)
    return acted.answers


def test_the_demo_lists_what_s_on_trial_by_the_host_s_own_listing() -> None:
    said = what_runs(Demo(clock=Fixed(), size=0)).splitlines()
    assert said[0] == "what runs · dev + clearer-marks steady-list"
    assert said[1].startswith("[x] steady-list ")
    assert said[3].startswith("[ ] rival-marks    conflicts with `clearer-marks`")
    assert said[4] == "▸ out · 1"
    assert any(
        each.startswith(" *  dev d38dbd2 + clearer-marks steady-list") for each in said
    )


def test_a_set_with_a_copy_kept_moves_the_host_there_and_nothing_else() -> None:
    demo = Demo(clock=Fixed(), size=0)
    # Leaving rival out too, as what `clearer-marks` keeps out would come in otherwise.
    answers = act(
        demo,
        "pick",
        {"branch": "clearer-marks", "on": False},
        {"branch": "rival-marks", "on": False},
    )
    assert answers[0].said == "The host moves to 1c0ffee, in a few seconds."
    assert demo.host.withheld.switched == ["1c0ffee"]
    said = what_runs(demo).splitlines()
    assert said[0] == "what runs · dev + steady-list"
    assert [each for each in said if each.startswith(" *")] == [
        " *  dev d38dbd2 + steady-list                running"
    ]


def test_ticking_one_box_leaves_the_rest_as_they_stand() -> None:
    demo = Demo(clock=Fixed(), size=0)
    act(demo, "pick", {"branch": "steady-list", "on": False})
    # Nobody took the rival out, and nothing lets it in yet: it isn't said to be out by them.
    said = what_runs(demo)
    assert "[ ] rival-marks    conflicts with" in said
    assert "out · 2" in said


def test_taking_out_what_keeps_a_rival_out_lets_it_in() -> None:
    demo = Demo(clock=Fixed(), size=0)
    [came] = act(demo, "pick", {"branch": "clearer-marks", "on": False})
    assert "waits on your yes" in came.said
    assert "[x] rival-marks" in what_runs(demo)
    assert demo.host.withheld.switched == []


def test_a_set_never_run_asks_its_yes_moving_nothing_the_host_runs() -> None:
    demo = Demo(clock=Fixed(), size=0)
    [came] = act(demo, "pick", {"branch": "quiet-banner", "on": True})
    assert "it waits on your yes: @54 in your inbox" in came.said
    assert demo.host.withheld.switched == []
    said = what_runs(demo).splitlines()
    assert "dev + clearer-marks quiet-banner steady-list waits on your yes" in said[0]
    assert said[0].startswith("what runs · dev + clearer-marks steady-list ·")


def test_every_box_of_a_send_is_one_pick_and_one_switch_at_most() -> None:
    demo = Demo(clock=Fixed(), size=0)
    answers = act(
        demo,
        "pick",
        {"branch": "clearer-marks", "on": False},
        {"branch": "steady-list", "on": False},
        {"branch": "rival-marks", "on": False},
    )
    assert [each.refused for each in answers] == [None, None, None]
    assert demo.host.withheld.switched == ["2c0ffee"]


def test_two_that_conflict_aren_t_taken_in_together_as_the_host_says() -> None:
    demo = Demo(clock=Fixed(), size=0)
    [came] = act(demo, "pick", {"branch": "rival-marks", "on": True})
    assert came.refused is not None
    assert "can't be picked together" in came.refused
    assert "Nothing moved" in came.refused
    assert demo.host.withheld.switched == []
    [one, _] = act(
        demo,
        "pick",
        {"branch": "rival-marks", "on": True},
        {"branch": "clearer-marks", "on": False},
    )
    assert one.refused is None
    assert "waits on your yes" in what_runs(demo).splitlines()[0]


async def merged(demo: Demo, branch: str) -> ActionAnswer:
    """Ask a branch merged, as Ctrl+Enter does, and wait for what runs apart on this loop to finish."""
    acting = Acting(
        repository=demo.lup_session().repository,
        module="versions",
        action="merge",
        arguments=[{"branches": [branch]}],
    )
    acted = await demo.ask(acting)
    assert isinstance(acted, Acted)
    this = asyncio.current_task()
    await asyncio.gather(*[each for each in asyncio.all_tasks() if each is not this])
    [answer] = acted.answers
    return answer


def test_a_branch_merged_is_off_trial_and_what_runs_doesn_t_restart() -> None:
    demo = Demo(clock=Fixed(), size=0, merge_takes=timedelta(0))
    [came] = [asyncio.run(merged(demo, "steady-list"))]
    assert "`steady-list` is merging" in came.said
    assert demo.host.withheld.switched == []
    said = what_runs(demo)
    assert "Landed `steady-list` on `dev`" in said
    assert "[x] steady-list" not in said


def test_a_merge_follows_dev_twice_keeping_the_zone_of_what_runs() -> None:
    demo = Demo(clock=Fixed(), size=0, merge_takes=timedelta(0))
    asyncio.run(merged(demo, "steady-list"))
    # `dev` now holds `steady-list`, so `dev` + `clearer-marks` is what ran, and nobody's asked.
    first = what_runs(demo).splitlines()[0]
    assert first == "what runs · dev + clearer-marks"


def test_a_merge_the_gate_stops_stays_on_trial_saying_why() -> None:
    demo = Demo(clock=Fixed(), size=0, merge_takes=timedelta(0))
    asyncio.run(merged(demo, "rival-marks"))
    said = what_runs(demo)
    assert "Not landed: the gate failed on the merge of `rival-marks`" in said
    assert "rival-marks" in said


def test_a_version_on_dev_as_it_stands_runs_again_its_boxes_with_it() -> None:
    demo = Demo(clock=Fixed(), size=0)
    [came] = act(
        demo,
        "run_again",
        {
            "commit": "1c0ffee",
            "current": True,
            "branches": ["steady-list"],
            "tips": ["steady-list-tip"],
            "dev": ON_DEV,
        },
    )
    assert came.said == "The host moves to 1c0ffee, in a few seconds."
    assert demo.host.withheld.switched == ["1c0ffee"]
    said = what_runs(demo)
    assert "[x] steady-list" in said
    assert "[x] clearer-marks" not in said


def test_an_older_version_runs_again_by_the_host_s_own_switch_saying_what_live_holds() -> (
    None
):
    demo = Demo(clock=Fixed(), size=0)
    [came] = act(demo, "run_again", {"commit": "1c0ffee"})
    assert came.said == "The host moves to 1c0ffee, in a few seconds."
    assert demo.host.withheld.switched == ["1c0ffee"]
    assert what_runs(demo).splitlines()[0] == (
        "what runs · dev + steady-list · live holds dev + clearer-marks steady-list"
    )


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
