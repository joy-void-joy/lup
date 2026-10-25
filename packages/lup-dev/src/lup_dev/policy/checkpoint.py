"""The events as the judge reads them, the calls running, and the checkpoint.

The judging core never sees a runtime: each adapter turns its hooks into a
session's events, lup's own (`lup.events.SessionEvent`), each extended here
with what the judge reads of it, the runtime's ids for its conversation among
it, and what the judge does at it (`Reported.apply`; `docs/judging-writes.md`,
*After a call: the checkpoint*).

A session holds one or more worktrees of its repository (`worktrees.py`), and a
call counts as running in each worktree its conversation works in when it starts
(`Holding.works`), so a worker busy in its own worktree holds back no checkpoint
in another's, and two conversations working in one wait on each other. A
checkpoint runs in each of those worktrees whenever a call finishes and no call of
the session counted there is running, another session's calls there holding none
of its checkpoints back, and again in each worktree the session holds when its
turn ends. It snapshots the worktree into the store, compares it with the accepted
tree, sets aside what was committed elsewhere or merged from it, judges a move of
`HEAD` once as its commits', judges the rest as an edit is judged, holds what asks
in place until the operator answers, puts back what they decline with the agent's
version saved, and moves the accepted tree on.

A call that runs a subagent isn't counted as running: the subagent's own calls
are, so its writes are judged as it makes them rather than when it ends. The
files changed are re-checked for the type errors of the files importing them, in
one background pass per worktree (`importers.py`), which the session's turn's end
waits for.

The session's turn's end holds only on what's left in the files its own
conversation touched, and in the files importing them where the pass found errors
(#41). A subagent's end never holds on what's left in its files: every worker
passes the gate before it hands back. A file tool's write is the conversation's
that made it; anything else a checkpoint lands is every conversation's whose
calls finished since the last one, since the checkpoint sees files, not who
wrote them. A subagent is at work from its first call to the end of its
conversation, and while one is, the session's end doesn't hold on a file they
both touched, which may be the subagent's in progress (#32).
"""

import asyncio
import difflib
import secrets
import shutil
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from functools import cached_property, reduce
from pathlib import Path
from typing import Literal, override

from filelock import FileLock

from lup import events
from lup.types import Model, MutableModel
from lup_dev.approval import approved
from lup_dev.clock import Clock
from lup_dev.codescan.conditions import declared
from lup_dev.codescan.contract import Checker, Due, Finding, Owner, Source
from lup_dev.codescan.ruff import Linter
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.load import load
from lup_dev.declaration.project import Project
from lup_dev.declaration.resolve import Declaration, resolve
from lup_dev.errors import LupDevError
from lup_dev.git import Git
from lup_dev.inbox import ends
from lup_dev.inbox.store import ChangedFile
from lup_dev.layout import CheckoutLayout, GitDirectoryLayout, Layout
from lup_dev.policy.flags import Flagging, Landed, Put, flagged
from lup_dev.policy.holds import (
    Announcing,
    HeldFile,
    Hold,
    Holds,
    answered,
    outcome,
)
from lup_dev.policy.importers import Conversation, Found, ImportersPass, Spawner
from lup_dev.policy.judge import Change, Judge, Judgement, RemovedNote
from lup_dev.policy.report import (
    Known,
    Look,
    Moved,
    MovedFile,
    Part,
    Refused,
    Reports,
    approval,
    fitted,
    information,
    moved,
    news,
    placed,
    refusal,
    removed_notes,
    text,
    turn_end,
)
from lup_dev.policy.roles import Roles
from lup_dev.policy.runtime import Runtime
from lup_dev.policy.store import Elsewhere, Entry, Heads, Held, Store, WorktreeState
from lup_dev.policy.verdicts import Verdict, VerdictLog
from lup_dev.policy.worktrees import Holding, Place, SessionIndex, place
from lup_dev.private.building import listed
from lup_dev.private.module import Private
from lup_dev.private.withheld import Facts, Withheld
from lup_dev.private.withheld import kept as listed_at
from lup_dev.stored import read_model, write_model


class Services(Model, arbitrary_types_allowed=True):
    """What judging reaches beyond the worktree: engine, ruff, clock, store."""

    checker: Checker
    linter: Linter
    clock: Clock
    layout: Layout
    spawner: Spawner
    integration: str
    """The branch whose tip holds the declaration every worktree is judged by,
    until the operator approves a commit (`lup_dev.approval`)."""
    announcing: Announcing
    """Where each hold is put before the operator, whose answer comes back to it."""
    facts: Facts
    """What the host says of itself, which a list of values never published is
    built from where no launch built one."""
    flagging: Flagging
    """Where each write that landed flagged is put before the operator."""


class Bench(Model, arbitrary_types_allowed=True):
    """Everything an event needs: the runtime it came from, and the services."""

    runtime: Runtime
    services: Services
    ended: Path | None = None
    """Where the host service marks the hook ended, its runtime having ended it
    before its answer, as when the operator interrupts its call
    (`HostLayout.ended`); none where nothing marks it, as for `lup-dev hook`."""

    reserve: int = 2_500
    """What the judge's answer leaves of what a hook tells whole, for the
    inbox's items told beside it: a message or a short review."""

    def interrupted(self) -> bool:
        """Say whether the hook's runtime ended it before its answer, as the host service marks it: a hold its call waits on gives up."""
        return self.ended is not None and self.ended.exists()

    def said(self, repository: Path, parts: list[Part]) -> str:
        """Say `parts` in what the judge's answer may take of a hook (`fitted`), a report too long kept whole in `repository`'s git directory."""
        reports = Reports(
            layout=GitDirectoryLayout(common=repository), clock=self.services.clock
        )
        return fitted(parts, self.runtime.fits() - self.reserve, reports)


class Reply(Model):
    """What the agent hears after an event, before the runtime spells it."""

    context: str = ""
    """Told beside the call's result."""
    block: str = ""
    """Why the conversation can't end yet; empty lets it end."""


def over(
    started: datetime | None, now: datetime, lifetime: timedelta = timedelta(hours=25)
) -> bool:
    """Say whether what a call started at `started` must be over by `now`.

    No call outlives its hooks, and none waits longer for its answer than a
    room's hook does (`hooked`, `launch/session.py`), above a hold's day: what
    started `lifetime` ago is over, though no hook reported its end. What has
    no start recorded, kept by a judge that didn't record one, counts as over
    too: a session running across the upgrade loses the count of a call once,
    and its turn's start or end clears the rest.
    """
    return started is None or now - started >= lifetime


class Call(Model):
    """A tool call in flight."""

    key: str
    session: str
    """The session making it."""
    agent: str
    """The conversation making it: empty for the session's own, else a subagent's."""
    tool: str
    turn: str | None = None
    """The runtime's id for the turn it runs in, where the runtime names its
    turns: its conversation's next turn starting means it's over."""
    started: datetime | None = None
    """When it started, by the judge's clock; none where a judge didn't record
    it, which counts it as over (`over`)."""

    def of(self, session: str, agent: str) -> bool:
        """Say whether conversation `agent` of `session` makes this call."""
        return self.session == session and self.agent == agent


class Running(MutableModel):
    """The calls running in one worktree, kept under a lock.

    A call no hook reported finishing, from a session long gone, is forgotten
    each time the list is kept, once it must be over (`over`): otherwise the
    list would grow with each, and every call's hooks read and rewrite it.
    """

    calls: list[Call] = []

    def lasting(self, now: datetime) -> None:
        """Forget each call that must be over by `now`."""
        self.calls = [each for each in self.calls if not over(each.started, now)]

    def idle(self, session: str) -> bool:
        """Say whether no call of `session` runs: what a checkpoint of `session` waits on.

        Another session's calls don't count: a call no hook will finish, from a
        configuration hooking only `PreToolUse` or a session that crashed, would
        otherwise keep every session's checkpoints from running there.
        """
        return not any(each.session == session for each in self.calls)


class Finished(Model):
    """What a call's finish, or a conversation's end, leaves in one worktree."""

    counted: bool
    """Whether the call, or one of the conversation's, counted as running there."""
    idle: bool
    """Whether no call of its session is left running there."""


class Pending(Model):
    """A file tool's write judged before it lands, waiting for its call to finish.

    What its judgement found was told beside the call, and an approval it
    needed logged and covering its path, as the operator answered: its call's
    finish only confirms it landed (`confirm`).
    """

    call: str
    path: Path
    blob: str
    """The would-be content's object id in the store."""
    removed: list[RemovedNote] = []
    judged: datetime | None = None
    """When it was let through, by the judge's clock, its call starting then;
    none where a judge didn't record it. Once its call must be over (`over`),
    it's forgotten, though no end confirmed it."""


