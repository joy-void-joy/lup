"""`lup-dev spawn trial`: the whole of a held session, tried once on the operator's machine, its report filed in their inbox.

A room has no podman, so no agent can run a held session end to end: this is
the operator's one command that does, on the real host service and a real
runtime, in a scratch worktree of the repository it's run in, which the
operator approved already. Each step says what it proves, and what failing it
would mean:
1. **held:** a session starts held, its launch's whole setup done by a launcher
   the host service started apart, called up once its first hook was heard;
   how long that took is what a launch costs;
2. **answers:** the operator's words through the inbox, as the dashboard sends
   them, reach the idle session as its next turn, and its answer comes back as
   its turn's end, as a terminal session's does;
3. **interrupts:** a turn running a long command is ended through the host, and
   the session takes the operator's next words;
4. **survives a restart:** the host service stops and starts again, the session
   and its room untouched, and the operator's words still reach it;
5. **ends:** the host ends the session and its room;
6. **resumes held:** the session resumes held, its conversation kept;
7. **a terminal takes it over:** a terminal launch resuming it finds it held,
   ends it on the operator's word, and runs a turn of its own on it;
8. **back to held:** held again, it has the terminal's turn in its record.

What it doesn't try: the runtime with no held session yet, holds of hours, a
dashboard's own clicks, a real interactive terminal (its turn runs with `-p`,
in the terminal's own launch).
"""

import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from lup.errors import LupError
from lup.types import Model, MutableModel
from lup_dev.clock import Clock
from lup_dev.errors import LupDevError
from lup_dev.host.client import HostClient
from lup_dev.host.held import End, HeldUp, Interrupt
from lup_dev.host.protocol import Done, HostError, Listed, Register
from lup_dev.inbox.protocol import (
    FileReport,
    FinishItem,
    Items,
    ListItems,
    SendItem,
    Shown,
)
from lup_dev.inbox.texts import written
from lup_ledger.parties import Conversation, Operator

if TYPE_CHECKING:
    from lup_dev.git import Git
    from lup_dev.inbox.store import Item


class TerminalRun(Model):
    """A terminal launch's run, as the trial drives it: its status, what it printed, and the questions it asked."""

    status: int
    output: str
    asked: list[str] = []


class Stage(Model, arbitrary_types_allowed=True):
    """One step of the trial as it's tried: its name, what failing it would mean, what tries it, and whether a failure leaves nothing after it to try."""

    name: str
    meaning: str
    """What failing it would mean, as the report says it."""
    tried: Callable[[], str]
    """Tries it, returning what was seen; raising where it didn't come to pass."""
    stops: bool = False
    """Whether nothing after it can be tried where it fails."""


class Step(Model):
    """One step of the trial once tried: its stage's name and meaning, whether it passed, what was seen, and how long it took."""

    name: str
    meaning: str
    passed: bool
    seen: str
    took: timedelta


