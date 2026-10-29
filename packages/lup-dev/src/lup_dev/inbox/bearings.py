"""What a new main session is told, once, as they start, of where their repository stands, as far as it's the session's to act on: the branches not landed, and what landed since the last main session started, each line saying where to read more.

`docs/inbox.md`, *A new main session's bearings*. A long main session ends
heavy, and the next one rebuilt what was open from raw records and days of the
inbox (#262), so a fresh one is told it at the one moment it's needed, their
context still empty: a session's own conversation starting anew or cleared
(`Heard.fresh`), never a resume, a compaction, a fork or a subagent, and never
again after.
- **Not landed:** each branch with commits on no remote branch, or whose
  worktree holds uncommitted changes, with its worktree, how many commits, and
  its last. A branch the local integration branch merged but whose landing
  waits is still not landed; the release branch, on its remote, is.
- **Running beside them:** where more than one other main conversation of the
  repository runs, each by their name, since several sessions may work on one
  repository at once, and one's open threads aren't abandoned.
- **Landed** on the remote's integration branch since the last main session
  started, its first-parent history, with whether that session still runs or
  when they were last heard, and how their exchange with the operator is read.

What waits for the operator isn't told: it's theirs to answer, and the
session starting can't act on it.

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
from lup_dev.host.service import Bearings, Running
from lup_dev.inbox.delivery import Delivery, clocked
from lup_dev.inbox.reading import Reader
from lup_dev.listing import many
from lup_ledger.parties import Conversation

if TYPE_CHECKING:
    from lup_dev.host.protocol import Register
    from lup_dev.inbox.store import Item


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


def starting(reader: Reader) -> list[Conversation]:
    """Return the conversation `reader` reads for, the session starting, as one that may share a name lup hasn't heard yet; none for the operator."""
    return [reader.reader] if isinstance(reader.reader, Conversation) else []


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
        """Return the main conversation of `starting`'s repository lup heard start last before them; none where it heard none."""
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
        """Return when lup first heard `conversation` in the launch they were last heard in."""
        return self.delivery.inbox.whereabouts[conversation.key()].since

    def page(
        self,
        starting: Conversation,
        last: Conversation | None,
        found: Repository,
        running: list[Running],
    ) -> str:
        """Say the bearings: what's not landed, the main sessions running beside the one starting where more than one does, and what landed since `last` started."""
        items = self.delivery.inbox.about(starting.repository)
        reader = Reader(
            delivery=self.delivery,
            reader=starting,
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
            self.beside(beside, reader) if len(beside) > 1 else [],
            # lup: defer(issue=262, why="the last handoff's note is told here, after what landed, once `handoff` writes one: it waits for spawn (#117)")
            self.landed(found, last, beside, reader, items),
        ]
        return "\n\n".join("\n".join(each) for each in sections if each)

    @staticmethod
    def named(last: Conversation, reader: Reader) -> str:
        """Name `last` for the session starting, who reads it: by their name, their runtime's ids beside it where another shares it, the session starting among them, which lup hasn't heard yet."""
        return reader.roster.who(last, starting(reader))

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

    def beside(self, beside: list[Running], reader: Reader) -> list[str]:
        """Say each main session of the repository running beside the one starting, by their name, their runtime's ids beside it where another shares it (`Reader.called`), and their worktree."""
        return [
            "Main sessions of this repository running beside you:",
            *(
                f"- {reader.called(Conversation(repository=each.launch.repository, runtime=each.launch.runtime, session=each.session))}, "
                f"in {each.launch.worktree}."
                for each in beside
            ),
        ]

    def landed(
        self,
        found: Repository,
        last: Conversation | None,
        beside: list[Running],
        reader: Reader,
        items: list[Item],
    ) -> list[str]:
        """Say what landed since the last main session started, whether they still run or when they were last heard, and how their exchange with the operator is read; that none was heard before, where none was."""
        if last is None:
            return ["No main session of this repository was heard before you."]
        running = any(each.session == last.session for each in beside)
        heard = (
            "still running"
            if running
            else f"last heard at {clocked(reader.heard(last, items))}"
        )
        title = self.named(last, reader)
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
                f'`conversation` "{reader.roster.handle(last, starting(reader))}", '
                "`every` and `whole`."
            ),
        ]