class Judged(Model):
    """Content already judged, which the next checkpoint accepts as it is."""

    path: Path
    blob: str
    agent: str = ""
    """The conversation that wrote it: empty for the session's own, else a subagent's."""
    told: bool = False
    """Whether what its judgement found was told as it was judged, beside the
    call that wrote it: a file tool's write, judged before it landed. The
    checkpoint accepting it doesn't tell it again; a held change the operator
    approved is told there, since its hold told only the answer."""


class Checked(Model):
    """What a checkpoint did, for the agent to hear, every file named in full.

    Its findings are those the conversation it's for wasn't told yet
    (`Session.news`).
    """

    refused: list[Refused] = []
    moves: list[Moved] = []
    findings: list[Finding] = []
    """lup's findings on the lines the calls changed."""
    information: list[Finding] = []
    untouched: list[Finding] = []
    importers: list[Finding] = []
    removed: list[RemovedNote] = []
    notices: list[str] = []
    """What else the agent hears: holds approved, late answers."""

    def parts(self) -> list[Part]:
        """Say everything the checkpoint did that the agent should hear, a part per section: what was refused, what a move brought, the notices and the notes removed, each always whole, and the findings, which a long report tells short (`fitted`)."""
        return [
            *(
                Part(whole=said)
                for said in [refusal(self.refused), moved(self.moves), *self.notices]
                if said
            ),
            *information(
                self.findings, self.information, self.untouched, self.importers
            ),
            *([Part(whole=removed_notes(self.removed))] if self.removed else []),
        ]

    def then(self, later: Checked) -> Checked:
        """Return this report followed by a later one."""
        return Checked(
            refused=[*self.refused, *later.refused],
            moves=[*self.moves, *later.moves],
            findings=[*self.findings, *later.findings],
            information=[*self.information, *later.information],
            untouched=[*self.untouched, *later.untouched],
            importers=[*self.importers, *later.importers],
            removed=[*self.removed, *later.removed],
            notices=[*self.notices, *later.notices],
        )

    @staticmethod
    def together(reports: list[Checked]) -> Checked:
        """Return `reports` as one, in order: each section gathers theirs, whichever worktree each is of."""
        return reduce(Checked.then, reports, Checked())


class Mail(Model):
    """A report waiting for a conversation other than the one a checkpoint ran for, its findings those it wasn't told."""

    agent: str
    checked: Checked = Checked()


type ByConversation[T] = dict[str, list[T]]
"""Kept for each conversation of a session: `""` for its own, a subagent's id else."""


class Session(MutableModel):
    """What the store remembers about one session in a worktree."""

    key: str
    runtime: str
    worktree: Path
    approved: list[Path] = []
    """Paths the operator approved, whose design asks are covered from then on."""
    touched: ByConversation[Path] = {}
    """Files each conversation changed, which must be clean when its turn ends."""
    watched: ByConversation[Path] = {}
    """Files importing what each conversation changed that had type errors, checked
    when its turn ends."""
    removed: dict[Path, list[RemovedNote]] = {}
    """By file, the notes present at the session's start that are gone since."""
    listed: list[RemovedNote] = []
    """Removed notes already listed at a turn's end."""
    pending: list[Pending] = []
    judged: list[Judged] = []
    participants: list[str] = []
    """Conversations whose calls finished since the last checkpoint."""
    mail: list[Mail] = []
    flagging: ByConversation[Path] = {}
    """Files each conversation wrote flagged, whose item in the operator's
    inbox may still gather its writes to them: a later write to one refreshes
    that item, whatever it flags, until the inbox says none gathers them
    (`policy/flags.py`). A write to any other file asks the inbox nothing."""
    known: ByConversation[Known] = {}
    """The findings in this worktree's files each conversation was told and
    that still stand, so it isn't told them again (`news`); forgotten when its
    conversation is compacted or cleared."""

    def news(self, agent: str, looks: list[Look]) -> list[Finding]:
        """Return what of `looks` conversation `agent` wasn't told, and remember it told."""
        heard = news(self.known.get(agent, []), looks)
        self.known = {**self.known, agent: heard.known}
        return heard.findings

    def waiting(self, now: datetime) -> None:
        """Forget each pending write whose call must be over by `now`, no end having confirmed it."""
        self.pending = [each for each in self.pending if not over(each.judged, now)]

    def files(self, agent: str) -> list[Path]:
        """Return the files conversation `agent` touched, and those it watches."""
        return list(
            dict.fromkeys([*self.touched.get(agent, []), *self.watched.get(agent, [])])
        )

    def flagged(self, agent: str, paths: list[Path]) -> None:
        """Note that conversation `agent` wrote `paths` flagged, each in an item of the operator's that gathers its writes to it."""
        self.flagging = kept_by(self.flagging, {path: [agent] for path in paths})

    def unflagged(self, agent: str, paths: list[Path]) -> None:
        """Forget `paths` of conversation `agent`'s, whose item the inbox says gathers its writes to them no more."""
        kept = [path for path in self.flagging.get(agent, []) if path not in paths]
        self.flagging = {**self.flagging, agent: kept}


def kept_by(
    kept: dict[str, list[Path]], wrote: dict[Path, list[str]]
) -> dict[str, list[Path]]:
    """Add each file in `wrote` to the files kept for each conversation it names."""
    agents = dict.fromkeys(agent for writers in wrote.values() for agent in writers)
    return {
        **kept,
        **{
            agent: list(
                dict.fromkeys(
                    [
                        *kept.get(agent, []),
                        *(path for path, writers in wrote.items() if agent in writers),
                    ]
                )
            )
            for agent in agents
        },
    }


def decoded(content: bytes | None) -> str | None:
    """Read file content as text, or none where there's no file."""
    return None if content is None else content.decode(errors="replace")


class LastDeclaration(Model):
    """The last of a repository's declarations that loaded, kept for when one can't.

    It's kept resolved, as the values judging reads: the declaration itself may
    hold a project's own module or runner, which JSON can't bring back.
    """

    declaration: Declaration
    commit: str
    """The commit it was read from."""
    told: str = ""
    """The failure to load a declaration that the agent was last told of."""


class Loaded(Model):
    """The declaration a worktree is judged by, and where it came from."""

    declaration: Declaration
    root: Path
    """Where it was imported from: a commit's export, or the worktree's own files.
    The conditions modules it names are read there too."""
    commit: str | None = None
    """The commit it was read from; none for the worktree's own files."""
    failure: str = ""
    """Why the declaration due couldn't load, where the repository's last stands in."""


