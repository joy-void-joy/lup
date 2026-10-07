"""The runtime-neutral events, the calls running, and the checkpoint.

The judging core never sees a runtime: each adapter turns its hooks into these
events (`docs/judging-writes.md`, *After a call: the checkpoint*):

| Event | When |
|---|---|
| `SessionStarted` | a session starts or resumes |
| `CallStarted` | a tool call is about to run |
| `CallFinished` | a tool call finished, or failed |
| `TurnEnded` | the agent ends its turn |
| `ConversationEnded` | a subagent's conversation ends |

A checkpoint runs whenever a call finishes and no other call is running, and again
when the turn ends. It snapshots the worktree into the store, compares it with the
accepted tree, sets aside what was committed elsewhere, judges the rest as an edit
is judged, puts back what's refused with the agent's version saved, holds what
asks on a runtime that can't ask before a call, and moves the accepted tree on.

A call that runs a subagent isn't counted as running: the subagent's own calls
are, so its writes are judged as it makes them rather than when it ends. The
files changed are re-checked for the type errors of the files importing them, in
one background pass per worktree, which the turn's end waits for.
"""

import difflib
import secrets
import sys
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import Literal, override

import sh
from filelock import FileLock, Timeout

from lup.types import Model, MutableModel
from lup_dev.changes import Held, Store, read_model, write_model
from lup_dev.checker import Checker, FileReport, Finding, Source
from lup_dev.clock import Clock
from lup_dev.conditions import declared
from lup_dev.holds import HeldFile, Hold, Holds
from lup_dev.judge import Change, Judge, Judgement, RemovedNote
from lup_dev.layout import Layout, StoreLayout
from lup_dev.project import Declared, load
from lup_dev.report import (
    Refused,
    information,
    refusal,
    removed_notes,
    sections,
    turn_end,
)
from lup_dev.roles import Roles
from lup_dev.ruff import Linter
from lup_dev.runtime import Runtime
from lup_dev.verdicts import Answer, Verdict, VerdictLog


class Spawner(ABC):
    """Starts the background importers pass of a worktree."""

    @abstractmethod
    def spawn(self, worktree: Path, log: Path) -> None:
        """Start the pass for the worktree at `worktree`, printing to `log`."""


class BackgroundSpawner(Spawner):
    """Starts the pass as its own process, detached from the hook that asks for it."""

    @override
    def spawn(self, worktree: Path, log: Path) -> None:
        log.parent.mkdir(parents=True, exist_ok=True)
        sh.Command(sys.executable)(
            "-m",
            "lup_dev.cli",
            "importers",
            str(worktree),
            _bg=True,
            _bg_exc=False,
            _new_session=True,
            _out=str(log),
            _err=str(log),
        )


class Services(Model, arbitrary_types_allowed=True):
    """What judging reaches beyond the worktree: engine, ruff, clock, store."""

    checker: Checker
    linter: Linter
    clock: Clock
    layout: Layout
    spawner: Spawner


class Bench(Model, arbitrary_types_allowed=True):
    """Everything an event needs: the runtime it came from, and the services."""

    runtime: Runtime
    services: Services


class Reply(Model):
    """What the agent hears after an event, before the runtime spells it."""

    context: str = ""
    """Told beside the call's result."""
    block: str = ""
    """Why the conversation can't end yet; empty lets it end."""


class Call(Model):
    """A tool call running now."""

    key: str
    agent: str
    """The conversation making it: empty for the session's own, else a subagent's."""
    tool: str


class Running(MutableModel):
    """The calls running in one worktree, kept under a lock."""

    calls: list[Call] = []


class Pending(Model):
    """A file tool's write judged before it lands, waiting for its call to finish."""

    call: str
    path: Path
    blob: str
    """The would-be content's object id in the store."""
    asked: bool
    """Whether the operator was asked: if the call runs, they approved."""
    verdict: Verdict
    removed: list[RemovedNote] = []


class Judged(Model):
    """Content already judged, which the next checkpoint accepts as it is."""

    path: Path
    blob: str


class Mail(Model):
    """A report waiting for a conversation other than the one a checkpoint ran for."""

    agent: str
    text: str


