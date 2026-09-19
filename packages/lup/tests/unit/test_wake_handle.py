"""What a session declares it can be woken by, and which half decides it.

The failure this is written against is a wake path that reads as present and
reaches nobody. A handle is a name a *peer's* tool resolves, so the only half
that can say whether one exists is the adapter for the runtime that resolves
it -- and for most of this repository's history nothing said anything, because
no writer took a wake at all and every member carried the empty default.
"""

from pathlib import Path

from lup.coordination.identity import mint_member_id
from lup.coordination.repository import RepositoryPeers
from lup.coordination.wake import WakePath, wake
from lup.providers.identity import native_wake


def test_a_launched_claude_session_is_woken_by_the_name_the_launch_gave_it() -> None:
    """`--name` sets what a listing reports and what a send resolves.

    So the handle is the name the session already answers to everywhere else,
    rather than either session id -- neither of which any peer can address.
    """
    declared = native_wake("claude", "dev-6")

    assert declared == WakePath(runtime="claude", handle="dev-6")


def test_a_claude_session_nobody_launched_declares_nothing() -> None:
    """Its addressable name is one only the session itself can read.

    Blank rather than a guess: a handle that resolves to nobody costs a
    sender the belief that a peer was nudged, which is worse than being told
    plainly that none will be.
    """
    assert native_wake("claude", "") == WakePath()


def test_codex_declares_nothing_even_though_its_verb_exists() -> None:
    """The half Codex has is the transport, and the half it lacks is the handle.

    `codex queue` reaches a session from any process, which is the half Claude
    Code lacks -- but it takes a thread id or session name, and the launch has
    no flag that names a session, so the roster's name would name a thread
    that does not exist.
    """
    assert native_wake("codex", "dev-6") == WakePath()


def test_a_runtime_nobody_declared_is_not_guessed_at() -> None:
    assert native_wake("something-else", "dev-6") == WakePath()


def test_a_declared_handle_reaches_the_roster_and_survives_the_fold(
    tmp_path: Path,
) -> None:
    """The property the whole change exists for.

    Every writer before this one dropped the wake on the floor: `join` took no
    such argument, so `roster.joined` got the model's empty default and every
    row in the store's history read `{runtime: '', handle: ''}` no matter what
    the session could actually be reached by.
    """
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()

    peers.join(
        member,
        tmp_path / "tree",
        cli_name="dev-6",
        wake=native_wake("claude", "dev-6"),
    )
    standing = [row for row in peers.present() if row.actor.id == member]

    assert [row.wake for row in standing] == [
        WakePath(runtime="claude", handle="dev-6")
    ]


def test_the_roster_row_is_what_hands_a_caller_the_instruction(
    tmp_path: Path,
) -> None:
    """End to end, because the two halves were each correct and never met.

    `wake()` has always known how to answer for a Claude member and never had
    one to answer for. This reads the path back off the roster the way a
    sender does and checks the instruction names the handle, rather than
    checking the two in isolation and assuming the join carried it.
    """
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    peers.join(
        member,
        tmp_path / "tree",
        cli_name="dev-6",
        wake=native_wake("claude", "dev-6"),
    )

    roused = wake(next(row.wake for row in peers.present()), "look at your inbox")

    assert not roused.reached
    assert "dev-6" in roused.instruction
    assert not roused.reason
