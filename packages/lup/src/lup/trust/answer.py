"""How a launch question is answered, and what the tab that answered it is told after.

Answered in the launcher's own inbox or at the terminal, both at once, and
the first recorded answer wins. The inbox is the review surface lup already
serves -- the queue, the file navigator, the diffs -- over the launcher's own
relay rather than a checkout's, served by the installed launcher's code on
loopback behind a capability only the printed address carries. The terminal
is there for the operator who launched from one and would rather type a
letter, and for a machine where the web extra is not installed.

What neither of them reads is the checkout. The relay is the launcher's own
(:meth:`lup.trust.record.TrustState.relay`), and the answer is taken from it
and nowhere else, because a checkout's queue is writable from inside the
container -- a session could otherwise answer the question about its own work.

The inbox serves one question, then stops. Before it does, the tab opened on
it is told what happens next (:class:`~lup.devtools.dev.questions.Continuation`)
and given a moment to hear it. A launch opening a session says so and hands
over. A command ``lup-launch run`` hands over runs beside the launcher
instead, and the first page it opens is sent to that tab (:mod:`lup.trust.tab`)
rather than to a second one; once the tab is sent there, or the command ends
without opening one, the inbox stops too. A launch that asked nothing opens
no inbox, and its command opens its pages as it always would.
"""

import secrets
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from select import select
from typing import IO, Protocol
from urllib.parse import urlparse

import sh
import typer
from rich.console import Console
from rich.syntax import Syntax

from lup.devtools.dev.questions import Continuation
from lup.policy.relay import PersistentQuestion, QuestionRelay
from lup.policy.review import FilePreview
from lup.trust.handoff import Handoff, Spawner, beside, executed, exit_status
from lup.trust.review import OPERATOR
from lup.trust.tab import REVIEW_TAB_ENV, announced_page
from lup.trust.zone import TrustError

type Preview = Callable[[PersistentQuestion], FilePreview]
"""How the answering surfaces learn a question's files."""

type Browser = Callable[[str], bool]
"""What opens a page in the operator's browser, answering whether one did."""


class Answerer(Protocol):
    """Whatever obtains the operator's answer to one launch question.

    A seam so the launch can be exercised without a browser or a terminal:
    what it needs back is the question as the relay settled it.
    """

    def __call__(self, question: PersistentQuestion) -> PersistentQuestion: ...


