"""A session's row is present while its pulse says so, and gone when it stops.

Written against the failure the roster had: every session that ever joined
read as running forever, because the only record that ends a row is the one a
session writes on its way out, and a killed session writes nothing. What is
asserted is the read a peer makes — the listing, and the claims that expire
with a session — and the sweep that makes the read durable.
"""

from datetime import datetime, timedelta
from pathlib import Path

from lup.channels.models import utc_now
from lup.coordination.identity import member_ref, mint_member_id
from lup.coordination.pulse import HEARTBEATS_DIR, Pulse, beat, heard_at
from lup.coordination.refs import ActorRef
from lup.coordination.repository import RepositoryPeers
from lup.coordination.roster import ActorJoined, SpawnedActor

FOREVER = Pulse(stale_after_seconds=3600.0)
"""A window nothing in a test outlives, for the rows that must read as present."""

INSTANTLY = Pulse(stale_after_seconds=0.0)
"""A window nothing fits in, for the rows that must read as gone."""


def joined(root: Path, name: str, pulse: Pulse) -> tuple[RepositoryPeers, str]:
    """One repository's peers, with a session on the roster and this pulse."""
    peers = RepositoryPeers(root, pulse=pulse)
    member = mint_member_id()
    peers.join(member, root / "tree", cli_name=name)
    return peers, member


def row(
    peers: RepositoryPeers, member: str, at: datetime | None = None
) -> SpawnedActor:
    """The one row the listing holds for this member, as the pulse leaves it."""
    [found] = [one for one in peers.present(at) if one.actor.id == member]
    return found


def test_a_beat_is_one_file_per_member_whose_time_is_the_beat(tmp_path: Path) -> None:
    assert heard_at(tmp_path, "abc") is None

    before = utc_now()
    beat(tmp_path, "abc")
    heard = heard_at(tmp_path, "abc")

    assert (tmp_path / HEARTBEATS_DIR / "abc").is_file()
    assert heard is not None
    assert before - timedelta(seconds=1) <= heard <= utc_now() + timedelta(seconds=1)


def test_a_session_just_joined_is_present_on_its_record_alone(tmp_path: Path) -> None:
    """The arrival counts as being heard, so a session needs no beat to be seen."""
    peers, member = joined(tmp_path, "mine", FOREVER)

    assert row(peers, member).running
    assert heard_at(peers.root, member) is None


def test_a_session_whose_pulse_stopped_reads_as_gone_and_says_since_when(
    tmp_path: Path,
) -> None:
    peers, member = joined(tmp_path, "mine", INSTANTLY)

    gone = row(peers, member)

    assert not gone.running
    assert gone.error.startswith("unheard since ")
    assert member not in peers.live_ids()


def test_a_beat_keeps_a_session_present_past_its_record(tmp_path: Path) -> None:
    """The record says when a session last spoke; the pulse says it is still there."""
    peers = RepositoryPeers(tmp_path, pulse=Pulse(stale_after_seconds=60.0))
    member = mint_member_id()
    long_ago = utc_now() - timedelta(hours=1)
    peers.cohort.roster.stream.append(
        ActorJoined(actor=member_ref(member), task="working", at=long_ago)
    )

    assert not row(peers, member).running

    peers.beat(member)

    assert row(peers, member).running


def test_a_spawned_agent_is_answered_for_by_its_spawner_not_by_a_pulse(
    tmp_path: Path,
) -> None:
    """Only a session answers for itself; a worker's finish is its process's word."""
    peers = RepositoryPeers(tmp_path, pulse=INSTANTLY)
    peers.cohort.roster.spawned(ActorRef(kind="worker", id="w1"), task="review")

    assert row(peers, "w1").running


def test_a_gone_session_no_longer_holds_its_claims(tmp_path: Path) -> None:
    """Expiry is the roster's, and the roster reads the pulse."""
    peers, member = joined(tmp_path, "mine", FOREVER)
    peers.touches.touched(member_ref(member), tmp_path / "tree" / "a.py")

    assert [claim.path for claim in peers.held()] == [str(tmp_path / "tree" / "a.py")]

    peers.pulse = INSTANTLY

    assert peers.held() == []


def test_a_sweep_writes_the_finish_and_the_next_join_revives_the_row(
    tmp_path: Path,
) -> None:
    peers, member = joined(tmp_path, "mine", INSTANTLY)

    retired = peers.sweep()

    assert [one.actor.id for one in retired] == [member]
    [recorded] = [one for one in peers.cohort.live() if one.actor.id == member]
    assert not recorded.running
    assert recorded.error.startswith("unheard since ")
    assert peers.sweep() == []

    peers.pulse = FOREVER
    peers.join(member, tmp_path / "tree", cli_name="mine")

    assert row(peers, member).running
    assert row(peers, member).error == ""


def test_the_listing_puts_the_present_first_whatever_the_record_says(
    tmp_path: Path,
) -> None:
    peers, stale = joined(tmp_path, "stale", Pulse(stale_after_seconds=60.0))
    long_ago = utc_now() - timedelta(hours=1)
    peers.cohort.roster.stream.append(
        ActorJoined(actor=member_ref(stale), task="working", at=long_ago)
    )
    fresh = mint_member_id()
    peers.join(fresh, tmp_path / "tree", cli_name="fresh")

    listed = [(view.cli_name, view.member.running) for view in peers.listing()]

    assert listed[0] == ("fresh", True)
    assert ("stale", False) in listed
