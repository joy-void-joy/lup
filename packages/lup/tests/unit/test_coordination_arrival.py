"""Native root identity binds only the launcher member that owns the worktree."""

from pathlib import Path
import io
import sys

import pytest

from lup.coordination.bare.arrival import Arrival, bind, main
from lup.coordination.bare.scope import execution_scope
from lup.coordination.bare.store import depart, session_actor, member_of
from lup.coordination.identity import mint_member_id
from lup.coordination.repository import RepositoryPeers


ARRIVAL_EVENTS = ("SessionStart", "UserPromptSubmit")


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
    assert bind(peers.root, member, "codex", arrival, ARRIVAL_EVENTS, "/native-home")
    peers.join(member, tmp_path, cli_name="root")
    found = member_of(peers.root, session_actor(member))
    assert found is not None
    assert found.get("wake") == {
        "runtime": "codex",
        "handle": "native-root",
        "session": "native-root",
        "home": "/native-home",
        "scope": execution_scope(),
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
    assert bind(peers.root, member, "codex", arrival, ARRIVAL_EVENTS)
    child: Arrival = {**arrival, "session_id": "native-child", **override}
    assert not bind(peers.root, member, "codex", child, ARRIVAL_EVENTS)
    found = member_of(peers.root, session_actor(member))
    assert found is not None
    assert found.get("wake", {}).get("handle") == "native-root"


def test_arrival_does_not_create_or_resurrect_a_member(tmp_path: Path) -> None:
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    arrival = Arrival(
        session_id="native-root", cwd=str(tmp_path), hook_event_name="SessionStart"
    )
    assert not bind(peers.root, member, "codex", arrival, ARRIVAL_EVENTS)
    peers.join(member, tmp_path, cli_name="root")
    assert bind(peers.root, member, "codex", arrival, ARRIVAL_EVENTS)
    assert depart(peers.root, session_actor(member))
    assert not bind(peers.root, member, "codex", arrival, ARRIVAL_EVENTS)


def test_arrival_rejects_member_path_traversal(tmp_path: Path) -> None:
    arrival = Arrival(
        session_id="native-root", cwd=str(tmp_path), hook_event_name="SessionStart"
    )
    assert not bind(tmp_path, "../parent", "codex", arrival, ARRIVAL_EVENTS)
    assert list(tmp_path.iterdir()) == []


def test_unexpected_hook_failure_is_visible_without_echoing_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["arrival", str(tmp_path), "member", "codex"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("malformed secret payload"))
    main()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Native session wake binding failed (JSONDecodeError)" in captured.err
    assert "secret" not in captured.err


@pytest.mark.parametrize("events", [(), ("OtherArrival",), ("",)])
def test_native_event_is_refused_unless_the_adapter_declared_it(
    tmp_path: Path, events: tuple[str, ...]
) -> None:
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    peers.join(member, tmp_path, cli_name="root")
    arrival = Arrival(
        session_id="native-root", cwd=str(tmp_path), hook_event_name="SessionStart"
    )
    assert not bind(peers.root, member, "codex", arrival, events)


def test_adapter_can_declare_its_own_arrival_event(tmp_path: Path) -> None:
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    peers.join(member, tmp_path, cli_name="root")
    arrival = Arrival(
        session_id="native-root", cwd=str(tmp_path), hook_event_name="RootReady"
    )
    assert bind(peers.root, member, "custom-runtime", arrival, ("RootReady",))


def test_missing_event_cannot_match_an_empty_declaration(tmp_path: Path) -> None:
    assert not bind(tmp_path, "member", "runtime", Arrival(), ("",))