class Session(MutableModel):
    """What the store remembers about one session in a worktree."""

    key: str
    runtime: str
    worktree: Path
    approved: list[Path] = []
    """Paths the operator approved, whose design asks are covered from then on."""
    touched: list[Path] = []
    """Files the session changed, which must be clean when its turn ends."""
    watched: list[Path] = []
    """Files importing what it changed that had type errors, checked at turn end."""
    removed: dict[Path, list[RemovedNote]] = {}
    """By file, the notes present at the session's start that are gone since."""
    listed: list[RemovedNote] = []
    """Removed notes already listed at a turn's end."""
    pending: list[Pending] = []
    judged: list[Judged] = []
    participants: list[str] = []
    """Conversations whose calls finished since the last checkpoint."""
    mail: list[Mail] = []


class Located(Model):
    """Which worktree a session runs in."""

    worktree: Path


class ImportersState(MutableModel):
    """What the background importers pass has left to do, and what it found."""

    pending: list[Path] = []
    """Files changed since the pass took its last batch."""
    found: list[FileReport] = []
    """What the pass found, waiting for the next checkpoint."""


class ImportersPass(Model):
    """One worktree's background pass re-checking the files importing what changed.

    One pass at a time. The pass holds a lock for its whole life, which the system
    frees however the process ends; a change while it runs adds to what it does
    next. It stops only once nothing is pending, releasing its lock before the
    state's, so a request never finds it gone with work left behind.
    """

    layout: StoreLayout
    root: Path

    def guard(self) -> FileLock:
        """Return the lock guarding the pass's state."""
        self.layout.home.mkdir(parents=True, exist_ok=True)
        return FileLock(self.layout.importers_lock)

    def runner(self) -> FileLock:
        """Return the lock a running pass holds."""
        self.layout.home.mkdir(parents=True, exist_ok=True)
        return FileLock(self.layout.importers_run, timeout=0)

    def state(self) -> ImportersState:
        """Read the pass's state; hold its guard."""
        return read_model(self.layout.importers, ImportersState) or ImportersState()

    def running(self) -> bool:
        """Say whether a pass runs now: whether its lock is held."""
        probe = self.runner()
        try:
            probe.acquire()
        except Timeout:
            return True
        probe.release()
        return False

    def request(self, changed: list[Path], spawner: Spawner) -> None:
        """Ask for the files importing `changed` to be re-checked.

        Starts a pass unless one runs; one that runs takes these next.
        """
        if not changed:
            return
        with self.guard():
            state = self.state()
            state.pending = list(dict.fromkeys([*state.pending, *changed]))
            write_model(self.layout.importers, state)
            if self.running():
                return
        spawner.spawn(self.root, self.layout.importers_log)

    def run(self, checker: Checker) -> None:
        """Run the pass until nothing is pending; return at once if another runs."""
        runner = self.runner()
        try:
            runner.acquire()
        except Timeout:
            return
        try:
            while self.step(checker, runner):
                pass
        finally:
            if runner.is_locked:
                runner.release()

    def step(self, checker: Checker, runner: FileLock) -> bool:
        """Re-check one batch; say whether to look for another."""
        with self.guard():
            state = self.state()
            batch = state.pending
            if not batch:
                runner.release()
                return False
            state.pending = []
            write_model(self.layout.importers, state)
        found = checker.importers(self.root, batch)
        with self.guard():
            state = self.state()
            state.found = [*state.found, *found]
            write_model(self.layout.importers, state)
        return True

    def collect(self) -> list[FileReport]:
        """Take what the pass found since the last collection."""
        with self.guard():
            state = self.state()
            found = state.found
            state.found = []
            write_model(self.layout.importers, state)
        return found

    def wait(
        self,
        checker: Checker,
        clock: Clock,
        patience: timedelta = timedelta(minutes=10),
        poll: timedelta = timedelta(seconds=1),
    ) -> None:
        """Wait for the pass to finish, so no type error surfaces after the turn.

        Work left pending with no pass running (one that failed as it started)
        is done here.
        """
        deadline = clock.now() + patience
        while self.running() and clock.now() < deadline:
            clock.sleep(poll.total_seconds())
        if not self.running():
            self.run(checker)


