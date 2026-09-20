"""Following a repository's sessions, without consuming what they are owed.

Written against the failures a watcher can introduce rather than the ones it
reports: a message consumed by the reader that was only meant to notice it, a
change reported twice, and a run that never lands because nothing told it the
population was gone.
"""

import socket
from pathlib import Path
from threading import Event, Thread

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
    nudge_text,
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


def test_nudging_wakes_a_peer_through_its_inbox_and_says_so_for_one_without(
    tmp_path: Path,
) -> None:
    """A peer that declared an inbox is woken through it; a peer that declared
    nothing is told so rather than skipped.
    """
    peers = RepositoryPeers(tmp_path)
    claude = mint_member_id()
    inbox = tmp_path / "claude.sock"
    # Joined on the roster directly so the wake path is on the first record,
    # then named, rather than through `join`, which declares none.
    peers.cohort.roster.joined(
        member_ref(claude),
        task="working",
        delivery=Delivery.INBOX,
        worktree=str(tmp_path / "claude"),
        wake=WakePath(runtime="claude", handle=str(inbox)),
    )
    peers.rename(claude, "claude")
    silent = mint_member_id()
    peers.join(silent, tmp_path / "silent", cli_name="silent")
    watcher = Watcher(peers, nudge=True)
    watcher.tick()

    peers.send("claude", "look")
    peers.send("silent", "look")
    # Served until closed rather than accepting once: how many times a tick
    # nudges one address is the watcher's business, and a listener that took
    # a single connection would fail the test on the second rather than
    # report what the watcher did.
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(inbox))
    listener.listen(8)
    listener.settimeout(0.1)
    stopping = Event()

    def serve_until_stopped() -> None:
        while not stopping.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            with connection:
                # Read to EOF before closing. The sender writes its frame and
                # closes, so a listener that closed first would reset the
                # connection with the frame still unread -- reported as a
                # broken pipe and a wake that did not land, which is this
                # stand-in's doing and not the watcher's. Timed, because a
                # sender that neither writes nor closes must cost this thread
                # a second rather than the whole suite.
                connection.settimeout(1.0)
                try:
                    while connection.recv(4096):
                        pass
                except TimeoutError:
                    continue

    serving = Thread(target=serve_until_stopped)
    serving.start()
    nudges = [event for event in watcher.tick() if isinstance(event, Nudged)]
    stopping.set()
    serving.join(timeout=5)
    listener.close()

    by_address = {nudge.address: nudge.outcome for nudge in nudges}
    assert by_address["claude"].reached
    assert "declared no wake path" in by_address["silent"].reason


def test_the_run_lands_when_the_roster_is_empty(tmp_path: Path) -> None:
    """A watcher with nobody to watch is finished, which is what lets it be a
    run at all: started against an empty roster it lands at once.
    """
    pipeline = watcher_pipeline(tmp_path, interval=0.01)

    summary = pipeline.execute(RunRequest(directory=tmp_path / "run"))

    assert summary.landed == 1


def test_a_nudge_carries_every_fresh_message_rather_than_the_newest(
    tmp_path: Path,
) -> None:
    """A wake arrives as a turn, so what it does not carry costs the peer one.

    Two messages posted between looks are equally new to a peer that has read
    neither. Handing over the last would leave the first readable only to
    somebody who thought to fold their inbox — which is the habit an idle peer
    does not have and the whole reason it is being nudged.
    """
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    peers.join(member, tmp_path / "tree", cli_name="reader")
    peers.send("reader", "the first thing")
    peers.send("reader", "the second thing")
    fresh = peers.waiting(member).messages

    carried = nudge_text(fresh)

    assert "the first thing" in carried
    assert "the second thing" in carried
    assert "coordination_inbox" in carried
