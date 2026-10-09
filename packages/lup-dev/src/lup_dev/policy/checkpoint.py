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

A session holds one or more worktrees of its repository (`worktrees.py`), and a
call counts as running in every worktree its session holds when it starts. A
checkpoint runs in each worktree the session holds whenever a call finishes and
no call counted there is running, and again in each when the turn ends. It
snapshots the worktree into the store, compares it with the accepted tree, sets
aside what was committed elsewhere or merged from it, judges a move of `HEAD` once
as its commits', judges the rest as an edit is judged, puts back what's refused
with the agent's version saved, holds what asks on a runtime that can't ask before
a call, and moves the accepted tree on.

A call that runs a subagent isn't counted as running: the subagent's own calls
are, so its writes are judged as it makes them rather than when it ends. The
files changed are re-checked for the type errors of the files importing them, in
one background pass per worktree (`importers.py`), which the turn's end waits for.
"""

import difflib
import secrets
import shutil
from abc import ABC, abstractmethod
from functools import cached_property
from pathlib import Path
from typing import Literal, override

from filelock import FileLock

from lup.types import Model, MutableModel
from lup_dev.clock import Clock
from lup_dev.codescan.conditions import declared
from lup_dev.codescan.contract import Checker, FileReport, Finding, Source
from lup_dev.codescan.ruff import Linter
from lup_dev.layout import Layout
from lup_dev.policy.holds import HeldFile, Hold, Holds, answered
from lup_dev.policy.importers import ImportersPass, Spawner
from lup_dev.policy.judge import Change, Judge, Judgement, RemovedNote
from lup_dev.policy.report import (
    Moved,
    MovedFile,
    Refused,
    information,
    moved,
    placed,
    refusal,
    removed_notes,
    sections,
    turn_end,
)
from lup_dev.policy.roles import Roles
from lup_dev.policy.runtime import Runtime
from lup_dev.policy.store import (
    Elsewhere,
    Entry,
    Git,
    Heads,
    Held,
    Store,
    read_model,
    write_model,
)
from lup_dev.policy.verdicts import Verdict, VerdictLog
from lup_dev.policy.worktrees import Holding, Place, SessionIndex, place
from lup_dev.project import Declared, Project, ProjectError, load


class Services(Model, arbitrary_types_allowed=True):
    """What judging reaches beyond the worktree: engine, ruff, clock, store."""

    checker: Checker
    linter: Linter
    clock: Clock
    layout: Layout
    spawner: Spawner
    integration: str
    """The branch whose tip holds the declaration every worktree is judged by."""


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
    """A tool call in flight."""

    key: str
    session: str
    """The session making it, which counts it in every worktree it holds."""
    agent: str
    """The conversation making it: empty for the session's own, else a subagent's."""
    tool: str

    def of(self, session: str, agent: str) -> bool:
        """Say whether conversation `agent` of `session` makes this call."""
        return self.session == session and self.agent == agent


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


def decoded(content: bytes | None) -> str | None:
    """Read file content as text, or none where there's no file."""
    return None if content is None else content.decode(errors="replace")


class LastDeclaration(Model):
    """The last of a repository's declarations that loaded, kept for when one can't."""

    declared: Declared
    commit: str
    """The commit it was read from."""
    told: str = ""
    """The failure to load a declaration that the agent was last told of."""


class Loaded(Model):
    """The declaration a worktree is judged by, and where it came from."""

    declared: Declared
    root: Path
    """Where it was imported from: a commit's export, or the worktree's own files.
    The conditions module it names is read there too."""
    commit: str | None = None
    """The commit it was read from; none for the worktree's own files."""
    failure: str = ""
    """Why the declaration due couldn't load, where the repository's last stands in."""


class Judging(Model):
    """Where the declaration a worktree is judged by is read from."""

    integration: str
    """The branch whose tip holds it; without one, the worktree's `HEAD` commit."""
    layout: Layout