class Judging(Model):
    """Where the declaration a worktree is judged by is read from."""

    integration: str
    """The branch whose tip holds it before the operator approves a commit;
    without one, the worktree's `HEAD` commit."""
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

        It's judged by the declaration at the commit the operator approved, or
        before any approval at the integration branch's tip, never by its own, so
        a branch can't change what judges it (#21).
        """
        store = Store(layout=services.layout.store(root), worktree=root)
        judging = Judging(integration=services.integration, layout=services.layout)
        return cls(root=root, repository=repository, store=store, judging=judging)

    @classmethod
    def main(cls, repository: Path, services: Services) -> Worktree:
        """Open the repository whose common git directory is `repository` at its main worktree, git pinned there, to read the declaration it's judged by.

        That declaration is the repository's whichever of its worktrees asks
        (`loaded`), so a repository's process makes its modules from it once
        for every launch (`lup_dev.worker`). The main worktree is a clone's
        root, or a bare repository's own directory.
        """
        root = Git.pinned(repository).main_worktree()
        store = Store(
            layout=services.layout.store(root), worktree=root, common=repository
        )
        judging = Judging(integration=services.integration, layout=services.layout)
        return cls(root=root, repository=repository, store=store, judging=judging)

    @cached_property
    def loaded(self) -> Loaded:
        """The declaration it's judged by, loaded when first read.

        Read from the commit the operator approved last for the repository
        (`lup_dev.approval`), with the person's own layer approved with it beside
        the declaration, never the worktree's own copy of it, so what runs on the
        host is what they approved. Before any approval, from the integration
        branch's tip, with no layer of the person's, or where the
        repository has no such branch, from the worktree's `HEAD` commit; the
        defaults before any commit. Each that loads is kept for the repository,
        and where one can't load, or the approved commit is gone from the
        repository, the last kept stands in.
        """
        judging = self.judging
        if judging is None:
            return Loaded(declaration=Declaration.read(self.root), root=self.root)
        approval = approved(judging.layout, self.repository)
        commit = (
            approval.commit
            if approval is not None
            else self.store.tip(judging.integration) or self.store.head()
        )
        if commit is None:
            return Loaded(declaration=Declaration.of(Project()), root=self.root)
        kept = judging.layout.declaration(self.repository)
        local = approval.local if approval is not None else None

        def read(commit: str) -> Loaded:
            if approval is not None and self.store.repository().commit(commit) is None:
                message = (
                    f"the commit approved last, {commit}, isn't in the repository: "
                    "approve the integration branch's tip with `lup-dev trust`"
                )
                raise ProjectError(message)
            source = self.exported(judging.layout, commit, local)
            return Loaded(
                declaration=Declaration.read(source), root=source, commit=commit
            )

        try:
            found = read(commit)
        except ProjectError as failure:
            last = read_model(kept, LastDeclaration)
            if last is None:
                raise
            return Loaded(
                declaration=last.declaration,
                root=self.exported(judging.layout, last.commit),
                commit=last.commit,
                failure=f"{commit}: {failure}",
            )
        with FileLock(kept.with_name(f"{kept.name}.lock")):
            last = read_model(kept, LastDeclaration)
            if (
                last is None
                or last.commit != commit
                or last.declaration != found.declaration
            ):
                told = last.told if last else ""
                write_model(
                    kept,
                    LastDeclaration(
                        declaration=found.declaration, commit=commit, told=told
                    ),
                )
        return found

    def exported(self, layout: Layout, commit: str, local: str | None = None) -> Path:
        """Return where `commit`'s Python modules are exported, with `local` beside its declaration, exporting them once.

        `local` is the person's own layer approved with the commit, which git
        holds none of; none where none was approved. A commit's export is
        written whole before it's moved into place, and the repository's
        earlier exports are removed: only the latest is read.
        """
        target = layout.exported(self.repository, commit, local)
        if target.is_dir():
            return target
        partial = target.with_name(f"{commit}.{secrets.token_hex(4)}.partial")
        self.store.export(commit, partial)
        if local is not None:
            CheckoutLayout(root=partial).local_declaration.write_text(local)
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
    def declaration(self) -> Declaration:
        """The declaration it's judged by, or the one standing in for it."""
        return self.loaded.declaration

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
            "approving `dev`'s with `lup-dev trust` fixes this; otherwise the "
            "declaration needs fixing."
        )

    @cached_property
    def roles(self) -> Roles:
        """The role of each path in it, from the declaration it's judged by."""
        return Roles(root=self.root, declaration=self.declaration)

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

    def ran(self, running: Running, now: datetime) -> None:
        """Store the calls running, forgetting those that must be over by `now`; hold the calls lock."""
        running.lasting(now)
        write_model(self.store.layout.calls, running)

    def recorded(self, key: str) -> Session | None:
        """Read what the store remembers about session `key`; none where nothing."""
        return read_model(self.store.layout.session(key), Session)

    def session(self, key: str, runtime: Runtime) -> Session:
        """Read what the store remembers about session `key`, or start remembering."""
        found = self.recorded(key)
        return found or Session(key=key, runtime=runtime.name(), worktree=self.root)

    def keep(self, session: Session) -> None:
        """Store what to remember about a session."""
        write_model(self.store.layout.session(session.key), session)

    def forget(self, key: str, agent: str) -> None:
        """Forget the findings session `key`'s conversation `agent` was told here (`Session.known`), so what still stands is told again."""
        with self.lock():
            session = self.recorded(key)
            if session is None or agent not in session.known:
                return
            session.known = {
                each: known for each, known in session.known.items() if each != agent
            }
            self.keep(session)

    def judge(
        self, services: Services, approved: list[Path], *, holding: bool = False
    ) -> Judge:
        """Return a judge for this worktree, the operator having approved `approved`, and holding each flagged write where `holding`.

        It finds the values never published listed on the host for the
        repository (`withheld`).
        """
        return Judge(
            root=self.root,
            roles=self.roles,
            checker=services.checker,
            linter=services.linter,
            conditions=declared(self.loaded.root, self.declaration.conditions),
            approved=approved,
            holding=holding,
            withheld=self.withheld(services),
        )

    def withheld(self, services: Services) -> Withheld | None:
        """Return the values never published listed on the host for the repository, building the list where none is kept and the declaration it's judged by selects `Private`, as a launch would, and keeping it.

        Where it can't be built, the judge finds none, and the write is judged
        as it would be without the module: a write is never refused for a
        value, and the door, which builds the list too, says why it can't.
        """
        data = services.layout.module_data(Private.name, self.repository)
        kept = read_model(listed_at(data), Withheld)
        if kept is not None or Private.name not in self.declaration.modules:
            return kept
        try:
            resolved = resolve(load(self.loaded.root).project)
            made = asyncio.run(
                listed(resolved, self.repository, services.facts, services.layout)
            )
        except LupDevError, OSError:
            return None
        return None if made is None else made.withheld

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

    def finish(self, session: str, call: str, now: datetime) -> Finished:
        """Note that `call` finished here by `now`; say whether it counted here, and whether no call of `session` is left running here."""
        with self.calls_lock():
            running = self.running()
            counted = any(each.key == call for each in running.calls)
            running.calls = [each for each in running.calls if each.key != call]
            self.ran(running, now)
            return Finished(counted=counted, idle=running.idle(session))

    def clear(self, session: str, agent: str, now: datetime) -> Finished:
        """Forget the calls conversation `agent` left running, by `now`; say whether one counted here, and whether none of its session's is left."""
        with self.calls_lock():
            running = self.running()
            counted = any(each.of(session, agent) for each in running.calls)
            running.calls = [
                each for each in running.calls if not each.of(session, agent)
            ]
            self.ran(running, now)
            return Finished(counted=counted, idle=running.idle(session))

    def busy(self, session: str, agent: str) -> bool:
        """Say whether a call of another conversation of `session` runs here."""
        with self.calls_lock():
            return any(
                each.session == session and not each.of(session, agent)
                for each in self.running().calls
            )


def begin(bench: Bench, worktree: Worktree, key: str) -> None:
    """Start, or resume, a session in a worktree: accept the worktree as it is.

    What changed while the session made no call there is the operator's work, a
    pull or another session's, and is accepted unjudged, and the worktree's `HEAD`
    is recorded with it. A file under an open hold isn't: it keeps its accepted
    content, left to the hold's answer, and the session starts from that. While a
    call of the session runs there (one left running as it resumes), the accepted
    tree stays, and that call's checkpoint judges what it writes. A resumed
    session keeps the tree it started from.
    """
    store = worktree.store
    with worktree.lock():
        with worktree.calls_lock():
            busy = not worktree.running().idle(key)
        accepted = store.accepted()
        start = accepted if busy else None
        if start is None:
            taken = store.snapshot()
            state = store.state()
            held = [each.path for each in state.holding]
            start = (
                store.unstage(accepted, held, [])
                if accepted is not None and held
                else taken
            )
            store.accept(start)
            head = store.head()
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
    agent: str = "",
    starts: bool = False,
) -> Holding | None:
    """Return a session's repository and the worktrees it holds, reaching more.

    The worktree its working directory is in is reached, since a hook's working
    directory follows the session, and so is `written`'s, where a file tool
    writes; conversation `agent` is noted to work in each (`Holding.works`).
    Reaching a worktree begins the session there; a session that `starts`, or
    resumes, begins again in every worktree it holds. A worktree whose root is
    gone isn't held. A session first seen outside every repository isn't judged.
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
        repository = held.repository

        def within(where: Place | None) -> Path | None:
            if where is None or where.repository != repository:
                return None
            return where.worktree

        reaching = [
            each for each in [within(here), within(written)] if each is not None
        ]
        reached = [each for each in reaching if held.reach(each)]
        noted = held.note(agent, started=within(here), wrote=within(written))
        if recorded is None or reached or released or noted:
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


def working(bench: Bench, held: Holding, agent: str) -> list[Worktree]:
    """Open each worktree conversation `agent` of a session works in."""
    services = bench.services
    return [Worktree.of(root, held.repository, services) for root in held.works(agent)]


class Planned(Model):
    """A changed file and what the checkpoint does with it."""

    path: Path
    change: Change | None = None
    """The session's change, judged as an edit is; none where it made none."""
    decide: bool = True
    """Whether its outcome decides what happens; else it was judged already."""
    told: bool = False
    """Whether what it was judged to hold was told as it was judged (`Judged.told`),
    so the checkpoint doesn't tell it again."""
    moved: Change | None = None
    """What a move of `HEAD` brought that no checkpoint judged, judged once as its
    commits'; none where the move brought nothing unjudged."""
    base: Entry | None = None
    """The file as `HEAD` has it, where a move changed it: the move is accepted,
    and a refused change goes back to it."""


