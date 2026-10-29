"""Parked threads woken where what they wait for comes: each trigger seen where lup already looks.

`docs/inbox.md`, *Threads*. A thread parked
until something comes (`Parked.until`) is woken by the first of its triggers
to come: lup draws a `Reopened` saying what came, and tells whoever answers for
the thread, its holder or else the holder above, a line (`Concerns.came`).
Nothing here runs on a timer of its own; each trigger is seen where lup looks
already:
- **at the sweep beside the host service,** every 30 seconds whether a session
  runs or not (`Sweeping`, `cli.py`, `swept`): a time come; a conversation
  ended, as `Concerns.live` reads it, so a session's own conversation ending
  with their launch, or cleared in it, which nothing tells the inbox as it
  happens; a condition holding, as the gate last found it (`Due.held`, kept by
  a whole run of `lup-dev rules check`, which asks each condition the project
  declares);
- **at a subagent's end,** as the host hears it (`Delivery.ended`): a
  conversation ended, at once;
- **at `land`,** once it pushed onto the integration branch (`landed`): each
  branch it landed; and each issue closing, through GitHub;
- **at each push the host makes that moves the integration branch,** `land`'s
  own among them (`pushed`): each commit in the history of what it pushed, as
  git on the host reads it;
- **as a session's own conversation starts,** started, resumed, cleared or
  compacted (`started`): each issue closing, through GitHub, apart, so their
  start waits on nothing.

GitHub is asked whether an issue closed at those two moments alone, once for
each issue the repository's parked threads wait on, and not at all where none
does. Where the launch's limits refuse reading issues, where `gh` can't say,
or where git can't, nothing is woken by it, and the service's log says why.
The gate's record is the room's to write, as its reminders are: a room could
wake its own repository's thread parked on a condition, which steers and
guards nothing.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal

from lup.errors import LupError
from lup.types import Model
from lup_dev.codescan.contract import Due
from lup_dev.codescan.directives import IssueRef
from lup_dev.errors import LupDevError
from lup_dev.forge.github import GitHub, GitHubError
from lup_dev.git import Git
from lup_dev.host.protocol import Register
from lup_dev.inbox.delivery import Delivery
from lup_dev.layout import GitDirectoryLayout
from lup_dev.stored import read_model
from lup_ledger.threads import (
    BranchLanded,
    CommitLanded,
    ConditionHeld,
    ConversationEnded,
    IssueClosed,
    Parked,
    Thread,
    TimeCame,
    Trigger,
)

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.inbox.concerns import Concerns
    from lup_dev.remote.protocol import Update


def hashed(commit: str) -> bool:
    """Say whether `commit` reads as a commit's hash, whole or its start: 4 to 64 hexadecimal digits. git is asked about nothing else, which it could read as an option.

    >>> hashed("c6576e49"), hashed("--output=x"), hashed("abc")
    (True, False, False)
    """
    return 4 <= len(commit) <= 64 and all(
        each in "0123456789abcdef" for each in commit.lower()
    )


async def github_state(launch: Register, issue: IssueRef) -> Literal["open", "closed"]:
    """Say whether `issue` is open or closed, through the operator's `gh` on the host, on `launch`'s repository on GitHub or the one `issue` names; raise `GitHubError` where `gh` can't say."""
    github = GitHub.launched(launch)
    return await github.state(issue.number, issue.repository)


def in_history(repository: Path, commits: list[str], tip: str) -> list[str]:
    """Return those of `commits`, as each is written, that name a commit in `tip`'s history, in the repository whose git directory is `repository`: each a hash, or its start naming one commit alone."""

    def landed(commit: str) -> bool:
        if not hashed(commit):
            return False
        git = Git.pinned(repository)
        found = git.commit(commit)
        if found is None:
            return False
        ran = git.run("merge-base", "--is-ancestor", found, tip, ok=[0, 1])
        return ran.status == 0

    return [each for each in commits if landed(each)]