def decoded(content: bytes | None) -> str | None:
    """Read file content as text, or none where there's no file."""
    return None if content is None else content.decode(errors="replace")


class Worktree(Model):
    """One worktree as the judge sees it: its store, its roles, its repository."""

    root: Path
    repository: Path
    """Its repository's shared git directory, which keys the verdict log."""
    store: Store
    declared: Declared
    roles: Roles

    @classmethod
    def at(cls, root: Path, layout: Layout) -> Worktree:
        """Open the worktree at `root`, its declaration loaded."""
        store = Store(layout=layout.store(root), worktree=root)
        common = store.repository().text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        found = load(root)
        return cls(
            root=root,
            repository=Path(common),
            store=store,
            declared=found,
            roles=Roles.of(root, found),
        )

    def lock(self) -> FileLock:
        """Return the lock a checkpoint holds over the store."""
        self.store.layout.home.mkdir(parents=True, exist_ok=True)
        return FileLock(self.store.layout.lock)

    def calls_lock(self) -> FileLock:
        """Return the lock over the calls running."""
        self.store.layout.home.mkdir(parents=True, exist_ok=True)
        return FileLock(self.store.layout.calls_lock)

    def running(self) -> Running:
        """Read the calls running; hold the calls lock."""
        return read_model(self.store.layout.calls, Running) or Running()

    def ran(self, running: Running) -> None:
        """Store the calls running; hold the calls lock."""
        write_model(self.store.layout.calls, running)

    def session(self, key: str, runtime: Runtime) -> Session:
        """Read what the store remembers about session `key`, or start remembering."""
        found = read_model(self.store.layout.session(key), Session)
        return found or Session(key=key, runtime=runtime.name(), worktree=self.root)

    def keep(self, session: Session) -> None:
        """Store what to remember about a session."""
        write_model(self.store.layout.session(session.key), session)

    def judge(self, services: Services, session: Session) -> Judge:
        """Return a judge for this worktree, as the session stands."""
        return Judge(
            root=self.root,
            roles=self.roles,
            checker=services.checker,
            linter=services.linter,
            conditions=declared(self.root, self.declared.project),
            approved=session.approved,
        )

    def verdicts(self, layout: Layout) -> VerdictLog:
        """Return this repository's verdict log."""
        return VerdictLog(path=layout.verdicts(self.repository))

    def importers(self) -> ImportersPass:
        """Return this worktree's importers pass."""
        return ImportersPass(layout=self.store.layout, root=self.root)

    def holds(self) -> Holds:
        """Return the holds kept in this worktree's store."""
        return Holds(layout=self.store.layout)


def locate(cwd: Path, session: str, layout: Layout) -> Path | None:
    """Return the worktree a session runs in: where it started, or around `cwd`.

    None where neither is a git worktree, which lup doesn't judge.
    """
    recorded = read_model(layout.session_worktree(session), Located)
    if recorded is not None:
        return recorded.worktree
    if not cwd.is_dir():
        return None
    found = sh.Command("git")(
        "rev-parse",
        "--show-toplevel",
        _cwd=str(cwd),
        _ok_code=[0, 128],
        _tty_out=False,
        _return_cmd=True,
    )
    if found.exit_code != 0:
        return None
    return Path(found.stdout.decode().strip())


def begin(bench: Bench, worktree: Worktree, key: str) -> None:
    """Start, or resume, a session: the accepted tree becomes the worktree as it is.

    What changed while no session ran there is the operator's work or a pull, and
    is accepted unjudged. A resumed session keeps the tree it started from.
    """
    store = worktree.store
    with worktree.lock():
        snapshot = store.snapshot()
        store.accept(snapshot)
        if store.started(key) is None:
            store.start(key, snapshot)
        state = store.state()
        state.tips = store.tips()
        store.remember(state)
        worktree.keep(worktree.session(key, bench.runtime))
    write_model(
        bench.services.layout.session_worktree(key), Located(worktree=worktree.root)
    )


