"""The dashboard's server, on a stand-in host: its API relaying requests and streaming their replies, and who may call it."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue, TypeAdapter

from lup.blocks import Fold, Load, OfAgent
from lup_dashboard.demo import Demo, files
from lup_dashboard.host import Host
from lup_dashboard.server import Access, application
from lup_dev.clock import Clock
from lup_dev.host.protocol import HostError, Listed, ListLaunches, Refused
from lup_dev.host.records import Called
from lup_dev.host.timings import TimingsStore
from lup_dev.host.workers import Viewed, Viewing
from lup_dev.inbox.protocol import (
    AnswerCheck,
    CheckShown,
    Conversed,
    Files,
    Items,
    ListInbox,
    ListItems,
    Reviewed,
    SendItem,
    Settled,
    ShowConversation,
)
from lup_dev.inbox.store import Approval, Decided, Item, Message, Text
from lup_dev.inbox.threaded import (
    ListThreads,
    MovedIntoThread,
    MoveIntoThread,
    SettleThread,
    ShowThread,
    ThreadRead,
    ThreadShown,
    ThreadsRead,
    ThreadStated,
)
from lup_ledger.parties import Conversation, Operator

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from lup_dashboard.api import Asked, Replied


class StandIn(Host):
    """Answers each request from what it was given, recording each asked."""

    def __init__(
        self,
        answers: dict[str, list[Replied]],
        *,
        reachable: bool = True,
        lasting: bool = False,
    ) -> None:
        self.answers = answers
        self.reachable = reachable
        self.lasting = lasting
        """Whether a watch, its replies given, waits for a change that never comes, as the host's do, rather than ending."""
        self.asked: list[Asked] = []
        self.settled: list[int] = []

    @override
    async def ask(self, request: Asked) -> Replied:
        self.asked.append(request)
        if not self.reachable:
            message = "no host service answers on control.sock"
            raise HostError(message)
        [first, *_] = self.answers[request.kind]
        return first

    @override
    async def watch(self, request: Asked) -> AsyncGenerator[Replied]:
        self.asked.append(request)
        if not self.reachable:
            message = "no host service answers on watch.sock"
            raise HostError(message)
        for replied in self.answers[request.kind]:
            yield replied
        if self.lasting:
            await asyncio.Event().wait()

    @override
    async def settle(self, number: int) -> None:
        self.settled.append(number)


GIVEN = "stand-in"

SOCKET = "ws://127.0.0.1:8766/api/socket"
"""The page's socket, by the address it's served at: another host name is refused."""


@pytest.fixture
def page(tmp_path: Path) -> Path:
    built = tmp_path / "page"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html><title>lup</title>")
    return built


def client(host: Host, page: Path) -> TestClient:
    app = application(host, Access(token=GIVEN, port=8766), page)
    return TestClient(app, base_url="http://127.0.0.1:8766")


def bearing() -> dict[str, str]:
    return {"Authorization": f"Bearer {GIVEN}"}


def test_ask_relays_a_request_to_the_host_and_returns_its_reply(page: Path) -> None:
    host = StandIn({"list": [Listed(launches=[])]})
    response = client(host, page).post(
        "/api/ask", json=ListLaunches().model_dump(), headers=bearing()
    )
    assert response.status_code == 200
    assert response.json() == {
        "kind": "listed",
        "launches": [],
        "sessions": {},
        "talkers": {},
        "running": None,
        "looks": {},
        "standing": {
            "folds": [],
            "tones": [],
            "drawers": [],
            "banners": [],
            "verbs": [],
        },
    }
    assert host.asked == [ListLaunches()]


def test_a_refusal_is_a_reply_like_any_other(page: Path) -> None:
    host = StandIn({"inbox-show": [Refused(error="no item 9")]})
    response = client(host, page).post(
        "/api/ask", json={"kind": "inbox-show", "number": 9}, headers=bearing()
    )
    assert response.json() == {"kind": "refused", "error": "no item 9"}


