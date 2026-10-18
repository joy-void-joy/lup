"""The judge's tool in a launched session: `judged`, what lup's judge made of the writes in the session's repository.

`docs/host-tools.md`, *lup's tools*. The judge runs on the host, and keeps its
verdict log and its holds in lup's state there, which no room mounts
(`docs/judging-writes.md`, *The verdict log*, *Asking the operator*), so a
session can't see from its room whether a write landed, was flagged, or waited
for the operator. `judged` reads them for the conversation calling, changing
nothing. The host service serves it as a `RoomTools` beside the inbox's, with
lup's state (`Layout`); the inbox sits below the judge in `lup_dev`'s layers, so
its tools don't read the judge's stores.

- **Whose verdicts:** the calling session's, by default: the log records each
  verdict's runtime and session, not which of the session's conversations
  wrote, so a subagent reads its session's. `every` reads every session's, and
  a move of `HEAD`'s, which is no session's.
- **Which holds:** the repository's, open and answered, whoever made them
  (`logged`, `policy/holds.py`). A held verdict's answer is its hold's where
  the operator gave one: the log has an approval only once the judge hears the
  call that waited finish (`answer`).
- **Nothing outside the repository:** what's listed is the launch's
  repository's, whose git directory the launcher found on the host
  (`Register.repository`), never one the room names. Every store is read to
  find its holds, and only those its log names are listed; `path` narrows
  what's listed, and names nothing to read.

A tool's docstring's first line is its summary, 50 characters at most, which the
guidance lists (`launch/guidance.py`); the rest is its description, which the
runtime's tool search finds. It answers in words, as `content`.
"""

import asyncio
from pathlib import Path
from typing import override

from pydantic import Field, JsonValue

from lup.tools.serving import Answer
from lup.tools.tool import Accepted, Refused, ToolSpec, bound, declared, lup_tool
from lup.types import Model
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import Register
from lup_dev.host.rooms import RoomTools
from lup_dev.inbox.delivery import clocked
from lup_dev.layout import Layout
from lup_dev.policy.holds import Hold, logged
from lup_dev.policy.verdicts import Verdict, VerdictLog


def where(verdict: Verdict) -> Path:
    """Return the file a verdict judged: absolute where the log names its worktree, as lup's reports name a file; else relative to it, as logged.

    >>> from datetime import UTC, datetime
    >>> verdict = Verdict(key="k", time=datetime(2026, 1, 1, tzinfo=UTC), session="s1",
    ...     runtime="r", tool="Edit", worktree=Path("/w"), path=Path("a.py"),
    ...     role="production", outcome="allow", reasons=["rules-pass"])
    >>> where(verdict)
    PosixPath('/w/a.py')
    """
    return verdict.path if verdict.worktree is None else verdict.worktree / verdict.path


class Scope(Model):
    """Which of the judge's verdicts and holds to read."""

    every: bool = Field(
        default=False,
        description=(
            "Every session's verdicts in this repository, each saying whose, a "
            "move of `HEAD`'s among them; left out, your session's alone."
        ),
    )
    path: Path | None = Field(
        default=None,
        description=(
            "One file to narrow the verdicts and the holds to: absolute, as lup's "
            "reports name it, or relative to its worktree's root, which matches it "
            "in every worktree. Left out, every file."
        ),
    )

    def covers(self, verdict: Verdict) -> bool:
        """Say whether `verdict` judged the file `path` names, by its path relative to its worktree or by its absolute one; every verdict, where it names none."""
        return self.path is None or self.path in [verdict.path, where(verdict)]

    def on(self) -> str:
        """Say what `path` narrows a heading to, or nothing where it names no file."""
        return "" if self.path is None else f" on {self.path}"