class Trial(MutableModel, arbitrary_types_allowed=True):
    """The trial's run: what it reaches, and what it saw."""

    host: HostClient
    spawn: Callable[[Path, str | None], HeldUp]
    """Starts a held session in the worktree given, resuming the session given,
    and returns it once it's up: `lup-dev spawn`'s own path."""
    terminal: Callable[[Path, str], TerminalRun]
    """Runs a terminal launch resuming the session given in the worktree
    given, answering its question to take a held session over yes, and
    returns how it ran."""
    running: Callable[[str], bool]
    """Says whether the container named runs, as podman says."""
    clock: Clock
    say: Callable[[str], None]
    worktree: Path
    """The scratch worktree the trial runs in."""
    patience: timedelta = timedelta(minutes=4)
    """How long an answer, a call or an end may take to show."""
    look: timedelta = timedelta(seconds=2)
    """How long apart the trial looks for what it waits on."""
    steps: list[Step] = []
    up: HeldUp | None = None
    conversation: Conversation | None = None

    def stages(self) -> list[Stage]:
        """Return the trial's steps, in the order they're tried, each with what failing it would mean."""
        return [
            Stage(
                name="held",
                meaning=(
                    "no session is held on this machine: what it saw says why, the "
                    "end of the launcher's log among it, and nothing after this "
                    "step was tried; a host service on a copy of lup from before "
                    "held sessions refuses `spawn` outright"
                ),
                tried=self.held,
                stops=True,
            ),
            Stage(
                name="answers",
                meaning=(
                    "the operator's words don't reach an idle held session, or its "
                    "answer doesn't come back: the inbox's wake through the "
                    "launcher, or the session's hooks, are broken"
                ),
                tried=self.answers,
            ),
            Stage(
                name="interrupts",
                meaning=(
                    "the dashboard's interrupt wouldn't stop a held session, or the "
                    "session wouldn't take words after one"
                ),
                tried=self.interrupts,
            ),
            Stage(
                name="survives a restart",
                meaning=(
                    "a restart of the host service, which every approval makes, "
                    "would take held sessions with it, or leave them unreachable"
                ),
                tried=self.restarted,
            ),
            Stage(
                name="ends",
                meaning="a held session's end leaves its room or its launch behind",
                tried=self.ends,
                stops=True,
            ),
            Stage(
                name="resumes held",
                meaning="an ended held session can't be picked up again held",
                tried=self.resumed,
            ),
            Stage(
                name="a terminal takes it over",
                meaning=(
                    "the way from held to a terminal is broken: the lock on its "
                    "writer, the end it asks, or the resume"
                ),
                tried=self.taken_over,
            ),
            Stage(
                name="back to held",
                meaning=(
                    "the way back from a terminal to held is broken, or the two "
                    "wrote records apart"
                ),
                tried=self.back,
            ),
        ]

    def run(self) -> list[Step]:
        """Try each step in order, stopping at the first failure that leaves nothing to try after it, and return what each saw; end whatever the trial left running."""
        try:
            self.steps = []
            for stage in self.stages():
                if not self.stepped(stage) and stage.stops:
                    break
        finally:
            self.ended()
        return self.steps

    def stepped(self, stage: Stage) -> bool:
        """Try one step, keep what it saw, say it, and say whether it passed: what lup or podman refused fails it, saying why."""
        began = self.clock.now()
        self.say(f"Trying: {stage.name}…")
        try:
            seen = stage.tried()
            passed = True
        except (LupDevError, LupError, OSError) as failed:
            seen = str(failed)
            passed = False
        done = Step(
            name=stage.name,
            meaning=stage.meaning,
            passed=passed,
            seen=seen,
            took=self.clock.now() - began,
        )
        self.steps = [*self.steps, done]
        said = "Passed" if passed else "Failed"
        self.say(f"{said}: {stage.name} ({spelled(done.took)}). {seen}")
        return passed

    def launch(self) -> Register:
        """Return the held launch as the host serves it; raise where it isn't served."""
        if self.up is None:
            message = "no held session is up"
            raise TrialError(message)
        up = self.up
        served = [each for each in self.host.launches() if each.launch == up.launch]
        if not served:
            message = f"the host serves no launch `{up.launch}`"
            raise TrialError(message)
        return served[0]

    def held(self) -> str:
        """Start the session held, and see the host serve it as held."""
        self.up = self.spawn(self.worktree, None)
        launch = self.launch()
        if not launch.held:
            message = f"`{launch.name}` is served, but not as a held session"
            raise TrialError(message)
        return (
            f"`{self.up.name}` holds the session {self.up.session}, its launcher's "
            f"log at {self.up.log}."
        )

    def answers(self) -> str:
        """Send the session words, and see its answer come back."""
        return self.answered(
            "Answer with the single word PAPAYA, and nothing else.", "PAPAYA"
        )

    def interrupts(self) -> str:
        """Have the session run a long command, interrupt it, see the turn end aborted, and the session take words after."""
        launch = self.launch()
        self.sent(
            "Run this in your shell, in the foreground, and wait for it to finish: "
            "python3 -c 'import time; time.sleep(600)'. Then answer with the single "
            "word LATE."
        )
        self.until(
            lambda: self.calling(launch.launch),
            "the session didn't start the long command",
        )
        self.host.ask(Interrupt(launch=launch.launch), Done)
        log = launch_log(self.up)
        self.until(
            lambda: "aborted_tools" in log.read_text(errors="replace"),
            "the launcher's log says no turn ended aborted after the interrupt",
        )
        answer = self.answered(
            "That was interrupted on purpose. Answer with the single word PEAR.",
            "PEAR",
        )
        return f"The turn ended at the interrupt, and then: {answer}"

    def restarted(self) -> str:
        """Stop the host service and start it again, see the session served and its room running, and its answer come back."""
        launch = self.launch()
        self.host.stop()
        self.host.ensure()
        again = self.launch()
        if not again.held:
            message = "the restarted service serves the launch, but not as held"
            raise TrialError(message)
        if launch.container is None or not self.running(launch.container):
            message = f"the room, {launch.container}, stopped with the service"
            raise TrialError(message)
        answer = self.answered("Answer with the single word MANGO.", "MANGO")
        return f"The service restarted, the room ran on, and then: {answer}"

    def ends(self) -> str:
        """End the session through the host, and see its launch and its room gone."""
        launch = self.launch()
        outstanding = self.host.held(End(launch=launch.launch))
        try:
            outstanding.reply(Done)
        finally:
            outstanding.close()
        self.until(
            lambda: launch.launch not in [each.launch for each in self.host.launches()],
            "the launch is still served after its end",
        )
        if launch.container is not None and self.running(launch.container):
            message = f"its room, {launch.container}, runs on after its end"
            raise TrialError(message)
        return "The session, its launch and its room ended."

    def resumed(self) -> str:
        """Resume the session held, and see it remember its first word."""
        session = self.session()
        self.up = self.spawn(self.worktree, session)
        answer = self.answered(
            "Which single word did I first ask you to answer with? Answer with "
            "that word alone.",
            "PAPAYA",
        )
        return f"Held again, it remembered: {answer}"

    def taken_over(self) -> str:
        """Have a terminal launch resume the held session, take it over, and answer."""
        session = self.session()
        held = self.launch()
        run = self.terminal(self.worktree, session)
        if not any("take it over" in each for each in run.asked):
            message = (
                "the terminal launch didn't ask to take the held session over; it "
                f"asked {run.asked or 'nothing'}, and printed:\n{run.output}"
            )
            raise TrialError(message)
        if run.status != 0 or "KIWI" not in run.output:
            message = (
                f"the terminal's turn ended with status {run.status} without the "
                f"word asked; it printed:\n{run.output}"
            )
            raise TrialError(message)
        if held.launch in [each.launch for each in self.host.launches()]:
            message = "the held launch is still served after the terminal took over"
            raise TrialError(message)
        return "The terminal ended the held launch, took the session, and answered."

    def back(self) -> str:
        """Resume the session held again, and see the terminal's turn in its record."""
        session = self.session()
        self.up = self.spawn(self.worktree, session)
        answer = self.answered(
            "List, in order, each single word I asked you to answer with so far, "
            "separated by spaces, and nothing else.",
            "KIWI",
        )
        return f"Held again after the terminal, its record had the terminal's turn: {answer}"

    def session(self) -> str:
        """Return the runtime's id for the session held last."""
        if self.up is None:
            message = "no session was held to resume"
            raise TrialError(message)
        return self.up.session

    def sent(self, text: str) -> Item:
        """Send the operator's words to the held session, as the dashboard does, and return the item."""
        launch = self.launch()
        shown = self.host.ask(SendItem(launch=launch.launch, text=text), Shown)
        recipient = shown.item.recipient
        if isinstance(recipient, Conversation):
            self.conversation = recipient
        return shown.item

    def answered(self, text: str, word: str) -> str:
        """Send `text`, and wait for the session's answer holding `word`: their turn's end in the operator's inbox."""
        sent = self.sent(text)
        found: list[Item] = []

        def came() -> bool:
            found[:] = [
                each
                for each in self.items()
                if each.number > sent.number
                and isinstance(each.recipient, Operator)
                and word.lower() in written(each).lower()
            ]
            return bool(found)

        self.until(came, f"no answer holding {word} came within {self.patience}")
        return f"it answered {written(found[0]).strip()!r}, @{found[0].number}."

    def items(self) -> list[Item]:
        """Return the items the session sent and was sent."""
        if self.conversation is None:
            return []
        return self.host.ask(ListItems(conversation=self.conversation), Items).items

    def calling(self, launch: str) -> bool:
        """Say whether the session's own conversation is running a call, as the host last heard."""
        listed: Listed = self.host.listed()
        return any(
            each.agent is None
            and each.activity is not None
            and each.activity.state == "calling"
            for each in listed.talkers.get(launch, [])
        )

    def until(self, done: Callable[[], bool], failure: str) -> None:
        """Wait, looking every `look`, until `done()`; raise `TrialError` saying `failure` past `patience`."""
        began = self.clock.now()
        while not done():
            if self.clock.now() - began >= self.patience:
                raise TrialError(failure)
            self.clock.sleep(self.look.total_seconds())

    def ended(self) -> None:
        """End the held launch the trial left running, where one is, saying what fails."""
        if self.up is None:
            return
        up = self.up
        try:
            served = [each.launch for each in self.host.launches()]
            if up.launch not in served:
                return
            outstanding = self.host.held(End(launch=up.launch))
            try:
                outstanding.reply(Done)
            finally:
                outstanding.close()
        except (LupDevError, LupError, OSError) as failed:
            self.say(f"The trial's held launch `{up.name}` wasn't ended: {failed}")

    def report(self) -> str:
        """Return the report: each step, whether it passed and what it saw, then what that means."""
        lines = [
            (
                f"**Spawn's trial**, `lup-dev spawn trial`, in {self.worktree}: "
                f"{sum(each.passed for each in self.steps)} of "
                f"{len(self.stages())} steps passed."
            ),
            "",
            *(
                f"- **{each.name}**, {'passed' if each.passed else 'failed'} in "
                f"{spelled(each.took)}: {each.seen}"
                for each in self.steps
            ),
            "",
        ]
        failed = [each for each in self.steps if not each.passed]
        ran = [each.name for each in self.steps]
        untried = [each.name for each in self.stages() if each.name not in ran]
        if not failed and not untried:
            lines.append(
                "**What it means:** a session lup holds with no terminal works end "
                "to end on this machine, on this runtime: it starts held, takes "
                "your words as its turns, answers into your inbox, stops at an "
                "interrupt, outlives a restart of the host service, ends, "
                "resumes, and passes to a terminal and back. A launch's setup "
                f"took {spelled(self.steps[0].took)}. Not tried here: the other "
                "runtime, holds of hours, and an interactive terminal."
            )
        else:
            lines.extend(
                f"**{each.name}** failing means {each.meaning}." for each in failed
            )
            if untried:
                lines.append(f"Not tried, after that: {', '.join(untried)}.")
        return "\n".join(lines)

    def filed(self, repository: Path, runtime: str) -> int:
        """File the report in the operator's inbox, as a note from the session it tried, or one named after the trial where none started, and take that session's answers off the operator's list; return the report's number."""
        for each in self.items():
            if isinstance(each.recipient, Operator) and isinstance(
                each.sender, Conversation
            ):
                try:
                    self.host.ask(FinishItem(number=each.number), Shown)
                except HostError as kept:
                    self.say(f"@{each.number} stays on your list: {kept}")
        sender = self.conversation or Conversation(
            repository=repository,
            runtime=runtime,
            session=f"spawn-trial-{uuid.uuid4()}",
        )
        shown = self.host.ask(
            FileReport(sender=sender, text=self.report(), worktree=self.worktree),
            Shown,
        )
        return shown.item.number


class TrialError(LupDevError):
    """A step of the trial that didn't come to pass."""


def launch_log(up: HeldUp | None) -> Path:
    """Return where the held launch's launcher writes; raise where none is up."""
    if up is None:
        message = "no held session is up"
        raise TrialError(message)
    return up.log


def spelled(took: timedelta) -> str:
    """Spell a step's time in whole seconds, or minutes and seconds.

    >>> spelled(timedelta(seconds=75.4)), spelled(timedelta(seconds=9))
    ('1 min 15 s', '9 s')
    """
    seconds = round(took.total_seconds())
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} min {rest} s" if minutes else f"{rest} s"


def scratch_worktree(beside: Path, git: Git, name: str, commit: str) -> Path:
    """Make a scratch worktree named `name` in the directory `beside`, detached at `commit`, for the trial, and return it.

    `git` is pinned to the repository's common git directory (`Git.pinned`):
    run in a worktree, git would follow the worktree's git directory, which a
    room writes, its `commondir` among it, to a `config` whose filters the
    checkout would run on the host (`docs/field-notes.md`, *Host-side git in a
    repository the room writes*).
    """
    scratch = beside / name
    git.run("worktree", "add", "--detach", str(scratch), commit)
    return scratch