def watched(number: int, request: Asked) -> JsonValue:
    """The page's frame starting watch `number` of `request`."""
    return {"kind": "watch", "number": number, "request": request.model_dump()}


def test_the_socket_sends_a_watchs_replies_under_its_number_then_its_end(
    page: Path,
) -> None:
    host = StandIn({"inbox-list": [Items(items=[]), Refused(error="stopped")]})
    with client(host, page).websocket_connect(SOCKET, headers=bearing()) as socket:
        socket.send_json(watched(7, ListInbox()))
        frames = [socket.receive_json() for _ in range(3)]
    assert frames == [
        {
            "kind": "watched",
            "number": 7,
            "reply": {
                "kind": "inbox-items",
                "items": [],
                "seen": [],
                "answers": [],
                "commented": [],
                "paths": [],
                "landings": {},
            },
        },
        {
            "kind": "watched",
            "number": 7,
            "reply": {"kind": "refused", "error": "stopped"},
        },
        {"kind": "ended", "number": 7, "why": "the host service closed the watch"},
    ]


def test_one_socket_carries_every_watch_and_a_stopped_one_says_no_more(
    page: Path,
) -> None:
    host = StandIn(
        {"list": [Listed(launches=[])], "inbox-list": [Items(items=[])]}, lasting=True
    )
    with client(host, page).websocket_connect(SOCKET, headers=bearing()) as socket:
        socket.send_json(watched(1, ListLaunches()))
        first = socket.receive_json()
        socket.send_json({"kind": "unwatch", "number": 1})
        socket.send_json(watched(2, ListInbox()))
        second = socket.receive_json()
    assert first == {
        "kind": "watched",
        "number": 1,
        "reply": {
            "kind": "listed",
            "launches": [],
            "sessions": {},
            "talkers": {},
            "running": None,
            "looks": {},
            "standing": {
                "folds": [],
                "tones": [],
                "drawers": [],
                "banners": [],
                "verbs": [],
            },
        },
    }
    # Watch 1, stopped, sends nothing more: not even its end.
    assert second == {
        "kind": "watched",
        "number": 2,
        "reply": {
            "kind": "inbox-items",
            "items": [],
            "seen": [],
            "answers": [],
            "commented": [],
            "paths": [],
            "landings": {},
        },
    }
    assert host.asked == [ListLaunches(), ListInbox()]


def test_a_host_out_of_reach_ends_the_watch_saying_why(page: Path) -> None:
    host = StandIn({}, reachable=False)
    with client(host, page).websocket_connect(SOCKET, headers=bearing()) as socket:
        socket.send_json(watched(3, ListInbox()))
        ended = socket.receive_json()
    assert ended == {
        "kind": "ended",
        "number": 3,
        "why": "no host service answers on watch.sock",
    }


def closed(served: TestClient, headers: dict[str, str]) -> int:
    """Open the socket with `headers` and return the code it's closed with."""
    with served.websocket_connect(SOCKET, headers=headers) as socket:
        return socket.receive()["code"]


def test_the_socket_needs_the_token_and_a_page_of_its_own_origin(page: Path) -> None:
    host = StandIn({"list": [Listed(launches=[])]}, lasting=True)
    served = client(host, page)
    without = closed(served, {})
    wrong = closed(served, {"Authorization": "Bearer no"})
    elsewhere = closed(served, {**bearing(), "Origin": "http://evil.example"})
    served.post("/api/session", headers=bearing())
    with served.websocket_connect(
        SOCKET, headers={"Origin": "http://127.0.0.1:8766"}
    ) as socket:
        socket.send_json(watched(1, ListLaunches()))
        by_cookie = socket.receive_json()
    assert [without, wrong, elsewhere] == [4401, 4401, 4403]
    assert by_cookie["kind"] == "watched"
    assert host.asked == [ListLaunches()]