def opened(bench: Bench, session: str, cwd: Path) -> Worktree | None:
    """Return the worktree a session runs in, starting the session if it's new."""
    root = locate(cwd, session, bench.services.layout)
    if root is None:
        return None
    worktree = Worktree.at(root, bench.services.layout)
    if worktree.store.started(session) is None:
        begin(bench, worktree, session)
    return worktree


class Planned(Model):
    """A changed file and what the checkpoint does with it."""

    change: Change
    decide: bool
    """Whether its outcome decides what happens; else it was judged already."""


class Checked(Model):
    """What a checkpoint did, for the agent to hear."""

    refused: list[Refused] = []
    information: list[Finding] = []
    untouched: list[Finding] = []
    importers: list[Finding] = []
    removed: list[RemovedNote] = []
    notices: list[str] = []
    """What else the agent hears: holds approved, late answers."""

    def text(self) -> str:
        """Say everything the checkpoint did that the agent should hear."""
        return sections(
            [
                refusal(self.refused),
                *self.notices,
                information(self.information, self.untouched, self.importers),
                removed_notes(self.removed),
            ]
        )

    def then(self, later: Checked) -> Checked:
        """Return this report followed by a later one."""
        return Checked(
            refused=[*self.refused, *later.refused],
            information=[*self.information, *later.information],
            untouched=[*self.untouched, *later.untouched],
            importers=[*self.importers, *later.importers],
            removed=[*self.removed, *later.removed],
            notices=[*self.notices, *later.notices],
        )


def kept(report: FileReport, findings: list[Finding]) -> list[Finding]:
    """Return `findings` the report's `ignore`s don't keep out."""
    return [
        found
        for found in findings
        if not any(
            directive.keeps(found.rule, found.span.start.line)
            for directive in report.directives
        )
    ]


def verdict(
    bench: Bench, session: str, tool: str, judgement: Judgement, *, held: bool = False
) -> Verdict:
    """Record a judgement as a verdict: `held` where it waits for the operator."""
    return Verdict(
        key=secrets.token_hex(8),
        time=bench.services.clock.now(),
        session=session,
        runtime=bench.runtime.name(),
        tool=tool,
        path=judgement.path,
        role=judgement.role,
        outcome="hold" if held else judgement.outcome,
        reasons=judgement.reasons(),
    )


def held_diff(store: Store, accepted: str, files: list[HeldFile]) -> str:
    """Show held files as a unified diff against the accepted tree."""

    def one(held: HeldFile) -> str:
        before = decoded(store.content(accepted, held.path)) or ""
        after = decoded(store.object(held.blob)) or ""
        lines = difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{held.path}",
            tofile=f"b/{held.path}",
        )
        return "".join(lines)

    return "".join(one(held) for held in files)


class Fates(Model):
    """A checkpoint's judgements, by what happens to each file."""

    refused: list[Judgement] = []
    held: list[Judgement] = []
    accepted: list[Judgement] = []


def fates(bench: Bench, judgements: list[Judgement], deciding: list[Path]) -> Fates:
    """Sort a checkpoint's judgements by what happens to each file.

    An ask made through the shell is refused, with a pointer back to the file
    tools, on a runtime that asks before a call; it's held on one that can't.
    """
    asks_before = bench.runtime.asks_before()

    def fate(judgement: Judgement) -> Literal["refused", "held", "accepted"]:
        if judgement.path not in deciding:
            return "accepted"
        match judgement.outcome:
            case "refuse":
                return "refused"
            case "ask":
                return "refused" if asks_before else "held"
            case "allow":
                return "accepted"

    each = {judgement.path: fate(judgement) for judgement in judgements}
    return Fates(
        refused=[j for j in judgements if each[j.path] == "refused"],
        held=[j for j in judgements if each[j.path] == "held"],
        accepted=[j for j in judgements if each[j.path] == "accepted"],
    )


