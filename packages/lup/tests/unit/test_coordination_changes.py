"""The roster's changes reaching a session at each prompt, from inside the plugin.

The prompt half reads the store through the same fold the typed library reads
it through, so nothing here pins one spelling against another — what is left
to assert is what a session must and must not be told: nothing on a quiet
roster, a baseline rather than a replay on the first prompt, the contested
path before everything else, and a standing fact once rather than at every
prompt, all over a store the typed writers produced.
"""

import json
import os
from datetime import timedelta
from pathlib import Path

from lup.channels.models import utc_now
from lup.coordination.bare import changes as fold
from lup.coordination.bare import store
from lup.coordination.bare.store import MEMBER_KIND, beat, member_path, session_actor
from lup.coordination.identity import member_ref, mint_member_id
from lup.coordination.repository import RepositoryPeers


def joined(peers: RepositoryPeers, worktree: Path, name: str) -> str:
    """One session on the roster, named, and the id it answers to."""
    member = mint_member_id()
    peers.join(member, worktree, cli_name=name)
    return member


def told(peers: RepositoryPeers, member: str, worktree: Path) -> list[str]:
    """What one prompt in *worktree* tells *member*."""
    return fold.changes(peers.root, member, worktree)


def changed(path: Path) -> Path:
    """A file that is there to be claimed, since a claim is settled by a stat.

    A claim records the path's modification time, so a claim over nothing
    stands for nobody — which is right, and means a test arranging one has to
    arrange the file too.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("value = 1\n", encoding="utf-8")
    return path


def silent_since(peers: RepositoryPeers, member: str, ago: timedelta) -> None:
    """Put this member's file back in time, the way a stopped session leaves it."""
    when = (utc_now() - ago).timestamp()
    os.utime(member_path(peers.root, session_actor(member)), (when, when))


def heard(peers: RepositoryPeers, member: str) -> str:
    """When this member was last heard from, as every reader reads it."""
    found = store.read_member(
        member_path(peers.root, session_actor(member)), running=True
    )
    return store.text(found.get("heard")) if found is not None else ""


def test_a_prompt_beats_for_the_session_it_was_submitted_from(tmp_path: Path) -> None:
    """The hook is the pulse a session without a tool server has."""
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    silent_since(peers, me, timedelta(hours=1))
    stopped = heard(peers, me)

    told(peers, me, tmp_path / "mine")

    assert heard(peers, me) > stopped


def test_a_peer_the_pulse_retired_reads_as_departed(tmp_path: Path) -> None:
    """A killed session leaves the look the way one that said goodbye does."""
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    other = joined(peers, tmp_path / "theirs", "reviewer")
    held = changed(tmp_path / "mine" / "src" / "a.py")
    peers.touched(other, held)
    silent_since(peers, other, timedelta(seconds=store.STALE_AFTER_SECONDS + 1))

    assert told(peers, me, tmp_path / "mine") == [
        "No other session is working in this repository; "
        "`coordination_peers` lists whoever arrives."
    ]

    beat(peers.root, session_actor(other))

    assert told(peers, me, tmp_path / "mine") == [
        f"reviewer holding at {held}",
        f"reviewer arrived — theirs — working in {tmp_path / 'theirs'}",
    ]


def test_the_fold_names_a_conversation_the_way_the_roster_names_it() -> None:
    """One key, derived twice: by the shared fold, and by the typed ref.

    The last spelling the two halves still derive separately. Everything else
    the store is made of is declared once and imported, but a conversation key
    is built from a kind and an id on both sides, and a look filed under one
    spelling while the roster folds the other is a session whose baseline
    never matches its own row.
    """
    assert (
        store.conversation_of(store.Actor(kind=store.MEMBER_KIND, id="abc123"))
        == member_ref("abc123").conversation()
    )


