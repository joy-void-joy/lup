"""What a new main session is told, once, as it starts, of where its repository stands: the branches not landed, what waits for the operator, and what landed since the last main session started, each line saying where to read more.

`docs/inbox.md`, *A new main session's bearings*. A long main session ends
heavy, and the next one rebuilt what was open from raw records and days of the
inbox (#262), so a fresh one is told it at the one moment it's needed, its
context still empty: a session's own conversation starting anew or cleared
(`Heard.fresh`), never a resume, a compaction, a fork or a subagent, and never
again after.
- **Not landed:** each branch with commits on no remote branch, or whose
  worktree holds uncommitted changes, with its worktree, how many commits, and
  its last. A branch the local integration branch merged but whose landing
  waits is still not landed; the release branch, on its remote, is.
- **Running beside it:** where more than one other main conversation of the
  repository runs, each by its name, since several sessions may work on one
  repository at once, and one's open threads aren't abandoned.
- **Waiting for the operator:** the last main session's items and its
  subagents' first, then the rest. What waits on the operator is a line each;
  news is counted by kind, and flagged writes by the landing each holds.
- **Landed** on the remote's integration branch since the last main session
  started, its first-parent history, with whether that session still runs or
  when it was last heard, and how its exchange with the operator is read.

It lives beside the inbox rather than with the judge (`policy/`): it reads the
inbox's items, names and whereabouts as `inbox/reading.py` does, and lists
worktrees through `lup_dev.git`, which every layer reads. The host service,
lowest of `lup_dev`'s layers, asks it through `Bearings` (`host/service.py`).
"""

import asyncio
from datetime import datetime
from itertools import batched
from pathlib import Path
from typing import TYPE_CHECKING, override

from lup.types import Model
from lup_dev.git import Git, GitError, nul_separated
from lup_dev.host.names import Names
from lup_dev.host.service import Bearings, Running
from lup_dev.inbox.delivery import Delivery, clocked, kind, opening, what
from lup_dev.inbox.reading import Reader
from lup_dev.inbox.store import (
    Conversation,
    Flagged,
    Item,
    Operator,
    Waiting,
    cited,
    ranked,
)
from lup_dev.listing import many

if TYPE_CHECKING:
    from lup_dev.host.protocol import Register


class Unlanded(Model):
    """A branch with work on no remote: its commits there, and its worktree's uncommitted changes."""

    branch: str
    worktree: Path | None
    """Where it's checked out; none where no worktree has it."""
    commits: int
    """Its commits on no remote branch."""
    changed: int
    """The files its worktree changes, or adds, and hasn't committed."""
    last: str
    """Its last commit, by its short id and its subject."""
    at: datetime


class Landed(Model):
    """A commit the remote's integration branch took, by its short id and its subject."""

    commit: str
    subject: str


class Repository(Model):
    """What git says of a repository as a session starts: its branches not landed, and what its integration branch landed since a moment."""

    unlanded: list[Unlanded]
    landed: list[Landed]
    onto: str
    """The integration branch they're measured against, as named where it's
    read: the remote's copy, `origin/dev`, where there's one, else the local
    branch."""
    unread: str | None = None
    """Why git couldn't be read, which the page says in place of what it would
    have read; none where it was read."""


def read_repository(
    repository: Path, integration: str, remote: str, since: datetime | None
) -> Repository:
    """Read `repository`'s branches not landed, and what `integration`, `remote`'s copy where there's one, landed from `since` on; nothing landed where `since` is none."""
    git = Git.pinned(repository)
    branches = git.text("for-each-ref", "--format=%(refname:short)", "refs/heads/")
    checked = {
        branch: worktree
        for worktree in git.worktrees()
        if worktree != repository and (branch := Git(cwd=worktree).branch()) is not None
    }

    def unlanded(branch: str) -> Unlanded:
        worktree = checked.get(branch)
        changed = (
            0
            if worktree is None
            else len(Git(cwd=worktree).text("status", "--porcelain").splitlines())
        )
        commits = git.text("rev-list", "--count", branch, "--not", "--remotes")
        short, at, subject = [
            each.strip()
            for each in nul_separated(
                git.run("log", "-1", "--format=%h%x00%cI%x00%s", branch).output
            )
        ]
        return Unlanded(
            branch=branch,
            worktree=worktree,
            commits=int(commits),
            changed=changed,
            last=f'{short} "{subject}"',
            at=datetime.fromisoformat(at),
        )

    found = [unlanded(branch) for branch in branches.splitlines()]
    tracked = f"{remote}/{integration}"
    onto = tracked if git.commit(f"refs/remotes/{tracked}") is not None else integration
    landed = (
        []
        if since is None
        else [
            Landed(commit=commit, subject=subject)
            for commit, subject in batched(
                nul_separated(
                    git.run(
                        "log",
                        "-z",
                        "--first-parent",
                        "--format=%h%x00%s",
                        f"--since={since.isoformat()}",
                        onto,
                    ).output
                ),
                2,
                strict=True,
            )
        ]
    )
    return Repository(
        unlanded=[each for each in found if each.commits or each.changed],
        landed=landed,
        onto=onto,
    )