class Worktree(Model):
    """One worktree as the judge sees it: its store, its roles, its repository."""

    root: Path
    repository: Path
    """Its repository's shared git directory, which keys the verdict log."""
    store: Store
    judging: Judging | None = None
    """Where the declaration it's judged by comes from: a commit, with the
    repository's last that loaded standing in where it can't load. None reads the
    worktree's own files, and lets a failure stand, as the gate does."""

    @classmethod
    def at(cls, root: Path, layout: Layout) -> Worktree:
        """Open the worktree at `root` as it stands, asking git for its repository.

        Its own declaration, uncommitted edits included, is the one it's read by,
        as the gate checks a branch, and it must load: nothing stands in for it.
        """
        common = Git(cwd=root).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        store = Store(layout=layout.store(root), worktree=root)
        return cls(root=root, repository=Path(common), store=store)

    @classmethod
    def of(cls, root: Path, repository: Path, services: Services) -> Worktree:
        """Open the worktree at `root` of the repository at `repository`, to judge.

        It's judged by the declaration at the integration branch's tip, not its
        own, so a branch can't change what judges it (#21).
        """
        store = Store(layout=services.layout.store(root), worktree=root)
        judging = Judging(integration=services.integration, layout=services.layout)
        return cls(root=root, repository=repository, store=store, judging=judging)

    @cached_property
    def loaded(self) -> Loaded:
        """The declaration it's judged by, loaded when first read.

        Read from the integration branch's tip, or where the repository has no
        such branch, from the worktree's `HEAD` commit; the defaults before any
        commit. Each that loads is kept for the repository, and where one can't
        load, the last kept stands in.
        """
        judging = self.judging
        if judging is None:
            return Loaded(declared=load(self.root), root=self.root)
        commit = self.store.tip(judging.integration) or self.store.head()
        if commit is None:
            return Loaded(declared=Declared(project=Project()), root=self.root)
        kept = judging.layout.declaration(self.repository)
        try:
            source = self.exported(judging.layout, commit)
            found = load(source)
        except ProjectError as failure:
            last = read_model(kept, LastDeclaration)
            if last is None:
                raise
            return Loaded(
                declared=last.declared,
                root=self.exported(judging.layout, last.commit),
                commit=last.commit,
                failure=f"{commit}: {failure}",
            )
        with FileLock(kept.with_name(f"{kept.name}.lock")):
            last = read_model(kept, LastDeclaration)
            if last is None or last.commit != commit:
                told = last.told if last else ""
                write_model(
                    kept, LastDeclaration(declared=found, commit=commit, told=told)
                )
        return Loaded(declared=found, root=source, commit=commit)

    def exported(self, layout: Layout, commit: str) -> Path:
        """Return where `commit`'s Python modules are exported, exporting them once.

        A commit's export is written whole before it's moved into place, and the
        repository's earlier exports are removed: only the latest is read.
        """
        target = layout.exported(self.repository, commit)
        if target.is_dir():
            return target
        partial = target.with_name(f"{commit}.{secrets.token_hex(4)}.partial")
        self.store.export(commit, partial)
        try:
            partial.rename(target)
        except OSError:
            if not target.is_dir():
                raise
            shutil.rmtree(partial)
        earlier = [
            each
            for each in target.parent.iterdir()
            if each != target and not each.name.endswith(".partial")
        ]
        for each in earlier:
            try:
                shutil.rmtree(each)
            except FileNotFoundError:
                continue  # another hook removed it first
        return target

    @property
    def declared(self) -> Declared:
        """The declaration it's judged by, or the one standing in for it."""
        return self.loaded.declared

    def told(self) -> str:
        """Say, once for each failure, that a stand-in declaration judges here."""
        loaded = self.loaded
        if not loaded.failure or self.judging is None:
            return ""
        kept = self.judging.layout.declaration(self.repository)
        with FileLock(kept.with_name(f"{kept.name}.lock")):
            last = read_model(kept, LastDeclaration)
            if last is None or last.told == loaded.failure:
                return ""
            write_model(kept, last.model_copy(update={"told": loaded.failure}))
        return (
            f"lup can't load the project's declaration at {loaded.failure}. It "
            "judges with the last of this repository's declarations that loaded, "
            f"from commit {loaded.commit}, until one loads. Tell the operator: if "
            "the declaration uses something the installed judge predates, "
            "reinstalling it from `dev` (`lup-dev install`) fixes this; otherwise "
            "the declaration needs fixing."
        )

    @cached_property
    def roles(self) -> Roles:
        """The role of each path in it, from the declaration it's judged by."""
        return Roles.of(self.root, self.declared)

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

    def judge(self, services: Services, approved: list[Path]) -> Judge:
        """Return a judge for this worktree, the operator having approved `approved`."""
        return Judge(
            root=self.root,
            roles=self.roles,
            checker=services.checker,
            linter=services.linter,
            conditions=declared(self.loaded.root, self.declared.project),
            approved=approved,
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

    def heads(self, layout: Layout) -> Heads:
        """Read each worktree's `HEAD` at its last checkpoint, for the repository."""
        return read_model(layout.heads(self.repository), Heads) or Heads()

    def record(self, layout: Layout, head: str | None) -> None:
        """Record this worktree's `HEAD` at a checkpoint, for every worktree to read."""
        path = layout.heads(self.repository)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(path.with_name(f"{path.name}.lock")):
            heads = read_model(path, Heads) or Heads()
            heads.worktrees = {**heads.worktrees, self.root: head}
            write_model(path, heads)

    def finish(self, call: str) -> bool:
        """Note that `call` finished here; say whether no call counted here runs."""
        with self.calls_lock():
            running = self.running()
            running.calls = [each for each in running.calls if each.key != call]
            self.ran(running)
            return not running.calls

    def clear(self, session: str, agent: str) -> bool:
        """Forget the calls a conversation left running; say whether none is left."""
        with self.calls_lock():
            running = self.running()
            running.calls = [
                each for each in running.calls if not each.of(session, agent)
            ]
            self.ran(running)
            return not running.calls


def begin(bench: Bench, worktree: Worktree, key: str) -> None:
    """Start, or resume, a session in a worktree: accept the worktree as it is.

    What changed while no session ran there is the operator's work or a pull, and
    is accepted unjudged, and the worktree's `HEAD` is recorded with it. While a
    call runs there, another session is at work in it: the accepted tree stays,
    and that call's checkpoint judges what it writes. A resumed session keeps the
    tree it started from.
    """
    store = worktree.store
    with worktree.lock():
        with worktree.calls_lock():
            busy = bool(worktree.running().calls)
        start = store.accepted() if busy else None
        if start is None:
            start = store.snapshot()
            store.accept(start)
            head = store.head()
            state = store.state()
            state.tips = store.tips(head)
            store.remember(state)
            worktree.record(bench.services.layout, head)
        if store.started(key) is None:
            store.start(key, start)
        worktree.keep(worktree.session(key, bench.runtime))


def holding(
    bench: Bench,
    session: str,
    cwd: Path,
    written: Place | None = None,
    *,
    starts: bool = False,
) -> Holding | None:
    """Return a session's repository and the worktrees it holds, reaching more.

    The worktree its working directory is in is reached, since a hook's working
    directory follows the session, and so is `written`'s, where a file tool
    writes. Reaching a worktree begins the session there; a session that
    `starts`, or resumes, begins again in every worktree it holds. A worktree
    whose root is gone isn't held. A session first seen outside every
    repository isn't judged.
    """
    index = SessionIndex(layout=bench.services.layout)
    here = place(cwd) if cwd.is_dir() else None
    with index.lock(session):
        recorded = index.read(session)
        held = recorded
        if held is None:
            if here is None:
                return None
            held = Holding(repository=here.repository)
        released = held.release_removed()
        reaching = [
            each.worktree
            for each in [here, written]
            if each is not None
            and each.worktree is not None
            and each.repository == held.repository
        ]
        reached = [root for root in reaching if held.reach(root)]
        if recorded is None or reached or released:
            index.write(session, held)
        for root in held.worktrees if starts else reached:
            begin(
                bench,
                Worktree.of(root, held.repository, bench.services),
                session,
            )
    return held


def worktrees(bench: Bench, held: Holding) -> list[Worktree]:
    """Open each worktree a session holds."""
    services = bench.services
    return [Worktree.of(root, held.repository, services) for root in held.worktrees]


class Planned(Model):
    """A changed file and what the checkpoint does with it."""

    path: Path
    change: Change | None = None
    """The session's change, judged as an edit is; none where it made none."""
    decide: bool = True
    """Whether its outcome decides what happens; else it was judged already."""
    moved: Change | None = None
    """What a move of `HEAD` brought that no checkpoint judged, judged once as its
    commits'; none where the move brought nothing unjudged."""
    base: Entry | None = None
    """The file as `HEAD` has it, where a move changed it: the move is accepted,
    and a refused change goes back to it."""


class Checked(Model):
    """What a checkpoint did, for the agent to hear, every file named in full."""

    refused: list[Refused] = []
    moves: list[Moved] = []
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
                moved(self.moves),
                *self.notices,
                information(self.information, self.untouched, self.importers),
                removed_notes(self.removed),
            ]
        )

    def then(self, later: Checked) -> Checked:
        """Return this report followed by a later one."""
        return Checked(
            refused=[*self.refused, *later.refused],
            moves=[*self.moves, *later.moves],
            information=[*self.information, *later.information],
            untouched=[*self.untouched, *later.untouched],
            importers=[*self.importers, *later.importers],
            removed=[*self.removed, *later.removed],
            notices=[*self.notices, *later.notices],
        )


