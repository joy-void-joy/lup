"""The judge's tools in a launched session: `judged`, what lup's judge made of the writes in the session's repository; `quiet`, which findings it holds back after the conversation's calls.

`docs/inbox.md`, *lup's tools*. The judge runs on the host, and keeps its
verdict log and its holds in lup's state there, which no room mounts
(`docs/judging-writes.md`, *The verdict log*, *Asking the operator*), so a
session can't see from its room whether a write landed, was flagged, or waited
for the operator. `judged` reads them for the conversation calling, changing
nothing. The host service serves the judge's tools as a `RoomTools` beside the
inbox's, with lup's state (`Layout`) and its clock; the inbox sits below the
judge in `lup_dev`'s layers, so its tools don't read the judge's stores.

`quiet` (`Quieter`; `docs/judging-writes.md`, *Quiet*) is served beside it and
run in the repository's process (`JudgeCalling`), as a module's tool is: lifting
a quiet tells what stands in the conversation's files, which the engine the
judge keeps warm there reads (`policy/quiet.py`). Its approved copy answers it,
so a copy that predates it refuses the call, which says so.

- **Whose verdicts:** the calling session's, by default: the log records each
  verdict's runtime and session, not which of the session's conversations
  wrote, so a subagent reads their session's. `every` reads every session's, and
  a move of `HEAD`'s, which is no session's.
- **Which holds:** the repository's, whoever made them (`logged`,
  `policy/holds.py`): those still open, and those answered where they're asked
  for, else counted. A held verdict's answer is its hold's where the operator
  gave one: the log has an approval only once the judge hears the call that
  waited finish (`settled`).
- **When:** `since` and `until` narrow the verdicts and the holds alike, by
  when each was made: a time, one without a zone read as the host's, as the
  answer says times (`clocked`); or a duration, counted back by the host
  service's clock.
- **Sized to be read whole:** an answer counts the verdicts it selects by
  outcome and reason (`tallied`, as `lup-dev verdicts` does), then lists the
  latest of them, and of each group of holds, up to the call's `limit` and
  `holds_limit` (`lup_dev.listing`). Where it leaves some out, it says how many,
  the `until` that reads them and the limit that lists them all, so nothing is
  out of reach. lup's own log held 4,000 verdicts after ten days, 785,000
  characters listed whole: more than a tool's result holds.
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

from pydantic import Field, JsonValue, PositiveInt

import lup
from lup.doors import bound, declared
from lup.tools.serving import Answer
from lup.tools.tool import Accepted, Refused, ToolSpec
from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import HostError, Register
from lup_dev.host.rooms import RoomTools
from lup_dev.host.workers import Called, JudgeCalling, LaunchModules
from lup_dev.inbox.delivery import clocked
from lup_dev.layout import Layout
from lup_dev.listing import Span, latest, many, unlisted
from lup_dev.policy.checkpoint import Bench
from lup_dev.policy.holds import Hold, Holds, logged
from lup_dev.policy.quiet import quieted
from lup_dev.policy.report import Kind
from lup_dev.policy.verdicts import Verdict, VerdictLog, tallied


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


class Scope(Span):
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
    answered: bool = Field(
        default=False,
        description=(
            "The holds the operator answered, listed too; left out, those still "
            "open alone, and the answered counted."
        ),
    )
    limit: PositiveInt = Field(
        default=50,
        description=(
            "How many verdicts to list at most, the latest: about 10,000 "
            "characters with `every`. Those left out are counted."
        ),
    )
    holds_limit: PositiveInt = Field(
        default=20,
        description="How many holds of each state to list at most, the latest.",
    )

    def covers(self, verdict: Verdict) -> bool:
        """Say whether `verdict` judged the file `path` names, by its path relative to its worktree or by its absolute one; every verdict, where it names none."""
        return self.path is None or self.path in [verdict.path, where(verdict)]

    def on(self) -> str:
        """Say what `path` narrows a heading to, or nothing where it names no file."""
        return "" if self.path is None else f" on {self.path}"


class Onlooker(Model, arbitrary_types_allowed=True):
    """One conversation of a launch, reading what the judge made of the writes in their repository: the tool's function, bound to them."""

    layout: Layout
    """lup's state on the host, where the verdict logs and the stores are."""
    launch: Register
    caller: Conversation
    clock: Clock
    """The host service's clock, which a duration in `since` or `until` counts
    back from."""

    @lup.tool(reads=True)
    async def judged(self, scope: Scope) -> str:
        """Read the judge's verdicts and holds.

        What lup's judge, on the host, made of each write in this repository,
        which your room doesn't show. First its verdicts counted by outcome
        and reason; then the latest of them, oldest first, a line each: when,
        the file, the tool that wrote it (`checkpoint` where a checkpoint
        found the change, `move` where a move of `HEAD` brought it), the
        outcome, its reasons, and the operator's answer where one came.
        `allow` lands; `hold` waits for the operator's answer, the call that
        wrote it waiting with it, however long they take. The reasons are what
        a hold waits on (`protected`, `operator`, `new-file`, `whole-file`,
        `public-api`, `ignore`, a rule); for an allow, what it flags for the
        operator's review, else the rules of the findings told, else the file's
        role (`rules-pass` for production code). Your session's verdicts by
        default, every session's with `every`. Then this repository's holds
        still open, and with `answered` those answered too: each with its key,
        when it was made and by whom, where it stands, whether a call
        still waits on it among that, its files with what each asks, and the
        operator's comment. `path`, `since` and `until` narrow the
        verdicts and the holds alike, and `limit` and `holds_limit` say how
        many to list. Where it leaves earlier ones out, the answer says how
        many, the `until` that reads them, and the limit that lists them all.
        It changes nothing.
        """
        return await asyncio.to_thread(self.read, scope)

    def read(self, scope: Scope) -> str:
        """Say the verdicts and the holds `scope` asks for: the log read whole, and every store, off the service's event loop."""
        log = VerdictLog(path=self.layout.verdicts(self.launch.repository)).read()
        kept = logged(self.layout, log)
        window = scope.window(self.clock.now())
        held = {verdict.key: hold for hold in kept for verdict in hold.verdicts}
        verdicts = sorted(
            (
                settled(verdict, held.get(verdict.key))
                for verdict in log
                if scope.covers(verdict)
                and window.covers(verdict.time)
                and (scope.every or self.ours(verdict))
            ),
            key=lambda verdict: verdict.time,
        )
        holds = [
            hold
            for hold in kept
            if window.covers(hold.created)
            and any(scope.covers(verdict) for verdict in hold.verdicts)
        ]
        narrowed = f"{scope.on()}{window.said()}"
        return "\n\n".join(
            [
                *self.verdicts(verdicts, narrowed, scope),
                *self.holds(holds, narrowed, scope),
            ]
        )

    def ours(self, verdict: Verdict) -> bool:
        """Say whether `verdict` judged a write of the calling session."""
        return (
            verdict.runtime == self.launch.runtime
            and verdict.session == self.caller.session
        )

    def verdicts(
        self, verdicts: list[Verdict], narrowed: str, scope: Scope
    ) -> list[str]:
        """Say `verdicts`: counted by outcome and reason, then the latest a line each, up to `scope`'s limit, with how many it leaves out; or that there's none."""
        every = scope.every
        if not verdicts:
            whose = "No session has a" if every else "Your session has no"
            return [f"{whose} verdict in this repository{narrowed}."]
        whose = "Every session's" if every else "Your session's"
        counted = [
            (
                f"{whose} {many(len(verdicts), 'verdict')} in this "
                f"repository{narrowed}, by outcome and reason:"
            ),
            *(tally.line() for tally in tallied(verdicts)),
        ]
        shown = latest(verdicts, lambda verdict: verdict.time, scope.limit)
        heading = (
            "Each, oldest first:"
            if len(shown) == len(verdicts)
            else f"The latest {len(shown)}, oldest first:"
        )
        lines = [
            heading,
            *(self.line(verdict, every=every) for verdict in shown),
            *unlisted(
                len(verdicts) - len(shown),
                "earlier verdict",
                shown[0].time,
                len(verdicts),
            ),
        ]
        return ["\n".join(counted), "\n".join(lines)]

    def line(self, verdict: Verdict, *, every: bool) -> str:
        """Say a verdict in a line: when, the file, the tool, the outcome with its reasons, the operator's answer, and with `every`, whose."""
        reasons = ", ".join(verdict.reasons)
        said = (
            f"{clocked(verdict.time)}  {where(verdict)}  {verdict.tool}  "
            f"{verdict.outcome} ({reasons}){answer(verdict)}"
        )
        if not every:
            return said
        if verdict.session is None:
            return f"{said}, by no session"
        if self.ours(verdict):
            return f"{said}, by your session"
        return f"{said}, by {verdict.runtime} session {verdict.session}"

    def holds(self, holds: list[Hold], narrowed: str, scope: Scope) -> list[str]:
        """Say `holds`: those still open; those answered where `scope` asks for them, else how many; or that there's none."""
        if not holds:
            return [f"This repository has no hold{narrowed}."]
        still = [hold for hold in holds if hold.answer is None]
        done = [hold for hold in holds if hold.answer is not None]
        listed = (
            [self.listing(still, "still open", narrowed, scope.holds_limit)]
            if still
            else [f"This repository has no hold still open{narrowed}."]
        )
        if not done:
            return listed
        if scope.answered:
            return [
                *listed,
                self.listing(done, "answered", narrowed, scope.holds_limit),
            ]
        counted = (
            f"Not listed: {many(len(done), 'hold')} answered{narrowed}, which "
            "`answered` lists."
        )
        return [*listed, counted]

    def listing(self, holds: list[Hold], state: str, narrowed: str, most: int) -> str:
        """Say `holds`, which share a `state`, under their heading: the latest `most`, with how many it leaves out."""
        shown = latest(holds, lambda hold: hold.created, most)
        return "\n".join(
            [
                f"This repository's holds {state}{narrowed}, oldest first:",
                *(self.held(hold) for hold in shown),
                *unlisted(
                    len(holds) - len(shown),
                    "earlier hold",
                    shown[0].created,
                    len(holds),
                    state=f" {state}",
                    limit="holds_limit",
                ),
            ]
        )

    def held(self, hold: Hold) -> str:
        """Say a hold: its key, when it was made and by whom, where it stands, each file with what it asks, and the operator's comment."""
        made = (
            f"a change by {self.maker(hold)}"
            if hold.commit is None
            else f"what commit {hold.commit} brought, found by {self.maker(hold)}"
        )
        waited = Holds(layout=self.layout.store(hold.worktree)).waited_on(hold.key)
        head = f"{hold.key}  {clocked(hold.created)}  {made}, {stands(hold, waited=waited)}"
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