def noted(root: Path, notes: list[RemovedNote]) -> list[RemovedNote]:
    """Name each removed note's file by its absolute path, under the worktree `root`."""
    return [note.model_copy(update={"path": root / note.path}) for note in notes]


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


def held_files(store: Store, accepted: str, files: list[HeldFile]) -> list[ChangedFile]:
    """Return each held file whole: its content in the accepted tree, and the held content, none where the change deletes it; with the judge's reading of it."""
    return [
        ChangedFile.of(
            held.path,
            store.content(accepted, held.path),
            store.object(held.blob) if held.blob else None,
            held.reading,
        )
        for held in files
    ]


class Fates(Model):
    """A checkpoint's judgements, by what happens to each file."""

    held: list[Judgement] = []
    accepted: list[Judgement] = []


def fates(judgements: list[Judgement], deciding: list[Path]) -> Fates:
    """Sort a checkpoint's judgements by what happens to each file: an ask this checkpoint decides is held, on every runtime, its agent waiting inside the hook."""

    def fate(judgement: Judgement) -> Literal["held", "accepted"]:
        if judgement.path not in deciding:
            return "accepted"
        match judgement.outcome:
            case "ask":
                return "held"
            case "allow":
                return "accepted"

    each = {judgement.path: fate(judgement) for judgement in judgements}
    return Fates(
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
    judged: dict[Path, Judged]
    """Content already judged, by path: the last judged there."""
    move: Move | None = None

    def plan(self, path: Path) -> Planned:
        """Plan what to do with one changed path."""
        store = self.store
        blob = store.blob(self.taken, path)
        prior = self.judged.get(path)
        after = decoded(store.content(self.taken, path))
        baseline = decoded(store.content(self.start, path))
        accepted = decoded(store.content(self.accepted, path))
        if prior is not None and prior.blob == blob:
            change = Change(path=path, before=accepted, after=after, baseline=baseline)
            return Planned(path=path, change=change, decide=False, told=prior.told)
        if self.move is not None and path in self.move.paths:
            return self.moving(path, self.move)
        if self.elsewhere.holds(path, blob):
            return Planned(path=path)
        before = accepted if prior is None else decoded(store.object(prior.blob))
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
    agent: str = ""
    """The runtime's id for the subagent whose call's finish ran it; empty for the
    session's own conversation."""
    call: str | None = None
    """The runtime's id for the call whose finish ran it; none at a turn's end."""


def act(
    bench: Bench, worktree: Worktree, snapshot: Snapshot, decided: Decided
) -> Acted:
    """Hold what waits, put before the operator, and accept the rest; hold the lock.

    A held file keeps its accepted content in the store, or `HEAD`'s where a
    move changed it, since the move is accepted, until the operator answers.
    """
    store = worktree.store
    root = worktree.root
    judged = decided.fates
    state = store.state()
    held_paths = [judgement.path for judgement in judged.held]
    kept_out = [*held_paths, *(each.path for each in state.holding)]
    bases = [plan.base for plan in decided.plans if plan.base and plan.path in kept_out]
    based = [base.path for base in bases]
    tree = (
        store.unstage(
            snapshot.accepted, [path for path in kept_out if path not in based], bases
        )
        if kept_out
        else snapshot.taken
    )
    held = [
        HeldFile(
            path=judgement.path,
            role=judgement.role,
            blob=store.blob(snapshot.taken, judgement.path) or "",
            reasons=[ask.kind for ask in judgement.asks],
            asks=[ask.reason for ask in judgement.asks],
            reading=judgement.reading(),
        )
        for judgement in judged.held
    ]
    hold = (
        worktree.holds().put(
            Hold(
                key=decided.hold,
                worktree=root,
                session=snapshot.session,
                agent=decided.agent or None,
                call=decided.call,
                created=bench.services.clock.now(),
                files=held,
                diff=held_diff(store, tree, held),
                verdicts=[each for each in decided.verdicts if each.path in held_paths],
            )
        )
        if held and decided.hold
        else None
    )
    if hold is not None:
        bench.services.announcing.announced(
            hold,
            bench.runtime.name(),
            worktree.repository,
            held_files(store, tree, held),
        )
    if tree != snapshot.accepted:
        store.accept(tree)
    state.tips = store.tips(snapshot.head)
    new_holding = [
        Held(hold=hold.key, path=each.path, blob=each.blob)
        for each in held
        if hold is not None
    ]
    state.holding = [*state.holding, *new_holding]
    store.remember(state)
    return Acted(hold=hold, landed=judged.accepted)


class Brought(Model):
    """What a move of `HEAD` brought, judged once: what to tell, what landed, and what landed flagged, to put before the operator."""

    told: Checked = Checked()
    """The move, and lup's findings on the lines its commits touched."""
    landed: list[Judgement] = []
    """Each file it brought, judged: their type errors and ruff's findings are
    told as a checkpoint's are, each once (`remember`)."""
    flagged: list[Landed] = []


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
            reading=judgement.reading(),
        )
        for judgement in asking
    ]
    if key is not None:
        hold = worktree.holds().put(
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
        services.announcing.announced(
            hold,
            bench.runtime.name(),
            worktree.repository,
            held_files(store, snapshot.accepted, files),
        )
    worktree.verdicts(services.layout).append(logged)
    report = Moved(
        worktree=root,
        head=move.after,
        files=[
            MovedFile(
                path=root / judgement.path,
                findings=placed(root, judgement.findings),
                asks=judgement.asks,
                removed=noted(root, judgement.removed),
            )
            for judgement in judgements
        ],
        hold=key,
    )
    told = Checked(moves=[report])
    landed = [
        Landed(
            change=change,
            judgement=judgement,
            session=snapshot.session,
            commit=move.after,
        )
        for change, judgement in zip(changes, judgements, strict=True)
        if judgement.outcome == "allow" and judgement.flags
    ]
    return Brought(told=told, landed=judgements, flagged=landed)


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


def checkpoint(
    bench: Bench, worktree: Worktree, key: str, agent: str, call: str | None = None
) -> Checked:
    """Judge what changed since the accepted tree, act on it, and report; `call` is the call whose finish ran it, which a hold it makes is anchored to.

    What landed flagged, the conversation's writes and what a move brought, is
    put before the operator once the store is released (`flagged`), with the
    conversation's writes to a file an item of its may gather, which refresh
    that item (`Session.flagging`). Holds are
    waited on then, settled, and the checkpoint runs again for what the
    operator approved.
    """
    services = bench.services
    store = worktree.store
    root = worktree.root
    with worktree.lock():
        session = worktree.session(key, bench.runtime)
        reviewed = orphans(bench, worktree)
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
            judged={**{each.path: each for each in session.judged}, **reviewed},
            move=moving(worktree, heads, head) if changed else None,
        )
        plans = [snapshot.plan(path) for path in changed]
        wrote = writers(session, plans, agent)
        changes = [plan.change for plan in plans if plan.change is not None]
        judgements = (
            worktree.judge(
                services,
                session.approved,
                holding=services.announcing.holding(
                    bench.runtime.name(), key, agent or None
                ),
            ).judge(changes)
            if changes
            else []
        )
        deciding = [plan.path for plan in plans if plan.change and plan.decide]
        fated = fates(judgements, deciding)
        approved = session.approved
        gathering = session.flagging.get(agent, [])
        landed = [
            Landed(
                change=change,
                judgement=judgement,
                session=key,
                agent=agent or None,
                call=call,
            )
            for change, judgement in zip(changes, judgements, strict=True)
            if judgement.path in deciding
            and judgement.outcome == "allow"
            and (judgement.flags or judgement.path in gathering)
        ]
        session.flagged(
            agent, [each.change.path for each in landed if each.judgement.flags]
        )
        held = [judgement.path for judgement in fated.held]
        hold = worktree.holds().unused() if held else None
        to = Attributed(worktree=root, session=key, tool="checkpoint")
        logged = [
            verdict(bench, to, judgement, hold if judgement.path in held else None)
            for judgement in judgements
            if judgement.path in deciding
        ]
        decided = Decided(
            fates=fated, plans=plans, verdicts=logged, hold=hold, agent=agent, call=call
        )
        acted = act(bench, worktree, snapshot, decided)
        worktree.verdicts(services.layout).append(logged)
        commits = brought(bench, worktree, snapshot, plans)
        if root not in heads.worktrees or heads.worktrees[root] != head:
            worktree.record(services.layout, head)
        notice = worktree.told() if plans else ""
        told = commits.told.then(Checked(notices=[notice] if notice else []))
        checked = remember(
            worktree,
            session,
            agent,
            acted,
            told=told,
            moved=commits.landed,
            wrote=wrote,
            heard=[plan.path for plan in plans if plan.told],
            unjudged=[
                plan.path
                for plan in plans
                if plan.change is None and plan.moved is None
            ],
        )
    runtime = bench.runtime.name()
    wrote_flagged = (
        flagged(
            services.flagging,
            worktree.judge(services, approved),
            runtime,
            worktree.repository,
            landed,
        )
        if landed
        else Put()
    )
    unflag(bench, worktree, key, agent, wrote_flagged.read)
    commits_flagged = (
        flagged(
            services.flagging,
            worktree.judge(services, []),
            runtime,
            worktree.repository,
            commits.flagged,
        )
        if commits.flagged
        else Put()
    )
    unsaid = [*wrote_flagged.unsaid, *commits_flagged.unsaid]
    checked = checked.then(Checked(notices=unsaid))
    python = list(
        dict.fromkeys(
            judgement.path
            for judgement in [*acted.landed, *commits.landed]
            if worktree.roles.checked(judgement.path)
        )
    )
    by = [
        Conversation(session=key, agent=writer)
        for writer in dict.fromkeys(writer for path in python for writer in wrote[path])
    ]
    worktree.importers().request(python, by, services.spawner)
    if acted.hold is None:
        return checked
    return checked.then(settle(bench, worktree, key, agent, acted.hold))


