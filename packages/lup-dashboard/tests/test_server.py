"""The dashboard's server, on a stand-in host: its API relaying requests and streaming their replies, and who may call it."""

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, override

import pytest
from fastapi.testclient import TestClient

from lup_dashboard.demo import Demo
from lup_dashboard.host import Host
from lup_dashboard.server import Access, application
from lup_dev.clock import Clock
from lup_dev.host.protocol import HostError, Listed, ListLaunches, Refused
from lup_dev.inbox.protocol import Items, ListInbox

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from pydantic import JsonValue

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
        {"kind": "watched", "number": 7, "reply": {"kind": "inbox-items", "items": []}},
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
        "reply": {"kind": "listed", "launches": [], "sessions": {}, "talkers": {}},
    }
    # Watch 1, stopped, sends nothing more: not even its end.
    assert second == {
        "kind": "watched",
        "number": 2,
        "reply": {"kind": "inbox-items", "items": []},
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
    served = client(Demo(clock=Fixed()), page)
    listed = served.post(
        "/api/ask", json=ListLaunches().model_dump(), headers=bearing()
    )
    items = served.post("/api/ask", json=ListInbox().model_dump(), headers=bearing())
    other = served.post(
        "/api/ask", json={"kind": "inbox-show", "number": 51}, headers=bearing()
    )
    names = [each["name"] for each in listed.json()["launches"]]
    assert names == ["lup-impl", "guidance-voice", "main", "nori-search"]
    assert [each["number"] for each in items.json()["items"]] == [51, 52, 53, 54]
    assert other.json() == {
        "kind": "refused",
        "error": "the demo doesn't answer `inbox-show`",
    }


def test_the_demo_keeps_a_draft_and_sends_it_keeping_whats_parked(page: Path) -> None:
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
    assert kept.json()["draft"]["comments"][1]["quote"]["text"] == "Fold"
    assert sent.json() == {"kind": "inbox-reviewed", "items": []}
    assert left.json()["draft"] == {
        "comments": [{"item": 53, "quote": None, "text": "Later."}],
        "done": [],
        "parked": [53],
    }
