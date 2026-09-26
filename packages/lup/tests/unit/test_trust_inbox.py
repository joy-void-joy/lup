"""A launch question is answered in the launcher's inbox or at its terminal, and only there.

The inbox is the review surface lup already serves, pointed at the launcher's
relay and its store: what is pinned is that it lists the launch question with
the files the store names, that an answer lands in the launcher's relay and
nowhere in the checkout, and that the terminal and the browser settle one
question between them.
"""

import io
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, urlparse

import pytest
import sh
import typer
from fastapi import FastAPI
import httpx
from httpx import ASGITransport, AsyncClient
from rich.console import Console

from lup.devtools.dev import questions
from lup.devtools.dev.questions import (
    Continuation,
    ReviewDecision,
    ReviewDetail,
    ReviewInbox,
)
from lup.policy.relay import QuestionRelay
from lup.trust import answer as answering
from lup.trust.answer import (
    InboxServer,
    Preview,
    ReviewSurfaces,
    TerminalAnswerer,
    Told,
)
from lup.trust.handoff import Handoff
from lup.trust.objects import ObjectStore
from lup.trust.review import (
    OPERATOR,
    TrustEvidence,
    TrustPreview,
    asked_once,
    launch_question,
)
from lup.trust.tab import REVIEW_TAB_ENV
from lup.trust.zone import FreeZones, LiveCheckout, TrustError, host_zone
from lup.web import serve as web_serve
from lup.web.serve import page_app