def unflag(
    bench: Bench, worktree: Worktree, key: str, agent: str, paths: list[Path]
) -> None:
    """Forget, in session `key`'s record, that an item gathers conversation `agent`'s writes to `paths`, as the inbox said none does: a write to one asks it nothing more."""
    if not paths:
        return
    with worktree.lock():
        session = worktree.session(key, bench.runtime)
        session.unflagged(agent, paths)
        worktree.keep(session)


def writers(
    session: Session, plans: list[Planned], agent: str
) -> dict[Path, list[str]]:
    """Say which conversations wrote each changed file, by path; hold the lock.

    Content judged before it landed, a file tool's write or a held write the
    operator approved, is the conversation's that made it. The checkpoint sees
    files, not who wrote them, so anything else is every conversation's whose
    calls finished since the last checkpoint, and the one it runs for: holding a
    conversation's end on a file it didn't write is the safe side (#41).
    """
    anyone = list(dict.fromkeys([*session.participants, agent]))
    last = {each.path: each.blob for each in session.judged}

    def wrote(plan: Planned) -> list[str]:
        if plan.decide:
            return anyone
        return list(
            dict.fromkeys(
                each.agent
                for each in session.judged
                if each.path == plan.path and each.blob == last[plan.path]
            )
        )

    return {plan.path: wrote(plan) for plan in plans}


def on_disk(root: Path, path: Path) -> str | None:
    """Read the file at `path` in the worktree at `root` as text, or none where there's no file."""
    whole = root / path
    return decoded(whole.read_bytes()) if whole.is_file() else None


def watch(worktree: Worktree, session: Session, found: Found) -> list[Look]:
    """Watch the files the importers pass found errors in; hold the lock.

    Each is watched for the conversations that wrote what the pass re-checked, in
    their own session's record: the pass is the worktree's, so `session`, whose
    hook collected what it found, may not be theirs. Return what the pass read
    of each file, its latest reading of one it read more than once: pyright's
    errors there, as the roles keep them, each file named relative to the
    worktree.
    """
    latest = {report.path: report for report in found.reports}
    looks = [
        Look(
            path=path,
            owners=["pyright"],
            findings=[
                each
                for each in worktree.roles.kept(report, report.findings)
                if each.owner != "lup"
            ],
            content=on_disk(worktree.root, path),
        )
        for path, report in latest.items()
    ]
    paths = [look.path for look in looks if look.findings]
    for key in dict.fromkeys(writer.session for writer in found.writers):
        record = session if key == session.key else worktree.recorded(key)
        if record is None:
            continue
        agents = [writer.agent for writer in found.writers if writer.session == key]
        record.watched = kept_by(record.watched, dict.fromkeys(paths, agents))
        if record is not session:
            worktree.keep(record)
    return looks


def remember(
    worktree: Worktree,
    session: Session,
    agent: str,
    acted: Acted,
    *,
    told: Checked,
    moved: list[Judgement],
    wrote: dict[Path, list[str]],
    heard: list[Path],
    unjudged: list[Path],
) -> Checked:
    """Note in the session what a checkpoint did, and report it; hold the lock.

    The report goes to the conversation the checkpoint ran for, and waits as mail
    for the others whose calls finished since the last one: the checkpoint sees
    files, not who wrote them. Each is told only the findings it wasn't told
    yet (`Session.news`). Each file landed is touched by the conversations
    `wrote` names for it. `told` is what a move of `HEAD` brought, which is no
    session's, and `moved` the files it brought, judged. The files in `heard`
    were told what was found in them as they were judged, so only the notes
    their writes removed are reported. The files in `unjudged` changed to
    content committed elsewhere, set aside unjudged: what was known of them is
    forgotten, so a finding they hold again is told again.
    """
    root = worktree.root
    landed = acted.landed
    fresh = [j for j in landed if j.path not in heard]
    importing = watch(worktree, session, worktree.importers().collect())
    every: list[Owner] = ["lup", "pyright", "ruff"]
    looks = [
        *(
            Look(
                path=j.path,
                owners=every,
                findings=[*j.findings, *j.information, *j.untouched],
                content=on_disk(root, j.path),
            )
            for j in fresh
        ),
        *(
            Look(
                path=j.path,
                owners=["pyright", "ruff"],
                findings=j.information,
                content=on_disk(root, j.path),
            )
            for j in moved
        ),
        *(Look(path=path, owners=every) for path in unjudged),
        *importing,
    ]
    said = Checked(
        removed=noted(root, [note for j in landed for note in j.removed]),
        notices=late_answers(worktree, session),
    ).then(told)

    def report(conversation: str) -> Checked:
        new = dict.fromkeys(session.news(conversation, looks))

        def kept(found: list[Finding]) -> list[Finding]:
            return placed(root, [each for each in found if each in new])

        return Checked(
            findings=kept([found for j in fresh for found in j.findings]),
            information=kept(
                [found for j in [*fresh, *moved] for found in j.information]
            ),
            untouched=kept([found for j in fresh for found in j.untouched]),
            importers=kept([found for look in importing for found in look.findings]),
        ).then(said)

    others = [other for other in session.participants if other != agent]
    checked = report(agent)
    mailed = [Mail(agent=other, checked=report(other)) for other in others]
    session.touched = kept_by(session.touched, {j.path: wrote[j.path] for j in landed})
    session.removed = {
        **session.removed,
        **{j.path: j.removed for j in landed if worktree.roles.ruled(j.path)},
    }
    session.judged = []
    session.participants = []
    session.mail = [*session.mail, *(mail for mail in mailed if mail.checked.parts())]
    worktree.keep(session)
    return checked


PUT_BACK = "It was put back, or never landed, and your version saved."
"""Said of a declined change whose hold no call waited on."""