def test_a_request_the_page_may_not_send_is_refused_before_the_host(page: Path) -> None:
    host = StandIn({})
    response = client(host, page).post(
        "/api/ask", json={"kind": "stop"}, headers=bearing()
    )
    assert response.status_code == 422
    assert host.asked == []


def test_the_api_needs_the_token_and_a_page_of_its_own_origin(page: Path) -> None:
    host = StandIn({"list": [Listed(launches=[])]})
    served = client(host, page)
    body = ListLaunches().model_dump()
    without = served.post("/api/ask", json=body)
    wrong = served.post("/api/ask", json=body, headers={"Authorization": "Bearer no"})
    elsewhere = served.post(
        "/api/ask", json=body, headers={**bearing(), "Origin": "http://evil.example"}
    )
    own = served.post(
        "/api/ask", json=body, headers={**bearing(), "Origin": "http://localhost:8766"}
    )
    assert [without.status_code, wrong.status_code, elsewhere.status_code] == [
        401,
        401,
        403,
    ]
    assert own.status_code == 200
    assert host.asked == [ListLaunches()]


def test_the_page_trades_its_token_for_the_cookie_it_calls_with(page: Path) -> None:
    host = StandIn({"list": [Listed(launches=[])]})
    served = client(host, page)
    traded = served.post("/api/session", headers=bearing())
    asked = served.post("/api/ask", json=ListLaunches().model_dump())
    assert traded.status_code == 204
    assert traded.headers["set-cookie"].startswith("lup-dashboard-8766=")
    assert "httponly" in traded.headers["set-cookie"].lower()
    assert "samesite=strict" in traded.headers["set-cookie"].lower()
    assert asked.status_code == 200


def test_a_host_name_other_than_its_own_is_refused(page: Path) -> None:
    host = StandIn({"list": [Listed(launches=[])]})
    app = application(host, Access(token=GIVEN, port=8766), page)
    rebound = TestClient(app, base_url="http://attacker.example:8766")
    assert (
        rebound.post("/api/ask", json={"kind": "list"}, headers=bearing()).status_code
        == 400
    )


def elsewhere(host: Host, page: Path, base: str) -> TestClient:
    """The dashboard listening on two addresses beyond localhost, reached at `base`."""
    access = Access(
        token=GIVEN,
        port=8766,
        addresses=[ip_address("10.8.0.2"), ip_address("fd00::2")],
    )
    return TestClient(application(host, access, page), base_url=base)


def test_an_address_the_dashboard_listens_on_beyond_localhost_takes_the_token_as_localhost_does(
    page: Path,
) -> None:
    host = StandIn({"list": [Listed(launches=[])]}, lasting=True)
    body = ListLaunches().model_dump()
    served = elsewhere(host, page, "http://10.8.0.2:8766")
    borne = served.post("/api/ask", json=body, headers=bearing())
    without = served.post("/api/ask", json=body)
    own = served.post(
        "/api/ask", json=body, headers={**bearing(), "Origin": "http://10.8.0.2:8766"}
    )
    other = served.post(
        "/api/ask", json=body, headers={**bearing(), "Origin": "http://10.8.0.3:8766"}
    )
    traded = served.post("/api/session", headers=bearing())
    by_cookie = served.post("/api/ask", json=body)
    with served.websocket_connect(
        "ws://10.8.0.2:8766/api/socket", headers={"Origin": "http://10.8.0.2:8766"}
    ) as socket:
        socket.send_json(watched(1, ListLaunches()))
        frame = socket.receive_json()
    six = elsewhere(host, page, "http://[fd00::2]:8766").post(
        "/api/ask", json=body, headers={**bearing(), "Origin": "http://[fd00::2]:8766"}
    )
    unbound = elsewhere(host, page, "http://10.8.0.3:8766").post(
        "/api/ask", json=body, headers=bearing()
    )
    assert [
        borne.status_code,
        without.status_code,
        own.status_code,
        other.status_code,
    ] == [200, 401, 200, 403]
    assert traded.headers["set-cookie"].startswith("lup-dashboard-8766=")
    assert by_cookie.status_code == 200
    assert frame["kind"] == "watched"
    assert six.status_code == 200
    assert unbound.status_code == 400