class Snapshot(Model):
    """The trees a checkpoint compares, and what it remembers of the worktree."""

    store: Store
    session: str
    taken: str
    """The worktree as it is now."""
    accepted: str
    start: str | None
    """The tree the session started from."""
    tips: list[str]
    """Commits whose content isn't judged again: those of the last checkpoint, and
    those arrived from a remote since."""
    judged: dict[Path, str]
    """Content already judged, by path: its object id."""

    def plan(self, path: Path) -> Planned | None:
        """Plan what to do with one changed path; none to set it aside unjudged."""
        store = self.store
        blob = store.blob(self.taken, path)
        prior = self.judged.get(path)
        after = decoded(store.content(self.taken, path))
        baseline = decoded(store.content(self.start, path))
        accepted = decoded(store.content(self.accepted, path))
        if prior is not None and prior == blob:
            change = Change(path=path, before=accepted, after=after, baseline=baseline)
            return Planned(change=change, decide=False)
        if store.committed(path, blob, self.tips):
            return None
        before = accepted if prior is None else decoded(store.object(prior))
        change = Change(path=path, before=before, after=after, baseline=baseline)
        return Planned(change=change, decide=True)


class Acted(Model):
    """What a checkpoint did to the files it judged."""

    refused: list[Refused] = []
    hold: Hold | None = None
    landed: list[Judgement] = []
    """The files accepted, judged now or before they landed."""


def act(bench: Bench, worktree: Worktree, snapshot: Snapshot, judged: Fates) -> Acted:
    """Put back what's refused, hold what waits, and accept the rest; hold the lock."""
    store = worktree.store
    state = store.state()
    number = state.saved + 1

    def put_back(judgement: Judgement) -> Refused:
        content = store.content(snapshot.taken, judgement.path)
        saved = (
            judgement.path
            if content is None
            else store.save(number, judgement.path, content)
        )
        return Refused(
            path=judgement.path,
            saved=saved,
            new=store.content(snapshot.accepted, judgement.path) is None,
            refusing=judgement.refusing,
            untouched=judgement.untouched,
            bypassed=judgement.asks if judgement.outcome == "ask" else [],
        )

    refused = [put_back(judgement) for judgement in judged.refused]
    held = [
        HeldFile(
            path=judgement.path,
            blob=store.blob(snapshot.taken, judgement.path) or "",
            reasons=[ask.reason for ask in judgement.asks],
        )
        for judgement in judged.held
    ]
    diff = held_diff(store, snapshot.accepted, held)
    hold = (
        worktree.holds().create(
            worktree.root, snapshot.session, held, diff, bench.services.clock
        )
        if held
        else None
    )
    refused_paths = [each.path for each in refused]
    holding = [each.path for each in state.holding]
    kept_out = [*refused_paths, *(each.path for each in held), *holding]
    tree = store.unstage(snapshot.accepted, kept_out)
    store.restore(snapshot.accepted, refused_paths)
    store.accept(tree)
    state.tips = store.tips()
    state.saved = number if refused else state.saved
    new_holding = [
        Held(hold=hold.key, path=each.path, blob=each.blob)
        for each in held
        if hold is not None
    ]
    state.holding = [*state.holding, *new_holding]
    store.remember(state)
    return Acted(refused=refused, hold=hold, landed=judged.accepted)


def checkpoint(bench: Bench, worktree: Worktree, key: str, agent: str) -> Checked:
    """Judge what changed since the accepted tree, act on it, and report.

    Holds, on a runtime that can't ask before a call, are waited on once the
    store is released, then settled, and the checkpoint runs again for what the
    operator approved.
    """
    services = bench.services
    store = worktree.store
    with worktree.lock():
        session = worktree.session(key, bench.runtime)
        taken = store.snapshot()
        accepted = store.accepted()
        if accepted is None:
            store.accept(taken)
            return Checked()
        state = store.state()
        holding = [each.path for each in state.holding]
        snapshot = Snapshot(
            store=store,
            session=key,
            taken=taken,
            accepted=accepted,
            start=store.started(key),
            tips=[*state.tips, *store.remote_tips()],
            judged={each.path: each.blob for each in session.judged},
        )
        planned = [
            plan
            for plan in (
                snapshot.plan(each.path)
                for each in store.changed(accepted, taken)
                if each.path not in holding
            )
            if plan is not None
        ]
        judgements = worktree.judge(services, session).judge(
            [plan.change for plan in planned]
        )
        deciding = [plan.change.path for plan in planned if plan.decide]
        acted = act(bench, worktree, snapshot, fates(bench, judgements, deciding))
        held = [] if acted.hold is None else [each.path for each in acted.hold.files]
        worktree.verdicts(services.layout).append(
            [
                verdict(
                    bench, key, "checkpoint", judgement, held=judgement.path in held
                )
                for judgement in judgements
                if judgement.path in deciding
            ]
        )
        checked = remember(worktree, session, agent, acted)
    python = [
        judgement.path
        for judgement in acted.landed
        if worktree.roles.is_python(judgement.path)
        and judgement.role in ["production", "test"]
    ]
    worktree.importers().request(python, services.spawner)
    if acted.hold is None:
        return checked
    return checked.then(settle(bench, worktree, key, agent, acted.hold))


