"""The verbs a session uses to reach the other sessions in its repository.

Distinct from the cohort's verbs, and the difference is who the population is.
A cohort's tools steer agents this session started: it knows their addresses
because it minted them, and it may redirect them because it owns them. These
address peers nobody here started, so there is no listing of "what I spawned"
to fall back on and no authority to redirect — what is left is finding out who
is here, saying what you are doing so they can find you, and telling one of
them something.

The descriptions are the whole documentation an agent gets, so they carry the
one fact that changes a decision: what a message will and will not do. A peer
reached through its own hook will read this before its next tool call; a peer
whose mail only waits in a file will read it whenever it next looks, which may
be never. A sender told "sent" cannot tell those apart, so nothing here says
"sent".
"""

from pathlib import Path

from pydantic import BaseModel, Field

from lup.channels.models import Door
from lup.coordination.repository import PeerView, RepositoryPeers
from lup.coordination.roster import Delivery
from lup.tools.mcp import LupMcpTool, ToolError, lup_tool


class NoInput(BaseModel):
    """A tool that asks the roster about itself takes no arguments."""


class PeerListOutput(BaseModel):
    """Every session working in this repository, the live ones first."""

    peers: list[PeerView] = []


class DescribeInput(BaseModel):
    description: str = Field(
        description=(
            "What you are working on now, in one line, as somebody deciding "
            "whether to interrupt you would want to read it"
        )
    )


class DescribeOutput(BaseModel):
    description: str


class PeerSayInput(BaseModel):
    address: str = Field(
        description=(
            "Which peer to reach. A name from the roster, or the bare id — a "
            "name somebody wrote down before that session renamed still works"
        )
    )
    text: str = Field(description="What the peer should read")


class PeerSayOutput(BaseModel):
    address: str
    delivery: Delivery = Field(
        description=(
            "What carries this. `inbox` means the peer's own hook puts it in "
            "front of its next tool call. `mailbox` means it waits in the file "
            "until that peer next looks, and nothing will wake it"
        )
    )
    outstanding: int = Field(
        description=(
            "How much is queued for that peer and not yet handed over, this "
            "message included"
        )
    )


class InboxOutput(BaseModel):
    """What was waiting for this session, consumed by the reading."""

    messages: list[str] = []


def create_peer_tools(
    peers: RepositoryPeers,
    member_id: str,
    worktree: Path,
    door: Door = Door.AGENT,
) -> list[LupMcpTool]:
    """The repository verbs, bound to one roster and one session's identity.

    The identity is bound here rather than taken as an argument for the reason
    a resolver worker's concern is: a session that could name itself in a call
    could describe another session's work as its own, or read another
    session's inbox — and neither is a thing to be trusted rather than made
    unspellable.
    """

    def present() -> None:
        """Put this session on the roster before it does anything with it.

        Every verb calls this, because a session that never joined is one
        nothing else can reach: a description applies to no member and the
        fold drops it, and a peer looking for who is working here reads a
        roster this session is absent from.

        Here rather than where the tools are built, because building them
        must not create the store — a session that never coordinates should
        leave no sign of having been able to. Idempotent through the roster's
        own announce, so every call after the first costs a fold rather than
        a record.

        ``INBOX`` because this session has the plugin carrying the delivery
        hook. What a member says about itself is what a sender is told, so
        claiming the weaker mode here would understate what a message does.
        """
        peers.join(member_id, worktree, delivery=Delivery.INBOX)

    @lup_tool(
        "List every session working in this repository, including the ones in "
        "other worktrees, with the ones still working first. Each row is who "
        "they are, which checkout they are in, what they are doing, and what "
        "reaches them.\n\n"
        "Reach for it before starting something substantial: another session "
        "may already be on it, may hold the file you are about to rewrite, or "
        "may have settled the question you are about to re-derive. It costs "
        "one call and the alternative is finding out at merge time.\n\n"
        "The person watching is not a row and needs no listing — they are "
        "always reachable at `user`. Returns {peers: [{address, cli_name, "
        "doing, member}]}.",
        name="coordination_peers",
    )
    async def coordination_peers(_params: NoInput) -> PeerListOutput:
        present()
        return PeerListOutput(peers=peers.listing())

    @lup_tool(
        "Say what you are working on now, so the roster tells the truth about "
        "you. Anyone listing this repository's sessions reads it.\n\n"
        "Call it when what you are doing changes, not once at the start: the "
        "roster is read by somebody deciding whether they can safely touch "
        "the same code, and a description from an hour ago answers that "
        "question wrongly. One line is enough — what you are on, not how it "
        "is going.",
        name="coordination_describe",
    )
    async def coordination_describe(params: DescribeInput) -> DescribeOutput:
        present()
        peers.describe(member_id, params.description)
        return DescribeOutput(description=params.description)

    @lup_tool(
        "Tell another session in this repository something. Use it to hand "
        "over a fact it could not have had — a bound you just computed, a "
        "decision that makes half its work moot, a file you are about to "
        "rewrite underneath it.\n\n"
        "This never blocks and never stops anything. It also never guarantees "
        "arrival: the reply says what carries it, and `mailbox` means nothing "
        "will wake that peer — it reads when it next looks. If what you need "
        "is a decision before you can continue, that is a question for the "
        "person, not a message to a peer.\n\n"
        "Address `user` to reach whoever is watching. Returns {address, "
        "delivery, outstanding}.",
        name="coordination_send",
    )
    async def coordination_send(params: PeerSayInput) -> PeerSayOutput:
        present()
        found = peers.send(params.address, params.text, door=door)
        if found is None:
            known = ", ".join(view.address for view in peers.listing()) or "none"
            raise ToolError(
                f"no session in this repository answers to {params.address!r}; "
                f"present: {known}"
            )
        return PeerSayOutput(
            address=found.label(),
            delivery=peers.cohort.delivery(found),
            outstanding=len(peers.waiting(member_id).messages),
        )

    @lup_tool(
        "Read what other sessions have said to you, and consume it. Use it "
        "when you want to check for messages deliberately — a session whose "
        "mail waits in a file has nothing that will interrupt it, so this is "
        "the only way it hears anything.\n\n"
        "Reading consumes: what this hands back will not be handed back "
        "again. Returns {messages: [text]}.",
        name="coordination_inbox",
    )
    async def coordination_inbox(_params: NoInput) -> InboxOutput:
        present()
        delivery = peers.take(member_id)
        return InboxOutput(
            messages=[
                f"[{'redirect' if message.redirect else 'message'} by "
                f"{message.door}] {message.text}"
                for message in delivery.messages
            ]
        )

    return [
        coordination_peers,
        coordination_describe,
        coordination_send,
        coordination_inbox,
    ]