class Coming(Model, arbitrary_types_allowed=True):
    """What the host sees come for the threads parked until it, each where lup already looks; the one place a parked thread is woken from."""

    delivery: Delivery
    integration: str
    """The integration branch's name, where a branch or a commit lands."""
    say: Callable[[str], None]
    """Where what couldn't be seen is said: the service's log."""
    states: Callable[[Register, IssueRef], Awaitable[Literal["open", "closed"]]] = (
        github_state
    )
    """Asks whether an issue is open or closed, through GitHub."""

    @property
    def concerns(self) -> Concerns:
        """The threads as agents work in them, read from the inbox as it stands."""
        return self.delivery.concerns()

    def swept(self) -> list[Thread]:
        """At the sweep: wake each thread parked until a time that came, a conversation that ended, or a condition the gate last found holding in its repository. Return those woken."""
        concerns = self.concerns
        now = self.delivery.clock.now()
        held: dict[Path, list[str]] = {}

        def holding(repository: Path) -> list[str]:
            if repository not in held:
                held[repository] = self.held(repository)
            return held[repository]

        def came(parked: Parked, trigger: Trigger) -> bool:
            match trigger:
                case TimeCame(at=at):
                    return at <= now
                case ConversationEnded(conversation=conversation):
                    return not concerns.live(conversation)
                case ConditionHeld(when=when):
                    return when in holding(parked.repository)
                case _:
                    return False

        return concerns.due(None, came)

    def held(self, repository: Path) -> list[str]:
        """Return the conditions the gate last found holding in the repository whose git directory is `repository`; none where it kept no record, or one that doesn't read, which is said."""
        try:
            due = read_model(GitDirectoryLayout(common=repository).due, Due)
        except (OSError, ValueError) as unread:
            self.say(
                f"The gate's record of what came due in {repository} didn't read, so "
                f"no thread parked on a condition there was woken: {unread}"
            )
            return []
        return [] if due is None else due.held

    async def guarded(
        self, launch: Register, moment: str, waking: Awaitable[list[Thread]]
    ) -> list[Thread]:
        """Return the threads `waking` wakes, at `moment`; none where it fails, said with why: the push, the landing or the session's start goes on whatever a parked thread does."""
        try:
            return await waking
        except (LupDevError, LupError) as failed:
            self.say(
                f"{launch.launch}: the threads parked until what came at {moment} "
                f"weren't woken: {failed}"
            )
            return []

    async def landed(
        self, launch: Register, onto: str, branches: list[str]
    ) -> list[Thread]:
        """At `land`, once it pushed onto `onto`, a gated branch by its short name: where that's the integration branch, wake each thread of the launch's repository parked until one of `branches` landed; then each until an issue that closed. Return those woken; none where waking fails, which is said."""
        return await self.guarded(
            launch, "a landing", self.landing(launch, onto, branches)
        )

    async def landing(
        self, launch: Register, onto: str, branches: list[str]
    ) -> list[Thread]:
        """Wake what `landed` wakes, raising what fails."""
        woken = (
            self.concerns.due(
                launch.repository,
                lambda _, trigger: (
                    isinstance(trigger, BranchLanded) and trigger.branch in branches
                ),
            )
            if onto == self.integration
            else []
        )
        return [*woken, *await self.closed(launch)]

    async def pushed(self, launch: Register, updates: list[Update]) -> list[Thread]:
        """At a push the host made for `launch`: where it moved the integration branch, wake each thread of the launch's repository parked until a commit in the history of what it pushed there. Return those woken; none where waking fails, which is said."""
        return await self.guarded(launch, "a push", self.commits(launch, updates))

    async def commits(self, launch: Register, updates: list[Update]) -> list[Thread]:
        """Wake what `pushed` wakes, raising what fails but git's word, which is said."""
        destination = f"refs/heads/{self.integration}"
        tip = next(
            (
                each.source
                for each in updates
                if each.destination == destination and each.source is not None
            ),
            None,
        )
        waited = [
            trigger.commit
            for parked in self.concerns.threads.parked(launch.repository)
            for trigger in parked.until
            if isinstance(trigger, CommitLanded)
        ]
        if tip is None or not waited:
            return []
        try:
            landed = await asyncio.to_thread(
                in_history, launch.repository, list(dict.fromkeys(waited)), tip
            )
        except LupDevError as failed:
            self.say(
                f"{launch.launch}: git couldn't say which commits a parked thread "
                f"waits on reached `{self.integration}`, so none was woken: {failed}"
            )
            return []
        return self.concerns.due(
            launch.repository,
            lambda _, trigger: (
                isinstance(trigger, CommitLanded) and trigger.commit in landed
            ),
        )

    async def started(self, launch: Register) -> None:
        """As a session's own conversation starts in `launch`: wake each thread of its repository parked until an issue that closed; nothing where waking fails, which is said."""
        await self.guarded(launch, "a session's start", self.closed(launch))

    async def closed(self, launch: Register) -> list[Thread]:
        """Wake each thread of `launch`'s repository parked until an issue that GitHub says closed, each issue asked once. Return those woken: none where none waits on an issue, where the launch's limits refuse reading issues, or where GitHub can't say, which is said."""
        waited = list(
            dict.fromkeys(
                trigger.issue
                for parked in self.concerns.threads.parked(launch.repository)
                for trigger in parked.until
                if isinstance(trigger, IssueClosed)
            )
        )
        if not waited:
            return []
        refusal = launch.limits.refusal("read-issues")
        if refusal is not None:
            self.say(
                f"{launch.launch}: no thread parked on an issue was woken: {refusal}"
            )
            return []
        closed = [each for each in waited if await self.closes(launch, each)]
        return self.concerns.due(
            launch.repository,
            lambda _, trigger: (
                isinstance(trigger, IssueClosed) and trigger.issue in closed
            ),
        )

    async def closes(self, launch: Register, issue: int | str) -> bool:
        """Say whether `issue`, as a parked thread names it, has closed; false where it names no issue, or GitHub can't say, which is said."""
        found = IssueRef.read(issue)
        if found is None:
            self.say(
                f"{launch.launch}: a thread is parked until `{issue}` closes, which "
                "names no issue: a number here, or `owner/name#7`"
            )
            return False
        try:
            return await self.states(launch, found) == "closed"
        except GitHubError as failed:
            self.say(
                f"{launch.launch}: GitHub couldn't say whether issue {found} closed, "
                f"so no thread parked on it was woken: {failed}"
            )
            return False
