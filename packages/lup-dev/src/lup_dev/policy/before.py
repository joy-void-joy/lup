"""A file tool's write before it lands: the would-be content, then the judgement.

Where a runtime's file tools say what they'll write before they write it, lup
judges that content and answers allow, ask or refuse before anything touches the
file (`docs/judging-writes.md`, *Before an edit lands*). A tool's call is one of
two proposals, in lup's own words:
- a replacement: the current file with one string replaced by another, once, or
  everywhere;
- a whole write: the content it carries.

A replacement whose string isn't there exactly as the tool requires is allowed:
the tool fails on its own. A refused write never touches the file, and the agent's
version is saved. A write allowed or asked is remembered until its call finishes,
so the checkpoint after it accepts that content as already judged.

A write is judged in the worktree of the session's repository its path is in,
which the session then holds; a write in the repository's own git directory
asks, since what's there runs outside the agent's reach; a write anywhere else
isn't judged here.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, override

from lup.types import Model
from lup_dev.policy.checkpoint import (
    Attributed,
    Bench,
    Pending,
    Worktree,
    decoded,
    holding,
    verdict,
)
from lup_dev.policy.judge import Ask, Change, Judgement
from lup_dev.policy.report import Refused, asked, placed, refusal
from lup_dev.policy.verdicts import VerdictLog
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

    outcome: Literal["allow", "ask", "refuse"] | None
    """None where lup doesn't judge the call, which the runtime then decides."""
    reason: str = ""
    """What's asked, or the refusal report; empty for an allow."""


def before(bench: Bench, proposal: Proposal, session: str, cwd: Path) -> Decision:
    """Judge a file tool's proposed write before it lands.

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
        reason = (
            f"{here.repository / here.path} is in the repository's git directory, "
            "which runs outside the agent's reach"
        )
        judgement = Judgement(
            path=here.path,
            role="protected",
            outcome="ask",
            asks=[Ask(kind="protected", reason=reason)],
        )
        to = Attributed(worktree=here.repository, session=session, tool=proposal.tool)
        VerdictLog(path=services.layout.verdicts(here.repository)).append(
            [verdict(bench, to, judgement)]
        )
        return Decision(outcome="ask", reason=asked(judgement.asks))
    worktree = Worktree.of(here.worktree, held.repository, services.layout)
    path = here.path
    store = worktree.store
    with worktree.lock():
        state = store.state()
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
        )
        judge = worktree.judge(services, record.approved)
        judgement = judge.judge([change], inform=False)[0]
        to = Attributed(worktree=worktree.root, session=session, tool=proposal.tool)
        logged = verdict(bench, to, judgement)
        match judgement.outcome:
            case "refuse":
                number = state.saved + 1
                saved = store.save(number, path, after.encode())
                state.saved = number
                store.remember(state)
                refused = Refused(
                    path=worktree.root / path,
                    saved=saved,
                    new=earlier is None,
                    refusing=placed(worktree.root, judgement.refusing),
                    untouched=placed(worktree.root, judgement.untouched),
                )
                decision = Decision(outcome="refuse", reason=refusal([refused]))
            case "ask" | "allow" as outcome:
                pending = Pending(
                    call=proposal.call,
                    path=path,
                    blob=store.keep(after.encode()),
                    asked=outcome == "ask",
                    verdict=logged,
                    removed=judgement.removed,
                )
                record.pending = [*record.pending, pending]
                worktree.keep(record)
                reason = asked(judgement.asks) if outcome == "ask" else ""
                decision = Decision(outcome=outcome, reason=reason)
    worktree.verdicts(services.layout).append([logged])
    return decision