def test_the_first_prompt_is_a_baseline_carrying_one_pointer(tmp_path: Path) -> None:
    """Attaching to a repository already at work says where the roster is, once."""
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    joined(peers, tmp_path / "theirs", "reviewer")

    first = told(peers, me, tmp_path / "mine")
    second = told(peers, me, tmp_path / "mine")

    assert first == [
        "1 other session is working in this repository; `coordination_peers` lists it."
    ]
    assert second == []


def test_a_lone_session_is_still_pointed_at_the_listing(tmp_path: Path) -> None:
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")

    assert told(peers, me, tmp_path / "mine") == [
        "No other session is working in this repository; "
        "`coordination_peers` lists whoever arrives."
    ]


def test_an_arrival_a_redescription_and_a_departure_are_each_one_line(
    tmp_path: Path,
) -> None:
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    told(peers, me, tmp_path / "mine")

    other = joined(peers, tmp_path / "theirs", "reviewer")
    arrived = told(peers, me, tmp_path / "mine")
    peers.describe(other, "reading the merge")
    redescribed = told(peers, me, tmp_path / "mine")
    peers.leave(other, summary="landed it")
    departed = told(peers, me, tmp_path / "mine")

    assert arrived == [f"reviewer arrived — theirs — working in {tmp_path / 'theirs'}"]
    assert redescribed == ["reviewer now: reading the merge"]
    assert departed == ["reviewer left — landed it"]
    assert told(peers, me, tmp_path / "mine") == []


def test_a_holding_under_this_checkout_is_told_and_one_elsewhere_is_not(
    tmp_path: Path,
) -> None:
    """Claims are keyed by absolute path, so another worktree's copy is not news.

    A lock over a prefix the checkout lies under is, because a write here
    would land beneath it.
    """
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    other = joined(peers, tmp_path / "theirs", "reviewer")
    told(peers, me, tmp_path / "mine")

    peers.touched(other, changed(tmp_path / "theirs" / "src" / "a.py"))
    elsewhere = told(peers, me, tmp_path / "mine")
    here = changed(tmp_path / "mine" / "src" / "a.py")
    peers.touched(other, here)
    told_here = told(peers, me, tmp_path / "mine")
    peers.lock(other, tmp_path)
    above = told(peers, me, tmp_path / "mine")

    assert elsewhere == []
    assert told_here == [f"reviewer holding at {here}"]
    assert above == [f"reviewer holding under {tmp_path}"]


def test_a_contested_path_comes_first_and_is_not_repeated_as_a_holding(
    tmp_path: Path,
) -> None:
    """The line a session about to write needs most is the one it reads first."""
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    told(peers, me, tmp_path / "mine")

    other = joined(peers, tmp_path / "mine", "reviewer")
    shared = changed(tmp_path / "mine" / "src" / "b.py")
    alone = changed(tmp_path / "mine" / "src" / "a.py")
    peers.touched(other, alone, shared)
    peers.touched(me, shared)

    assert told(peers, me, tmp_path / "mine") == [
        f"contested at {shared} — mine, reviewer",
        f"reviewer holding at {alone}",
        f"reviewer arrived — mine — working in {tmp_path / 'mine'}",
    ]


def test_a_departure_takes_its_name_off_a_contested_claim(tmp_path: Path) -> None:
    """Expiry is the roster's: a stopped session's share of a claim goes with it.

    Only the departure is news. The survivor's hold on the path was already
    on the record under the contested line, so it is not told again as a
    holding — and the path stops being contested without a line of its own,
    because the departure is the whole of what changed.
    """
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    other = joined(peers, tmp_path / "mine", "reviewer")
    third = joined(peers, tmp_path / "mine", "third")
    shared = changed(tmp_path / "mine" / "src" / "b.py")
    peers.touched(other, shared)
    peers.touched(third, shared)
    told(peers, me, tmp_path / "mine")

    peers.leave(third)

    assert told(peers, me, tmp_path / "mine") == ["third left"]
    assert told(peers, me, tmp_path / "mine") == []


