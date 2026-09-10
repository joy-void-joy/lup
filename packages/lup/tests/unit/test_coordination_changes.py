"""The roster's changes reaching a session at each prompt, from inside the plugin.

The fold is a verbatim copy with no import of the code that wrote what it
reads, so what is pinned first is the spellings the two halves agree on. The
rest is written against what a session must and must not be told: nothing on
a quiet roster, a baseline rather than a replay on the first prompt, and the
contested path before everything else — over a store the typed writers
produced, so the copy is read against the record as it is really written.
"""

from pathlib import Path

from lup.coordination import changes as fold
from lup.coordination.identity import (
    MEMBER_KIND,
    NAMES_FILE,
    member_ref,
    mint_member_id,
)
from lup.coordination.repository import RepositoryPeers
from lup.coordination.roster import ROSTER_FILE
from lup.coordination.touches import TOUCHES_FILE


def joined(peers: RepositoryPeers, worktree: Path, name: str) -> str:
    """One session on the roster, named, and the id it answers to."""
    member = mint_member_id()
    peers.join(member, worktree, cli_name=name)
    return member


def told(peers: RepositoryPeers, member: str, worktree: Path) -> list[str]:
    """What one prompt in *worktree* tells *member*."""
    return fold.changes(peers.root, member, worktree)


def test_the_copy_and_its_source_spell_the_store_alike() -> None:
    """What stands in for the import the verbatim copy cannot have."""
    assert fold.ROSTER_FILE == ROSTER_FILE
    assert fold.NAMES_FILE == NAMES_FILE
    assert fold.TOUCHES_FILE == TOUCHES_FILE
    assert fold.MEMBER_KIND == MEMBER_KIND


def test_the_copy_names_its_look_the_way_the_roster_names_the_member() -> None:
    """The look file is `ActorRef.conversation`, derived twice and pinned once."""
    assert f"{fold.MEMBER_KIND}-abc123" == member_ref("abc123").conversation()


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

    peers.touches.touched(member_ref(other), tmp_path / "theirs" / "src" / "a.py")
    elsewhere = told(peers, me, tmp_path / "mine")
    peers.touches.touched(member_ref(other), tmp_path / "mine" / "src" / "a.py")
    here = told(peers, me, tmp_path / "mine")
    peers.lock(other, tmp_path)
    above = told(peers, me, tmp_path / "mine")

    assert elsewhere == []
    assert here == [f"reviewer holding at {tmp_path / 'mine' / 'src' / 'a.py'}"]
    assert above == [f"reviewer holding under {tmp_path}"]


def test_a_contested_path_comes_first_and_is_not_repeated_as_a_holding(
    tmp_path: Path,
) -> None:
    """The line a session about to write needs most is the one it reads first."""
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    told(peers, me, tmp_path / "mine")

    other = joined(peers, tmp_path / "mine", "reviewer")
    shared = tmp_path / "mine" / "src" / "b.py"
    peers.touches.touched(member_ref(other), tmp_path / "mine" / "src" / "a.py")
    peers.touches.contested(member_ref(other), shared, rivals=[member_ref(me)])

    assert told(peers, me, tmp_path / "mine") == [
        f"contested at {shared} — reviewer, mine",
        f"reviewer holding at {tmp_path / 'mine' / 'src' / 'a.py'}",
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
    shared = tmp_path / "mine" / "src" / "b.py"
    peers.touches.contested(member_ref(other), shared, rivals=[member_ref(third)])
    told(peers, me, tmp_path / "mine")

    peers.leave(third)

    assert told(peers, me, tmp_path / "mine") == ["third left"]
    assert told(peers, me, tmp_path / "mine") == []


def test_an_unreadable_look_re_baselines_rather_than_replays(tmp_path: Path) -> None:
    """Of the two ways to be wrong about a look, only one costs a single line."""
    peers = RepositoryPeers(tmp_path)
    me = joined(peers, tmp_path / "mine", "mine")
    joined(peers, tmp_path / "theirs", "reviewer")
    told(peers, me, tmp_path / "mine")
    (peers.root / fold.LOOKS_DIR / f"{MEMBER_KIND}-{me}.json").write_text("not a look")

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
    assert not (peers.root / fold.LOOKS_DIR).exists()


def test_the_envelope_is_the_shape_both_runtimes_read() -> None:
    assert fold.envelope("UserPromptSubmit", ["one", "two"]) == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "one\ntwo",
        }
    }
