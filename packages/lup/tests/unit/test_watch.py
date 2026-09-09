"""Following a repository's sessions, without consuming what they are owed.

Written against the failures a watcher can introduce rather than the ones it
reports: a message consumed by the reader that was only meant to notice it, a
change reported twice, and a run that never lands because nothing told it the
population was gone.
"""

from pathlib import Path

from lup.coordination.identity import member_ref, mint_member_id
from lup.coordination.repository import RepositoryPeers
from lup.coordination.roster import Delivery
from lup.coordination.wake import WakePath
from lup.coordination.watch import (
    Arrived,
    Departed,
    Mailed,
    Nudged,
    Redescribed,
    Watcher,
)
from lup.coordination.watcher import watcher_pipeline
from lup.runs.pipeline import RunRequest


def joined(root: Path, name: str) -> tuple[RepositoryPeers, str]:
    peers = RepositoryPeers(root)
    member = mint_member_id()
    peers.join(member, root / name, cli_name=name)
    return peers, member


def test_the_first_look_reports_the_live_roster_as_a_baseline(tmp_path: Path) -> None:
    """Attaching to a repository already at work says who is there once."""
    peers, _member = joined(tmp_path, "reviewer")
    watcher = Watcher(peers)

    first = watcher.tick()
    second = watcher.tick()

    assert [type(event) for event in first] == [Arrived]
    assert first[0].address == "reviewer"
    assert second == []


def test_a_description_change_and_a_departure_are_each_reported_once(
    tmp_path: Path,
) -> None:
    peers, member = joined(tmp_path, "reviewer")
    watcher = Watcher(peers)
    watcher.tick()

    peers.describe(member, "reading the merge")
    [changed] = watcher.tick()
    peers.leave(member, summary="landed it")
    [gone] = watcher.tick()

    assert isinstance(changed, Redescribed) and changed.doing == "reading the merge"
    assert isinstance(gone, Departed) and gone.summary == "landed it"
    assert watcher.tick() == []


def test_mail_is_reported_without_being_consumed(tmp_path: Path) -> None:
    """The watcher notices; the peer still reads. A watcher that consumed would
    be the reason a message vanished.
    """
    peers, member = joined(tmp_path, "reviewer")
    watcher = Watcher(peers)
    watcher.tick()

    peers.send("reviewer", "the parser is yours")
    [mailed] = watcher.tick()

    assert isinstance(mailed, Mailed) and mailed.text == "the parser is yours"
    assert [message.text for message in peers.waiting(member).messages] == [
        "the parser is yours"
    ]
    assert watcher.tick() == []


def test_a_member_filter_narrows_the_mail_and_not_the_roster(tmp_path: Path) -> None:
    peers, _first = joined(tmp_path, "first")
    second = mint_member_id()
    peers.join(second, tmp_path / "second", cli_name="second")
    watcher = Watcher(peers, member="second")
    baseline = watcher.tick()

    peers.send("first", "for first")
    peers.send("second", "for second")
    events = watcher.tick()

    assert {event.address for event in baseline} == {"first", "second"}
    assert [event.text for event in events if isinstance(event, Mailed)] == [
        "for second"
    ]


def test_nudging_reports_the_runtime_asymmetry_rather_than_hiding_it(
    tmp_path: Path,
) -> None:
    """A Claude peer cannot be woken by a process, so the nudge says what would
    wake it; a peer that declared nothing is told so rather than skipped.
    """
    peers = RepositoryPeers(tmp_path)
    claude = mint_member_id()
    # Joined on the roster directly so the wake path is on the first record,
    # then named, rather than through `join`, which declares none.
    peers.cohort.roster.joined(
        member_ref(claude),
        task="working",
        delivery=Delivery.INBOX,
        worktree=str(tmp_path / "claude"),
        wake=WakePath(runtime="claude", handle="claude [ab12]"),
    )
    peers.names.rename(claude, "claude")
    silent = mint_member_id()
    peers.join(silent, tmp_path / "silent", cli_name="silent")
    watcher = Watcher(peers, nudge=True)
    watcher.tick()

    peers.send("claude", "look")
    peers.send("silent", "look")
    nudges = [event for event in watcher.tick() if isinstance(event, Nudged)]

    by_address = {nudge.address: nudge.outcome for nudge in nudges}
    assert "SendMessage" in by_address["claude"].instruction
    assert not by_address["claude"].reached
    assert "declared no wake path" in by_address["silent"].reason


def test_the_run_lands_when_the_roster_is_empty(tmp_path: Path) -> None:
    """A watcher with nobody to watch is finished, which is what lets it be a
    run at all: started against an empty roster it lands at once.
    """
    pipeline = watcher_pipeline(tmp_path, interval=0.01)

    summary = pipeline.execute(RunRequest(directory=tmp_path / "run"))

    assert summary.landed == 1
