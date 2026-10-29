"""Threads, the ledger's first kind: a concern, with what's in it and where it stands.

`packages/lup-ledger/README.md`, *Threads*. A thread is a node with a short
name unique in its repository, a title, the thread it's under, and the one
conversation holding it, or none. What's in it are edges drawn to it:
- **a member,** a node in it by an `In` edge: an item, a check;
- **a part** of an item moved into it by its id (`Moved`), the operator's
  words, which counts as a member too;
- **a reference** from an item of another thread that touches it (`Refers`),
  which is no member;
- **its status,** the latest of the edges saying where it stands (`Status`):
  parked until something comes, done to confirm, settled, declined, or
  reopened.

How it stands is read from those edges at each read, never stored
(`Standing.read`): its status, what in it waits on the operator, and who's on it.
"""

from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, Self, override

from pydantic import AwareDatetime, Field, SerializeAsAny

from lup.types import Model
from lup_ledger.parties import Conversation, Lup, Operator
from lup_ledger.records import Edge, Kinds, Name, Node

if TYPE_CHECKING:
    from collections.abc import Callable

type State = Literal[
    "working",
    "waiting on the operator",
    "parked",
    "done to confirm",
    "settled",
    "declined",
]
"""Where a thread stands: worked on; waiting on the operator, for a check or
an item of theirs to answer; parked until something comes; done in an agent's
word, for the operator to confirm; settled by the operator; or declined."""


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


# lup: defer(issue=345, why="a moved part reads as open until the thread's holder answers it, once their answer is a node that can be drawn to it")
class Moved(Edge):
    """A part of an item moved into a thread by its id: the operator's words there, which the thread's holder answers.

    A part counts as a member of the thread it's moved into, while its item
    stays in its own. A part is in one thread at a time, like a node.
    """

    kind: Literal["ledger:moved"] = "ledger:moved"
    source: int
    """The item whose part it is."""
    part: Annotated[int, Field(ge=1)]
    """The part's place in its item, from 1: its id is `<source>.<part>`, cited `@2159.3`."""

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
    """An edge saying where its thread stands: the latest drawn is its status.

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
    # lup: defer(issue=345, why="nothing yet sees a trigger come due, which wakes the thread with a `Reopened`: the host a landing, an end and a time; `gh` an issue; the gate a condition")
    until: Annotated[list[Trigger], Field(min_length=1)]
    """What wakes it."""
    why: str = ""


class Done(Status):
    """A thread done, in the word of an agent on it, for the operator to confirm by trying what it says."""

    kind: Literal["ledger:done"] = "ledger:done"
    stands: ClassVar[State] = "done to confirm"
    by: Conversation
    to_try: str
    """What the operator tries to confirm it, in the agent's words."""


class Settled(Status):
    """A thread settled: only the operator settles one."""

    kind: Literal["ledger:settled"] = "ledger:settled"
    stands: ClassVar[State] = "settled"
    by: Operator


class Declined(Status):
    """A thread declined: nothing will be done about it. Only the operator declines one."""

    kind: Literal["ledger:declined"] = "ledger:declined"
    stands: ClassVar[State] = "declined"
    by: Operator
    why: str = ""


class Reopened(Status):
    """A thread reopened: back to whoever was on it, after it was parked, done, settled or declined.

    The operator reopens one, and lup does where what a parked one waits for
    comes; an agent never does.
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


class Member(Model):
    """What's in a thread: a node in it, or a part of one moved into it, with the edges drawn to that node, oldest first."""

    node: SerializeAsAny[Node]
    part: int | None = None
    """The part moved into the thread, by its place in the node; none where the node itself is in it."""
    drawn: list[SerializeAsAny[Edge]] = []


class Standing(Model):
    """Where a thread stands, as read from the edges drawn to it and to what's in it."""

    state: State
    status: SerializeAsAny[Status] | None = None
    """The latest edge saying where it stands, which carries what it says (what
    a parked thread waits for, what to try); none where nothing has."""
    waiting: list[Member] = []
    """What in it waits on the operator, oldest first, whatever its status."""
    on: list[Conversation] = []
    """Who's on it: its holder first, then each conversation that wrote what's in it."""

    @classmethod
    def read(cls, thread: Thread, drawn: list[Edge], members: list[Member]) -> Self:
        """Read where `thread` stands from `drawn`, the edges drawn to it, oldest first, and `members`, what's in it.

        Its latest status says it, but for a thread working or reopened, which
        waits on the operator where a member does.
        """
        statuses = [each for each in drawn if isinstance(each, Status)]
        status = statuses[-1] if statuses else None
        waiting = [each for each in members if each.node.waiting(each.drawn)]
        stands = "working" if status is None else status.stands
        state = "waiting on the operator" if stands == "working" and waiting else stands
        holder = [] if thread.holder is None else [thread.holder]
        writers = [
            each.node.by for each in members if isinstance(each.node.by, Conversation)
        ]
        return cls(
            state=state,
            status=status,
            waiting=waiting,
            on=list(dict.fromkeys([*holder, *writers])),
        )
