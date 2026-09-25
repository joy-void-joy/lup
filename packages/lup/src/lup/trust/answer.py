"""How a launch question is answered: in the launcher's own inbox, or at the terminal.

Both at once, and the first recorded answer wins. The inbox is the review
surface lup already serves -- the queue, the file navigator, the diffs -- over
the launcher's own relay rather than a checkout's, served by the installed
launcher's code on loopback behind a capability only the printed address
carries. The terminal is there for the operator who launched from one and
would rather type a letter, and for a machine where the web extra is not
installed.

What neither of them reads is the checkout. The relay is the launcher's own
(:meth:`lup.trust.record.TrustState.relay`), and the answer is taken from it
and nowhere else, because a checkout's queue is writable from inside the
container -- a session could otherwise answer the question about its own work.
"""

import secrets
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from select import select
from typing import IO, Protocol

from rich.console import Console
from rich.syntax import Syntax

from lup.policy.relay import PersistentQuestion, QuestionRelay
from lup.policy.review import FilePreview
from lup.trust.review import OPERATOR
from lup.trust.zone import TrustError

type Preview = Callable[[PersistentQuestion], FilePreview]
"""How the answering surfaces learn a question's files."""


class Answerer(Protocol):
    """Whatever obtains the operator's answer to one launch question.

    A seam so the launch can be exercised without a browser or a terminal:
    what it needs back is the question as the relay settled it.
    """

    def __call__(self, question: PersistentQuestion) -> PersistentQuestion: ...


class InboxServer:
    """The review inbox the launcher serves over its own relay, on a loopback port.

    Bound before the address is printed, so the address is the one the socket
    holds -- an ephemeral port by default, because a fixed one collides with
    the operator's own `dev questions serve` and with a second launch waiting
    beside this one.
    """

    def __init__(
        self,
        root: Path,
        relay: QuestionRelay,
        preview: Preview,
        port: int = 0,
        host: str = "127.0.0.1",
    ) -> None:
        import uvicorn

        from lup.devtools.dev.questions import review_app

        self.bound = socket.create_server((host, port))
        chosen = self.bound.getsockname()[1]
        self.url = f"http://{host}:{chosen}"
        self.token = secrets.token_urlsafe(32)
        application = review_app(
            self.url,
            self.token,
            (root,),
            log=relay.path,
            preview=preview,
            notify=False,
        )
        self.server = uvicorn.Server(
            uvicorn.Config(application, log_level="warning", access_log=False)
        )
        self.thread = threading.Thread(
            target=self.server.run,
            kwargs={"sockets": [self.bound]},
            name="lup-launch-inbox",
            daemon=True,
        )

    def address(self) -> str:
        """The address to open: the page, with its capability in the fragment."""
        return f"{self.url}/#token={self.token}"

    def start(self) -> "InboxServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        """Ask the server to finish, and wait for it to let the port go."""
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.bound.close()


def unified(preview: FilePreview) -> list[Syntax | str]:
    """Every file of a question as the terminal shows it: its name, then its diff."""
    shown: list[Syntax | str] = [preview.notice] if preview.notice else []
    return [
        *shown,
        *[
            part
            for change in preview.files
            for part in (
                [f"{change.operation():<9} {change.path}"]
                + (
                    ["    unchanged"]
                    if change.unchanged()
                    else [Syntax(change.unified(), "diff", theme="ansi_dark")]
                )
            )
        ],
    ]


def summary(question: PersistentQuestion, preview: FilePreview) -> list[str]:
    """What the terminal says before it asks: the reason, and every path involved."""
    return [
        question.reason,
        *([preview.notice] if preview.notice else []),
        *[f"  {change.operation():<9} {change.path}" for change in preview.files],
    ]


def settled(relay: QuestionRelay, question: PersistentQuestion) -> PersistentQuestion:
    """The question as the relay holds it now, which is the only authority."""
    found = relay.find(question.id)
    if found is None:
        raise TrustError(
            f"the launch question {question.id} vanished from {relay.path}"
        )
    return found


class TerminalAnswerer:
    """Answers a launch question from the terminal while an inbox may answer it too.

    Polls the relay between keystrokes, so an answer given in the browser ends
    the prompt; a letter typed here is recorded through the same relay, whose
    transaction lets only the first answer stand.
    """

    def __init__(
        self,
        relay: QuestionRelay,
        preview: Preview,
        console: Console,
        stream: IO[str] = sys.stdin,
        interval: float = 0.5,
        interactive: bool | None = None,
    ) -> None:
        """``interactive`` is whether to read ``stream`` at all; unset, it is read
        exactly when it is a terminal, since a pipe nobody types into would only
        ever answer with its end."""
        self.relay = relay
        self.preview = preview
        self.console = console
        self.stream = stream
        self.interval = interval
        self.interactive = stream.isatty() if interactive is None else interactive

    def prompt(self) -> None:
        self.console.print(
            "Approve this launch? [a]pprove, [r]eject, [d]iff — or answer in the inbox: ",
            end="",
            markup=False,
        )

    def answered(self, question: PersistentQuestion, approved: bool) -> None:
        """Record a terminal answer, unless the inbox already recorded one."""
        try:
            self.relay.answer(
                question.id,
                OPERATOR,
                approved,
                "answered at the launching terminal",
            )
        except ValueError:
            return

    def __call__(self, question: PersistentQuestion) -> PersistentQuestion:
        preview = self.preview(question)
        for line in summary(question, preview):
            self.console.print(line, markup=False, highlight=False)
        reading = self.interactive
        if reading:
            self.prompt()
        while True:
            current = settled(self.relay, question)
            if current.state != "pending":
                return current
            if not reading:
                time.sleep(self.interval)
                continue
            ready, _writable, _failed = select([self.stream], [], [], self.interval)
            if not ready:
                continue
            typed = self.stream.readline()
            if not typed:
                reading = False
                continue
            match typed.strip().lower():
                case "a" | "approve" | "y" | "yes":
                    self.answered(question, True)
                case "r" | "reject" | "n" | "no":
                    self.answered(question, False)
                case "d" | "diff":
                    for part in unified(preview):
                        self.console.print(part, markup=False, highlight=False)
                    self.prompt()
                case _:
                    self.prompt()


def asked_and_answered(
    question: PersistentQuestion,
    root: Path,
    relay: QuestionRelay,
    preview: Preview,
    console: Console,
    port: int = 0,
    open_page: bool = True,
    stream: IO[str] = sys.stdin,
) -> PersistentQuestion:
    """Ask one launch question on every surface available, and return its answer.

    The inbox is started where the web extra is installed; the terminal asks
    where there is a terminal. Where neither is available nothing could ever
    answer, and waiting forever would look like a hung launch, so that is
    refused with what would fix it.
    """
    try:
        server = InboxServer(root, relay, preview, port).start()
    except ImportError:
        server = None
        console.print(
            "The review inbox is unavailable: this launcher was installed without "
            "its web extra (`lup[web]`), so the question is asked here only.",
            markup=False,
        )
    if server is None and not stream.isatty():
        raise TrustError(
            "nothing can answer the launch question: there is no terminal here and "
            "the review inbox is not installed. Reinstall the launcher with "
            "`lup[web]`, or launch from a terminal."
        )
    try:
        if server is not None:
            console.print(f"Review inbox: {server.address()}", markup=False)
            if open_page:
                webbrowser.open(server.address())
        return TerminalAnswerer(relay, preview, console, stream)(question)
    finally:
        if server is not None:
            server.stop()