BASE_URL: Final = "http://127.0.0.1:8765"
TOKEN: Final = "launcher-capability"
AUTHORIZATION: Final = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def isolated_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the API without building the frontend, as the inbox tests do."""

    def build(title: str, url: str, surface: str) -> FastAPI:
        return page_app(title, url, "<!doctype html><main>Review inbox</main>")

    monkeypatch.setattr(web_serve, "bundle_app", build)


def run_git(cwd: Path, *arguments: str) -> str:
    return str(sh.Command("git")("-C", str(cwd), *arguments, _tty_out=False))


class Asked:
    """One launch question recorded in a launcher relay, over a real store."""

    def __init__(self, tmp_path: Path) -> None:
        self.checkout = tmp_path / "work"
        run_git(tmp_path, "init", "-q", "-b", "main", str(self.checkout))
        (self.checkout / "app.py").write_text("print('approved')\n")
        run_git(self.checkout, "add", "-A")
        run_git(self.checkout, "commit", "-q", "-m", "base")
        self.root = LiveCheckout.at(self.checkout, {"PATH": os.defpath}).root
        self.store = ObjectStore(root=tmp_path / "state" / "objects.git").prepared()
        self.relay = QuestionRelay(tmp_path / "state" / "questions.jsonl")
        base = host_zone(
            LiveCheckout.at(self.root, {"PATH": os.defpath}), self.store, FreeZones()
        )
        (self.checkout / "app.py").write_text("print('changed')\n")
        current = host_zone(
            LiveCheckout.at(self.root, {"PATH": os.defpath}), self.store, FreeZones()
        )
        self.question = self.relay.record(
            launch_question(
                self.root,
                TrustEvidence(
                    worktree=str(self.root),
                    runtime="claude",
                    base=base.tree,
                    current=current.tree,
                    free=[],
                    declared=[],
                ),
                "Launching claude runs this checkout's code on this machine.",
            )
        )
        self.preview = TrustPreview(
            self.root, self.store, otherwise=questions.captured_preview
        )

    def client(self) -> AsyncClient:
        application = questions.review_app(
            BASE_URL,
            TOKEN,
            (self.root,),
            log=self.relay.path,
            preview=self.preview,
            notify=False,
        )
        return AsyncClient(transport=ASGITransport(app=application), base_url=BASE_URL)


async def test_the_launchers_inbox_shows_the_launch_question_from_its_store(
    tmp_path: Path,
) -> None:
    asked = Asked(tmp_path)
    async with asked.client() as http:
        listed = ReviewInbox.model_validate(
            (await http.get("/api/reviews", headers=AUTHORIZATION)).json()
        )
        [row] = listed.reviews
        detail = ReviewDetail.model_validate(
            (await http.get(f"/api/reviews/{row.key}", headers=AUTHORIZATION)).json()
        )

    assert row.answerable
    assert row.paths == ["app.py"]
    [shown] = detail.files
    assert shown.before == "print('approved')\n"
    assert shown.after == "print('changed')\n"
    assert detail.notification is None


async def test_an_inbox_answer_lands_in_the_launchers_relay_and_nowhere_else(
    tmp_path: Path,
) -> None:
    asked = Asked(tmp_path)
    async with asked.client() as http:
        [row] = ReviewInbox.model_validate(
            (await http.get("/api/reviews", headers=AUTHORIZATION)).json()
        ).reviews
        response = await http.post(
            f"/api/reviews/{row.key}/answer",
            headers={**AUTHORIZATION, "Origin": BASE_URL},
            json={
                "approved": True,
                "note": "",
                "fingerprint": asked.question.fingerprint,
            },
        )

    decision = ReviewDecision.model_validate(response.json())
    settled = asked.relay.find(asked.question.id)
    assert settled is not None and settled.state == "approved"
    assert decision.review.question == settled
    assert "reads it from the relay" in decision.notification.detail
    assert not (asked.checkout / ".lup").exists()


def test_the_terminal_answers_what_the_operator_types(tmp_path: Path) -> None:
    asked = Asked(tmp_path)
    reading, writing = os.pipe()
    with os.fdopen(writing, "w") as typed:
        typed.write("d\na\n")
    output = io.StringIO()
    with os.fdopen(reading) as stream:
        settled = TerminalAnswerer(
            asked.relay,
            asked.preview,
            Console(file=output, width=200),
            stream,
            interval=0.01,
            interactive=True,
        )(asked.question)

    assert settled.state == "approved"
    assert settled.answer is not None and settled.answer.principal == OPERATOR
    assert "print('changed')" in output.getvalue()


def test_an_answer_given_elsewhere_ends_the_terminal_prompt(tmp_path: Path) -> None:
    asked = Asked(tmp_path)
    asked.relay.answer(asked.question.id, OPERATOR, False, "rejected in the browser")

    settled = TerminalAnswerer(
        asked.relay,
        asked.preview,
        Console(file=io.StringIO()),
        io.StringIO(),
        interval=0.01,
        interactive=False,
    )(asked.question)

    assert settled.state == "rejected"


def test_a_question_nothing_could_answer_is_refused_rather_than_waited_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = Asked(tmp_path)

    def uninstalled(
        root: Path,
        relay: QuestionRelay,
        preview: Preview,
        port: int = 0,
        told: Told | None = None,
    ) -> InboxServer:
        raise ImportError(f"no web extra to serve {root} from {relay.path}")

    monkeypatch.setattr(answering, "InboxServer", uninstalled)
    surfaces = ReviewSurfaces(
        Console(file=io.StringIO()), "claude", stream=io.StringIO()
    )

    with pytest.raises(TrustError, match="nothing can answer"):
        surfaces.ask(asked.question, asked.relay, asked.preview, asked.root)


def test_the_same_question_in_another_launch_is_not_a_second_question(
    tmp_path: Path,
) -> None:
    asked = Asked(tmp_path)
    again = launch_question(
        asked.root,
        TrustEvidence.model_validate(asked.question.operation.payload),
        asked.question.reason,
    )

    reused = asked_once(asked.relay, again)

    assert reused.id == asked.question.id
    assert [entry.id for entry in asked.relay.questions()] == [asked.question.id]


def test_the_launchers_inbox_serves_its_relay_on_its_own_loopback_port(
    tmp_path: Path,
) -> None:
    asked = Asked(tmp_path)
    server = InboxServer(asked.root, asked.relay, asked.preview).start()
    try:
        refused = httpx.get(f"{server.url}/api/reviews", timeout=10)
        listed = httpx.get(
            f"{server.url}/api/reviews",
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        )
    finally:
        server.stop()

    assert server.address().startswith("http://127.0.0.1:")
    assert "#token=" in server.address()
    assert refused.status_code == 401
    [row] = ReviewInbox.model_validate(listed.json()).reviews
    assert row.id == asked.question.id
    assert not server.thread.is_alive()


PAGE_COMMAND = Path(__file__).parent / "fixtures" / "page_command.py"
"""A command that serves a page and opens it, as ``lup-launch run`` hands one over."""


class Tab:
    """The operator's tab on a launcher's inbox: it answers there, then follows what it is told.

    As the page does, over the inbox's own API: the pending question is
    answered with its fingerprint, and the snapshot is read until it carries
    a page to go to, says its last, or the inbox stops answering. A tab that
    does not follow is one the operator closed.
    """

    def __init__(self, approve: bool = True, follows: bool = True) -> None:
        self.approve = approve
        self.follows = follows
        self.opened: list[str] = []
        self.told: list[Continuation] = []
        self.thread: threading.Thread | None = None

    def browser(self, address: str) -> bool:
        """Open a page: the first is the inbox, and is followed; the rest are recorded."""
        self.opened.append(address)
        if self.follows and self.thread is None:
            self.thread = threading.Thread(
                target=self.follow, args=(address,), daemon=True
            )
            self.thread.start()
        return True

    def read(self, base: str, headers: dict[str, str]) -> ReviewInbox:
        return ReviewInbox.model_validate(
            httpx.get(f"{base}/api/reviews", headers=headers, timeout=10).json()
        )

    def follow(self, address: str) -> None:
        link = urlparse(address)
        base = f"{link.scheme}://{link.netloc}"
        [token] = parse_qs(link.fragment)["token"]
        headers = {"Authorization": f"Bearer {token}"}
        [row] = self.read(base, headers).reviews
        detail = ReviewDetail.model_validate(
            httpx.get(
                f"{base}/api/reviews/{row.key}", headers=headers, timeout=10
            ).json()
        )
        httpx.post(
            f"{base}/api/reviews/{row.key}/answer",
            headers={**headers, "Origin": base},
            json={
                "approved": self.approve,
                "note": "",
                "fingerprint": detail.question.fingerprint,
            },
            timeout=10,
        )
        for _ in range(1500):
            try:
                told = self.read(base, headers).continuation
            except httpx.TransportError:
                return
            if told is not None and (not self.told or self.told[-1] != told):
                self.told.append(told)
            if told is not None and (told.url or told.final):
                return
            time.sleep(0.02)

    def done(self) -> None:
        """Wait for the tab to have stopped following."""
        if self.thread is not None:
            self.thread.join(timeout=30)


def free_port() -> int:
    """A loopback port nothing listens on, for a command's page."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def page_command(port: int, lasting: float = 1.0, status: int = 3) -> Handoff:
    """A hand-off of a command that serves a page on ``port`` (none at 0) and exits."""
    return Handoff(
        argv=[sys.executable, str(PAGE_COMMAND), str(port), str(lasting), str(status)],
        # lup: ignore[os-environ] — the child imports lup from this interpreter's
        # environment; BROWSER keeps a page it opened itself from reaching a real one
        environment={**os.environ, "BROWSER": "true"},
    )


