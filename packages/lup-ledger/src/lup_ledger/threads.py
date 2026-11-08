"""Threads, the ledger's first kind: a concern, with what's in it and where it stands.

`packages/lup-ledger/README.md`, *Threads*. A thread is a node with a short
name unique in its repository, a title, the thread it's under, and the one
conversation holding it, or none. What's in it are edges drawn to it:
- **a member,** a node in it by an `In` edge: an item, a check;
- **a part** of an item moved into it by its id (`Moved`), the operator's
  words, or an item whole moved in by its number while it stays in its own,
  as a friction the operator gathers there: each counts as a member too;
- **a reference** from an item of another thread that touches it (`Refers`),
  which is no member;
- **its status,** the edges saying where it stands (`Status`): parked until
  something comes, done to confirm, settled, declined, or reopened.

How it stands is read from those edges at each read, never stored
(`Standing.read`): its two marks, read apart (`Marks`), what in it waits on the
operator, and who's on it.

A root an earlier lup kept for a session stays on the ledger, and is read as
absent (`Thread.root`, `without_roots`): what's under it reads as at the top,
and what's in it as in no thread.
"""

from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, Self, override

from pydantic import AwareDatetime, Field, SerializeAsAny

from lup.types import Model
from lup_ledger.parties import Conversation, Lup, Operator
from lup_ledger.records import Edge, Kinds, Name, Node

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

type State = Literal[
    "working",
    "nobody running",
    "waiting on the operator",
    "parked",
    "done to confirm",
    "settled",
    "declined",
]
"""Where a thread stands: worked on; nobody running to work on it, its holder
ended or never there and nobody above it answering, which is read at each read
and never drawn; waiting on the operator, for a check or an item of theirs to
answer; parked until something comes; done in an agent's word, for the operator
to confirm; settled, by the operator, or by lup on a thread it made of what came
before threads; or declined."""

ROOT = "a main session's root thread"
"""What an earlier lup titled the thread it kept for each session, which is read
as absent (`Thread.root`)."""


def thread_only(edge: Edge, target: Node) -> str | None:
    """Say why `edge` can't be drawn to `target`, where `target` isn't a thread; none where it is."""
    if isinstance(target, Thread):
        return None
    return (
        f"a `{edge.kind}` is drawn to a thread, and @{target.number} is a "
        f"`{target.kind}`"
    )


class Thread(Node):
    """A concern: what the operator and the agents on it say, check and decide about one thing.

    Any number of agents may be on it; one holds it, leading it. A thread under
    another is a sub-thread, as deep as needed.
    """

    kind: Literal["ledger:thread"] = "ledger:thread"
    name: Name
    """What `thread=` and `@` take, unique among the names of its repository's
    nodes, and never an agent's name there."""
    title: str
    """What it's about, in a line."""
    parent: int | None = None
    """The number of the thread it's under; none for one at the top."""
    holder: Conversation | None = None
    """The conversation leading it; none where nobody does."""

    @property
    def root(self) -> bool:
        """Whether it's a root an earlier lup kept for a session, which is read as absent: its title says so, as it opened each.

        >>> from datetime import UTC, datetime
        >>> from pathlib import Path
        >>> made = {"number": 4, "repository": Path("/r"), "by": Operator(), "at": datetime(2026, 1, 1, tzinfo=UTC), "name": "dev"}
        >>> Thread(title=ROOT, **made).root, Thread(title="Lag", **made).root
        (True, False)
        """
        return self.parent is None and self.title == ROOT

    @override
    def refused(self, found: Callable[[int], Node | None]) -> str | None:
        """Refuse a parent that isn't a thread of the same repository, or that is under this thread, which would make a loop."""
        number = self.parent
        while number is not None:
            if number == self.number:
                return f"@{self.number} would be under itself"
            parent = found(number)
            match parent:
                case None:
                    return f"its parent, @{number}, isn't on the ledger"
                case Thread(repository=repository) if repository != self.repository:
                    return f"its parent, @{number}, is another repository's"
                case Thread(parent=above):
                    number = above
                case _:
                    return f"its parent, @{number}, is a `{parent.kind}`, not a thread"
        return None


def without_roots(threads: list[Thread]) -> list[Thread]:
    """Return `threads`, a repository's or every one's, as they're read: each root gone (`Thread.root`), and each thread right under one at the top."""
    roots = [each.number for each in threads if each.root]
    return [
        each.model_copy(update={"parent": None}) if each.parent in roots else each
        for each in threads
        if each.number not in roots
    ]