class RepositoryBearings(Model, Bearings, arbitrary_types_allowed=True):
    """A new main session's bearings, from the inbox `delivery` keeps and the repository's git."""

    delivery: Delivery
    integration: str
    """The branch work lands on, as lup's settings name it
    (`LUP_INTEGRATION_BRANCH`)."""
    remote: str = "origin"
    """The remote whose copy of the integration branch is what's landed, as
    `land` lands on it; the local branch where there's none."""

    @override
    async def told(
        self, launch: Register, session: str, running: list[Running]
    ) -> str | None:
        starting = Conversation(
            repository=launch.repository, runtime=launch.runtime, session=session
        )
        last = self.last(starting)
        since = None if last is None else self.started(last)
        try:
            found = await asyncio.to_thread(
                read_repository, launch.repository, self.integration, self.remote, since
            )
        except GitError as unread:
            found = Repository(
                unlanded=[], landed=[], onto=self.integration, unread=str(unread)
            )
        return self.page(starting, last, found, running)

    def last(self, starting: Conversation) -> Conversation | None:
        """Return the main conversation of `starting`'s repository lup heard start last before it; none where it heard none."""
        mains = [
            place
            for place in self.delivery.inbox.whereabouts.values()
            if place.conversation.agent is None
            and place.conversation.repository == starting.repository
            and place.conversation != starting
        ]
        latest = max(mains, key=lambda place: place.since, default=None)
        return None if latest is None else latest.conversation

    def started(self, conversation: Conversation) -> datetime:
        """Return when lup first heard `conversation` in the launch it was last heard in."""
        return self.delivery.inbox.whereabouts[conversation.key()].since

    def page(
        self,
        starting: Conversation,
        last: Conversation | None,
        found: Repository,
        running: list[Running],
    ) -> str:
        """Say the bearings: what's not landed, the main sessions running beside it where more than one does, what waits for the operator, and what landed since `last` started."""
        items = self.delivery.inbox.about(starting.repository)
        reader = Reader(
            delivery=self.delivery,
            reader=starting,
            names=Names(path=self.delivery.layout.names).all(),
        )
        beside = [
            each
            for each in running
            if each.session != starting.session
            and each.launch.repository == starting.repository
        ]
        sections = [
            [
                (
                    "lup: where this repository stands as you start, told once. "
                    "Each line says where to read more."
                )
            ],
            self.unlanded(found),
            self.beside(beside) if len(beside) > 1 else [],
            self.waiting(items, last, reader),
            # lup: defer(issue=262, why="the last handoff's note is told here, after what landed, once `handoff` writes one: it waits for spawn (#117)")
            self.landed(found, last, beside, reader, items),
        ]
        return "\n\n".join("\n".join(each) for each in sections if each)

    def unlanded(self, found: Repository) -> list[str]:
        """Say each branch not landed: its worktree, its commits on no remote and the last, and its uncommitted changes; or why git couldn't be read."""
        if found.unread is not None:
            return [f"lup couldn't read this repository's git: {found.unread}"]
        if not found.unlanded:
            return [
                (
                    f"Not landed on `{found.onto}`: nothing. Every branch is on a "
                    "remote, and no worktree holds a change."
                )
            ]

        def said(each: Unlanded) -> str:
            where = (
                "with no worktree" if each.worktree is None else f"in {each.worktree}"
            )
            commits = (
                f"{many(each.commits, 'commit')}, the last {each.last}, "
                f"{clocked(each.at)}"
                if each.commits
                else "no commit"
            )
            changed = (
                f"; {many(each.changed, 'file')} changed, not committed"
                if each.changed
                else ""
            )
            return f"- `{each.branch}`, {where}: {commits}{changed}."

        return [
            (
                f"Not landed on `{found.onto}` (`git log <branch> --not --remotes` "
                "reads a branch's commits; `git -C <worktree> status` its changes):"
            ),
            *(said(each) for each in found.unlanded),
        ]

    def beside(self, beside: list[Running]) -> list[str]:
        """Say each main session of the repository running beside the one starting, by its name, its runtime's id and its worktree."""
        return [
            "Main sessions of this repository running beside you:",
            *(
                f"- `{each.name}` ({each.launch.runtime} session {each.session}), "
                f"in {each.launch.worktree}."
                for each in beside
            ),
        ]

    def waiting(
        self, items: list[Item], last: Conversation | None, reader: Reader
    ) -> list[str]:
        """Say what waits for the operator: the last main session's items and its subagents' first, then the rest; each item waiting on them a line, news counted by kind, flagged writes by the landing each holds."""
        waiting = [
            item
            for item in items
            if item.recipient == Operator() and isinstance(item.state, Waiting)
        ]
        if not waiting:
            return ["Nothing waits for the operator."]

        def ours(item: Item) -> bool:
            sender = item.sender
            return isinstance(sender, Conversation) and sender.main() == last

        first = [item for item in waiting if ours(item)]
        rest = [item for item in waiting if not ours(item)]
        whose = (
            ""
            if last is None or not first
            else (
                f", {'all' if not rest else len(first)} from "
                f"{reader.titled(last, items)} and its subagents"
                f"{', listed first' if rest else ''}"
            )
        )
        return [
            (
                f"Waiting for the operator: {many(len(waiting), 'item')}{whose} "
                "(`inbox` lists them; with `number`, one whole):"
            ),
            *self.grouped(first, reader, items),
            *self.grouped(rest, reader, items),
        ]

    def grouped(
        self, items: list[Item], reader: Reader, known: list[Item]
    ) -> list[str]:
        """Say `items`: each waiting on the operator a line, then news counted by kind, then flagged writes by the branch whose landing each holds."""
        asking = [
            f"- {cited(item.number)} {what(item)} from "
            f"{reader.called(item.sender, known, naming='paths')}: {opening(item)}"
            for item in items
            if ranked(item.reason).name == "waiting on you"
        ]
        news = [item for item in items if ranked(item.reason).name == "news"]
        kinds = list(dict.fromkeys(kind(item) for item in news))
        counted = ", ".join(
            f"{len([item for item in news if kind(item) == each])} `{each}`"
            for each in kinds
        )
        told = (
            [f"- News, by kind: {counted} (`inbox` with those `kinds` lists them)."]
            if news
            else []
        )
        flags = [item for item in items if isinstance(item.reason, Flagged)]
        branches = list(
            dict.fromkeys(
                item.reason.branch for item in flags if isinstance(item.reason, Flagged)
            )
        )

        def holding(branch: str | None) -> str:
            numbers = ", ".join(
                cited(item.number)
                for item in flags
                if isinstance(item.reason, Flagged) and item.reason.branch == branch
            )
            return (
                f"on no branch, {numbers}"
                if branch is None
                else f"`{branch}`'s, {numbers}"
            )

        flagged = (
            [
                (
                    f"- {many(len(flags), 'flagged write')}, holding landings: "
                    f"{'; '.join(holding(each) for each in branches)}."
                )
            ]
            if flags
            else []
        )
        return [*asking, *told, *flagged]

    def landed(
        self,
        found: Repository,
        last: Conversation | None,
        beside: list[Running],
        reader: Reader,
        items: list[Item],
    ) -> list[str]:
        """Say what landed since the last main session started, whether it still runs or when it was last heard, and how its exchange with the operator is read; that none was heard before, where none was."""
        if last is None:
            return ["No main session of this repository was heard before you."]
        running = any(each.session == last.session for each in beside)
        heard = (
            "still running"
            if running
            else f"last heard at {clocked(reader.heard(last, items))}"
        )
        title = reader.titled(last, items)
        started = clocked(self.started(last))
        landed = (
            [f"- {each.commit} {each.subject}" for each in found.landed]
            if found.landed
            else ["- Nothing."]
            if found.unread is None
            else ["- Unread: git couldn't be read, as said above."]
        )
        return [
            (
                f"Landed on `{found.onto}` since {title}, the last main session "
                f"({heard}), started at {started} (`git show <commit>` reads one):"
            ),
            *landed,
            (
                f"What {title} and the operator said to each other: `inbox` with "
                f'`conversation` "{last.session}", `every` and `whole`.'
            ),
        ]
