"""Which roots host git may enter, and which repositories lup comes to trust.

The judgement is :func:`lup.sandbox.pointers.verdict`'s; this is the half that
acts on it for a command about to run host git -- refusing a real mismatch,
remembering every repository that vouches for itself, and deciding whether one
nothing vouches for is trusted on first sight or only reported.

A first sighting is remembered only from the host, and only where nothing
could have built the repository to be trusted: not inside territory a contained
session writes, and not while a lup session is running in it. Anything else is
reported rather than refused, since a repository lup has not met is not a
mismatch -- it is the gap the report names.
"""

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from lup.coordination.repository import RepositoryPeers
from lup.sandbox.known import host_side, known_repositories, remember, store_directory
from lup.sandbox.pointers import Verdict, refusal, unvouchable, verdict, vouched_from
from lup.sandbox.rail import Lease


class Trust(BaseModel, frozen=True):
    """What a command says before host git runs in its roots."""

    refusal: str = ""
    notices: list[str] = []


class Sighting(BaseModel, frozen=True):
    """A root leading git to a repository nothing vouches for, and why it waits."""

    verdict: Verdict
    withheld: str


def store_exposure(lease: Lease) -> str:
    """Why this lease would let a container write lup's store, or empty.

    The store holds the repositories the host vouches for, so a mount over it
    is a way for a contained session to add the one it built. Checked against
    every mount, read-only ones too: a container has no reason to read it
    either, and a mount it may not write today is one a later lease may widen.
    """
    store = store_directory().resolve()
    mount = lease.answers_from(store)
    if mount is None:
        return ""
    return (
        f"This launch would mount {mount}, which holds lup's store of trusted "
        f"repositories at {store}, so a container could add a repository of its "
        "own to it. Set XDG_STATE_HOME outside every mounted root, or leave "
        f"{mount} unmounted."
    )


def live_session(repository: Path) -> bool:
    """Whether a lup session is running in this repository, by its roster."""
    return any(member.running for member in RepositoryPeers(repository).present())


def withheld_because(judged: Verdict, trusted: Sequence[Path]) -> str:
    """Why a first sighting is not remembered, or empty where it may be."""
    if judged.candidate is None or judged.checkout is None:
        return ""
    if reason := unvouchable(judged.candidate, judged.checkout, trusted):
        return reason
    if live_session(judged.candidate):
        return f"a lup session is running in {judged.candidate}"
    return ""


def said(sighting: Sighting) -> str:
    """The line a first sighting is reported with, remembered or not."""
    judged = sighting.verdict
    if not sighting.withheld:
        return (
            f"First sighting: {judged.root} leads git to {judged.candidate}, "
            "which lup now trusts."
        )
    return (
        f"Unverified: {judged.root} leads git to {judged.candidate}, which lup "
        f"has not seen and cannot find by path. Not recorded, because "
        f"{sighting.withheld}. Host git there reads that repository's config."
    )


def judged_roots(roots: Sequence[Path], operator: Path | None = None) -> Trust:
    """Judge every root, remember what vouches for itself, and say the rest.

    ``operator`` is where the command was run from: the repositories found by
    path from there vouch for the roots beside the ones the store remembers.
    Inside a launched session nothing is remembered and no first sighting is
    reported -- the store is the host's, and a session has none -- but a
    mismatch refuses there all the same.
    """
    trusted = [
        *known_repositories(),
        *(vouched_from(operator) if operator is not None else []),
    ]
    verdicts = [verdict(root, trusted) for root in roots]
    refused = "\n".join(
        message for judged in verdicts if (message := refusal(judged.drifts))
    )
    if refused:
        return Trust(refusal=refused)
    if not host_side():
        return Trust()
    sightings = [
        Sighting(verdict=judged, withheld=withheld_because(judged, trusted))
        for judged in verdicts
        if judged.candidate is not None
    ]
    remember(
        [
            *(
                judged.repository
                for judged in verdicts
                if judged.repository is not None
            ),
            *(
                sighting.verdict.candidate
                for sighting in sightings
                if not sighting.withheld and sighting.verdict.candidate is not None
            ),
        ]
    )
    return Trust(notices=[said(sighting) for sighting in sightings])