def settled(verdict: Verdict, hold: Hold | None) -> Verdict:
    """Return a verdict with the operator's answer: its hold's, where it was held and they answered; else the one logged.

    The hold has their answer as soon as they give it. The log has an approval
    of a write its agent waited on only once the judge hears their call finish,
    which a runtime whose hooks don't report a call's finish never tells it.
    """
    if hold is None or hold.answer is None:
        return verdict
    given = "approved" if hold.answer.approved else "declined"
    return verdict.model_copy(update={"answer": given})


def answer(verdict: Verdict) -> str:
    """Say the operator's answer to a verdict, after its outcome: the one it has; else that none came yet to what waits for one, or nothing."""
    if verdict.answer is not None:
        return f", {verdict.answer}"
    if verdict.outcome in ["ask", "hold"]:
        return ", no answer yet"
    return ""


def stands(hold: Hold, *, waited: bool) -> str:
    """Say where a hold stands: answered, and when; or waiting, and whether a call waits with it, which `waited` says (`Holds.waited_on`)."""
    if hold.answer is not None:
        verdict = "approved" if hold.answer.approved else "declined"
        return f"{verdict} at {clocked(hold.answer.time)}"
    if hold.commit is not None:
        return "waiting for the operator, no call waiting on it"
    if hold.interrupted:
        return (
            "waiting for the operator: its call was interrupted, so the change was "
            "put back and its version saved"
        )
    if hold.abandoned:
        return (
            "waiting for the operator: nobody answered in time, so the change was "
            "put back and its version saved"
        )
    if waited:
        return "waiting for the operator, its call waiting on their answer"
    return (
        "waiting for the operator, no call waiting on it any more: lup's host "
        "service went away mid-wait, and their answer reaches its session at a "
        "later call"
    )


