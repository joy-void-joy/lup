"""What the host offers on each item, and what sending a draft does with what no longer waits, over the demo's own state through the server, as the page asks it (`lup_dashboard/handled.py`)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from fastapi.testclient import TestClient

from lup_dashboard.demo import Demo
from lup_dashboard.server import Access, application
from lup_dev.clock import Clock
from lup_dev.inbox.protocol import Items, ListInbox, Listing, Reviewed
from lup_dev.inbox.store import (
    Answered,
    Approval,
    Decided,
    Done,
    Item,
    Superseded,
)

if TYPE_CHECKING:
    from pydantic import JsonValue

TOKEN = "a token"

LUP = Path("/home/op/lup.git")

APPROVAL = 54
"""The demo's approval of a host zone."""

QUESTION = 51
"""The demo's question from the parser subagent."""

NOTE = 52
"""The demo's note from the voice session."""

HELD = 55
"""The demo's held change."""


class Fixed(Clock):
    """A clock at one moment."""

    @override
    def now(self) -> datetime:
        return datetime(2026, 10, 1, 12, tzinfo=UTC)

    @override
    def sleep(self, seconds: float) -> None:
        del seconds


class Served:
    """The demo over the server the page talks to, a fresh state for each test."""

    def __init__(self, tmp_path: Path) -> None:
        page = tmp_path / "page"
        page.mkdir()
        (page / "index.html").write_text("<!doctype html><title>lup</title>")
        self.demo = Demo(clock=Fixed(), size=0)
        self.client = TestClient(
            application(self.demo, Access(token=TOKEN, port=8766), page),
            base_url="http://127.0.0.1:8766",
        )

    def asked(self, request: dict[str, JsonValue]) -> JsonValue:
        """Ask what the page asks, and return what it's answered."""
        answer = self.client.post(
            "/api/ask", json=request, headers={"Authorization": f"Bearer {TOKEN}"}
        )
        answer.raise_for_status()
        return answer.json()

    def drafted(self, draft: dict[str, JsonValue]) -> None:
        """Keep `draft`, as the page keeps it as it's written."""
        self.asked({"kind": "inbox-keep-draft", "draft": draft})

    def sent(self) -> Reviewed:
        """Send the draft kept, as Ctrl+Enter does."""
        return Reviewed.model_validate(self.asked({"kind": "inbox-send-draft"}))

    def item(self, number: int) -> Item:
        """Return item `number` as it stands."""
        return self.demo.host.inbox.item(number)

    def superseded(self, number: int) -> int:
        """Ask a later approval of the same repository, which supersedes approval `number`, and return its number."""
        was = self.item(number).reason
        assert isinstance(was, Approval)
        later = Approval(
            text="Approve the host zone of lup at the tip?",
            summary="",
            repository=was.repository,
            fingerprint="later",
        )
        made = asyncio.run(
            self.demo.host.delivery.asked(later, "", [], LUP / "tree" / "dev")
        )
        assert isinstance(self.item(number).state, Superseded)
        return made.number


@pytest.fixture
def served(tmp_path: Path) -> Served:
    return Served(tmp_path)


def said(reply: Reviewed) -> list[tuple[int, str, str]]:
    """Return what the reply set aside: on what, what it was, and what's said."""
    return [(each.number, each.part, each.said) for each in reply.unanswerable]


def test_a_mark_on_an_approval_superseded_since_is_dropped_and_said_and_nothing_is_installed(
    served: Served,
) -> None:
    served.drafted({"done": [APPROVAL]})
    later = served.superseded(APPROVAL)

    reply = served.sent()

    assert reply.approved == []
    assert said(reply) == [
        (APPROVAL, "done", f"@{APPROVAL} superseded by @{later}, not approved")
    ]
    assert served.demo.host.withheld.settled == []
    assert served.demo.host.inbox.draft().done == []


def test_declining_an_approval_superseded_since_is_dropped_and_said(
    served: Served,
) -> None:
    served.drafted({"declined": [APPROVAL]})
    later = served.superseded(APPROVAL)

    reply = served.sent()

    assert reply.declined == []
    assert said(reply) == [
        (APPROVAL, "declined", f"@{APPROVAL} superseded by @{later}, not declined")
    ]


def test_a_comment_on_a_held_change_declined_since_stays_its_answer_and_reaches_its_agent(
    served: Served,
) -> None:
    served.asked({"kind": "inbox-answer-approval", "number": HELD, "approved": False})
    served.drafted(
        {"comments": [{"item": HELD, "text": "And keep the file as it was."}]}
    )

    reply = served.sent()

    assert reply.approved == []
    assert reply.declined == []
    state = served.item(HELD).state
    assert isinstance(state, Decided)
    assert not state.approved
    # The comment isn't lost: it goes as a message, quoting what it's on.
    [review] = reply.items
    assert review.recipient == served.item(HELD).sender
    [(number, part, words)] = said(reply)
    assert (number, part) == (HELD, "comment")
    assert "declined" in words


