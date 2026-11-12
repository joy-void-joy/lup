"""lup's lines told a conversation in no item, kept and shown among what they exchanged: a concern's lines and tags, what the operator did to it, and the words those lines carried them."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup.blocks import OfAgent, Span
from lup_dev import cli
from lup_dev.host.names import Names
from lup_dev.host.protocol import Limits, Register
from lup_dev.host.pushes import Pushes
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.protocol import Exchanged, ItemsListing, ListItems
from lup_dev.inbox.store import (
    HEARD,
    KINDS,
    Comment,
    Inbox,
    Left,
    Review,
    Whereabouts,
    heard,
    left_for,
)
from lup_dev.inbox.tools import Sending, Speaker, ThreadedRemark, Threading
from lup_dev.layout import Layout
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Operator

if TYPE_CHECKING:
    from conftest import FakeClock

REPOSITORY = Path("/work/lup.git")


class Silent(Notices):
    """Raises nothing."""

    @override
    async def notify(self, summary: str, body: str) -> None:
        pass


@pytest.fixture
def delivery(tmp_path: Path, clock: FakeClock) -> Delivery:
    """A delivery over an inbox under `tmp_path`, outside any service."""
    known = cli.Adapters(known=cli.adapters())
    return Delivery(
        inbox=Inbox.opened(
            Ledger.opened(LedgerLayout(home=tmp_path / "ledger"), KINDS)
        ),
        waker=cli.Wakers(adapters=known),
        pushes=Pushes(),
        layout=Layout(state=tmp_path / "state", runtime=tmp_path / "run").host,
        notices=Silent(),
        clock=clock,
        say=lambda _: None,
    )


def main(session: str, runtime: str = "claude") -> Conversation:
    return Conversation(repository=REPOSITORY, runtime=runtime, session=session)


def launched(
    delivery: Delivery, name: str, session: str, runtime: str = "claude"
) -> Register:
    """Serve a launch named `name` on `runtime`, its session `session` heard in it, its name kept for the session."""
    register = Register(
        launch=name,
        runtime=runtime,
        worktree=Path(f"/work/{name}"),
        repository=REPOSITORY,
        judge=Path("/judge/lup-dev"),
        limits=Limits(actions=[], protected=[]),
        github=None,
    )
    record = delivery.layout.record(name)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(register.model_dump_json())
    Names(path=delivery.layout.names).keep(session, name)
    delivery.heard_in(main(session, runtime), register, None)
    return register


def spawned(
    delivery: Delivery, register: Register, parent: Conversation, agent: str, name: str
) -> Conversation:
    """Hear a subagent `agent` of `parent`'s session, spawned by `parent`, named `name`."""
    party = parent.model_copy(update={"agent": agent})
    delivery.heard_in(party, register, parent, name)
    return party


def speaker(delivery: Delivery, register: Register, party: Conversation) -> Speaker:
    return Speaker(delivery=delivery, launch=register, party=party)


def said(coroutine: object) -> str:
    """Run a tool's call, and return what it says."""
    assert asyncio.iscoroutine(coroutine)
    return asyncio.run(coroutine).text


def told(delivery: Delivery, party: Conversation) -> list[str]:
    """Take what lup left for `party`, as their next call is told it."""
    return delivery.taken_words(party)


def drawer(delivery: Delivery, party: Conversation) -> Exchanged:
    """Return what `party` exchanged, as their `messages` drawer reads it from the core (`ListItems`)."""
    listed = asyncio.run(
        ItemsListing(delivery=delivery).answer(ListItems(conversation=party))
    )
    assert isinstance(listed, Exchanged)
    return listed


def spoken_as(spans: list[Span]) -> str:
    return "".join(each.text for each in spans)


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_a_passage_moved_to_an_agent_shows_in_their_messages_as_the_operator_s_words_moved_by_whom(
    delivery: Delivery, clock: FakeClock, runtime: str
) -> None:
    register = launched(delivery, "lead", "s1", runtime)
    lead = speaker(delivery, register, main("s1", runtime))
    said(lead.note(ThreadedRemark(remark="Go.")))
    [note] = delivery.inbox.items
    fixer = spawned(delivery, register, main("s1", runtime), "a1", "fixer")
    review = asyncio.run(
        delivery.posted(
            Review(
                covers=[note],
                comments=[Comment(item=note, text="Fix the cursor.")],
            ),
            Operator(),
            main("s1", runtime),
            None,
        )
    )
    clock.sleep(60)
    said(
        lead.thread(
            Threading(
                name="cursor",
                title="The cursor",
                move=[f"{review.number}.1"],
                hand="fixer",
            )
        )
    )
    clock.sleep(60)
    told(delivery, fixer)

    handed, moved = drawer(delivery, fixer).relayed
    # The operator's words, reaching the fixer as moved there by the lead.
    assert spoken_as(moved.heading) == (
        f"@{review.number}.1 you → lead/fixer · moved by lead into @cursor"
    )
    assert spoken_as(moved.line) == (
        f"← @{review.number}.1 your words, moved by lead into @cursor"
    )
    assert (moved.text, moved.lups, moved.by) == ("Fix the cursor.", False, None)
    assert moved.at == clock.now()
    # lup's own line, saying the lead handed it: lup's, never the operator's.
    assert spoken_as(handed.heading) == "lup → lead/fixer"
    assert handed.text == (
        '`lead` handed you @cursor, "The cursor": you hold it, and what you send '
        "lands there."
    )
    assert handed.lups
    # The lead's drawer holds the review, and none of what the fixer was told.
    lead_s = drawer(delivery, main("s1", runtime))
    assert [each.item.number for each in lead_s.received] == [review.number]
    assert lead_s.relayed == []