class Quieting(Model):
    """Which findings to hold back after your calls."""

    kinds: list[Kind] = Field(
        description=(
            "The kinds of findings lup holds back after your calls: `rules`, lup's "
            "findings on the lines you changed; `changed`, type errors and ruff's "
            "findings in the files changed; `untouched`, lup's findings on lines "
            "no change touched; `importers`, type errors in files importing what "
            "changed. Empty lifts the quiet, and the answer tells what stands "
            "that you weren't told."
        )
    )


class Quieter(Model, arbitrary_types_allowed=True):
    """One conversation of a launch, asking lup to hold some findings back after their calls: the tool's function, bound to them, in the repository's process."""

    bench: Bench
    """The judge's bench, with the launch's runtime, made once for the process."""
    caller: Conversation

    @lup.tool
    async def quiet(self, quieting: Quieting) -> str:
        """Hold back some findings until you lift it.

        In a wide change, a refactor across many files or several edits in a
        row to one, you know the work is broken and will fix it later, so
        being told each finding after each call is noise. lup holds back the
        `kinds` of findings named, after every call of yours from then on:
        they aren't told, and aren't counted told. A call naming other kinds
        holds those instead. `kinds` empty lifts the quiet, and the answer
        tells once what stands then that you weren't told, in the files you
        touched and those importing them, as they stand rather than each
        state in between. Refusals, held writes and the operator's answers,
        moves of `HEAD`, values never published, and the list your turn's end
        is held on still come through. The quiet is yours alone, not your
        subagents' or your parent's, and lasts across turns until you lift it
        or your conversation ends.
        """
        return await asyncio.to_thread(
            quieted,
            self.bench,
            self.caller.session,
            self.caller.agent or "",
            quieting.kinds,
        )