def test_space_d_on_a_question_answered_since_makes_no_review_and_leaves_its_answer(
    served: Served,
) -> None:
    served.asked(
        {
            "kind": "inbox-answer",
            "number": QUESTION,
            "rulings": [
                {"decision": 1, "verdict": "leaning"},
                {"decision": 2, "verdict": "leaning"},
            ],
        }
    )
    answered = served.item(QUESTION).state
    assert isinstance(answered, Answered)
    served.drafted({"done": [QUESTION]})

    reply = served.sent()

    assert reply.items == []
    assert served.item(QUESTION).state == answered
    [(number, part, words)] = said(reply)
    assert (number, part) == (QUESTION, "done")
    assert words.startswith(f"@{QUESTION} not marked done: it's answered at ")


def test_a_comment_on_a_note_read_since_reaches_its_sender_and_leaves_it_as_it_stands(
    served: Served,
) -> None:
    served.drafted({"done": [NOTE]})
    served.sent()
    read = served.item(NOTE).state
    assert isinstance(read, Done)
    served.drafted({"comments": [{"item": NOTE, "text": "One more thing."}]})

    reply = served.sent()

    [review] = reply.items
    assert review.recipient == served.item(NOTE).sender
    assert served.item(NOTE).state == read
    assert said(reply) == []


def test_an_approval_answered_before_isn_t_installed_again_by_answering_it_again(
    served: Served,
) -> None:
    served.asked(
        {"kind": "inbox-answer-approval", "number": APPROVAL, "approved": False}
    )
    served.asked(
        {"kind": "inbox-answer-approval", "number": APPROVAL, "approved": True}
    )

    state = served.item(APPROVAL).state
    assert isinstance(state, Decided)
    assert not state.approved
    assert served.demo.host.withheld.settled == []


def test_what_s_left_for_later_and_no_longer_waits_clears_as_the_draft_is_sent_saying_nothing(
    served: Served,
) -> None:
    served.asked({"kind": "inbox-answer-approval", "number": HELD, "approved": True})
    served.drafted({"parked": [HELD], "done": [NOTE]})

    reply = served.sent()

    assert said(reply) == []
    assert served.demo.host.inbox.draft().parked == []


def test_every_answer_the_demo_offers_is_taken_and_leaves_what_it_answered_offering_none(
    served: Served,
) -> None:
    """A key is offered only where it does what it says: every mark an item offers, sent together, is applied with nothing set aside, and each then offers nothing but a comment, a mark left on it dropped and said."""
    items = served.demo.host.inbox.items
    offered = [
        (each.number, offer.argument["list"])
        for each in items.values()
        for offer in each.offers
        if offer.action == "inbox-mark"
    ]
    done = [number for number, listed in offered if listed == "done"]
    assert len(done) > 10
    # Each has `done` and `parked` on offer, one declined too: done, for all of them.
    served.drafted({"done": list(done)})

    reply = served.sent()

    assert said(reply) == []
    for number in done:
        item = served.item(number)
        assert not item.asks, number
        assert [each.verb for each in item.offers] == ["comment"], number
    # Sent again as a stale page would, nothing is made, nothing answered again, and each is said.
    made = max(served.demo.host.inbox.items)
    standing = {each: served.item(each).state for each in done}
    served.drafted({"done": list(done)})

    again = served.sent()

    assert sorted(number for number, _, _ in said(again)) == sorted(done)
    assert again.items == []
    assert again.approved == []
    assert max(served.demo.host.inbox.items) == made
    assert {each: served.item(each).state for each in done} == standing


def test_what_s_said_before_the_send_is_what_the_send_says(served: Served) -> None:
    served.drafted(
        {
            "done": [APPROVAL],
            "comments": [{"item": HELD, "text": "And keep the file as it was."}],
        }
    )
    served.asked({"kind": "inbox-answer-approval", "number": HELD, "approved": False})
    later = served.superseded(APPROVAL)

    listed = Items.model_validate(served.asked({"kind": "inbox-list"}))

    assert [each.number for each in listed.past] == [APPROVAL, HELD]
    assert later in [each.number for each in listed.items]
    assert APPROVAL not in [each.number for each in listed.items]
    assert listed.set_aside == served.sent().unanswerable


def test_a_room_s_listing_says_nothing_of_the_operator_s_draft(served: Served) -> None:
    served.drafted({"done": [APPROVAL]})
    served.superseded(APPROVAL)

    listing = Listing(delivery=served.demo.host.delivery)
    scoped = asyncio.run(listing.scoped(ListInbox(), LUP))

    assert isinstance(scoped, Items)
    assert scoped.past == []
    assert scoped.set_aside == []
