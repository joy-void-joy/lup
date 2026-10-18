"""The dashboard's server, on a stand-in host: its API relaying requests and streaming their replies, and who may call it."""

import json
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

    from lup_dashboard.api import Asked, Replied


class StandIn(Host):
    """Answers each request from what it was given, recording each asked."""

    def __init__(
        self, answers: dict[str, list[Replied]], *, reachable: bool = True
    ) -> None:
        self.answers = answers
        self.reachable = reachable
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
        for replied in self.answers[request.kind]:
            yield replied


GIVEN = "stand-in"


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


def test_watch_streams_each_reply_as_an_event(page: Path) -> None:
    host = StandIn({"inbox-list": [Items(items=[]), Refused(error="stopped")]})
    with client(host, page).stream(
        "POST", "/api/watch", json=ListInbox().model_dump(), headers=bearing()
    ) as response:
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]
    assert response.headers["content-type"].startswith("text/event-stream")
    assert events == [
        {"kind": "inbox-items", "items": []},
        {"kind": "refused", "error": "stopped"},
    ]


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
