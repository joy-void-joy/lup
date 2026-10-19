"""A file tool's write before it lands: the would-be content, then the judgement.

Where a runtime's file tools say what they'll write before they write it, lup
judges that content before anything touches the file (`docs/judging-writes.md`,
*Before an edit lands*): it's allowed, or, where it asks, held, the call waiting
in its hook for the operator's answer to the item it is in their inbox, and let
through or denied with it. A tool's call is one of two proposals, in lup's own
words:
- a replacement: the current file with one string replaced by another, once, or
  everywhere;
- a whole write: the content it carries.

A replacement whose string isn't there exactly as the tool requires is allowed:
the tool fails on its own. A write let through is remembered until its call
finishes, so the checkpoint after it accepts that content as already judged, and
tells its findings; one flagged is put before the operator as it's let through,
holding no one, as is one to a file whose item may still gather the
conversation's writes, refreshing it (`flags.py`); one declined, or left
unanswered, never lands, and the agent's version is saved.

A write is judged in the worktree of the session's repository its path is in,
which the session then holds; a write in the repository's own git directory
asks, since what's there runs outside the agent's reach; a write anywhere else
isn't judged here.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, override

from lup.types import Model
from lup_dev.git import Git
from lup_dev.inbox.store import ChangedFile
from lup_dev.policy.checkpoint import (
    Attributed,
    Bench,
    Pending,
    Worktree,
    decoded,
    holding,
    unflag,
    verdict,
)
from lup_dev.policy.flags import Landed, Put, flagged
from lup_dev.policy.holds import HeldFile, Hold, answered, unified
from lup_dev.policy.judge import Ask, Change, Judgement
from lup_dev.policy.report import Refused, information, placed, refusal, sections
from lup_dev.policy.worktrees import place


class Proposal(Model, ABC):
    """What a file tool proposes to write, before it runs."""

    call: str
    tool: str
    """The runtime's name for the tool, as the verdict log records it."""
    path: Path
    """The file, as an absolute path."""

    @abstractmethod
    def content(self, current: str | None) -> str | None:
        """Return the file's content once written; none where the tool would fail.

        `current` is the file as it stands, none where it doesn't exist.
        """

    @abstractmethod
    def whole(self) -> bool:
        """Say whether it writes the whole file, rather than changing part of it."""


class Replacement(Proposal):
    """Replace a string in the file: once, or everywhere."""

    old: str
    new: str
    everywhere: bool = False

    @override
    def content(self, current: str | None) -> str | None:
        """Replace as the tool does, or return none where it would refuse.

        >>> edit = Replacement(call="1", tool="t", path=Path("/a"), old="x", new="y")
        >>> edit.content("axa")
        'aya'
        >>> edit.content("axx") is None
        True
        """
        if current is None:
            return self.new if not self.old else None
        found = current.count(self.old) if self.old else 0
        if found == 0 or (found > 1 and not self.everywhere):
            return None
        # lup: ignore("string-replace", why="it is the file tool's own replacement")
        return current.replace(self.old, self.new, -1 if self.everywhere else 1)

    @override
    def whole(self) -> bool:
        return False


class Overwrite(Proposal):
    """Write the whole file with the content carried."""

    text: str

    @override
    def content(self, current: str | None) -> str | None:
        return self.text

    @override
    def whole(self) -> bool:
        return True


class Decision(Model):
    """What lup answers before a file tool's call runs."""

    outcome: Literal["allow", "deny"] | None
    """None where lup doesn't judge the call, which the runtime then decides."""
    reason: str = ""
    """Why a write is denied, or what the operator added to letting it through;
    empty for a plain allow."""
    told: str = ""
    """What the agent is told beside a write let through: lup's findings in it,
    its type errors and ruff's, as a checkpoint reports them. A runtime whose
    file tools are judged before they land runs no checkpoint after the call to
    tell them, so they're told with the call, before the agent's next line."""


def told(root: Path, judgement: Judgement) -> str:
    """Say what a write's judgement found, its files named from `root`, as a checkpoint reports it; nothing where it found nothing."""
    return information(
        placed(root, judgement.findings),
        placed(root, judgement.information),
        placed(root, judgement.untouched),
        [],
    )