def test_a_standing_notice_is_told_once_and_again_when_it_is_lifted(
    tmp_path: Path,
) -> None:
    """A fact about the whole repository, and a reader told it rather than sent it.

    Once, because a session here reads one prompt after another for hours and
    a line repeated at each of them is read at none. The session that starts
    tomorrow reads it at its own first prompt, which is what a notice being
    state rather than mail buys.
    """
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    told(peers, me, tmp_path / "mine")

    peers.notify("dev is frozen for the release", by="dev-2")
    posted = told(peers, me, tmp_path / "mine")
    quiet = told(peers, me, tmp_path / "mine")
    [standing] = peers.cohort.mail.standing()
    peers.cohort.mail.retract(standing.id)
    lifted = told(peers, me, tmp_path / "mine")

    assert posted == ["standing: dev is frozen for the release (dev-2)"]
    assert quiet == []
    assert lifted == ["no longer standing: dev is frozen for the release (dev-2)"]


def test_a_session_arriving_under_a_notice_reads_it_at_its_first_prompt(
    tmp_path: Path,
) -> None:
    """The half a message could never reach: whoever starts after it was posted."""
    peers = RepositoryPeers(tmp_path)
    peers.notify("dev is frozen for the release")
    latecomer = joined(peers, tmp_path / "mine", "mine")

    assert told(peers, latecomer, tmp_path / "mine") == [
        "standing: dev is frozen for the release",
        "No other session is working in this repository; "
        "`coordination_peers` lists whoever arrives.",
    ]


def test_an_unreadable_look_re_baselines_rather_than_replays(tmp_path: Path) -> None:
    """Of the two ways to be wrong about a look, only one costs a single line."""
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    joined(peers, tmp_path / "theirs", "reviewer")
    told(peers, me, tmp_path / "mine")
    (peers.root / store.LOOKS_DIR / f"{MEMBER_KIND}-{me}.json").write_text("not a look")

    assert told(peers, me, tmp_path / "mine") == [
        "1 other session is working in this repository; `coordination_peers` lists it."
    ]


def test_two_sessions_in_one_checkout_each_keep_their_own_look(
    tmp_path: Path,
) -> None:
    """A look is per member, so a peer's prompt does not consume this one's changes."""
    peers = RepositoryPeers(tmp_path)
    first = joined(peers, tmp_path / "mine", "first")
    second = joined(peers, tmp_path / "mine", "second")
    told(peers, first, tmp_path / "mine")

    joined(peers, tmp_path / "mine", "third")
    told(peers, second, tmp_path / "mine")

    assert told(peers, first, tmp_path / "mine") == [
        f"third arrived — mine — working in {tmp_path / 'mine'}"
    ]


def test_a_store_that_is_not_there_says_nothing_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """The failure that must not stop a prompt, and must not create a store either."""
    assert fold.changes(tmp_path / "absent", "abc123", tmp_path) == []
    assert not (tmp_path / "absent").exists()


def test_a_session_with_no_identity_is_told_nothing(tmp_path: Path) -> None:
    peers = RepositoryPeers(tmp_path)
    joined(peers, tmp_path / "mine", "mine")

    assert fold.changes(peers.root, "", tmp_path / "mine") == []
    assert not (peers.root / store.LOOKS_DIR).exists()