def late_answers(worktree: Worktree, session: Session) -> list[str]:
    """Tell the answers given to holds no agent waited on; hold the lock.

    For a hold whose wait ran out or whose call was interrupted, an approval
    covers the paths for the rest of the session, so the saved version can go
    back into place; so it does for one whose call's process ended, settled at
    a checkpoint (`orphans`), told with whether the change is in place. For a
    move's, the session that found the move hears the answer, and a decline
    changes no file.
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
        if hold.orphaned:
            return (
                "lup's host service went away while your call waited for the "
                f"operator's answer to the change to {named}, which they have since "
                f"{verb}{comment} {placed(hold) if approved else PUT_BACK}"
            )
        after = (
            "your call was interrupted" if hold.interrupted else "the hold timed out"
        )
        return (
            f"After {after}, the operator {verb} the change to {named}"
            f"{comment} Your version was saved when it was put back."
        )

    def placed(hold: Hold) -> str:
        on_disk = all(
            (worktree.root / held.path).is_file()
            and (worktree.root / held.path).read_bytes()
            == worktree.store.object(held.blob)
            for held in hold.files
        )
        if on_disk:
            return "It's in place."
        return (
            "It isn't in place, the file having changed since: make the change "
            "again if it's still wanted."
        )

    return [told(hold) for hold in holds.late() if hold.session == session.key]


def settle(
    bench: Bench, worktree: Worktree, key: str, agent: str, hold: Hold
) -> Checked:
    """Wait for the operator's answer to `hold`, then act on it.

    An approval accepts the held content as it is, the agent told it was held
    and approved (`approval`); a decline, or no answer in time, puts it back
    with the agent's version saved. A call its runtime ended while it waited
    (`Bench.interrupted`) gives up as on no answer, its conversation told at
    its next call, since nothing hears this one's answer. The call holds its
    lock while it waits (`Holds.waiting`); a hold settled meanwhile with no
    call waiting on it (`orphans`) is a later checkpoint's to tell.
    """
    services = bench.services
    store = worktree.store
    root = worktree.root
    holds = worktree.holds()
    paths = [held.path for held in hold.files]
    log = worktree.verdicts(services.layout)
    with holds.waiting(hold.key):
        answer = holds.wait(hold.key, services.clock, ended=bench.interrupted)
        interrupted = answer is None and bench.interrupted()
        with worktree.lock():
            state = store.state()
            if all(each.hold != hold.key for each in state.holding):
                return Checked()
            state.holding = [each for each in state.holding if each.hold != hold.key]
            if answer is None or not answer.approved:
                accepted = store.accepted() or ""
                number = state.saved + 1
                refused = [
                    Refused(
                        path=root / held.path,
                        saved=store.save(
                            number, held.path, store.object(held.blob) or b""
                        ),
                        new=store.content(accepted, held.path) is None,
                        declined=None if answer is None else answer.comment,
                        unanswered=answer is None and not interrupted,
                        interrupted=interrupted,
                    )
                    for held in hold.files
                ]
                store.restore(accepted, paths)
                state.saved = number
                store.remember(state)
                if answer is None:
                    holds.mark(hold.key, abandoned=True, interrupted=interrupted)
                if interrupted:
                    session = worktree.session(key, bench.runtime)
                    told = Mail(agent=agent, checked=Checked(refused=refused))
                    session.mail = [*session.mail, told]
                    worktree.keep(session)
                log.append(answered(hold, outcome(holds, hold.key, answer)))
                return Checked(refused=refused)
            session = worktree.session(key, bench.runtime)
            session.judged = [
                *session.judged,
                *(
                    Judged(path=held.path, blob=held.blob, agent=agent)
                    for held in hold.files
                ),
            ]
            session.approved = list(dict.fromkeys([*session.approved, *paths]))
            store.remember(state)
            worktree.keep(session)
    log.append(answered(hold, "approved"))
    told = approval([root / path for path in paths], answer.comment)
    return Checked(notices=[told]).then(checkpoint(bench, worktree, key, agent))


def orphans(bench: Bench, worktree: Worktree) -> dict[Path, Judged]:
    """Settle each open hold no call waits on any more, as its call would have; hold the lock.

    A call's wait ends with its process, the host service's or the launch's,
    leaving its hold open and its files held (`Held`), whoever's checkpoint
    finds it. Once the operator answers, an approval keeps the change as
    reviewed: a file tool's write, which never landed, is made where the file
    is still as it was accepted, and the content approved that's on disk is
    returned by path, for the checkpoint to accept unjudged; a decline puts the
    file back as it was accepted, a file tool's write that landed anyway among
    it, and saves the agent's version. Unanswered past its patience, it's put
    back and saved as a call's would be, and stays open. Each is logged, and
    told to its session at that session's next checkpoint (`late_answers`).
    """
    store = worktree.store
    holds = worktree.holds()
    state = store.state()
    now = bench.services.clock.now()

    def due(key: str) -> Hold | None:
        hold = holds.get(key)
        if hold is None or not hold.waited() or holds.waited_on(key):
            return None
        if hold.answer is None and now < hold.created + holds.patience:
            return None
        return hold

    found = [due(key) for key in dict.fromkeys(each.hold for each in state.holding)]
    settled = [hold for hold in found if hold is not None]
    if not settled:
        return {}
    keys = [hold.key for hold in settled]
    state.holding = [each for each in state.holding if each.hold not in keys]
    reviewed = {
        each.path: each
        for hold in settled
        for each in orphaned(bench, worktree, state, hold)
    }
    store.remember(state)
    return reviewed


def orphaned(
    bench: Bench, worktree: Worktree, state: WorktreeState, hold: Hold
) -> list[Judged]:
    """Settle one hold no call waits on any more, its answer come or its patience out (`orphans`); return the content approved that's on disk, accepted as reviewed.

    `state` is the worktree's, kept by the caller, which counts what's saved.
    """
    store = worktree.store
    holds = worktree.holds()
    accepted = store.accepted()
    log = worktree.verdicts(bench.services.layout)
    answer = hold.answer
    if answer is not None and answer.approved:
        holds.mark(hold.key, orphaned=True)
        log.append(answered(hold, "approved"))
        return [
            Judged(path=held.path, blob=held.blob, agent=hold.agent or "", told=True)
            for held in hold.files
            if approve(worktree, hold, held, accepted)
        ]
    number = state.saved + 1
    for held in hold.files:
        store.save(number, held.path, store.object(held.blob) or b"")
    state.saved = number
    if accepted is not None:
        store.restore(accepted, [held.path for held in hold.files])
    holds.mark(hold.key, abandoned=answer is None, orphaned=answer is not None)
    log.append(answered(hold, "unanswered" if answer is None else "declined"))
    return []


def approve(
    worktree: Worktree, hold: Hold, held: HeldFile, accepted: str | None
) -> bool:
    """Keep one file of an approved hold no call waits on any more, making a file tool's write that never landed where the file is still as it was accepted; say whether the content approved is on disk."""
    store = worktree.store
    there = worktree.root / held.path
    content = store.object(held.blob) if held.blob else None
    current = there.read_bytes() if there.is_file() else None
    left = store.content(accepted, held.path) if accepted else None
    if hold.proposed and content is not None and current == left:
        there.parent.mkdir(parents=True, exist_ok=True)
        there.write_bytes(content)
        return True
    return content is not None and current == content


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


class Conversations(MutableModel):
    """What a conversation's turn's end needs to know of the others (#32, #41), and of its own ends before."""

    working: list[str] = []
    """The subagents at work, each from its first call to its conversation's end."""
    passed: ByConversation[Finding] = {}
    """What each conversation's turn last ended past: findings that hold none of
    its later ends (`inbox/ends.py`)."""


class ConversationRecord(Model):
    """Where a session keeps its `Conversations`, under a lock its hooks share.

    A subagent shares its session's id, and may touch a file another conversation
    of the session touched too (#32). It's known to be at work from its first call
    to the end of its conversation, on every runtime: a runtime that reported no
    end for it leaves it at work until the session starts again.
    """

    layout: Layout
    session: str

    def lock(self) -> FileLock:
        """Return the lock over the record."""
        path = self.layout.conversations(self.session)
        path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(path.with_name(f"{path.name}.lock"))

    def read(self) -> Conversations:
        """Read the record; hold the lock."""
        path = self.layout.conversations(self.session)
        return read_model(path, Conversations) or Conversations()

    def keep(self, conversations: Conversations) -> None:
        """Store the record; hold the lock."""
        write_model(self.layout.conversations(self.session), conversations)

    def opened(self, agent: str) -> None:
        """Note that subagent `agent` is at work, since it made a call."""
        with self.lock():
            kept = self.read()
            if agent in kept.working:
                return
            kept.working = [*kept.working, agent]
            self.keep(kept)

    def closed(self, agent: str) -> None:
        """Note that subagent `agent`'s conversation ended."""
        with self.lock():
            kept = self.read()
            if agent not in kept.working:
                return
            kept.working = [each for each in kept.working if each != agent]
            self.keep(kept)

    def restarted(self) -> None:
        """Forget the subagents at work: the session starts, or starts again.

        A subagent still at work is noted again at its next call. What its turns
        ended past is kept, so a resumed session isn't held again on it.
        """
        with self.lock():
            self.keep(Conversations(passed=self.read().passed))