def before(
    bench: Bench,
    proposal: Proposal,
    session: str,
    cwd: Path,
    agent: str | None = None,
) -> Decision:
    """Judge a file tool's proposed write before it lands; `agent` is the runtime's id for the subagent writing, none for the session's own conversation.

    A file outside the session's repository isn't judged: edits in another
    repository come with launch and spawn.
    """
    here = place(proposal.path)
    held = holding(bench, session, cwd, here)
    if here is None or held is None or here.repository != held.repository:
        return Decision(outcome=None)
    disk = proposal.path
    after = proposal.content(disk.read_text() if disk.is_file() else None)
    if after is None:
        return Decision(outcome="allow")
    services = bench.services
    if here.worktree is None:
        written = here.repository / here.path
        reason = (
            f"{written} is in the repository's git directory, which runs outside "
            "the agent's reach"
        )
        judgement = Judgement(
            path=here.path,
            role="protected",
            outcome="ask",
            asks=[Ask(kind="protected", reason=reason)],
        )
        home = place(cwd)
        if home is None or home.worktree is None:
            return Decision(
                outcome="deny",
                reason=(
                    f"{reason}: lup holds such a write for the operator in the "
                    "worktree a session works in, and this one works in none"
                ),
            )
        keeping = Worktree.of(home.worktree, held.repository, services)
        earlier = disk.read_text() if disk.is_file() else None
        return held_write(
            bench,
            keeping,
            session=session,
            proposal=proposal,
            earlier=earlier,
            after=after,
            judgement=judgement,
            agent=agent,
            outside=here.repository,
        )
    worktree = Worktree.of(here.worktree, held.repository, services)
    path = here.path
    store = worktree.store
    with worktree.lock():
        record = worktree.session(session, bench.runtime)
        accepted = store.accepted()
        prior = [each.blob for each in record.judged if each.path == path]
        earlier = store.object(prior[-1]) if prior else store.content(accepted, path)
        change = Change(
            path=path,
            before=decoded(earlier),
            after=after,
            baseline=decoded(store.content(store.started(session), path)),
            whole=proposal.whole() and (earlier is not None or disk.is_file()),
            published=not Git(cwd=worktree.root).ignored(path),
        )
        each_held = services.announcing.holding(bench.runtime.name(), session, agent)
        judge = worktree.judge(services, record.approved, holding=each_held)
        judgement = judge.judge([change], inform=False)[0]
        to = Attributed(worktree=worktree.root, session=session, tool=proposal.tool)
        logged = None if judgement.outcome == "ask" else verdict(bench, to, judgement)
        writer = agent or ""
        gathering = path in record.flagging.get(writer, [])
        if logged is not None:
            pending = Pending(
                call=proposal.call,
                path=path,
                blob=store.keep(after.encode()),
                asked=False,
                verdict=logged,
                removed=judgement.removed,
            )
            record.pending = [*record.pending, pending]
            record.flagged(writer, [path] if judgement.flags else [])
            worktree.keep(record)
    if logged is None:
        return held_write(
            bench,
            worktree,
            session=session,
            proposal=proposal,
            earlier=change.before,
            after=after,
            judgement=judgement,
            agent=agent,
        )
    worktree.verdicts(services.layout).append([logged])
    landed = Landed(
        change=change,
        judgement=judgement,
        session=session,
        agent=agent,
        call=proposal.call,
    )
    put = (
        flagged(
            services.flagging,
            judge,
            bench.runtime.name(),
            worktree.repository,
            [landed],
        )
        if judgement.flags or gathering
        else Put()
    )
    unflag(bench, worktree, session, writer, put.read)
    return Decision(
        outcome="allow", told=sections([told(worktree.root, judgement), *put.unsaid])
    )


def held_write(
    bench: Bench,
    worktree: Worktree,
    *,
    session: str,
    proposal: Proposal,
    earlier: str | None,
    after: str,
    judgement: Judgement,
    agent: str | None = None,
    outside: Path | None = None,
) -> Decision:
    """Hold a write that asks before it lands, the call waiting in its hook, and answer as the operator does.

    The hold is kept in `worktree`'s store and put in the operator's inbox
    (`Announcing`); no lock is held while it waits. A write `outside` the
    worktree, in its repository's git directory, is kept in the store of the
    worktree the session works in, its verdict the git directory's, and is no
    write of that worktree's once let through. Approved, the write is let
    through, the approval covering the path for the rest of the session as an
    asked call that ran does (`confirm`), and their comment told; declined, or
    left unanswered within the patience, it's denied, and the agent's version
    saved, the hold staying open where nobody answered.
    """
    services = bench.services
    store = worktree.store
    holds = worktree.holds()
    path = judgement.path
    where = worktree.root if outside is None else outside
    to = Attributed(worktree=where, session=session, tool=proposal.tool)
    with worktree.lock():
        key = holds.unused()
        logged = verdict(bench, to, judgement, key)
        held = HeldFile(
            path=path,
            role=judgement.role,
            blob=store.keep(after.encode()),
            reasons=[ask.kind for ask in judgement.asks],
            asks=[ask.reason for ask in judgement.asks],
            reading=judgement.reading(),
        )
        hold = holds.put(
            Hold(
                key=key,
                worktree=worktree.root,
                session=session,
                agent=agent,
                call=proposal.call,
                created=services.clock.now(),
                files=[held],
                diff=unified(path, earlier, after),
                verdicts=[logged],
            )
        )
    log = worktree.verdicts(services.layout)
    log.append([logged])
    whole = ChangedFile.of(
        path,
        None if earlier is None else earlier.encode(),
        after.encode(),
        held.reading,
    )
    services.announcing.announced(
        hold, bench.runtime.name(), worktree.repository, [whole]
    )
    answer = holds.wait(key, services.clock)
    if answer is not None and answer.approved:
        # Logged as it's given: no hook may report the call's finish, which would.
        log.append(answered(hold, "approved"))
    if answer is not None and answer.approved and outside is not None:
        said = f"The operator approved it: {answer.comment}" if answer.comment else ""
        return Decision(outcome="allow", reason=said, told=told(where, judgement))
    if answer is not None and answer.approved:
        with worktree.lock():
            record = worktree.session(session, bench.runtime)
            pending = Pending(
                call=proposal.call,
                path=path,
                blob=held.blob,
                asked=True,
                verdict=logged,
                removed=judgement.removed,
            )
            record.pending = [*record.pending, pending]
            # The approval covers the path from now: no hook may report the call's finish (`confirm`).
            record.approved = list(dict.fromkeys([*record.approved, path]))
            worktree.keep(record)
        said = f"The operator approved it: {answer.comment}" if answer.comment else ""
        return Decision(outcome="allow", reason=said, told=told(where, judgement))
    with worktree.lock():
        state = store.state()
        number = state.saved + 1
        saved = store.save(number, path, after.encode())
        state.saved = number
        store.remember(state)
    if answer is None:
        holds.mark(key, abandoned=True)
    log.append(answered(hold, "unanswered" if answer is None else "declined"))
    refused = Refused(
        path=where / path,
        saved=saved,
        new=earlier is None,
        declined=None if answer is None else answer.comment,
        unanswered=answer is None,
    )
    return Decision(outcome="deny", reason=refusal([refused]))