def test_a_host_out_of_reach_is_said(page: Path) -> None:
    host = StandIn({}, reachable=False)
    response = client(host, page).post(
        "/api/ask", json=ListLaunches().model_dump(), headers=bearing()
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "no host service answers on control.sock"}


def test_everything_else_is_the_page(page: Path) -> None:
    served = client(StandIn({}), page)
    assert served.get("/").text == "<!doctype html><title>lup</title>"
    navigated = served.get("/agents/one", headers={"Accept": "text/html"})
    assert navigated.text == "<!doctype html><title>lup</title>"


class Fixed(Clock):
    """A clock at one moment."""

    @override
    def now(self) -> datetime:
        return datetime(2026, 10, 1, 12, tzinfo=UTC)

    @override
    def sleep(self, seconds: float) -> None:
        del seconds


def test_the_demo_serves_its_stand_in_launches_and_refuses_the_rest(page: Path) -> None:
    served = client(Demo(clock=Fixed(), size=0), page)
    listed = served.post(
        "/api/ask", json=ListLaunches().model_dump(), headers=bearing()
    )
    items = served.post("/api/ask", json=ListInbox().model_dump(), headers=bearing())
    other = served.post(
        "/api/ask", json={"kind": "inbox-show", "number": 51}, headers=bearing()
    )
    names = [each["name"] for each in listed.json()["launches"]]
    assert names == ["lup-impl", "guidance-voice", "main", "magpie-search"]
    assert [each["number"] for each in items.json()["items"]] == [
        45,
        51,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
        59,
        60,
        68,
        69,
        62,
        67,
        70,
        64,
        65,
        66,
    ]
    assert other.json() == {
        "kind": "refused",
        "error": "the demo doesn't answer `inbox-show`",
    }


def test_the_demo_answers_a_module_s_view_with_the_module_s_own_layout_over_its_stand_ins(
    page: Path,
) -> None:
    served = client(Demo(clock=Fixed(), size=0), page)
    lup = Path("/home/op/lup.git")
    parser = OfAgent(runtime="claude", session="s1", agent="a02")

    def viewed(view: str, argument: JsonValue) -> Viewed | Refused:
        asked = Viewing(
            repository=lup, module="transcripts", view=view, argument=argument
        )
        answered = served.post(
            "/api/ask", json=asked.model_dump(mode="json"), headers=bearing()
        )
        return TypeAdapter[Viewed | Refused](Viewed | Refused).validate_python(
            answered.json()
        )

    listed = Listed.model_validate(
        served.post(
            "/api/ask", json=ListLaunches().model_dump(), headers=bearing()
        ).json()
    )
    drawer = viewed("conversation", parser.model_dump(mode="json"))
    assert isinstance(drawer, Viewed)
    # The module's own layout: its summary, its folds, its items woven in, each
    # call read whole as its fold opens, from its own view.
    lines = drawer.blocks.text().splitlines()
    assert lines[0].startswith("conversation · ")
    assert "▸ → @51 question to you · waiting on you" in lines
    [loaded] = [
        each.content
        for each in drawer.blocks.blocks
        if isinstance(each, Fold)
        and isinstance(each.content, Load)
        and each.content.view == "call"
        and each.content.argument.get("id") == "call-51"
    ]
    assert drawer.watch.of == parser
    assert "call-finished" in drawer.watch.on
    call = viewed("call", loaded.argument)
    assert isinstance(call, Viewed)
    assert "Which way should the reader read each kind of line?" in call.blocks.text()
    assert call.watch.on == ["call-finished"]
    # How every repository's views look, for the page to draw them by.
    assert [
        (each.module, each.view, each.place.letter)
        for each in listed.looks[lup].drawers
    ] == [
        ("adapters", "tasks", "t"),
        ("judge", "since", "s"),
        ("transcripts", "conversation", "v"),
    ]
    assert listed.standing == listed.looks[lup]
    assert {"earlier", "calls", "items", "call"} <= {
        each.name for each in listed.looks[lup].folds
    }
    refused = viewed("nowhere", parser.model_dump(mode="json"))
    assert isinstance(refused, Refused)
    assert "has a view `nowhere`" in refused.error