async def judge_call(bench: Bench, calling: JudgeCalling) -> Answer:
    """Run, in the repository's process, a call to one of the judge's tools served there (`Quieter`), for the conversation calling: its arguments validated, its answer in words.

    Arguments that don't validate are refused, saying why, as the library's
    tools refuse them.
    """
    quieter = Quieter(bench=bench, caller=calling.caller)
    found = [tool for tool in bound(quieter) if tool.spec().name == calling.name]
    if not found:
        return Answer(
            text=f"lup's judge runs no tool named `{calling.name}` here", error=True
        )
    [tool] = found
    match await tool.call(calling.arguments):
        case Accepted(answer=said):
            return Answer(text=said)
        case Refused(rejection=rejection):
            return Answer(text=f"Refused: {rejection.reason}", error=True)


class JudgeTools(Model, RoomTools, arbitrary_types_allowed=True):
    """The judge's tools, as the host service serves them to each launched session, beside the inbox's."""

    layout: Layout
    """lup's state on the host, where the verdict logs and the stores are."""
    clock: Clock
    """The host service's clock."""
    modules: LaunchModules
    """Each launch's repository's process, which runs `quiet` (`Quieter`)."""

    @override
    def specs(self) -> list[ToolSpec]:
        return [*declared(Onlooker).values(), *declared(Quieter).values()]

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

        `judged` runs here; `quiet` in the launch's repository's process, which
        says why where it couldn't. Arguments that don't validate are refused,
        saying why, as the library's tools refuse them.
        """
        if name in declared(Quieter):
            return await self.relayed(name, arguments, launch, caller)
        onlooker = Onlooker(
            layout=self.layout, launch=launch, caller=caller, clock=self.clock
        )
        [tool] = [tool for tool in bound(onlooker) if tool.spec().name == name]
        match await tool.call(arguments):
            case Accepted(answer=said):
                return Answer(text=said)
            case Refused(rejection=rejection):
                return Answer(text=f"Refused: {rejection.reason}", error=True)

    async def relayed(
        self, name: str, arguments: JsonValue, launch: Register, caller: Conversation
    ) -> Answer:
        """Pass a call to `name` to `launch`'s repository's process, and return what it answered; where it couldn't, say why, a copy that predates the tool among it."""
        calling = JudgeCalling(
            launch=launch, name=name, arguments=arguments, caller=caller
        )
        try:
            reply = await self.modules.ask(launch, calling)
        except HostError as failed:
            return Answer(
                text=(
                    f"`{name}` didn't run: {failed}. Where the repository's process "
                    "answers no `judge-call`, its approved copy of lup predates "
                    f"`{name}`, which runs once the operator approves one that has it."
                ),
                error=True,
            )
        match reply:
            case Called(answer=answer):
                return answer
            case _:
                return Answer(
                    text=f"`{name}` didn't run: the repository's process replied {reply.kind}",
                    error=True,
                )