def mail_for(worktree: Worktree, key: str, agent: str, runtime: Runtime) -> Checked:
    """Take the reports waiting for conversation `agent`, as one.

    A hook its runtime ended takes none (`Bench.interrupted`): nothing hears its
    answer, so they wait for the next.
    """
    with worktree.lock():
        session = worktree.session(key, runtime)
        waiting = [mail.checked for mail in session.mail if mail.agent == agent]
        session.mail = [mail for mail in session.mail if mail.agent != agent]
        worktree.keep(session)
    return Checked.together(waiting)


def confirm(bench: Bench, worktree: Worktree, key: str, agent: str, call: str) -> None:
    """Note that a call finished: a write judged before it landed has landed.

    It's conversation `agent`'s, and the content lup accepts from then on: a
    later write to the file is judged against it, at its call's start or at a
    checkpoint, and the checkpoint accepting it tells no more of what was told
    as it was judged.
    """
    with worktree.lock():
        session = worktree.session(key, bench.runtime)
        landed = [pending for pending in session.pending if pending.call == call]
        session.pending = [
            pending for pending in session.pending if pending.call != call
        ]
        session.waiting(bench.services.clock.now())
        session.judged = [
            *session.judged,
            *(
                Judged(path=pending.path, blob=pending.blob, agent=agent, told=True)
                for pending in landed
            ),
        ]
        session.removed = {
            **session.removed,
            **{pending.path: pending.removed for pending in landed},
        }
        session.participants = list(dict.fromkeys([*session.participants, agent]))
        worktree.keep(session)


def unclean(bench: Bench, worktree: Worktree, paths: list[Path]) -> list[Finding]:
    """Return lup's findings, the type errors and ruff's findings left in `paths`.

    As the files stand on disk, those that hold there (`Roles.kept`): lup's only
    where its rules read, so a test's are pyright's and ruff's alone, and none
    the declaration exempts the file from or an `ignore` keeps; each named by
    its absolute path. A finding ruff, or `lup-dev rules fix`, clears safely
    isn't one: the session landing the work applies the fix. The engine and
    ruff are asked with the rule selection and the runner of the declaration the
    worktree is judged by.
    """
    services = bench.services
    sources = [
        Source(path=path)
        for path in paths
        if (worktree.root / path).is_file() and worktree.roles.checked(path)
    ]
    if not sources:
        return []
    declaration = worktree.declaration
    reports = services.checker.check(
        worktree.root, sources, declaration.rules, declaration.runner
    )
    ruff = services.linter.findings(worktree.root, sources, declaration.runner)
    found = [
        found
        for report in reports
        for found in worktree.roles.kept(
            report,
            [*report.findings, *(each for each in ruff if each.path == report.path)],
        )
        if not found.fixable
    ]
    return placed(worktree.root, found)


class Ended(Model):
    """A conversation's turn's end in one worktree: its checkpoint, what's left."""

    checked: Checked
    remaining: list[Finding]
    """What's left in the files the conversation touched, and in those importing
    them, which holds its end: none in a file a subagent at work touched too,
    which may be its in progress (#32), and none at a subagent's end."""


def ended(
    bench: Bench,
    worktree: Worktree,
    key: str,
    agent: str,
    working: list[str],
    *,
    judging: bool = True,
) -> Ended:
    """Run conversation `agent`'s turn's end in one worktree the session holds.

    The checkpoint; then, at the session's own end, the importers pass waited on,
    and what's left in the files its conversation touched and in those importing
    them. What's left in a file a subagent in `working` touched too isn't
    counted: it may be the subagent's in progress. A subagent's end finds
    nothing, so runs no check and doesn't wait for the pass, which the next
    checkpoint or the session's end collects: every worker passes the gate
    before it hands back. A file under an open hold isn't anyone's until the
    operator answers, so it holds no end. Without `judging`,
    no checkpoint: another conversation's call is running there, whose finish
    runs it, so its writes in progress aren't judged as this one's, put back
    under it, or told to a conversation that didn't make them.
    """
    services = bench.services
    checked = checkpoint(bench, worktree, key, agent) if judging else Checked()
    if agent:
        return Ended(checked=checked, remaining=[])
    worktree.importers().wait(
        services.checker, worktree.declaration.runner, services.clock
    )
    with worktree.lock():
        session = worktree.session(key, bench.runtime)
        watch(worktree, session, worktree.importers().collect())
        worktree.keep(session)
        held = [each.path for each in worktree.store.state().holding]
    mine = [path for path in session.files(agent) if path not in held]
    shared = [
        worktree.root / path
        for path in mine
        if any(path in session.files(other) for other in working)
    ]
    found = unclean(bench, worktree, mine)
    return Ended(
        checked=checked,
        remaining=[each for each in found if each.path not in shared],
    )


def unlisted(bench: Bench, worktree: Worktree, key: str) -> list[RemovedNote]:
    """Take the notes present at the session's start, removed since, not listed yet."""
    with worktree.lock():
        session = worktree.session(key, bench.runtime)
        removed = [note for notes in session.removed.values() for note in notes]
        listing = [note for note in removed if note not in session.listed]
        session.listed = [*session.listed, *listing]
        worktree.keep(session)
    return noted(worktree.root, listing)


def end_turn(
    bench: Bench,
    event: Reported,
    opened: list[Worktree],
    judging: list[Path],
    *,
    repository: Path,
    after_block: bool,
    listing: bool,
) -> Reply:
    """End conversation `event.agent`'s turn in each worktree its session holds.

    In each, a checkpoint where `judging` names its root; at the session's own
    end, the importers pass waited on, and what's left in the files its
    conversation touched (`ended`), which a subagent's end never holds on. Those
    hold the session's end once per finding, across turns (`holding`, the
    inbox's `ends.py`): except in a file a subagent at work touched too, which
    may be its in progress (#32); not at an end following a hold (`after_block`),
    which ends whatever's left; and not for a finding an earlier turn ended
    past, until it's gone and comes back. What doesn't hold isn't told: the
    agent heard each finding as its write was judged, and an end held on it
    just before told it again. What a turn's end must tell still blocks, at
    either end: each is told once. With `listing`, the notes present at the
    session's start and removed since are listed, once. A block too long for
    a hook is fitted to it, kept whole in `repository`'s git directory
    (`Bench.said`).
    """
    session, agent = event.session, event.agent
    record = ConversationRecord(layout=bench.services.layout, session=session)
    with record.lock():
        working = [each for each in record.read().working if each != agent]
    endings = [
        ended(
            bench,
            worktree,
            session,
            agent,
            working,
            judging=worktree.root in judging,
        )
        for worktree in opened
    ]
    notes = (
        [note for worktree in opened for note in unlisted(bench, worktree, session)]
        if listing
        else []
    )
    waiting = [
        mail_for(worktree, session, agent, bench.runtime)
        for worktree in opened
        if not bench.interrupted()
    ]
    left = [found for end in endings for found in end.remaining]
    told = Checked(
        refused=[found for end in endings for found in end.checked.refused],
        moves=[move for end in endings for move in end.checked.moves],
        notices=[notice for end in endings for notice in end.checked.notices],
    ).parts()
    listed = [
        *([Part(whole=removed_notes(notes))] if notes else []),
        *Checked.together(waiting).parts(),
    ]
    telling = bool(text([*told, *listed]))
    with record.lock():
        kept = record.read()
        passed = kept.passed.get(agent, [])
        holds = bool(ends.holding(left, passed, after_block=after_block))
        if not (holds or telling):
            kept.passed = {**kept.passed, agent: left}
            record.keep(kept)
    parts = [*told, *(turn_end(left) if holds else []), *listed]
    return Reply(block=bench.said(repository, parts))


class Reported(Model, ABC):
    """One of a session's events, as its runtime's hook reports it to the judge: the conversation it's from, and what the judge does at it.

    Each of the judge's events is lup's own (`lup.events`), with what the
    judge reads of it beside.
    """

    session: str
    agent: str = ""
    """The conversation it's from: empty for the session's own, else a subagent's."""
    cwd: Path

    @abstractmethod
    def apply(self, bench: Bench) -> Reply:
        """Act on the event, and say what the agent hears."""


