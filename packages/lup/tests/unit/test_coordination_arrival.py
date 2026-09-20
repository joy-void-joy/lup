"""Native root identity binds only the launcher member that owns the worktree."""

from pathlib import Path

import pytest

from lup.coordination.bare.arrival import Arrival, bind
from lup.coordination.bare.store import depart, session_actor, member_of
from lup.coordination.identity import mint_member_id
from lup.coordination.repository import RepositoryPeers


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit"])
def test_hook_binds_native_thread_and_rejoining_preserves_it(
    tmp_path: Path, event: str
) -> None:
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    peers.join(member, tmp_path, cli_name="root")
    arrival = Arrival(
        session_id="native-root", cwd=str(tmp_path), hook_event_name=event
    )
    assert bind(peers.root, member, "codex", arrival)
    peers.join(member, tmp_path, cli_name="root")
    found = member_of(peers.root, session_actor(member))
    assert found is not None
    assert found.get("wake") == {
        "runtime": "codex",
        "handle": "native-root",
        "session": "native-root",
    }


@pytest.mark.parametrize(
    "override",
    [
        Arrival(agent_id="child"),
        Arrival(agent_type="reviewer"),
        Arrival(hook_event_name="SubagentStart"),
        Arrival(cwd="/somewhere/else"),
        Arrival(session_id=""),
    ],
)
def test_child_or_foreign_hook_cannot_replace_parent_wake(
    tmp_path: Path, override: Arrival
) -> None:
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    peers.join(member, tmp_path, cli_name="root")
    arrival = Arrival(
        session_id="native-root", cwd=str(tmp_path), hook_event_name="SessionStart"
    )
    assert bind(peers.root, member, "codex", arrival)
    child: Arrival = {**arrival, "session_id": "native-child", **override}
    assert not bind(peers.root, member, "codex", child)
    found = member_of(peers.root, session_actor(member))
    assert found is not None
    assert found.get("wake", {}).get("handle") == "native-root"


def test_arrival_does_not_create_or_resurrect_a_member(tmp_path: Path) -> None:
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    arrival = Arrival(
        session_id="native-root", cwd=str(tmp_path), hook_event_name="SessionStart"
    )
    assert not bind(peers.root, member, "codex", arrival)
    peers.join(member, tmp_path, cli_name="root")
    assert bind(peers.root, member, "codex", arrival)
    assert depart(peers.root, session_actor(member))
    assert not bind(peers.root, member, "codex", arrival)


def test_arrival_rejects_member_path_traversal(tmp_path: Path) -> None:
    arrival = Arrival(
        session_id="native-root", cwd=str(tmp_path), hook_event_name="SessionStart"
    )
    assert not bind(tmp_path, "../parent", "codex", arrival)
    assert list(tmp_path.iterdir()) == []
