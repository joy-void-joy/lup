"""What a native call reaching another session is judged by.

A runtime that can address another session offers a second way to reach one,
and the two acts are not the same. A message on the coordination stream is a
durable record every worktree folds and every later session can read; a native
send is a call whose text exists only inside whichever process received it. So
where both would reach the same member, this stops the one leaving no record
and names the one that does — and where the native call reaches somebody the
roster has never heard of, it says nothing at all.

That asymmetry is the whole design. A subagent this session started is on no
repository roster, so continuing one passes through untouched; a listing
speaking for a wider population than this repository is left to speak for it,
with this repository's own roster attached rather than substituted. Refusing
the listing was considered and is wrong for a measurable reason: most of what
it returns is sessions in other repositories, which a repository-scoped roster
is structurally incapable of holding, so the redirect would answer a question
the reader did not ask.
"""

from .decision import KernelDecision
from .rows import PeerRedirectRow
from .tools import TOOL_ESCALATE_HINT, escalated_reason


def undeclared_roster(
    reason: str = "no roster is declared for this repository",
) -> KernelDecision:
    """The answer to a peer call where nothing coordinates: leave it alone.

    ``defer`` rather than a verdict, because a project whose sessions do not
    coordinate has said nothing about this call and the runtime's own
    permissions are the whole of what should decide it. An ``ask`` here would
    price a listing at an approval for every project that declined the module.
    """
    return KernelDecision("defer", reason)


def addressed_peer(values: list[str], addresses: list[str]) -> str:
    """Which live member this call names, or nothing where it names none.

    Matched against every string the call carries rather than against a named
    field, for the reason a refusal is: which field a runtime spells a
    recipient in is that runtime's business, and a check knowing one spelling
    would fail open on the rest. Whole values only — a message *mentioning* a
    peer is not a message addressed to one.
    """
    return next((value for value in values if value in addresses), "")


def decide_peer_send(
    values: list[str], addresses: list[str], row: PeerRedirectRow | None
) -> KernelDecision:
    """Judge one native send against who this repository's roster holds.

    A hit denies and says where the same peer is reached durably. A miss
    defers: the target is a subagent this session started, a teammate, or a
    session in another repository, and every one of those is a use the native
    call is the only way to make.
    """
    if row is None:
        return undeclared_roster()
    named = addressed_peer(values, addresses)
    if not named:
        return KernelDecision("defer", "no member of this repository's roster")
    why = escalated_reason(values)
    if why:
        return KernelDecision("ask", f"escalated ({why}): {row['send_reason']}")
    return KernelDecision("deny", f"{named}: {row['send_reason']}" + TOOL_ESCALATE_HINT)


def decide_peer_listing(row: PeerRedirectRow | None) -> KernelDecision:
    """Judge one native listing, which is to say leave it alone.

    Always a deferral. The call answers a question this repository's roster
    cannot, so there is nothing here to permit and nothing to refuse — what
    the roster has to offer rides alongside as context rather than as a
    verdict, and a verdict is the one thing that could take the answer away.
    """
    if row is None:
        return undeclared_roster()
    return KernelDecision("defer", "a wider population than this repository's roster")


def peer_listing_context(listing: list[str], row: PeerRedirectRow | None) -> str:
    """This repository's roster, framed so a reader can tell it from the wider one.

    Empty where nothing has joined, because an attachment saying a roster is
    empty teaches a reader nothing they could act on and is paid for on every
    listing call. Empty likewise where no roster is declared at all.
    """
    if row is None or not listing:
        return ""
    return "\n".join([row["listing_note"], *[f"  {line}" for line in listing]])