def remember(worktree: Worktree, session: Session, agent: str, acted: Acted) -> Checked:
    """Note in the session what a checkpoint did, and report it; hold the lock.

    The report goes to the conversation the checkpoint ran for, and waits as mail
    for the others whose calls finished since the last one: the checkpoint sees
    files, not who wrote them.
    """
    landed = acted.landed
    importing = [
        found
        for report in worktree.importers().collect()
        for found in kept(report, report.findings)
        if found.owner != "lup"
    ]
    checked = Checked(
        refused=acted.refused,
        information=[found for j in landed for found in j.information],
        untouched=[found for j in landed for found in j.untouched],
        importers=importing,
        removed=[note for j in landed for note in j.removed],
        notices=late_answers(worktree, session),
    )
    report = checked.text()
    others = [other for other in session.participants if other != agent]
    session.touched = list(dict.fromkeys([*session.touched, *(j.path for j in landed)]))
    session.watched = list(
        dict.fromkeys([*session.watched, *(found.path for found in importing)])
    )
    session.removed = {
        **session.removed,
        **{j.path: j.removed for j in landed if j.role == "production"},
    }
    session.judged = []
    session.participants = []
    session.mail = [
        *session.mail,
        *(Mail(agent=other, text=report) for other in others if report),
    ]
    worktree.keep(session)
    return checked


def late_answers(worktree: Worktree, session: Session) -> list[str]:
    """Tell the answers given to holds after their wait ran out; hold the lock.

    An approval covers the paths for the rest of the session, so the saved
    version can go back into place.
    """
    holds = worktree.holds()

    def told(hold: Hold) -> str:
        holds.mark(hold.key, delivered=True)
        paths = [held.path for held in hold.files]
        answer = hold.answer
        approved = answer is not None and answer.approved
        if approved:
            session.approved = list(dict.fromkeys([*session.approved, *paths]))
        verb = "approved" if approved else "declined"
        comment = (
            f": {answer.comment}" if answer is not None and answer.comment else "."
        )
        named = ", ".join(str(path) for path in paths)
        return (
            f"After the hold timed out, the operator {verb} the change to {named}"
            f"{comment} Your version was saved when it was put back."
        )

    return [told(hold) for hold in holds.late() if hold.session == session.key]