class Told:
    """What the inbox tells its tab once the question is answered, and whether it heard.

    The inbox asks for it with every snapshot it serves, so the first one
    served after something was said is the tab hearing it.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.said: Continuation | None = None
        self.heard = threading.Event()

    def say(self, continuation: Continuation) -> None:
        """Tell the tab this next, and forget it heard anything before."""
        with self.lock:
            self.said = continuation
            self.heard.clear()

    def __call__(self) -> Continuation | None:
        """What the inbox serves now, where anything was said."""
        with self.lock:
            if self.said is not None:
                self.heard.set()
            return self.said


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
        told: Told | None = None,
    ) -> None:
        import uvicorn

        from lup.devtools.dev.questions import review_app

        self.told = told if told is not None else Told()
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
            continued=self.told,
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
    transaction lets only the first answer stand. What the question is about
    was said before the inbox opened; the prompt only asks, and ``d`` shows
    every diff.
    """

    def __init__(
        self,
        relay: QuestionRelay,
        preview: Preview,
        console: Console,
        stream: IO[str] = sys.stdin,
        interval: float = 0.5,
        interactive: bool | None = None,
        inbox: bool = True,
    ) -> None:
        """``interactive`` is whether to read ``stream`` at all; unset, it is read
        exactly when it is a terminal, since a pipe nobody types into would only
        ever answer with its end. ``inbox`` is whether an inbox answers too."""
        self.relay = relay
        self.preview = preview
        self.console = console
        self.stream = stream
        self.interval = interval
        self.interactive = stream.isatty() if interactive is None else interactive
        self.inbox = inbox

    def prompt(self) -> None:
        elsewhere = " — or answer in the inbox" if self.inbox else ""
        self.console.print(
            f"Approve? [a]pprove, [r]eject, [d] every diff{elsewhere}: ",
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


def answering(url: str, within: float, running: Callable[[], bool]) -> bool:
    """Whether a page on this machine's loopback answers within ``within`` seconds.

    A page elsewhere answers as far as this launcher can tell: it is the
    browser's to reach. One on loopback is the command's own server, which
    it names before it listens, and a tab sent there too soon finds nothing.
    """
    address = urlparse(url)
    if address.hostname not in ("127.0.0.1", "localhost", "::1"):
        return True
    port = address.port or (443 if address.scheme == "https" else 80)
    deadline = time.monotonic() + within
    for _ in iter(lambda: time.monotonic() < deadline and running(), False):
        try:
            with socket.create_connection((address.hostname, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class ReviewSurfaces:
    """Where one launch's question is answered, and the tab the launch goes on in.

    ``named`` is what answering runs, as the tab is told it. The inbox is
    opened only when a question is asked, and a tab on it only where
    ``open_page`` says so and a browser opened; ``--no-open`` is a launch
    answered at the terminal with no browser at all. ``heard_within`` is how
    long the tab is given to hear what it is told before the inbox stops,
    and ``page_within`` how long a page the command opened is given to answer
    before the tab is sent there anyway.
    """

    def __init__(
        self,
        console: Console,
        named: str,
        port: int = 0,
        open_page: bool = True,
        stream: IO[str] = sys.stdin,
        browser: Browser = webbrowser.open,
        spawn: Spawner = beside,
        heard_within: float = 5.0,
        page_within: float = 30.0,
    ) -> None:
        self.console = console
        self.named = named
        self.port = port
        self.open_page = open_page
        self.stream = stream
        self.browser = browser
        self.spawn = spawn
        self.heard_within = heard_within
        self.page_within = page_within
        self.told = Told()
        self.inbox: InboxServer | None = None
        self.tab = False

    def ask(
        self,
        question: PersistentQuestion,
        relay: QuestionRelay,
        preview: Preview,
        root: Path,
    ) -> PersistentQuestion:
        """Ask one launch question on every surface available, and return its answer.

        The inbox is started where the web extra is installed; the terminal
        asks where there is a terminal. Where neither is available nothing
        could ever answer, and waiting forever would look like a hung launch,
        so that is refused with what would fix it. The inbox keeps serving
        after the answer, for what its tab is told next.
        """
        try:
            self.inbox = InboxServer(
                root, relay, preview, self.port, told=self.told
            ).start()
        except ImportError:
            self.console.print(
                "The review inbox is unavailable: this launcher was installed "
                "without its web extra (`lup[web]`), so the question is asked "
                "here only.",
                markup=False,
            )
        if self.inbox is None and not self.stream.isatty():
            raise TrustError(
                "nothing can answer the launch question: there is no terminal here "
                "and the review inbox is not installed. Reinstall the launcher with "
                "`lup[web]`, or launch from a terminal."
            )
        if self.inbox is not None:
            self.console.print(f"Review inbox: {self.inbox.address()}", markup=False)
            if self.open_page:
                self.tab = self.opened(self.inbox.address())
        answered = TerminalAnswerer(
            relay,
            preview,
            self.console,
            self.stream,
            inbox=self.inbox is not None,
        )(question)
        if answered.state != "approved":
            self.concluded(
                Continuation(
                    message="Rejected: nothing from this checkout ran.", final=True
                )
            )
        return answered

    def opened(self, url: str) -> bool:
        """Open a page in the operator's browser, answering whether one opened."""
        try:
            return self.browser(url)
        except (webbrowser.Error, OSError):
            return False

    def concluded(self, continuation: Continuation) -> bool:
        """Tell the tab one last thing, give it a moment to hear it, and stop the inbox.

        Answers whether the tab heard it: a tab the operator closed hears
        nothing, and what it would have been sent to is then theirs to open.
        """
        if self.inbox is None:
            return False
        heard = False
        if self.tab:
            self.told.say(continuation)
            heard = self.told.heard.wait(self.heard_within)
        self.close()
        return heard

    def close(self) -> None:
        """Stop the inbox, where one is serving."""
        if self.inbox is not None:
            self.inbox.stop()
            self.inbox = None

    def launch(self, handoff: Handoff) -> None:
        """Hand a session's launch over, having told the tab where it opens."""
        self.concluded(
            Continuation(
                message=f"Approved: {self.named} opens in your terminal.", final=True
            )
        )
        executed(handoff)

    def run(self, handoff: Handoff) -> None:
        """Hand a command over, beside this launcher where a tab waits for its page.

        Without a tab it is handed over the way a launch is, and opens its
        pages itself. With one, it runs as a child on this terminal, told
        where to hand its first page, and this launcher ends with its status.
        """
        if self.inbox is None or not self.tab:
            self.close()
            executed(handoff)
            return
        directory = Path(tempfile.mkdtemp(prefix="lup-review-tab-"))
        handshake = directory / "page.json"
        told = handoff.model_copy(
            update={
                "environment": {
                    **handoff.environment,
                    REVIEW_TAB_ENV: str(handshake),
                }
            }
        )
        try:
            status = self.followed(told, handshake)
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        raise typer.Exit(status)

    def followed(self, handoff: Handoff, handshake: Path) -> int:
        """Run a command beside this launcher, sending the tab to the first page it opens.

        The command owns the terminal, so the signals typed at it are its to
        act on: this launcher ignores them while it waits, as a shell does.
        """
        self.told.say(
            Continuation(
                message=(
                    f"Approved: {self.named} is starting in your terminal, and this "
                    "tab goes on to the page it opens."
                )
            )
        )
        running = self.spawn(handoff)
        ignored = {
            number: signal.signal(number, signal.SIG_IGN)
            for number in (signal.SIGINT, signal.SIGQUIT)
        }
        try:
            for _ in iter(lambda: self.inbox is not None and running.is_alive(), False):
                page = announced_page(handshake)
                if page is None:
                    time.sleep(0.1)
                    continue
                self.sent_to(page, running)
            status = exit_status(running)
        finally:
            for number, previous in ignored.items():
                signal.signal(number, previous)
        self.concluded(
            Continuation(
                message=f"{self.named} has finished in your terminal.", final=True
            )
        )
        return status

    def sent_to(self, page: str, running: sh.RunningCommand) -> None:
        """Send the tab to a page once it answers, or open it anew where the tab has gone."""
        answering(page, self.page_within, running.is_alive)
        heard = self.concluded(
            Continuation(message=f"Opening {page}", url=page, final=True)
        )
        if not heard:
            self.opened(page)