class Check(Node):
    """Something only the operator can try, in a thread: an experiment, a measurement, a step on the host.

    It waits on the operator until they answer it (`Answered`).
    """

    kind: Literal["ledger:check"] = "ledger:check"
    name: Name | None = None
    text: str
    """What to try, and what to look for, in the words of the agent asking."""

    @override
    def waiting(self, drawn: list[Edge]) -> bool:
        return not any(isinstance(each, Answered) for each in drawn)


class In(Edge):
    """A node in a thread, a member of it: an item, a check.

    A node is in one thread at a time: drawn again to another, it's moved there.
    """

    kind: Literal["ledger:in"] = "ledger:in"
    source: int
    """The node in the thread."""

    @override
    def refused(self, source: Node | None, target: Node) -> str | None:
        if isinstance(source, Thread):
            return (
                f"@{source.number} is a thread, which is under another by its "
                "`parent`, not in it"
            )
        return thread_only(self, target)

    @override
    def replaces(self, earlier: Edge) -> bool:
        return isinstance(earlier, In)


class Moved(Edge):
    """A part of an item moved into a thread by its id, the operator's words there, which the thread's holder answers; or an item whole moved in by its number, as a friction the operator gathers into a concern.

    Either counts as a member of the thread it's moved into, while its item
    stays in its own: where `In` takes a node out of its thread, this leaves it
    there, its own thread's history whole. Each is in one thread at a time by
    it, as a node is by `In`. A part waits on whoever answers for the thread
    until a node in the thread answers it (`Edge.answers`), whoever wrote that
    node (`answered`); an item whole waits on nobody, the thread being what
    stays open until it's settled.
    """

    kind: Literal["ledger:moved"] = "ledger:moved"
    source: int
    """The item whose part it is, or the item moved whole."""
    part: Annotated[int, Field(ge=1)] | None = None
    """The part's place in its item, from 1: its id is `<source>.<part>`, cited
    `@2159.3`; none for the item whole."""

    @override
    def refused(self, source: Node | None, target: Node) -> str | None:
        return thread_only(self, target)

    @override
    def replaces(self, earlier: Edge) -> bool:
        return isinstance(earlier, Moved) and earlier.part == self.part


class Refers(Edge):
    """An item of one thread that touches another: shown in that other as a line pointing at it, whole in its own.

    It makes the item no member of the thread it refers to, and nothing there
    waits on it.
    """

    kind: Literal["ledger:refers"] = "ledger:refers"
    source: int
    """The item referring to the thread."""

    @override
    def refused(self, source: Node | None, target: Node) -> str | None:
        return thread_only(self, target)


class Answered(Edge):
    """The operator's answer to a check: a tick, or what they saw.

    Its source, where there is one, is the operator's item that answered it.
    """

    kind: Literal["ledger:answered"] = "ledger:answered"
    source: int | None = None
    by: Operator
    text: str = ""
    """What they saw, in their words; empty for a tick."""

    @override
    def refused(self, source: Node | None, target: Node) -> str | None:
        if isinstance(target, Check):
            return None
        return (
            f"an answer is drawn to a check, and @{target.number} is a `{target.kind}`"
        )


class IssueClosed(Model):
    """An issue closing."""

    trigger: Literal["issue closed"] = "issue closed"
    issue: int | str
    """Its number in the thread's repository, or `owner/name#7` elsewhere, as `defer`'s `issue=` takes it."""


class BranchLanded(Model):
    """A branch landing on the integration branch."""

    trigger: Literal["branch landed"] = "branch landed"
    branch: str


class CommitLanded(Model):
    """A commit reaching the integration branch."""

    trigger: Literal["commit landed"] = "commit landed"
    commit: str
    """Its hash, whole or its start."""


class ConversationEnded(Model):
    """A conversation ending: a session's own, or a subagent."""

    trigger: Literal["conversation ended"] = "conversation ended"
    conversation: Conversation


class TimeCame(Model):
    """A time coming."""

    trigger: Literal["time came"] = "time came"
    at: AwareDatetime


class ConditionHeld(Model):
    """A condition holding, named as `defer`'s `when=` names one: a `Condition` one of the project's modules declares in Python."""

    trigger: Literal["condition held"] = "condition held"
    when: str
    """The condition's name, as the project's modules bind it."""


type Trigger = Annotated[
    IssueClosed
    | BranchLanded
    | CommitLanded
    | ConversationEnded
    | TimeCame
    | ConditionHeld,
    Field(discriminator="trigger"),
]
"""What a parked thread waits for."""


