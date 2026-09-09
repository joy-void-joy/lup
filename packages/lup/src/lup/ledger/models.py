"""What a ledger holds: nodes, the edges between them, and where each stands.

**This module declares no node type and no edge type.** It declares the two
bases every one of them extends, and nothing about what a task is, what a
claim owes, or what counts as verified — those belong to whoever declares the
type, because a library that answered them would be one every adopter had to
argue with.

**Types stay separate.** A `Task` and a `Claim` are unrelated models with
their own fields, sharing a log rather than a shape. Nothing unions them
outside the boundary where stored JSON becomes objects again, so reading a
task's holder is `task.holder` and not a lookup into an untyped bag.

**Standing is not a field.** A stored status is a label that outlives whatever
justified it: the evidence is withdrawn, the file it was checked against
changes, and the label sits there reading as current. So each type answers for
its own standing when somebody asks, over the edges pointing at it, and is
allowed to answer something weaker than it did yesterday. A claim cannot
outrun its support, because nothing records that it ever had any.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from lup.coordination.refs import ActorRef


class Standing(BaseModel, frozen=True):
    """One reading of where a node stands, as of whoever just asked.

    A label and the reason for it, because a status a reader cannot
    interrogate is one they either trust blindly or ignore. The reason is what
    makes a regression legible: "was verified, and a file it was checked
    against changed" is actionable where a label going quietly from green to
    amber is not.
    """

    label: str
    reason: str = ""


class LedgerEdge(BaseModel, frozen=True):
    """One relation between two nodes, in whichever direction its type means.

    Nodes rather than any particular type of node: an edge runs from a task to
    a claim as readily as between two tasks, which is the whole reason one log
    holds every type. An id is an id.
    """

    kind: str
    """Which relation this is, namespaced by whoever declared it.

    Carried on the record as well as in the class so a reader whose build
    lacks the declaring module can still say what it met, rather than seeing
    an edge it cannot name.
    """

    source: str
    target: str
    author: ActorRef
    at: datetime

    def refusal(self, source: "LedgerNode", target: "LedgerNode") -> str:
        """Why this edge may not be drawn between these two, or nothing.

        The one check a node cannot make about itself, which is why it is
        here: an edge is the only thing that sees both ends. Each type answers
        or declines, and declining is the base's answer — most relations are
        somebody organising their own notes and have nothing to object to.

        Words rather than a boolean, because a refusal a writer cannot read is
        one they will retry verbatim.
        """
        del source, target
        return ""


class LedgerNode(BaseModel, frozen=True):
    """One durable claim somebody recorded, in the shape every type shares.

    A node is what survives the session that wrote it, which is the whole
    distinction between this and the observed state
    :mod:`lup.coordination.touches` keeps: a touch says what a live session
    holds right now and expires with it, while a node is meant to be read by
    somebody who was not there.
    """

    id: str
    kind: str
    """Which type this is, namespaced by whoever declared it.

    On the record rather than inferred from the class, because one log holds
    every vocabulary and a reader will meet types its build never loaded. It
    is also what tells two modules' ``task`` apart.
    """

    title: str = Field(min_length=1)
    text: str = ""
    """What it says, in whoever wrote it's own words. Empty is honest."""

    author: ActorRef
    """Who recorded it, stamped by the store from the caller's identity.

    Provenance a writer cannot spell is provenance a writer cannot get wrong,
    which is the difference between a record that attributes and one that
    repeats what somebody claimed about themselves.
    """

    at: datetime
    attachments: list[str] = []
    """Content digests of the blobs this node carries, in the order attached."""

    def standing(self, incoming: list[LedgerEdge]) -> Standing:
        """Where this node stands, given everything pointing at it.

        Run when somebody asks and never stored. The base's answer is what a
        ledger can say without being told anything about evidence — it was
        written down — which is honest rather than a placeholder, and it means
        a type with no epistemics is one class and no overrides.
        """
        del incoming
        return Standing(label="recorded")