def test_the_demo_weaves_a_conversations_items_into_its_view_a_message_sent_from_the_page_among_them(
    page: Path,
) -> None:
    demo = Demo(clock=Fixed())
    served = client(demo, page)
    parser = Conversation(
        repository=Path("/home/op/lup.git"), runtime="claude", session="s1", agent="a02"
    )
    sending = SendItem(launch="a1f0", text="Go on.", agent="a02")
    sent = served.post("/api/ask", json=sending.model_dump(), headers=bearing())
    asked = Viewing(
        repository=parser.repository,
        module="transcripts",
        view="conversation",
        argument={"runtime": "claude", "session": "s1", "agent": "a02"},
    )
    viewed = Viewed.model_validate(
        served.post(
            "/api/ask", json=asked.model_dump(mode="json"), headers=bearing()
        ).json()
    )
    elsewhere = SendItem(launch="d4c3", text="Hello?")
    unsent = served.post("/api/ask", json=elsewhere.model_dump(), headers=bearing())
    found = demo.exchanged(parser)
    assert sent.json()["item"]["number"] == 101
    assert [each.item.number for each in found.sent] == [47, 51, 57, 59, 67]
    assert found.sent[0].item.call == "call-47"
    assert [(each.item.number, each.text) for each in found.received] == [
        (48, "Good: keep the two readers apart."),
        (101, "Go on."),
    ]
    # Each a line where it happened in the conversation's view, as the core words it.
    lines = viewed.blocks.text().splitlines()
    assert "▸ ← @101 your message" in lines
    assert "▸ → @51 question to you · waiting on you" in lines
    # The page reads a conversation's items only through that view.
    listed = served.post(
        "/api/ask",
        json=ListItems(conversation=parser).model_dump(mode="json"),
        headers=bearing(),
    )
    assert listed.status_code == 422
    assert unsent.json() == {
        "kind": "refused",
        "error": "no session of launch `d4c3` has started",
    }


def test_the_demo_reads_a_conversations_steps_each_call_a_line_saying_what_it_did(
    page: Path,
) -> None:
    served = client(Demo(clock=Fixed()), page)
    asked = ShowConversation(runtime="claude", session="s1", agent="a02")
    read = Conversed.model_validate(
        served.post("/api/ask", json=asked.model_dump(), headers=bearing()).json()
    )
    called = [each for each in read.entries if isinstance(each, Called)]
    assert called
    assert all(each.gist is not None for each in called)


def test_the_demo_keeps_a_draft_and_sends_it_taking_what_it_covers_off_the_list_but_whats_parked(
    page: Path,
) -> None:
    served = client(Demo(clock=Fixed()), page)
    draft = {
        "comments": [
            {"item": 51, "text": "Yes."},
            {
                "item": 51,
                "quote": {"text": "Fold", "start": 0, "end": 4},
                "text": "Keep the name.",
            },
            {"item": 53, "text": "Later."},
        ],
        "done": [52],
        "parked": [53],
    }
    kept = served.post(
        "/api/ask", json={"kind": "inbox-keep-draft", "draft": draft}, headers=bearing()
    )
    sent = served.post("/api/ask", json={"kind": "inbox-send-draft"}, headers=bearing())
    left = served.post("/api/ask", json={"kind": "inbox-draft"}, headers=bearing())
    waiting = served.post("/api/ask", json={"kind": "inbox-list"}, headers=bearing())
    numbers = [each["number"] for each in waiting.json()["items"]]
    assert kept.json()["draft"]["comments"][1]["quote"]["text"] == "Fold"
    assert 51 not in numbers
    assert 52 not in numbers
    assert 53 in numbers
    assert sent.json() == {
        "kind": "inbox-reviewed",
        "items": [],
        "read": [52],
        "approved": [],
        "declined": [],
        "noted": [],
        "kept": [],
    }
    assert left.json()["draft"] == {
        "comments": [
            {"id": "", "item": 53, "quote": None, "on": None, "text": "Later."}
        ],
        "letters": [],
        "remarks": [],
        "done": [],
        "declined": [],
        "parked": [53],
        "marks": [],
    }


