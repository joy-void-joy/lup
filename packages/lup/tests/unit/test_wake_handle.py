"""What a session declares it can be woken by, and which half decides it.

The failure this is written against is a wake path that reads as present and
reaches nobody. What a handle even is differs by runtime -- a thread a
command names, or a socket on this filesystem -- so the only half that can
say whether one exists is the adapter for that runtime. For most of this
repository's history nothing said anything, because no writer took a wake at
all and every member carried the empty default.
"""

import json
import socket
from pathlib import Path
from threading import Thread

import pytest

from lup.coordination.identity import mint_member_id
from lup.coordination.repository import RepositoryPeers
from lup.coordination.wake import WakePath, wake
from lup.providers.identity import native_wake


def test_a_claude_session_declares_the_inbox_its_runtime_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runtime tells a session's own processes where that session listens.

    So the handle is read rather than derived: the session bound the socket
    and the launcher only asked where, which makes a path computed here a
    second opinion about a file exactly one process created.
    """
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "/tmp/cc-socks/91.sock")

    declared = native_wake("claude", "dev-6")

    assert declared == WakePath(runtime="claude", handle="/tmp/cc-socks/91.sock")


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property the whole change exists for.

    Every writer before this one dropped the wake on the floor: `join` took no
    such argument, so `roster.joined` got the model's empty default and every
    row in the store's history read `{runtime: '', handle: ''}` no matter what
    the session could actually be reached by.
    """
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()

    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", str(tmp_path / "in.sock"))
    peers.join(
        member,
        tmp_path / "tree",
        cli_name="dev-6",
        wake=native_wake("claude", "dev-6"),
    )
    standing = [row for row in peers.present() if row.actor.id == member]

    assert [row.wake for row in standing] == [
        WakePath(runtime="claude", handle=str(tmp_path / "in.sock"))
    ]


def test_the_roster_row_is_what_actually_wakes_the_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end, because the two halves were each correct and never met.

    `wake()` has always known how to answer for a Claude member and never had
    one to answer for. This reads the path back off the roster the way a
    sender does and checks a frame reaches the socket, rather than checking
    the two in isolation and assuming the join carried it.
    """
    inbox = tmp_path / "in.sock"
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", str(inbox))
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    peers.join(
        member,
        tmp_path / "tree",
        cli_name="dev-6",
        wake=native_wake("claude", "dev-6"),
    )

    delivered: list[bytes] = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(inbox))
        listener.listen(1)

        def take_one_frame() -> None:
            connection, _ = listener.accept()
            with connection:
                delivered.append(connection.recv(4096))

        waiting = Thread(target=take_one_frame)
        waiting.start()
        roused = wake(next(row.wake for row in peers.present()), "look at your inbox")
        waiting.join(timeout=5)

    assert roused.reached
    assert not roused.reason
    assert json.loads(delivered[0])["message"]["content"] == "look at your inbox"