def child(handoff: Handoff) -> sh.RunningCommand:
    """Start a hand-off beside the test, its output kept out of the test's terminal."""
    return sh.Command(handoff.argv[0])(
        *handoff.argv[1:],
        _env=handoff.environment,
        _bg=True,
        _bg_exc=False,
        _ok_code=list(range(256)),
        _return_cmd=True,
    )


def surfaces_for(tab: Tab, named: str, open_page: bool = True) -> ReviewSurfaces:
    return ReviewSurfaces(
        Console(file=io.StringIO()),
        named,
        open_page=open_page,
        stream=io.StringIO(),
        browser=tab.browser,
        spawn=child,
        heard_within=5.0,
    )


def refused(address: str) -> bool:
    """Whether nothing answers at an inbox's address any more."""
    try:
        httpx.get(address, timeout=2)
    except httpx.TransportError:
        return True
    return False


def test_a_session_launch_tells_the_tab_and_stops_the_inbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = Asked(tmp_path)
    tab = Tab()
    surfaces = surfaces_for(tab, "claude")
    handed: list[Handoff] = []
    monkeypatch.setattr(answering, "executed", handed.append)

    answered = surfaces.ask(asked.question, asked.relay, asked.preview, asked.root)
    [inbox] = tab.opened
    surfaces.launch(page_command(0))
    tab.done()

    assert answered.state == "approved"
    assert tab.told[-1] == Continuation(
        message="Approved: claude opens in your terminal.", final=True
    )
    assert len(handed) == 1
    assert surfaces.inbox is None
    assert refused(inbox)


