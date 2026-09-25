"""A launch question is answered in the launcher's inbox or at its terminal, and only there.

The inbox is the review surface lup already serves, pointed at the launcher's
relay and its store: what is pinned is that it lists the launch question with
the files the store names, that an answer lands in the launcher's relay and
nowhere in the checkout, and that the terminal and the browser settle one
question between them.
"""

import io
import os
from pathlib import Path
from typing import Final

import pytest
import sh
from fastapi import FastAPI
import httpx
from httpx import ASGITransport, AsyncClient
from rich.console import Console

from lup.devtools.dev import questions
from lup.devtools.dev.questions import ReviewDecision, ReviewDetail, ReviewInbox
from lup.policy.relay import QuestionRelay
from lup.trust import answer as answering
from lup.trust.answer import InboxServer, Preview, TerminalAnswerer, asked_and_answered
from lup.trust.objects import ObjectStore
from lup.trust.review import (
    OPERATOR,
    TrustEvidence,
    TrustPreview,
    asked_once,
    launch_question,
)
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
        root: Path, relay: QuestionRelay, preview: Preview, port: int = 0
    ) -> InboxServer:
        raise ImportError(f"no web extra to serve {root} from {relay.path}")

    monkeypatch.setattr(answering, "InboxServer", uninstalled)

    with pytest.raises(TrustError, match="nothing can answer"):
        asked_and_answered(
            asked.question,
            asked.root,
            asked.relay,
            asked.preview,
            Console(file=io.StringIO()),
            stream=io.StringIO(),
        )


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