def transcript(path: Path, roots: int) -> str:
    """A transcript holding this many conversation roots, a turn and a note under each.

    The shape a rewind leaves in the runtime's own file: every root is a
    prompt with no parent, and the attachments between turns parent nothing
    a turn descends from.
    """
    lines = [
        json.dumps(entry)
        for n in range(roots)
        for entry in (
            {"type": "user", "uuid": f"root-{n}", "parentUuid": None},
            {"type": "assistant", "uuid": f"turn-{n}", "parentUuid": f"root-{n}"},
            {"type": "attachment", "uuid": f"note-{n}", "parentUuid": f"turn-{n}"},
        )
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_a_rewind_clears_what_the_row_said_and_re_baselines(tmp_path: Path) -> None:
    """A new root in the same transcript is the one sign a rewind leaves.

    What the row said and which conversation said it are one write, on this
    member's own file: a reader meeting the row after a rewind cannot find a
    description belonging to a conversation that is gone.
    """
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    joined(peers, tmp_path / "theirs", "reviewer")
    peers.describe(me, "the work the rewind discards")
    log = tmp_path / "session.jsonl"
    fold.changes(peers.root, me, tmp_path / "mine", transcript(log, roots=1))
    assert fold.changes(peers.root, me, tmp_path / "mine", str(log)) == []

    rewound = fold.changes(peers.root, me, tmp_path / "mine", transcript(log, roots=2))

    assert rewound == [
        fold.MOVED_LINE,
        "1 other session is working in this repository; `coordination_peers` lists it.",
    ]
    [mine] = [row for row in peers.listing() if row.member.actor.id == me]
    assert mine.member.description == ""
    assert mine.member.running
    assert fold.changes(peers.root, me, tmp_path / "mine", str(log)) == []


def test_a_rewind_keeps_the_name_the_worktree_and_the_claims(tmp_path: Path) -> None:
    """A rewind is not a departure: only what the conversation said goes."""
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    held = changed(tmp_path / "mine" / "src" / "a.py")
    peers.touched(me, held)
    log = tmp_path / "session.jsonl"
    fold.changes(peers.root, me, tmp_path / "mine", transcript(log, roots=1))

    fold.changes(peers.root, me, tmp_path / "mine", transcript(log, roots=2))

    assert peers.called(me) == "mine"
    assert [claim.path for claim in peers.held()] == [str(held)]
    [mine] = [row for row in peers.listing() if row.member.actor.id == me]
    assert mine.member.worktree == str(tmp_path / "mine")


def test_a_peer_whose_conversation_moved_is_told_as_on_its_task(
    tmp_path: Path,
) -> None:
    """What a discarded conversation said is unsaid until the session speaks again."""
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    other = joined(peers, tmp_path / "theirs", "reviewer")
    peers.describe(other, "reading the merge")
    told(peers, me, tmp_path / "mine")
    log = tmp_path / "theirs.jsonl"
    fold.changes(peers.root, other, tmp_path / "theirs", transcript(log, roots=1))

    fold.changes(peers.root, other, tmp_path / "theirs", transcript(log, roots=2))
    moved = told(peers, me, tmp_path / "mine")
    peers.describe(other, "reading the rebase")
    spoke = told(peers, me, tmp_path / "mine")

    assert moved == [f"reviewer now: working in {tmp_path / 'theirs'}"]
    assert spoke == ["reviewer now: reading the rebase"]


def test_the_envelope_is_the_shape_both_runtimes_read() -> None:
    assert fold.envelope("UserPromptSubmit", ["one", "two"]) == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "one\ntwo",
        }
    }


def test_a_claim_over_a_path_that_went_is_read_as_ended(tmp_path: Path) -> None:
    """The fold asks the filesystem, so a path that went stops being reported.

    Nothing has to agree on a timeout and nothing has to be written: the claim
    carries the modification time it left the path at, and a path that is gone
    answers for itself.
    """
    peers = RepositoryPeers(tmp_path)
    other = joined(peers, tmp_path / "mine", "reviewer")
    held = changed(tmp_path / "mine" / "src" / "a.py")
    peers.touched(other, held)
    assert [claim["path"] for claim in store.held(peers.root, [other])] == [str(held)]

    held.unlink()

    assert store.held(peers.root, [other]) == []


def test_a_claim_somebody_else_has_written_since_stops_standing(
    tmp_path: Path,
) -> None:
    """A claim is evidence of what this session left, not of who may write next."""
    peers = RepositoryPeers(tmp_path)
    other = joined(peers, tmp_path / "mine", "reviewer")
    held = changed(tmp_path / "mine" / "src" / "a.py")
    peers.touched(other, held)

    later = utc_now() + timedelta(seconds=60)
    os.utime(held, (later.timestamp(), later.timestamp()))

    assert store.held(peers.root, [other]) == []