class Onlooker(Model):
    """One conversation of a launch, reading what the judge made of the writes in its repository: the tool's function, bound to it."""

    layout: Layout
    """lup's state on the host, where the verdict logs and the stores are."""
    launch: Register
    caller: Conversation

    @lup_tool
    async def judged(self, scope: Scope) -> str:
        """Read the judge's verdicts and holds.

        What lup's judge, on the host, made of each write in this repository,
        which your room doesn't show. Its verdicts, oldest first, a line each:
        when, the file, the tool that wrote it (`checkpoint` where a checkpoint
        found the change, `move` where a move of `HEAD` brought it), the
        outcome, its reasons, and the operator's answer where one came.
        `allow` lands; `hold` waits for the operator's answer, the call that
        wrote it waiting with it, however long they take. The reasons are what
        a hold waits on (`protected`, `operator`, `new-file`, `whole-file`,
        `public-api`, `ignore`, a rule); for an allow, what it flags for the
        operator's review, else the rules of the findings told, else the file's
        role (`rules-pass` for production code). Your session's verdicts by
        default, every session's with `every`. Then this repository's holds,
        those still open and those answered: each with its key, when it was
        made and by whom, where it stands, its files with what each asks, and
        the operator's comment. `path` narrows both to one file. It changes
        nothing.
        """
        return await asyncio.to_thread(self.read, scope)

    def read(self, scope: Scope) -> str:
        """Say the verdicts and the holds `scope` asks for: the log read whole, and every store, off the service's event loop."""
        log = VerdictLog(path=self.layout.verdicts(self.launch.repository)).read()
        kept = logged(self.layout, log)
        verdicts = sorted(
            (
                verdict
                for verdict in log
                if scope.covers(verdict) and (scope.every or self.ours(verdict))
            ),
            key=lambda verdict: verdict.time,
        )
        holds = [
            hold
            for hold in kept
            if any(scope.covers(verdict) for verdict in hold.verdicts)
        ]
        held = {verdict.key: hold for hold in kept for verdict in hold.verdicts}
        return "\n\n".join(
            [self.verdicts(verdicts, held, scope), *self.holds(holds, scope)]
        )

    def ours(self, verdict: Verdict) -> bool:
        """Say whether `verdict` judged a write of the calling session."""
        return (
            verdict.runtime == self.launch.runtime
            and verdict.session == self.caller.session
        )

    def verdicts(
        self, verdicts: list[Verdict], held: dict[str, Hold], scope: Scope
    ) -> str:
        """Say `verdicts`, a line each under their heading, each held one with the hold `held` keeps it in; or that there's none."""
        if not verdicts:
            whose = "No session has" if scope.every else "Your session has no"
            return f"{whose} verdict in this repository{scope.on()}."
        whose = "Every session's" if scope.every else "Your session's"
        heading = f"{whose} verdicts in this repository{scope.on()}, oldest first:"
        lines = [
            self.line(verdict, held.get(verdict.key), every=scope.every)
            for verdict in verdicts
        ]
        return "\n".join([heading, *lines])

    def line(self, verdict: Verdict, hold: Hold | None, *, every: bool) -> str:
        """Say a verdict in a line: when, the file, the tool, the outcome with its reasons, the operator's answer, its hold's where it was held, and with `every`, whose."""
        reasons = ", ".join(verdict.reasons)
        said = (
            f"{clocked(verdict.time)}  {where(verdict)}  {verdict.tool}  "
            f"{verdict.outcome} ({reasons}){answer(verdict, hold)}"
        )
        if not every:
            return said
        if verdict.session is None:
            return f"{said}, by no session"
        if self.ours(verdict):
            return f"{said}, by your session"
        return f"{said}, by {verdict.runtime} session {verdict.session}"

    def holds(self, holds: list[Hold], scope: Scope) -> list[str]:
        """Say `holds`, those still open, then those answered, each under its heading; or that there's none."""
        if not holds:
            return [f"This repository has no hold{scope.on()}."]
        groups = {
            "still open": [hold for hold in holds if hold.answer is None],
            "answered": [hold for hold in holds if hold.answer is not None],
        }
        return [
            "\n".join(
                [
                    f"This repository's holds {state}{scope.on()}, oldest first:",
                    *(self.held(hold) for hold in group),
                ]
            )
            for state, group in groups.items()
            if group
        ]

    def held(self, hold: Hold) -> str:
        """Say a hold: its key, when it was made and by whom, where it stands, each file with what it asks, and the operator's comment."""
        made = (
            f"a change by {self.maker(hold)}"
            if hold.commit is None
            else f"what commit {hold.commit} brought, found by {self.maker(hold)}"
        )
        head = f"{hold.key}  {clocked(hold.created)}  {made}, {stands(hold)}"
        files = [
            f"  {where(verdict)}: {', '.join(verdict.reasons)}"
            for verdict in hold.verdicts
        ]
        comment = (
            [f"  The operator's comment: {hold.answer.comment}"]
            if hold.answer is not None and hold.answer.comment
            else []
        )
        return "\n".join([head, *files, *comment])

    def maker(self, hold: Hold) -> str:
        """Name the conversation that made a hold's change, or found a move's, for the conversation calling.

        A hold records no runtime: its session's id is its runtime's own.
        """
        if hold.session != self.caller.session:
            subagent = "" if hold.agent is None else f"'s subagent {hold.agent}"
            return f"session {hold.session}{subagent}"
        if hold.agent == self.caller.agent:
            return "you"
        if hold.agent is None:
            return "your session's own conversation"
        return f"your session's subagent {hold.agent}"


def answer(verdict: Verdict, hold: Hold | None) -> str:
    """Say the operator's answer to a verdict, after its outcome: that of `hold`, where it was held and they answered; else the one logged; else that none came yet to what waits for one, or nothing.

    The hold has their answer as soon as they give it. The log has an approval
    of a write its agent waited on only once the judge hears its call finish,
    which a runtime whose hooks don't report a call's finish never tells it.
    """
    if hold is not None and hold.answer is not None:
        return ", approved" if hold.answer.approved else ", declined"
    if verdict.answer is not None:
        return f", {verdict.answer}"
    if verdict.outcome in ["ask", "hold"]:
        return ", no answer yet"
    return ""


def stands(hold: Hold) -> str:
    """Say where a hold stands: answered, and when; or waiting, and what waits with it."""
    if hold.answer is not None:
        verdict = "approved" if hold.answer.approved else "declined"
        return f"{verdict} at {clocked(hold.answer.time)}"
    if hold.commit is not None:
        return "waiting for the operator, no call waiting on it"
    if hold.abandoned:
        return (
            "waiting for the operator: nobody answered in time, so the change was "
            "put back and its version saved"
        )
    return "waiting for the operator, its call waiting on their answer"


class JudgeTools(Model, RoomTools):
    """The judge's tools, as the host service serves them to each launched session, beside the inbox's."""

    layout: Layout
    """lup's state on the host, where the verdict logs and the stores are."""

    @override
    def specs(self) -> list[ToolSpec]:
        return list(declared(Onlooker).values())

    @override
    async def call(
        self,
        name: str,
        arguments: JsonValue,
        launch: Register,
        caller: Conversation,
        call: str | None,
    ) -> Answer:
        """Run the tool `name` for `caller`, a conversation of `launch`: its arguments validated, its answer in words.

        Arguments that don't validate are refused, saying why, as the library's
        tools refuse them.
        """
        onlooker = Onlooker(layout=self.layout, launch=launch, caller=caller)
        [tool] = [tool for tool in bound(onlooker) if tool.spec().name == name]
        match await tool.call(arguments):
            case Accepted(answer=said):
                return Answer(text=said)
            case Refused(rejection=rejection):
                return Answer(text=f"Refused: {rejection.reason}", error=True)