class Status(Edge):
    """An edge saying where its thread stands: the latest drawn is its status, and each moves one of its two marks (`Marks`).

    Its source, where there is one, is the item that said it.
    """

    source: int | None = None
    stands: ClassVar[State]
    """Where a thread stands while this is its latest status; `working` for one
    that reopens it, which waits on the operator where a member does."""

    @override
    def refused(self, source: Node | None, target: Node) -> str | None:
        return thread_only(self, target)


class Parked(Status):
    """A thread set aside until something comes: the first of its triggers to come due wakes it."""

    kind: Literal["ledger:parked"] = "ledger:parked"
    stands: ClassVar[State] = "parked"
    until: Annotated[list[Trigger], Field(min_length=1)]
    """What wakes it: the first to come draws a `Reopened` by lup, each seen
    where lup already looks (`lup_dev.policy.coming`)."""
    why: str = ""


class Done(Status):
    """A thread done, in the word of an agent on it, for the operator to confirm by trying what it says."""

    kind: Literal["ledger:done"] = "ledger:done"
    stands: ClassVar[State] = "done to confirm"
    by: Conversation
    to_try: str
    """What the operator tries to confirm it, in the agent's words."""


class Settled(Status):
    """A thread settled: by the operator; or by lup, saying why, where it made a thread of what came before threads and nothing in it waited on them. Never by an agent."""

    kind: Literal["ledger:settled"] = "ledger:settled"
    stands: ClassVar[State] = "settled"
    by: Annotated[Operator | Lup, Field(discriminator="party")]
    why: str = ""
    """Why lup settled it; the operator's says nothing."""


class Declined(Status):
    """A thread declined: nothing will be done about it. Only the operator declines one."""

    kind: Literal["ledger:declined"] = "ledger:declined"
    stands: ClassVar[State] = "declined"
    by: Operator
    why: str = ""


class Reopened(Status):
    """A thread reopened: back to whoever was on it, after it was parked, done, settled or declined.

    The operator reopens one, opening both its marks, and lup does where what a
    parked one waits for comes, opening the agent's alone; an agent never does.
    """

    kind: Literal["ledger:reopened"] = "ledger:reopened"
    stands: ClassVar[State] = "working"
    by: Annotated[Operator | Lup, Field(discriminator="party")]
    why: str = ""


KINDS = Kinds(
    nodes=[Thread, Check],
    edges=[In, Moved, Refers, Answered, Parked, Done, Settled, Declined, Reopened],
)
"""The kinds the ledger declares itself."""


class Marks(Model):
    """A thread's two marks, each its own, read apart from the edges saying where it stands: the agent's, done, parked or open, and the operator's, cleared or open.

    Neither moves the other: an agent saying a thread is done after the
    operator cleared it leaves it cleared, and the operator clearing one an
    agent said is done keeps their account. A sub-thread has marks of its own,
    whatever its parent's. The operator reopening it opens both; lup reopening
    one parked, as what it waited for came, opens the agent's alone. Nothing new
    is stored: they're the `Status` edges an earlier lup read as one, its latest.
    """

    agent: Annotated[Done | Parked, Field(discriminator="kind")] | None = None
    """The agent's mark: the latest `Done` or `Parked`, where nothing reopened
    it since; none where it's open."""
    operator: Annotated[Settled | Declined, Field(discriminator="kind")] | None = None
    """The operator's mark, cleared: the latest `Settled` or `Declined`, where
    they didn't reopen it since; none where it's open."""

    @classmethod
    def read(cls, statuses: Sequence[Status]) -> Self:
        """Read both marks from `statuses`, the edges saying where a thread stands, oldest first.

        >>> from datetime import UTC, datetime
        >>> from pathlib import Path
        >>> worker = Conversation(repository=Path("/r"), runtime="r", session="s")
        >>> drawn = {"target": 4, "repository": Path("/r"), "at": datetime(2026, 1, 1, tzinfo=UTC)}
        >>> done = Done(by=worker, to_try="Type.", **drawn)
        >>> settled = Settled(by=Operator(), **drawn)
        >>> Marks.read([done, settled]) == Marks.read([settled, done]) == Marks(agent=done, operator=settled)
        True
        >>> Marks.read([done, settled, Reopened(by=Operator(), **drawn)])
        Marks(agent=None, operator=None)
        >>> Marks.read([settled, Reopened(by=Lup(), **drawn)]) == Marks(operator=settled)
        True
        """
        agent: Done | Parked | None = None
        operator: Settled | Declined | None = None
        for each in statuses:
            match each:
                case Done() | Parked():
                    agent = each
                case Settled() | Declined():
                    operator = each
                case Reopened(by=Operator()):
                    agent, operator = None, None
                case Reopened():
                    agent = None
                case _:
                    pass
        return cls(agent=agent, operator=operator)

    @property
    def done(self) -> Done | None:
        """The agent's account of what's done, where their mark says it is; none else."""
        return self.agent if isinstance(self.agent, Done) else None