def test_the_demo_reads_its_threads_as_the_host_does_and_the_operator_settles_one_and_answers_a_check(
    page: Path,
) -> None:
    served = client(Demo(clock=Fixed(), size=0), page)

    def threads() -> dict[str, ThreadRead]:
        asked = served.post(
            "/api/ask", json=ListThreads().model_dump(), headers=bearing()
        )
        listed = ThreadsRead.model_validate(asked.json())
        return {each.thread.name: each for each in listed.threads}

    def shown(number: int, *, whole: bool = False) -> ThreadShown:
        asked = ShowThread(number=number, whole=whole).model_dump()
        replied = served.post("/api/ask", json=asked, headers=bearing())
        return ThreadShown.model_validate(replied.json())

    read = threads()
    assert {name: each.section for name, each in read.items()} == {
        "lup-impl": "waiting on you",
        "transcript-reader": "waiting on you",
        "auth-survey": "new",
        "clock-ticks": "every thread",
        "legacy-cache": "every thread",
        "reader-names": "every thread",
        "guidance-voice": "waiting on you",
        "voice-branch": "every thread",
        "main": "waiting on you",
        "dev": "every thread",
        "docs-pass": "every thread",
    }
    reader = read["transcript-reader"]
    assert [each.what for each in reader.asks] == ["a question", "a check"]
    assert read["guidance-voice"].state == "done to confirm"
    # The parser's question and check, read, still show, after the latest three
    # read besides, but the flagged write, their exchange with their subagent
    # among them; the rest folds under what came earlier.
    conversation = shown(reader.thread.number)
    assert [(each.spot.node, each.seen) for each in conversation.entries] == [
        (67, True),
        (70, True),
        (51, False),
        (311, False),
        (57, True),
    ]
    assert conversation.left == 3
    # A part of the operator's words moved in says what they said, open.
    [part] = shown(read["voice-branch"].thread.number, whole=True).entries
    assert part.unanswered
    assert part.said == (
        "Once that's done, put it on its branch for me to read. "
        "Keep the examples short."
    )

    voice = read["guidance-voice"].thread.number
    settled = served.post(
        "/api/ask", json=SettleThread(number=voice).model_dump(), headers=bearing()
    )
    assert ThreadStated.model_validate(settled.json()).read.state == "settled"
    check = reader.asks[1].node
    answered = served.post(
        "/api/ask", json=AnswerCheck(number=check).model_dump(), headers=bearing()
    )
    assert CheckShown.model_validate(answered.json()).thread == "transcript-reader"
    after = threads()
    assert after["guidance-voice"].section == "every thread"
    assert [each.what for each in after["transcript-reader"].asks] == ["a question"]
    refused = served.post(
        "/api/ask", json=SettleThread(number=9999).model_dump(), headers=bearing()
    )
    assert refused.json() == {
        "kind": "refused",
        "error": "the demo has no thread @9999",
    }