def test_a_run_sends_the_tab_to_the_page_its_command_opened(tmp_path: Path) -> None:
    """The same tab goes on to the page; no second one opens, and the inbox stops."""
    asked = Asked(tmp_path)
    tab = Tab()
    surfaces = surfaces_for(tab, "lup-devtools setup dashboard")
    port = free_port()

    surfaces.ask(asked.question, asked.relay, asked.preview, asked.root)
    [inbox] = tab.opened
    with pytest.raises(typer.Exit) as ended:
        surfaces.run(page_command(port, lasting=1.0, status=3))
    tab.done()

    page = f"http://127.0.0.1:{port}/"
    assert tab.told[-1] == Continuation(message=f"Opening {page}", url=page, final=True)
    assert tab.opened == [inbox]
    assert ended.value.exit_code == 3
    assert surfaces.inbox is None
    assert refused(inbox)


def test_a_command_opening_no_page_ends_the_inbox_when_it_ends(tmp_path: Path) -> None:
    asked = Asked(tmp_path)
    tab = Tab()
    surfaces = surfaces_for(tab, "lup-devtools setup secret GEMINI_API_KEY")

    surfaces.ask(asked.question, asked.relay, asked.preview, asked.root)
    [inbox] = tab.opened
    with pytest.raises(typer.Exit) as ended:
        surfaces.run(page_command(0, lasting=0.2, status=0))
    tab.done()

    assert tab.told[-1] == Continuation(
        message="lup-devtools setup secret GEMINI_API_KEY has finished in your terminal.",
        final=True,
    )
    assert ended.value.exit_code == 0
    assert refused(inbox)


def test_a_page_whose_tab_was_closed_opens_in_a_new_one(tmp_path: Path) -> None:
    asked = Asked(tmp_path)
    asked.relay.answer(asked.question.id, OPERATOR, True, "answered before the tab")
    tab = Tab(follows=False)
    surfaces = surfaces_for(tab, "lup-devtools setup dashboard")
    surfaces.heard_within = 0.3
    port = free_port()

    surfaces.ask(asked.question, asked.relay, asked.preview, asked.root)
    with pytest.raises(typer.Exit):
        surfaces.run(page_command(port, lasting=1.0))

    [inbox, page] = tab.opened
    assert page == f"http://127.0.0.1:{port}/"
    assert refused(inbox)


def test_without_a_tab_a_run_is_handed_over_as_a_launch_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--no-open``: no browser at all, and the command opens its own pages."""
    asked = Asked(tmp_path)
    asked.relay.answer(asked.question.id, OPERATOR, True, "answered at the terminal")
    tab = Tab()
    surfaces = surfaces_for(tab, "lup-devtools setup dashboard", open_page=False)
    handed: list[Handoff] = []
    monkeypatch.setattr(answering, "executed", handed.append)

    surfaces.ask(asked.question, asked.relay, asked.preview, asked.root)
    surfaces.run(page_command(free_port()))

    assert tab.opened == []
    assert len(handed) == 1
    assert REVIEW_TAB_ENV not in handed[0].environment
    assert surfaces.inbox is None


def test_a_rejection_tells_the_tab_that_nothing_ran(tmp_path: Path) -> None:
    asked = Asked(tmp_path)
    tab = Tab(approve=False)
    surfaces = surfaces_for(tab, "claude")

    answered = surfaces.ask(asked.question, asked.relay, asked.preview, asked.root)
    tab.done()

    assert answered.state == "rejected"
    assert tab.told[-1] == Continuation(
        message="Rejected: nothing from this checkout ran.", final=True
    )
    assert surfaces.inbox is None
