"""The validated surface for keeping a peer's mail on the record, and its erasure.

The library declares none. Whether this project's sessions coordinate at all
is the coordination module's answer rather than the policy's, so this states
the shape a declaration takes and
:func:`lup.coordination.policy.peer_policy` builds one from the store's own
layout — which is what keeps the directory spelled once, in the module that
owns it, instead of once there and once in a compiled hook.
:mod:`lup.policy.kernel.peers` decides against the erased row.
"""

from pydantic import BaseModel, Field

from lup.policy.kernel.rows import PeerPolicyRow


class PeerPolicy(BaseModel, frozen=True):
    """Where this project's sessions find each other, and what a caller is told.

    Carried as one declaration rather than two because it is one subject read
    two ways — reaching a peer, and finding out who there is to reach. A
    project stating only half of it would redirect a send while leaving a
    listing to speak, unqualified, for a population its roster does not hold.

    ``store`` is the roster's directory beneath the repository's shared git
    directory, as path parts. Parts rather than a joined string because the
    dispatcher rebuilds the path with the host's own separator, and a compiled
    literal carrying one platform's answers on one platform.
    """

    store: list[str] = Field(min_length=1)
    roster_file: str = Field(min_length=1)
    names_file: str = Field(min_length=1)
    send_reason: str = Field(min_length=1)
    listing_note: str = Field(min_length=1)


def erase_peer_policy(declared: PeerPolicy | None) -> PeerPolicyRow | None:
    """Erase the validated declaration into the primitive row the kernel reads."""
    if declared is None:
        return None
    return PeerPolicyRow(
        store=list(declared.store),
        roster_file=declared.roster_file,
        names_file=declared.names_file,
        send_reason=declared.send_reason,
        listing_note=declared.listing_note,
    )