def stood(marks: Marks, *, waiting: bool, running: bool = True) -> State:
    """Say where a thread stands in a word, given its `marks`, whether something in it `waiting` on the operator, and whether anyone `running` answers for it: cleared, as the operator's mark says; else as the agent's says, done or parked; else waiting on the operator where something in it does, and else worked on only where someone answers for it.

    >>> stood(Marks(), waiting=True), stood(Marks(), waiting=False)
    ('waiting on the operator', 'working')
    >>> stood(Marks(), waiting=False, running=False), stood(Marks(), waiting=True, running=False)
    ('nobody running', 'waiting on the operator')
    """
    if marks.operator is not None:
        return marks.operator.stands
    if marks.agent is not None:
        return marks.agent.stands
    if waiting:
        return "waiting on the operator"
    return "working" if running else "nobody running"


class Member(Model):
    """What's in a thread: a node in it, or a part of one moved into it, with the edges drawn to that node, oldest first."""

    node: SerializeAsAny[Node]
    part: int | None = None
    """The part moved into the thread, by its place in the node; none where the node itself is in it."""
    moved: bool = False
    """Whether it's in the thread as moved there (`Moved`), its node staying in
    its own: a part always is, an item whole where it was moved whole."""
    drawn: list[SerializeAsAny[Edge]] = []


def answered(member: Member, members: list[Member]) -> bool:
    """Say whether `member`, a part of the operator's words moved into a thread whose members are `members`, is answered: a node in the thread answers it (`Edge.answers`), citing it or answering the whole of what it's of, whoever wrote it.

    The answer is where the operator reads it, beside their words: whoever
    answers for the thread from above answers into it, naming it as they
    send. A citation from outside the thread is a reference, no answer, so a
    mover saying where they routed a part doesn't close it. A subagent's
    counts, since a subagent starts on their parent's thread and the work their
    parent handed them answers there. A node itself in the thread, never a
    part, nor an item moved in whole from another, is what answers.
    """
    return answering(member, members) is not None


def answering(member: Member, members: list[Member]) -> int | None:
    """Return the node in a thread whose members are `members` that answers `member`, a part of the operator's words moved in, the first drawn, by its number; none where nothing in it does, or `member` is no part (`answered`)."""
    if member.part is None:
        return None
    inside = [each.node.number for each in members if not each.moved]
    return next(
        (
            each.source
            for each in member.drawn
            if each.answers(member.part) and each.source in inside
        ),
        None,
    )


class Standing(Model):
    """Where a thread stands, as read from the edges drawn to it and to what's in it."""

    state: State
    status: SerializeAsAny[Status] | None = None
    """The latest edge saying where it stands, which carries what it says (what
    a parked thread waits for, what to try); none where nothing has."""
    marks: Marks = Marks()
    """Its two marks, the agent's and the operator's, each read apart."""
    waiting: list[Member] = []
    """What in it waits on the operator, oldest first, whatever its status."""
    unanswered: list[Member] = []
    """The parts of the operator's words moved into it that nothing answers yet
    (`answered`), oldest first: each waits on whoever answers for the thread."""
    on: list[Conversation] = []
    """Who's on it: its holder first, then each conversation that wrote what's
    in it, but an item moved in whole from another, whose writer wrote it there."""

    @classmethod
    def read(
        cls,
        thread: Thread,
        drawn: list[Edge],
        members: list[Member],
        *,
        running: bool = True,
    ) -> Self:
        """Read where `thread` stands from `drawn`, the edges drawn to it, oldest first, `members`, what's in it, and whether anyone `running` answers for it.

        Its marks say it, each read apart (`Marks`), but for a thread open by
        both, which waits on the operator where a member does, and else is
        worked on only where someone answers for it (`stood`).
        """
        statuses = [each for each in drawn if isinstance(each, Status)]
        status = statuses[-1] if statuses else None
        marks = Marks.read(statuses)
        waiting = [each for each in members if each.node.waiting(each.drawn)]
        state = stood(marks, waiting=bool(waiting), running=running)
        holder = [] if thread.holder is None else [thread.holder]
        writers = [
            each.node.by
            for each in members
            if isinstance(each.node.by, Conversation) and not each.moved
        ]
        unanswered = [
            each
            for each in members
            if each.part is not None and not answered(each, members)
        ]
        return cls(
            state=state,
            status=status,
            marks=marks,
            waiting=waiting,
            unanswered=unanswered,
            on=list(dict.fromkeys([*holder, *writers])),
        )
