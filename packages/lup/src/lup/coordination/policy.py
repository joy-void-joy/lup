"""What the permission policy is told about this repository's sessions.

The hook that judges a call runs as a bare script outside every import graph,
so it cannot ask this package anything. What it can be handed is data, compiled
into the plugin beside it — and what it genuinely needs is where the roster and
the claim record live, which is this package's own layout rather than a path a
policy could be configured with. Handing it over from here is what stops those
directories being spelled twice: renaming the store moves the hook with it.

The prose is a default rather than a fixture. What a stopped caller should
reach for is a judgement about the surfaces a project offers, and a project
that renamed its own is entitled to say so without editing the library.
"""

from lup.coordination.identity import MEMBER_ENV, NAMES_FILE
from lup.coordination.roster import ROSTER_FILE
from lup.coordination.store import COORDINATION_DIR, STORE_DIR
from lup.coordination.touches import TOUCHES_FILE, WINDOWS_DIR
from lup.policy.peer_policy import PeerPolicy

SEND_REDIRECT = (
    "that address is a session on this repository's roster, and a native send"
    " reaches it through a channel no other worktree can fold — nothing later"
    " can read that the two of you agreed on anything. Say it with the"
    " `coordination_send` tool instead, which reaches the same peer, records"
    " it where every session working in this clone can read it, and tells you"
    " whether the peer's own hook will put it in front of that peer's next"
    " tool call or it waits in the file until they next look"
)
"""Why the durable path is the one worth taking, for a send that would not.

Names what the other surface buys rather than only refusing, because a sender
told no and nothing else sends the same message again through whatever it
tries next. The delivery report is the half a native send has no answer for at
all: it cannot say whether anybody will hear this.
"""

LISTING_NOTE = (
    "This repository's own roster, which is a different population from the"
    " listing above: these are the sessions working in this clone, in whatever"
    " worktree, and they include peers no account-scoped listing can see."
    " Reach any of them with `coordination_send`, which records what it"
    " carries. The person watching is always at `user`."
)
"""How the roster is framed beside a listing that speaks for something wider.

The two are different objects and the whole risk is a reader taking one for
the other, so the note says which is which before it says what to do — an
attachment that only offered a tool would read as a correction of the listing
it rides on.
"""

CLAIM_HELD = (
    "a live session in this repository has that path, which nobody declared —"
    " it is there because that session's own calls changed it, or because it"
    " took the prefix deliberately. Writing under it is how two sessions"
    " overwrite each other between merges, and the loser finds out at merge"
    " time. Ask the holder with `coordination_send` first, or go ahead if you"
    " already know what they are doing. A claim expires with the session"
    " holding it, so one still standing means that session has not stopped"
)
"""What an editor of a path somebody else is in is told, and what to do about it.

An approval question rather than a refusal, because the answer is genuinely
the operator's: two sessions editing one file is sometimes exactly right, and
a policy that decided otherwise would refuse ordinary work. What it must not
be is silent — the failure this exists for is finding out at merge time.
"""


def peer_policy(
    send_reason: str = SEND_REDIRECT,
    listing_note: str = LISTING_NOTE,
    claim_reason: str = CLAIM_HELD,
) -> PeerPolicy:
    """This repository's sessions, as the compiled permission hook reads them."""
    return PeerPolicy(
        store=[STORE_DIR, COORDINATION_DIR],
        roster_file=ROSTER_FILE,
        names_file=NAMES_FILE,
        touches_file=TOUCHES_FILE,
        windows_dir=WINDOWS_DIR,
        send_reason=send_reason,
        listing_note=listing_note,
        claim_reason=claim_reason,
        member_env=MEMBER_ENV,
    )