def test_the_demo_moves_frictions_and_how_it_felt_from_the_pile_into_a_thread_as_the_host_does(
    page: Path,
) -> None:
    served = client(Demo(clock=Fixed(), size=0), page)

    def asked(request: Asked) -> JsonValue:
        return served.post(
            "/api/ask", json=request.model_dump(mode="json"), headers=bearing()
        ).json()

    def threads() -> dict[str, ThreadRead]:
        listed = ThreadsRead.model_validate(asked(ListThreads()))
        return {each.thread.name: each for each in listed.threads}

    before = threads()
    # The parser's friction stays in the pile, though it came before where the operator read its thread.
    assert before["transcript-reader"].pile == [57]
    assert before["guidance-voice"].pile == [58]
    moved = MovedIntoThread.model_validate(
        asked(MoveIntoThread(numbers=[57, 58], title="The gate's silent rebuild"))
    )
    gate = moved.read.thread
    assert (moved.opened, moved.moved, gate.name, gate.parent) == (
        True,
        [57, 58],
        "the-gate-s-silent-rebuild",
        before["lup-impl"].thread.number,
    )
    after = threads()
    assert (after["transcript-reader"].pile, after["guidance-voice"].pile) == ([], [])
    gathered = ThreadShown.model_validate(
        asked(ShowThread(number=gate.number, whole=True))
    )
    assert [(each.spot.node, each.moved) for each in gathered.entries] == [
        (57, True),
        (58, True),
    ]
    landed = ThreadShown.model_validate(
        asked(ShowThread(number=before["transcript-reader"].thread.number, whole=True))
    )
    assert [each.went for each in landed.entries if each.spot.node == 57] == [
        gate.number
    ]
    refused = asked(MoveIntoThread(numbers=[51], thread=gate.number))
    assert refused == {
        "kind": "refused",
        "error": "only frictions and how it felt are moved from the pile to read",
    }


def test_the_demo_keeps_one_order_of_the_reviews_groups_for_every_page(
    page: Path,
) -> None:
    served = client(Demo(clock=Fixed()), page)

    def keep(places: list[str], gone: list[str]) -> JsonValue:
        asked = {"kind": "inbox-keep-order", "places": places, "gone": gone}
        return served.post("/api/ask", json=asked, headers=bearing()).json()

    one = keep(["now b", "now a"], [])
    other = keep(["now a", "now c"], ["now b"])
    shown = served.post("/api/ask", json={"kind": "inbox-order"}, headers=bearing())
    assert one == {"kind": "inbox-ordered", "order": {"places": ["now b", "now a"]}}
    assert other == {"kind": "inbox-ordered", "order": {"places": ["now a", "now c"]}}
    assert shown.json() == other


def test_the_demo_keeps_what_the_page_measured_of_itself_as_the_host_does(
    page: Path, tmp_path: Path
) -> None:
    served = client(Demo(clock=Fixed(), timings=tmp_path / "timings"), page)
    start = datetime(2026, 10, 1, 11, 55, tzinfo=UTC)
    report = {
        "page": "dashboard",
        "session": "a1b2c3",
        "browser": {"name": "Chrome", "version": "151", "device": "desktop"},
        "windows": [
            {
                "sequence": 1,
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=5)).isoformat(),
                "size": {"lines": 15_203},
                "keys": {"typing": {"painted": {"16": 3}, "under": 2}},
            }
        ],
    }
    asked = {"kind": "page-timings-keep", "report": report}
    kept = served.post("/api/ask", json=asked, headers=bearing())
    assert kept.json() == {"kind": "page-timings-kept", "windows": 1}
    read = TimingsStore(home=tmp_path / "timings").read("dashboard", Fixed().now())
    assert [(each.session, each.window.keys["typing"].keys()) for each in read] == [
        ("a1b2c3", 5)
    ]


def settling(approved: bool, reason: Approval | Message) -> Settled:
    """The host's reply to an approval answered: its item, as it stands."""
    item = Item(
        number=7,
        reason=reason,
        sender=Operator(),
        recipient=Operator(),
        made=datetime(2026, 10, 1, 12, tzinfo=UTC),
        state=Decided(at=datetime(2026, 10, 1, 12, tzinfo=UTC), approved=approved),
    )
    return Settled(item=item, here=True)


ZONE = Approval(
    text="Approve the host zone?", summary="", repository=Path("/r"), fingerprint="f"
)