def noted(root: Path, notes: list[RemovedNote]) -> list[RemovedNote]:
    """Name each removed note's file by its absolute path, under the worktree `root`."""
    return [note.model_copy(update={"path": root / note.path}) for note in notes]


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


class Attributed(Model):
    """What a verdict is attributed to: its worktree, its session, its tool."""

    worktree: Path
    """The worktree the file is in, or the repository's git directory."""
    session: str | None
    """None for a move of `HEAD`, whose commits the checkpoint can't attribute."""
    tool: str


def verdict(
    bench: Bench, to: Attributed, judgement: Judgement, hold: str | None = None
) -> Verdict:
    """Record a judgement as a verdict.

    A file held under hold `hold` is logged under a key its answer is logged
    under too.
    """
    return Verdict(
        key=f"{hold}:{judgement.path}" if hold else secrets.token_hex(8),
        time=bench.services.clock.now(),
        session=to.session,
        runtime=bench.runtime.name(),
        tool=to.tool,
        worktree=to.worktree,
        path=judgement.path,
        role=judgement.role,
        outcome="hold" if hold else judgement.outcome,
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


class Move(Model):
    """The worktree's `HEAD` moving since the last checkpoint.

    A commit, a merge, a pull, a checkout or a reset: the files it changed whose
    content is that of the commit `HEAD` moved to were put there by git, not typed.
    """

    before: str | None
    """The commit `HEAD` named at the last checkpoint; none where it named none."""
    after: str | None
    """The commit it names at this checkpoint; none where it names none."""
    paths: list[Path]
    """The files that differ between the two."""


class Snapshot(Model):
    """The trees a checkpoint compares, and what it remembers of the worktree."""

    store: Store
    session: str
    taken: str
    """The worktree as it stands."""
    accepted: str
    head: str | None
    """The commit the worktree's `HEAD` names; none before its first."""
    start: str | None
    """The tree the session started from; none where nothing changed to judge."""
    elsewhere: Elsewhere
    """Content judged before, which isn't judged again."""
    judged: dict[Path, str]
    """Content already judged, by path: its object id."""
    move: Move | None = None

    def plan(self, path: Path) -> Planned:
        """Plan what to do with one changed path."""
        store = self.store
        blob = store.blob(self.taken, path)
        prior = self.judged.get(path)
        after = decoded(store.content(self.taken, path))
        baseline = decoded(store.content(self.start, path))
        accepted = decoded(store.content(self.accepted, path))
        if prior is not None and prior == blob:
            change = Change(path=path, before=accepted, after=after, baseline=baseline)
            return Planned(path=path, change=change, decide=False)
        if self.move is not None and path in self.move.paths:
            return self.moving(path, self.move)
        if self.elsewhere.holds(path, blob):
            return Planned(path=path)
        before = accepted if prior is None else decoded(store.object(prior))
        change = Change(path=path, before=before, after=after, baseline=baseline)
        return Planned(path=path, change=change)

    def moving(self, path: Path, move: Move) -> Planned:
        """Plan a path a move of `HEAD` changed: the move's part, then the rest.

        What the move brought that wasn't judged elsewhere is judged once, as its
        commits', against the accepted content. What changed after the move is
        the session's, judged against `HEAD`'s content, so the session isn't
        asked about what the commit brought.
        """
        store = self.store
        base = store.entry(move.after, path)
        brought = decoded(store.object(base.blob)) if base.blob else None
        accepted = decoded(store.content(self.accepted, path))
        unjudged = base.blob != store.blob(self.accepted, path) and not (
            self.elsewhere.holds(path, base.blob)
        )
        moved = (
            Change(path=path, before=accepted, after=brought, baseline=accepted)
            if unjudged
            else None
        )
        blob = store.blob(self.taken, path)
        if blob == base.blob or self.elsewhere.holds(path, blob):
            return Planned(path=path, moved=moved, base=base)
        rest = Change(
            path=path,
            before=brought,
            after=decoded(store.content(self.taken, path)),
            baseline=decoded(store.content(self.start, path)),
        )
        return Planned(path=path, change=rest, moved=moved, base=base)


class Acted(Model):
    """What a checkpoint did to the files it judged."""

    refused: list[Refused] = []
    hold: Hold | None = None
    landed: list[Judgement] = []
    """The files accepted, judged at this checkpoint or before they landed."""


class Decided(Model):
    """What a checkpoint decided: each file's fate, the verdicts, a hold's key."""

    fates: Fates
    plans: list[Planned]
    verdicts: list[Verdict]
    hold: str | None
    """The key a hold of this checkpoint is kept under; none where nothing's held."""


def act(
    bench: Bench, worktree: Worktree, snapshot: Snapshot, decided: Decided
) -> Acted:
    """Put back what's refused, hold what waits, and accept the rest; hold the lock.

    A refused or held file goes back to its accepted content, or to `HEAD`'s
    where a move changed it, since the move is accepted.
    """
    store = worktree.store
    root = worktree.root
    judged = decided.fates
    state = store.state()
    number = state.saved + 1
    refused_paths = [judgement.path for judgement in judged.refused]
    held_paths = [judgement.path for judgement in judged.held]
    kept_out = [*refused_paths, *held_paths, *(each.path for each in state.holding)]
    bases = [plan.base for plan in decided.plans if plan.base and plan.path in kept_out]
    based = [base.path for base in bases]
    tree = (
        store.unstage(
            snapshot.accepted, [path for path in kept_out if path not in based], bases
        )
        if kept_out
        else snapshot.taken
    )

    def put_back(judgement: Judgement) -> Refused:
        content = store.content(snapshot.taken, judgement.path)
        saved = (
            root / judgement.path
            if content is None
            else store.save(number, judgement.path, content)
        )
        return Refused(
            path=root / judgement.path,
            saved=saved,
            new=store.content(tree, judgement.path) is None,
            refusing=placed(root, judgement.refusing),
            untouched=placed(root, judgement.untouched),
            bypassed=judgement.asks if judgement.outcome == "ask" else [],
        )

    refused = [put_back(judgement) for judgement in judged.refused]
    held = [
        HeldFile(
            path=judgement.path,
            role=judgement.role,
            blob=store.blob(snapshot.taken, judgement.path) or "",
            reasons=[ask.kind for ask in judgement.asks],
            asks=[ask.reason for ask in judgement.asks],
        )
        for judgement in judged.held
    ]
    hold = (
        worktree.holds().put(
            Hold(
                key=decided.hold,
                worktree=root,
                session=snapshot.session,
                created=bench.services.clock.now(),
                files=held,
                diff=held_diff(store, tree, held),
                verdicts=[each for each in decided.verdicts if each.path in held_paths],
            )
        )
        if held and decided.hold
        else None
    )
    store.restore(tree, refused_paths)
    if tree != snapshot.accepted:
        store.accept(tree)
    state.tips = store.tips(snapshot.head)
    state.saved = number if refused else state.saved
    new_holding = [
        Held(hold=hold.key, path=each.path, blob=each.blob)
        for each in held
        if hold is not None
    ]
    state.holding = [*state.holding, *new_holding]
    store.remember(state)
    return Acted(refused=refused, hold=hold, landed=judged.accepted)


class Brought(Model):
    """What a move of `HEAD` brought, judged once: what to tell, and what landed."""

    told: Checked = Checked()
    landed: list[Judgement] = []


def brought(
    bench: Bench, worktree: Worktree, snapshot: Snapshot, plans: list[Planned]
) -> Brought:
    """Judge what a move of `HEAD` brought, once, as its commits'; hold the lock.

    Never put back: that would leave the working tree different from `HEAD`, and
    the next `git restore` would bring it back unjudged. Its verdicts are logged
    with no session, since the checkpoint can't tell who committed, and its asks
    are kept as a hold no agent waits on, for the operator to answer after the
    fact. It's told to the conversations whose calls finished since the last
    checkpoint, as any report is.
    """
    move = snapshot.move
    changes = [plan.moved for plan in plans if plan.moved is not None]
    if move is None or not changes:
        return Brought()
    services = bench.services
    store = worktree.store
    root = worktree.root
    judgements = worktree.judge(services, []).judge(changes)
    asking = [judgement for judgement in judgements if judgement.outcome == "ask"]
    asked_paths = [judgement.path for judgement in asking]
    key = worktree.holds().unused() if asking else None
    to = Attributed(worktree=root, session=None, tool="move")
    logged = [
        verdict(bench, to, judgement, key if judgement.path in asked_paths else None)
        for judgement in judgements
    ]
    bases = {plan.path: plan.base for plan in plans if plan.base is not None}
    files = [
        HeldFile(
            path=judgement.path,
            role=judgement.role,
            blob=bases[judgement.path].blob or "",
            reasons=[ask.kind for ask in judgement.asks],
            asks=[ask.reason for ask in judgement.asks],
        )
        for judgement in asking
    ]
    if key is not None:
        worktree.holds().put(
            Hold(
                key=key,
                worktree=root,
                session=snapshot.session,
                created=services.clock.now(),
                files=files,
                diff=held_diff(store, snapshot.accepted, files),
                commit=move.after,
                verdicts=[each for each in logged if each.path in asked_paths],
            )
        )
    worktree.verdicts(services.layout).append(logged)
    report = Moved(
        worktree=root,
        head=move.after,
        files=[
            MovedFile(
                path=root / judgement.path,
                findings=placed(root, judgement.refusing),
                asks=judgement.asks,
                removed=noted(root, judgement.removed),
            )
            for judgement in judgements
        ],
        hold=key,
    )
    information = [found for judgement in judgements for found in judgement.information]
    told = Checked(moves=[report], information=placed(root, information))
    return Brought(told=told, landed=judgements)


def moving(worktree: Worktree, heads: Heads, head: str | None) -> Move | None:
    """Return how the worktree's `HEAD` moved since its last checkpoint, if it did.

    None where it didn't, where no `HEAD` was recorded for the worktree yet, and
    where it names no commit at this checkpoint, so no commit brought anything.
    """
    if head is None or worktree.root not in heads.worktrees:
        return None
    last = heads.worktrees[worktree.root]
    if last == head:
        return None
    return Move(before=last, after=head, paths=worktree.store.moved(last, head))


def checkpoint(bench: Bench, worktree: Worktree, key: str, agent: str) -> Checked:
    """Judge what changed since the accepted tree, act on it, and report.

    Holds, on a runtime that can't ask before a call, are waited on once the
    store is released, then settled, and the checkpoint runs again for what the
    operator approved.
    """
    services = bench.services
    store = worktree.store
    root = worktree.root
    with worktree.lock():
        session = worktree.session(key, bench.runtime)
        taken = store.snapshot()
        accepted = store.accepted()
        head = store.head()
        if accepted is None:
            store.accept(taken)
            worktree.record(services.layout, head)
            return Checked()
        state = store.state()
        holding = [each.path for each in state.holding]
        changed = [
            each.path
            for each in (store.changed(accepted, taken) if taken != accepted else [])
            if each.path not in holding
        ]
        heads = worktree.heads(services.layout)
        others = [
            each
            for other, each in heads.worktrees.items()
            if other != root and each is not None
        ]
        remote = store.remote_tips() if changed else []
        snapshot = Snapshot(
            store=store,
            session=key,
            taken=taken,
            accepted=accepted,
            head=head,
            start=store.started(key) if changed else None,
            elsewhere=Elsewhere(store=store, commits=[*state.tips, *others, *remote]),
            judged={each.path: each.blob for each in session.judged},
            move=moving(worktree, heads, head) if changed else None,
        )
        plans = [snapshot.plan(path) for path in changed]
        changes = [plan.change for plan in plans if plan.change is not None]
        judgements = (
            worktree.judge(services, session.approved).judge(changes) if changes else []
        )
        deciding = [plan.path for plan in plans if plan.change and plan.decide]
        fated = fates(bench, judgements, deciding)
        held = [judgement.path for judgement in fated.held]
        hold = worktree.holds().unused() if held else None
        to = Attributed(worktree=root, session=key, tool="checkpoint")
        logged = [
            verdict(bench, to, judgement, hold if judgement.path in held else None)
            for judgement in judgements
            if judgement.path in deciding
        ]
        decided = Decided(fates=fated, plans=plans, verdicts=logged, hold=hold)
        acted = act(bench, worktree, snapshot, decided)
        worktree.verdicts(services.layout).append(logged)
        commits = brought(bench, worktree, snapshot, plans)
        if root not in heads.worktrees or heads.worktrees[root] != head:
            worktree.record(services.layout, head)
        notice = worktree.told() if plans else ""
        told = commits.told.then(Checked(notices=[notice] if notice else []))
        checked = remember(worktree, session, agent, acted, told)
    python = [
        judgement.path
        for judgement in [*acted.landed, *commits.landed]
        if worktree.roles.checked(judgement.path)
    ]
    worktree.importers().request(list(dict.fromkeys(python)), services.spawner)
    if acted.hold is None:
        return checked
    return checked.then(settle(bench, worktree, key, agent, acted.hold))


def remember(
    worktree: Worktree, session: Session, agent: str, acted: Acted, told: Checked
) -> Checked:
    """Note in the session what a checkpoint did, and report it; hold the lock.

    The report goes to the conversation the checkpoint ran for, and waits as mail
    for the others whose calls finished since the last one: the checkpoint sees
    files, not who wrote them. `told` is what a move of `HEAD` brought, which is
    no session's.
    """
    root = worktree.root
    landed = acted.landed
    importing = [
        found
        for report in worktree.importers().collect()
        for found in kept(report, report.findings)
        if found.owner != "lup"
    ]
    checked = Checked(
        refused=acted.refused,
        information=placed(root, [found for j in landed for found in j.information]),
        untouched=placed(root, [found for j in landed for found in j.untouched]),
        importers=placed(root, importing),
        removed=noted(root, [note for j in landed for note in j.removed]),
        notices=late_answers(worktree, session),
    ).then(told)
    report = checked.text()
    others = [other for other in session.participants if other != agent]
    session.touched = list(dict.fromkeys([*session.touched, *(j.path for j in landed)]))
    session.watched = list(
        dict.fromkeys([*session.watched, *(found.path for found in importing)])
    )
    session.removed = {
        **session.removed,
        **{j.path: j.removed for j in landed if worktree.roles.ruled(j.path)},
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
    """Tell the answers given to holds no agent waited on; hold the lock.

    For a hold whose wait ran out, an approval covers the paths for the rest of
    the session, so the saved version can go back into place. For a move's, the
    session that found the move hears the answer, and a decline changes no file.
    """
    holds = worktree.holds()

    def told(hold: Hold) -> str:
        holds.mark(hold.key, delivered=True)
        paths = [held.path for held in hold.files]
        answer = hold.answer
        approved = answer is not None and answer.approved
        verb = "approved" if approved else "declined"
        comment = (
            f": {answer.comment}." if answer is not None and answer.comment else "."
        )
        named = ", ".join(str(worktree.root / path) for path in paths)
        if hold.commit is not None:
            kept = (
                ""
                if approved
                else " Nothing was changed: revert it only at the operator's word."
            )
            return (
                f"The operator {verb} what commit {hold.commit} brought to {named}"
                f"{comment}{kept}"
            )
        if approved:
            session.approved = list(dict.fromkeys([*session.approved, *paths]))
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
    root = worktree.root
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
                    path=root / held.path,
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
            log.append(answered(hold, "unanswered" if answer is None else "declined"))
            return Checked(refused=refused)
        session = worktree.session(key, bench.runtime)
        session.judged = [
            *session.judged,
            *(Judged(path=held.path, blob=held.blob) for held in hold.files),
        ]
        session.approved = list(dict.fromkeys([*session.approved, *paths]))
        store.remember(state)
        worktree.keep(session)
    log.append(answered(hold, "approved"))
    comment = f": {answer.comment}" if answer.comment else "."
    named = ", ".join(str(root / path) for path in paths)
    notice = Checked(
        notices=[f"The operator approved the held change to {named}{comment}"]
    )
    return notice.then(checkpoint(bench, worktree, key, agent))


class Warned(MutableModel):
    """The failures of the judge a session's operator was warned of, each once."""

    failures: list[str] = []


def first_warning(layout: Layout, session: str, failure: str) -> bool:
    """Note that the operator is warned of `failure`; say whether it's the first time.

    A failure of the judge at a turn's end is the operator's to fix, not the
    agent's, so the turn ends, and the operator hears of it once per session
    rather than at every turn (#21).
    """
    path = layout.warned(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(path.with_name(f"{path.name}.lock")):
        warned = read_model(path, Warned) or Warned()
        if failure in warned.failures:
            return False
        warned.failures = [*warned.failures, failure]
        write_model(path, warned)
    return True


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
    found errors, as they stand on disk, once `ignore`s apply, each named by its
    absolute path. A finding ruff fixes safely isn't one: the session landing the
    work applies the fix.
    """
    services = bench.services
    paths = [
        path
        for path in dict.fromkeys([*session.touched, *session.watched])
        if (worktree.root / path).is_file() and worktree.roles.checked(path)
    ]
    importing = worktree.importers().collect()
    sources = [Source(path=path) for path in paths]
    reports = services.checker.check(worktree.root, sources) if sources else []
    ruff = services.linter.findings(worktree.root, sources) if sources else []
    found = [
        found
        for report in [*reports, *importing]
        for found in kept(
            report,
            [*report.findings, *(each for each in ruff if each.path == report.path)],
        )
        if found.owner != "lup" and not found.fixable
    ]
    return placed(worktree.root, found)


class Ended(Model):
    """A turn's end in one worktree: its checkpoint, and what's left to clean."""

    checked: Checked
    remaining: list[Finding]
    """Type errors and ruff's findings left in what the session touched."""
    unlisted: list[RemovedNote]
    """Notes present at the session's start, removed since, not listed before."""


def ended(bench: Bench, worktree: Worktree, key: str, agent: str) -> Ended:
    """Run a turn's end in one worktree the session holds.

    The checkpoint, the importers pass waited on, what's left in the files the
    session touched, and the notes present at its start and removed since,
    listed once.
    """
    services = bench.services
    checked = checkpoint(bench, worktree, key, agent)
    worktree.importers().wait(services.checker, services.clock)
    with worktree.lock():
        session = worktree.session(key, bench.runtime)
        removed = [note for notes in session.removed.values() for note in notes]
        unlisted = [note for note in removed if note not in session.listed]
        session.listed = [*session.listed, *unlisted]
        worktree.keep(session)
    return Ended(
        checked=checked,
        remaining=unclean(bench, worktree, session),
        unlisted=noted(worktree.root, unlisted),
    )


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
    """A session started, or resumed: it begins again in each worktree it holds."""

    @override
    def apply(self, bench: Bench) -> Reply:
        holding(bench, self.session, self.cwd, starts=True)
        return Reply()


class CallStarted(Event):
    """A tool call is about to run: it counts in every worktree its session holds."""

    call: str
    tool: str
    spawns: bool = False
    """Whether the call runs a subagent, whose own calls count instead."""

    @override
    def apply(self, bench: Bench) -> Reply:
        held = holding(bench, self.session, self.cwd)
        if held is None or self.spawns:
            return Reply()
        call = Call(
            key=self.call, session=self.session, agent=self.agent, tool=self.tool
        )
        for worktree in worktrees(bench, held):
            with worktree.calls_lock():
                running = worktree.running()
                running.calls = [*running.calls, call]
                worktree.ran(running)
        return Reply()


class CallFinished(Event):
    """A tool call finished, whether it succeeded or failed.

    A checkpoint runs in each worktree the session holds where no counted call
    is still running, one after another, and the agent hears their reports
    together. One that never started (a runtime can report a command's end on a
    later call) leaves the calls running as they are, and a checkpoint still runs
    where none is.
    """

    call: str

    @override
    def apply(self, bench: Bench) -> Reply:
        held = holding(bench, self.session, self.cwd)
        if held is None:
            return Reply()
        opened = worktrees(bench, held)
        idle = [worktree for worktree in opened if worktree.finish(self.call)]
        for worktree in opened:
            confirm(bench, worktree, self.session, self.agent, self.call)
        checked = [
            checkpoint(bench, worktree, self.session, self.agent) for worktree in idle
        ]
        waiting = [
            mail_for(worktree, self.session, self.agent, bench.runtime)
            for worktree in opened
        ]
        return Reply(context=sections([*(each.text() for each in checked), *waiting]))


class TurnEnded(Event):
    """The agent ended its turn.

    In each worktree the session holds, its conversation's calls that never
    reported finishing are cleared, a checkpoint runs, the importers pass is
    waited on, and the turn can't end while the files it touched have type
    errors or ruff's findings. The notes present at the session's start and
    removed since are listed once.
    """

    @override
    def apply(self, bench: Bench) -> Reply:
        held = holding(bench, self.session, self.cwd)
        if held is None:
            return Reply()
        opened = worktrees(bench, held)
        for worktree in opened:
            worktree.clear(self.session, self.agent)
        ends = [ended(bench, worktree, self.session, self.agent) for worktree in opened]
        waiting = [
            mail_for(worktree, self.session, self.agent, bench.runtime)
            for worktree in opened
        ]
        return Reply(
            block=sections(
                [
                    refusal([found for end in ends for found in end.checked.refused]),
                    moved([move for end in ends for move in end.checked.moves]),
                    *(notice for end in ends for notice in end.checked.notices),
                    turn_end([found for end in ends for found in end.remaining]),
                    removed_notes([note for end in ends for note in end.unlisted]),
                    *waiting,
                ]
            )
        )


class ConversationEnded(Event):
    """A subagent's conversation ended; the session's own turn goes on.

    Its calls are cleared in each worktree the session holds, and a checkpoint
    runs in each where none is left running.
    """

    @override
    def apply(self, bench: Bench) -> Reply:
        held = holding(bench, self.session, self.cwd)
        if held is None:
            return Reply()
        opened = worktrees(bench, held)
        idle = [
            worktree for worktree in opened if worktree.clear(self.session, self.agent)
        ]
        checked = [
            checkpoint(bench, worktree, self.session, self.agent) for worktree in idle
        ]
        waiting = [
            mail_for(worktree, self.session, self.agent, bench.runtime)
            for worktree in opened
        ]
        return Reply(
            block=sections(
                [
                    refusal([found for each in checked for found in each.refused]),
                    moved([move for each in checked for move in each.moves]),
                    *waiting,
                ]
            )
        )
