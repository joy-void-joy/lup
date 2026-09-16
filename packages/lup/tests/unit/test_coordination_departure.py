"""A session's departure, written by the verbatim hook and read by the typed roster.

The writer has no import of the reader, so what is pinned first is the
spellings the two share; the rest is the record itself, folded by the roster
that owns its shape, so a departure the hook wrote reads exactly as one the
typed writer would have.
"""

from pathlib import Path

from lup.coordination import departure
from lup.coordination.identity import MEMBER_KIND, mint_member_id
from lup.coordination.repository import RepositoryPeers
from lup.coordination.roster import ROSTER_FILE


def joined(root: Path, name: str) -> tuple[RepositoryPeers, str]:
    """One repository's peers, with a session on the roster."""
    peers = RepositoryPeers(root)
    member = mint_member_id()
    peers.join(member, root / "tree", cli_name=name)
    return peers, member


def running(peers: RepositoryPeers, member: str) -> bool:
    [found] = [one for one in peers.cohort.live() if one.actor.id == member]
    return found.running


def test_the_copy_and_its_source_spell_the_store_alike() -> None:
    assert departure.ROSTER_FILE == ROSTER_FILE
    assert departure.MEMBER_KIND == MEMBER_KIND


def test_a_departure_ends_the_row_the_typed_reader_folds(tmp_path: Path) -> None:
    peers, member = joined(tmp_path, "mine")

    assert departure.depart(peers.root, member)

    assert not running(peers, member)


def test_a_session_that_never_joined_leaves_nothing(tmp_path: Path) -> None:
    """A finish for nobody is a line every fold ignores and a store should not carry."""
    peers, _ = joined(tmp_path, "other")
    before = (peers.root / ROSTER_FILE).read_text("utf-8")

    assert not departure.depart(peers.root, "nobody")
    assert not departure.depart(peers.root, "")

    assert (peers.root / ROSTER_FILE).read_text("utf-8") == before


def test_a_departed_session_leaves_once_and_rejoins_as_itself(tmp_path: Path) -> None:
    """Idempotent on the way out, and no obstacle on the way back in."""
    peers, member = joined(tmp_path, "mine")

    assert departure.depart(peers.root, member)
    assert not departure.depart(peers.root, member)

    peers.join(member, tmp_path / "tree", cli_name="mine")

    assert running(peers, member)
    assert len([one for one in peers.cohort.live() if one.actor.id == member]) == 1