@pytest.mark.parametrize(
    ("approved", "reason", "acted"),
    [
        (True, ZONE, [7]),
        (False, ZONE, []),
        (True, Message(kind="note", text="not an approval"), []),
    ],
)
def test_an_approval_approved_on_the_page_is_acted_on_as_the_terminal_does(
    page: Path, approved: bool, reason: Approval | Message, acted: list[int]
) -> None:
    host = StandIn({"inbox-answer-approval": [settling(approved, reason)]})
    client(host, page).post(
        "/api/ask",
        json={"kind": "inbox-answer-approval", "number": 7, "approved": approved},
        headers=bearing(),
    )
    assert host.settled == acted


def test_about_says_the_pages_build_as_it_stands_on_disk(page: Path) -> None:
    served = client(StandIn({}), page)
    first = served.get("/api/about", headers=bearing()).json()
    (page / "index.html").write_text("<!doctype html><title>lup, built again</title>")
    second = served.get("/api/about", headers=bearing()).json()
    assert first["demo"] is False
    assert (
        first["build"]
        == hashlib.sha256(b"<!doctype html><title>lup</title>").hexdigest()
    )
    assert second["build"] != first["build"]


def test_a_host_zone_the_sent_draft_approved_is_acted_on_as_the_terminal_would(
    page: Path,
) -> None:
    zone = settling(approved=True, reason=ZONE).item
    note = settling(
        approved=True, reason=Message(kind="note", text="Fine.")
    ).item.model_copy(update={"number": 8})
    host = StandIn({"inbox-send-draft": [Reviewed(items=[], approved=[zone, note])]})
    response = client(host, page).post(
        "/api/ask", json={"kind": "inbox-send-draft"}, headers=bearing()
    )
    assert response.json()["approved"][0]["number"] == 7
    assert host.settled == [7]


def test_the_demos_approval_is_read_from_its_parse_until_its_types_are_read(
    page: Path,
) -> None:
    demo = Demo(clock=Fixed(), types_read=timedelta(hours=1))
    served = client(demo, page)

    def approval() -> tuple[bool, list[str]]:
        items = served.post("/api/ask", json={"kind": "inbox-list"}, headers=bearing())
        [typing] = [
            each["reason"]["typing"]
            for each in items.json()["items"]
            if each["number"] == 54
        ]
        shown = served.post(
            "/api/ask",
            json={"kind": "inbox-show-files", "number": 54},
            headers=bearing(),
        )
        found = [
            finding["rule"]
            for each in shown.json()["files"]
            for finding in each["reading"]["findings"]
        ]
        return typing, found

    assert approval() == (True, [])
    assert demo.reading is not None
    demo.typed()
    assert approval() == (False, ["string-split"])


def test_the_demos_files_carry_readings_each_placed_on_a_line_its_file_has() -> None:
    for number in [54, 55, 59, 60]:
        shown = files(number)
        assert isinstance(shown, Files)
        for each in shown.files:
            assert each.reading is not None, each.path
            after = each.after.text if isinstance(each.after, Text) else ""
            placed = [
                *(ask.line for ask in each.reading.asks if ask.line is not None),
                *(found.start for found in each.reading.findings),
            ]
            assert all(1 <= line <= len(after.splitlines()) for line in placed)


def test_the_demos_approval_holds_as_many_lines_more_as_asked_half_of_them_tests() -> (
    None
):
    def held(lines: int) -> list[tuple[str, int]]:
        shown = files(54, lines=lines)
        assert isinstance(shown, Files)
        return [
            (each.reading.role, len(each.after.text.splitlines()))
            for each in shown.files
            if each.reading is not None and isinstance(each.after, Text)
        ]

    own = held(0)
    grown = held(20_000)[len(own) :]
    roles = {role for role, _ in grown}
    total = sum(count for _, count in grown)
    assert roles == {"production", "test"}
    assert 20_000 <= total < 21_000
    assert sum(count for role, count in grown if role == "test") == total // 2