def settle(
    bench: Bench, worktree: Worktree, key: str, agent: str, hold: Hold
) -> Checked:
    """Wait for the operator's answer to `hold`, then act on it.

    An approval accepts the held content as it is; a decline, or no answer in
    time, puts it back with the agent's version saved.
    """
    services = bench.services
    store = worktree.store
    answer = worktree.holds().wait(hold.key, services.clock)
    paths = [held.path for held in hold.files]
    log = worktree.verdicts(services.layout)
    with worktree.lock():
        state = store.state()
        state.holding = [each for each in state.holding if each.hold != hold.key]
        if answer is None or not answer.approved:
            accepted = store.accepted() or ""
            number = state.saved + 1
            refused = [
                Refused(
                    path=held.path,
                    saved=store.save(number, held.path, store.object(held.blob) or b""),
                    new=store.content(accepted, held.path) is None,
                    declined=None if answer is None else answer.comment,
                    unanswered=answer is None,
                )
                for held in hold.files
            ]
            store.restore(accepted, paths)
            state.saved = number
            store.remember(state)
            if answer is None:
                worktree.holds().mark(hold.key, abandoned=True)
            outcome: Answer = "unanswered" if answer is None else "declined"
            log.append(answered(bench, key, hold, outcome))
            return Checked(refused=refused)
        session = worktree.session(key, bench.runtime)
        session.judged = [
            *session.judged,
            *(Judged(path=held.path, blob=held.blob) for held in hold.files),
        ]
        session.approved = list(dict.fromkeys([*session.approved, *paths]))
        store.remember(state)
        worktree.keep(session)
    log.append(answered(bench, key, hold, "approved"))
    comment = f": {answer.comment}" if answer.comment else "."
    named = ", ".join(str(path) for path in paths)
    notice = Checked(
        notices=[f"The operator approved the held change to {named}{comment}"]
    )
    return notice.then(checkpoint(bench, worktree, key, agent))


def answered(bench: Bench, key: str, hold: Hold, answer: Answer) -> list[Verdict]:
    """Record the operator's answer to a hold, one verdict per file."""
    return [
        Verdict(
            key=f"{hold.key}:{held.path}",
            time=bench.services.clock.now(),
            session=key,
            runtime=bench.runtime.name(),
            tool="checkpoint",
            path=held.path,
            role="production",
            outcome="hold",
            reasons=held.reasons,
            answer=answer,
        )
        for held in hold.files
    ]


def mail_for(worktree: Worktree, key: str, agent: str, runtime: Runtime) -> str:
    """Take the reports waiting for conversation `agent`."""
    with worktree.lock():
        session = worktree.session(key, runtime)
        waiting = [mail.text for mail in session.mail if mail.agent == agent]
        session.mail = [mail for mail in session.mail if mail.agent != agent]
        worktree.keep(session)
    return sections(waiting)


def confirm(bench: Bench, worktree: Worktree, key: str, agent: str, call: str) -> None:
    """Note that a call finished: a write judged before it landed has landed.

    If the operator was asked about it, the call running means they approved, and
    the approval covers the path for the rest of the session.
    """
    with worktree.lock():
        session = worktree.session(key, bench.runtime)
        landed = [pending for pending in session.pending if pending.call == call]
        session.pending = [
            pending for pending in session.pending if pending.call != call
        ]
        session.judged = [
            *session.judged,
            *(Judged(path=pending.path, blob=pending.blob) for pending in landed),
        ]
        asked = [pending.path for pending in landed if pending.asked]
        session.approved = list(dict.fromkeys([*session.approved, *asked]))
        session.removed = {
            **session.removed,
            **{pending.path: pending.removed for pending in landed},
        }
        session.participants = list(dict.fromkeys([*session.participants, agent]))
        worktree.keep(session)
    worktree.verdicts(bench.services.layout).append(
        [
            pending.verdict.model_copy(update={"answer": "approved"})
            for pending in landed
            if pending.asked
        ]
    )


def unclean(bench: Bench, worktree: Worktree, session: Session) -> list[Finding]:
    """Return the type errors and ruff's findings left in what the session touched.

    The files it changed, and the files importing them where the background pass
    found errors, as they stand on disk, once `ignore`s apply.
    """
    services = bench.services
    paths = [
        path
        for path in dict.fromkeys([*session.touched, *session.watched])
        if (worktree.root / path).is_file()
        and worktree.roles.is_python(path)
        and worktree.roles.role(path) in ["production", "test"]
    ]
    importing = worktree.importers().collect()
    sources = [Source(path=path) for path in paths]
    reports = services.checker.check(worktree.root, sources) if sources else []
    ruff = services.linter.findings(worktree.root, sources) if sources else []
    return [
        found
        for report in [*reports, *importing]
        for found in kept(
            report,
            [*report.findings, *(each for each in ruff if each.path == report.path)],
        )
        if found.owner != "lup"
    ]