class SessionStarted(Reported, events.SessionStarted):
    """A session started, or resumed: it begins again in each worktree it holds.

    Its record of the subagents at work starts again too, and its main
    conversation is told the deferred work its repository's gate last found due
    (`Due`), once at each start, since the gate doesn't fail on it. A
    conversation whose runtime compacted or cleared it forgets the findings it
    knew, so what still stands is told again at its next call.
    """

    forgotten: bool = False
    """Whether the conversation holds none of what it was told before: its
    runtime compacted it, or cleared it."""

    @override
    def apply(self, bench: Bench) -> Reply:
        held = holding(bench, self.session, self.cwd, agent=self.agent, starts=True)
        if held is None:
            return Reply()
        if self.forgotten:
            for worktree in worktrees(bench, held):
                worktree.forget(self.session, self.agent)
        if self.agent:
            return Reply()
        record = ConversationRecord(layout=bench.services.layout, session=self.session)
        record.restarted()
        due = read_model(GitDirectoryLayout(common=held.repository).due, Due)
        return Reply(context="" if due is None else due.told())


def counted(bench: Bench, session: str) -> list[Call]:
    """Return the calls of `session` counted as running in the worktrees it holds, each once."""
    index = SessionIndex(layout=bench.services.layout)
    with index.lock(session):
        held = index.read(session)
    if held is None:
        return []

    def running(worktree: Worktree) -> list[Call]:
        with worktree.calls_lock():
            return [
                each for each in worktree.running().calls if each.session == session
            ]

    calls = [each for worktree in worktrees(bench, held) for each in running(worktree)]
    return list({each.key: each for each in calls}.values())


class TurnStarted(Reported, events.TurnStarted):
    """A turn of conversation `agent` starts, or a prompt arrives in its turn: the calls of its session the runtime shows are over stop counting as running.

    A call the runtime never reports finishing, one the operator interrupts
    among them, holds back the checkpoints where it counts until its
    conversation's turn ends, and a turn the operator interrupts may report no
    end. A prompt can arrive while a call of the conversation still runs, so
    the turn's start clears only what the runtime shows over: the calls in
    `over`, whose results their conversations' records hold, and, where the
    runtime names its turns (`turn`), the conversation's calls of another turn.
    No checkpoint runs: what they wrote is judged at the next one.
    """

    turn: str | None = None
    """The runtime's id for the turn the prompt starts or arrives in; none where
    it names none."""
    over: list[str] = []
    """The runtime's ids for the session's calls it shows are over."""

    def ended(self, call: Call) -> bool:
        """Say whether `call`, counted as running, is over."""
        if call.session != self.session:
            return False
        later = (
            call.agent == self.agent
            and self.turn is not None
            and call.turn is not None
            and call.turn != self.turn
        )
        return call.key in self.over or later

    @override
    def apply(self, bench: Bench) -> Reply:
        held = holding(bench, self.session, self.cwd, agent=self.agent)
        if held is None:
            return Reply()
        now = bench.services.clock.now()
        for worktree in worktrees(bench, held):
            with worktree.calls_lock():
                running = worktree.running()
                left = [
                    each
                    for each in running.calls
                    if not self.ended(each) and not over(each.started, now)
                ]
                if left != running.calls:
                    running.calls = left
                    worktree.ran(running, now)
        return Reply()


class CallStarted(Reported, events.CallStarted):
    """A tool call is about to run: it counts in every worktree its conversation works in (`Holding.works`).

    A subagent's call notes that the subagent is at work.
    """

    spawns: bool = False
    """Whether the call runs a subagent, whose own calls count instead."""
    turn: str | None = None
    """The runtime's id for the turn it runs in; none where it names none."""

    @override
    def apply(self, bench: Bench) -> Reply:
        held = holding(bench, self.session, self.cwd, agent=self.agent)
        if held is None:
            return Reply()
        if self.agent:
            record = ConversationRecord(
                layout=bench.services.layout, session=self.session
            )
            record.opened(self.agent)
        if self.spawns:
            return Reply()
        now = bench.services.clock.now()
        call = Call(
            key=self.call,
            session=self.session,
            agent=self.agent,
            tool=self.tool,
            turn=self.turn,
            started=now,
        )
        for worktree in working(bench, held, self.agent):
            with worktree.calls_lock():
                running = worktree.running()
                running.calls = [*running.calls, call]
                worktree.ran(running, now)
        return Reply()


class CallFinished(Reported, events.CallFinished):
    """A tool call finished, whether it succeeded or failed.

    It's confirmed in each worktree it counted in or its conversation works in,
    and a checkpoint runs in each of those where no call of the session is still
    running, one after another, the agent hearing their reports together;
    another session's calls there don't hold it back. One that never started (a
    runtime can report a command's end on a later call) leaves the calls running
    as they are, and a checkpoint still runs where none is.
    """

    @override
    def apply(self, bench: Bench) -> Reply:
        held = holding(bench, self.session, self.cwd, agent=self.agent)
        if held is None:
            return Reply()
        opened = worktrees(bench, held)
        works = held.works(self.agent)
        left = {
            worktree.root: worktree.finish(
                self.session, self.call, bench.services.clock.now()
            )
            for worktree in opened
        }
        ran = [
            worktree
            for worktree in opened
            if left[worktree.root].counted or worktree.root in works
        ]
        for worktree in ran:
            confirm(bench, worktree, self.session, self.agent, self.call)
        checked = [
            checkpoint(bench, worktree, self.session, self.agent, self.call)
            for worktree in ran
            if left[worktree.root].idle
        ]
        waiting = [
            mail_for(worktree, self.session, self.agent, bench.runtime)
            for worktree in opened
            if not bench.interrupted()
        ]
        told = Checked.together([*checked, *waiting])
        return Reply(context=bench.said(held.repository, told.parts()))


class TurnEnded(Reported, events.TurnEnded):
    """The session's own conversation ended its turn.

    In each worktree the session holds, its calls that never reported finishing
    are cleared, a checkpoint runs, the importers pass is waited on, and the turn
    can't end while the files it touched have type errors or ruff's findings
    (`end_turn`). The notes present at the session's start and removed since are
    listed once. Another conversation's calls are left running, and a worktree
    one counts in, one a subagent works in, gets no checkpoint: that call's
    finish runs it.
    """

    after_block: bool = False
    """Whether the turn went on because its end blocked just before."""

    @override
    def apply(self, bench: Bench) -> Reply:
        held = holding(bench, self.session, self.cwd, agent=self.agent)
        if held is None:
            return Reply()
        opened = worktrees(bench, held)
        for worktree in opened:
            worktree.clear(self.session, self.agent, bench.services.clock.now())
        judging = [
            worktree.root
            for worktree in opened
            if not worktree.busy(self.session, self.agent)
        ]
        return end_turn(
            bench,
            self,
            opened,
            judging,
            repository=held.repository,
            after_block=self.after_block,
            listing=True,
        )


class ConversationEnded(Reported, events.ConversationEnded):
    """A subagent's conversation ended its turn; the session's own goes on.

    Its calls are cleared in each worktree the session holds, and a checkpoint
    runs in each it works in or one of its calls counted in, where none of the
    session's is left running: what it left elsewhere is the session's turn's
    end's to judge. Its end holds on
    what it must be told, each told once (`end_turn`): a refusal, a move, a
    checkpoint's notice, mail. It never holds on the type errors and ruff's
    findings left in its files: every worker passes the gate before it hands
    back. Its end ends its time at work, unless it's blocked, which keeps the
    subagent going; an end its runtime reads no answer to (`final`) ends it
    whatever it tells.
    """

    final: bool = False
    """Whether its runtime reads nothing its end answers, as where it was stopped
    or its turn failed on an error from the model's API: no block keeps it
    going, so its time at work ends."""

    @override
    def apply(self, bench: Bench) -> Reply:
        held = holding(bench, self.session, self.cwd, agent=self.agent)
        if held is None:
            return Reply()
        opened = worktrees(bench, held)
        works = held.works(self.agent)
        left = {
            worktree.root: worktree.clear(
                self.session, self.agent, bench.services.clock.now()
            )
            for worktree in opened
        }
        idle = [
            root
            for root, each in left.items()
            if each.idle and (each.counted or root in works)
        ]
        reply = end_turn(
            bench,
            self,
            opened,
            idle,
            repository=held.repository,
            after_block=False,
            listing=False,
        )
        if self.agent and (self.final or not reply.block):
            record = ConversationRecord(
                layout=bench.services.layout, session=self.session
            )
            record.closed(self.agent)
        return reply