def test_the_operator_settling_a_concern_shows_in_its_holder_s_messages_as_lup_s_line(
    delivery: Delivery, clock: FakeClock
) -> None:
    register = launched(delivery, "dev", "s1")
    holder = spawned(delivery, register, main("s1"), "a1", "fixer")
    said(
        speaker(delivery, register, holder).thread(
            Threading(name="cursor", title="The cursor", hold=True)
        )
    )
    concerns = delivery.concerns()
    clock.sleep(60)
    concerns.settled(concerns.named(REPOSITORY, "cursor"))
    settled_at = clock.now()

    [waiting] = drawer(delivery, holder).relayed
    clock.sleep(60)
    told(delivery, holder)
    [settled] = drawer(delivery, holder).relayed

    assert spoken_as(waiting.heading) == "lup → dev/fixer · not told yet"
    assert waiting.at == settled_at
    assert spoken_as(settled.heading) == "lup → dev/fixer"
    assert spoken_as(settled.line) == "← from lup"
    assert (settled.text, settled.lups) == ("the operator settled @cursor.", True)
    assert settled.at == clock.now()
    # Told once: the line stays in the drawer, and nothing waits to be told.
    assert told(delivery, holder) == []


def test_an_item_told_whole_to_a_thread_s_holder_shows_in_their_messages_as_its_writer_s(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    lead = speaker(delivery, register, main("s1"))
    said(lead.note(ThreadedRemark(remark="Go.")))
    holder = spawned(delivery, register, main("s1"), "a1", "fixer")
    reviewer = spawned(delivery, register, main("s1"), "a2", "reviewer")
    said(
        speaker(delivery, register, holder).thread(
            Threading(name="lag", title="The cursor jumps", hold=True)
        )
    )
    said(
        speaker(delivery, register, reviewer).note(
            ThreadedRemark(remark="Seen it twice.", thread="lag")
        )
    )
    said(
        lead.send(
            Sending(
                to="operator", kind="note", text="Typing fast moves it.", thread="lag"
            )
        )
    )
    landed = max(delivery.inbox.items)

    to_holder = drawer(delivery, holder).relayed[-1]
    [to_reviewer] = drawer(delivery, reviewer).relayed

    assert spoken_as(to_holder.heading) == (
        f"@{landed} dev → dev/fixer · note · landed in @lag · not told yet"
    )
    assert spoken_as(to_holder.line) == (
        f"← @{landed} note from dev, landed in @lag · not told yet"
    )
    assert to_holder.text == "Typing fast moves it."
    assert to_holder.by == OfAgent(runtime="claude", session="s1")
    assert not to_holder.lups
    # Others on the thread got a line: lup's.
    assert to_reviewer.lups
    assert to_reviewer.text == (
        f"in @lag, a note from `dev`, @{landed}: Typing fast moves it."
    )


def test_lup_s_lines_are_records_of_their_own_an_older_lup_reading_whereabouts_never_meets(
    delivery: Delivery,
) -> None:
    register = launched(delivery, "dev", "s1")
    holder = spawned(delivery, register, main("s1"), "a1", "fixer")
    said(
        speaker(delivery, register, holder).thread(
            Threading(name="cursor", title="The cursor", hold=True)
        )
    )
    concerns = delivery.concerns()
    concerns.settled(concerns.named(REPOSITORY, "cursor"))
    told(delivery, holder)
    concerns.reopened(concerns.named(REPOSITORY, "cursor"), "")

    ledger = delivery.inbox.ledger
    # What every lup reads its whereabouts by holds them alone, as an older one reads them.
    places = ledger.plains(HEARD, Whereabouts)
    assert sorted(places) == sorted(heard(each) for each in delivery.inbox.whereabouts)
    assert places[heard(holder.key())].words == ["lup: the operator reopened @cursor."]
    # Opened again, as after a restart, the lines read from their own records.
    again = Inbox.opened(ledger)
    lines = again.lines_of(holder)
    assert [(each.number, each.text, each.told is None) for each in lines] == [
        (1, "lup: the operator settled @cursor.", False),
        (2, "lup: the operator reopened @cursor.", True),
    ]
    assert [*ledger.plains(left_for(holder.key()), Left)] == [
        left_for(holder.key(), 1),
        left_for(holder.key(), 2),
    ]
    assert not left_for(holder.key()).startswith(HEARD)