class Event(Model, ABC):
    """Something a runtime reports, in lup's own words."""

    session: str
    agent: str = ""
    """The conversation it's from: empty for the session's own, else a subagent's."""
    cwd: Path

    @abstractmethod
    def apply(self, bench: Bench) -> Reply:
        """Act on the event, and say what the agent hears."""


class SessionStarted(Event):
    """A session started, or resumed."""

    @override
    def apply(self, bench: Bench) -> Reply:
        root = locate(self.cwd, self.session, bench.services.layout)
        if root is None:
            return Reply()
        begin(bench, Worktree.at(root, bench.services.layout), self.session)
        return Reply()


class CallStarted(Event):
    """A tool call is about to run."""

    call: str
    tool: str
    spawns: bool = False
    """Whether the call runs a subagent, whose own calls count instead."""

    @override
    def apply(self, bench: Bench) -> Reply:
        worktree = opened(bench, self.session, self.cwd)
        if worktree is None or self.spawns:
            return Reply()
        with worktree.calls_lock():
            running = worktree.running()
            call = Call(key=self.call, agent=self.agent, tool=self.tool)
            running.calls = [*running.calls, call]
            worktree.ran(running)
        return Reply()


class CallFinished(Event):
    """A tool call finished, whether it succeeded or failed.

    One that never started (a runtime can report a command's end on a later
    call) leaves the calls running as they are, and a checkpoint still runs if
    none is.
    """

    call: str

    @override
    def apply(self, bench: Bench) -> Reply:
        worktree = opened(bench, self.session, self.cwd)
        if worktree is None:
            return Reply()
        with worktree.calls_lock():
            running = worktree.running()
            running.calls = [call for call in running.calls if call.key != self.call]
            worktree.ran(running)
            idle = not running.calls
        confirm(bench, worktree, self.session, self.agent, self.call)
        if not idle:
            return Reply(
                context=mail_for(worktree, self.session, self.agent, bench.runtime)
            )
        checked = checkpoint(bench, worktree, self.session, self.agent)
        waiting = mail_for(worktree, self.session, self.agent, bench.runtime)
        return Reply(context=sections([checked.text(), waiting]))


class TurnEnded(Event):
    """The agent ended its turn.

    Its calls that never reported finishing are cleared, a checkpoint runs, the
    importers pass is waited on, and the turn can't end while the files it
    touched have type errors or ruff's findings. The notes present at the
    session's start and removed since are listed once.
    """

    @override
    def apply(self, bench: Bench) -> Reply:
        worktree = opened(bench, self.session, self.cwd)
        if worktree is None:
            return Reply()
        services = bench.services
        with worktree.calls_lock():
            running = worktree.running()
            running.calls = [call for call in running.calls if call.agent != self.agent]
            worktree.ran(running)
        checked = checkpoint(bench, worktree, self.session, self.agent)
        worktree.importers().wait(services.checker, services.clock)
        with worktree.lock():
            session = worktree.session(self.session, bench.runtime)
            removed = [note for notes in session.removed.values() for note in notes]
            unlisted = [note for note in removed if note not in session.listed]
            session.listed = [*session.listed, *unlisted]
            worktree.keep(session)
        remaining = unclean(bench, worktree, session)
        waiting = mail_for(worktree, self.session, self.agent, bench.runtime)
        return Reply(
            block=sections(
                [
                    refusal(checked.refused),
                    *checked.notices,
                    turn_end(remaining),
                    removed_notes(unlisted),
                    waiting,
                ]
            )
        )


class ConversationEnded(Event):
    """A subagent's conversation ended; the session's own turn goes on."""

    @override
    def apply(self, bench: Bench) -> Reply:
        worktree = opened(bench, self.session, self.cwd)
        if worktree is None:
            return Reply()
        with worktree.calls_lock():
            running = worktree.running()
            running.calls = [call for call in running.calls if call.agent != self.agent]
            worktree.ran(running)
            idle = not running.calls
        checked = (
            checkpoint(bench, worktree, self.session, self.agent) if idle else None
        )
        waiting = mail_for(worktree, self.session, self.agent, bench.runtime)
        report = refusal(checked.refused) if checked is not None else ""
        return Reply(block=sections([report, waiting]))
