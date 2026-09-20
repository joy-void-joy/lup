"""The rendered native hook delivers mail without granting tool permission."""

import json
import os
from pathlib import Path

import pytest
import sh

from lup.coordination.identity import MEMBER_ENV, member_ref
from lup.coordination.repository import RepositoryPeers
from lup.providers.peer_delivery import GUARD_SCRIPT, RUNTIME_MODULE
from lup.types import JsonObject
from lup_template.harness.composition import claude_target, codex_target
from tests.unit.test_roster_prompt_hook import laid_out, rendered, shipped


def test_malformed_native_input_is_diagnosed_without_consuming(
    native_delivery: tuple[Path, Path, RepositoryPeers],
) -> None:
    guard, repository, peers = native_delivery
    peers.cohort.mail.send(member_ref("abc123"), "still waiting")
    errors: list[str] = []
    output = str(
        sh.sh(
            str(guard),
            _in="{invalid-sensitive-input",
            _cwd=str(repository),
            _env={**os.environ, MEMBER_ENV: "abc123"},
            _err=errors.append,
        )
    )
    assert output == ""
    assert "Peer mail delivery failed" in "".join(errors)
    assert "sensitive-input" not in "".join(errors)
    assert len(peers.cohort.mail.waiting(member_ref("abc123")).messages) == 1


@pytest.fixture(params=["claude", "codex"])
def native_delivery(
    request: pytest.FixtureRequest, tmp_path: Path
) -> tuple[Path, Path, RepositoryPeers]:
    target = claude_target if request.param == "claude" else codex_target
    artifacts = shipped(target)
    plugin = rendered(f".{request.param}")
    hooks = json.loads(artifacts[plugin / "hooks/hooks.json"].content)["hooks"]
    [group] = [
        group
        for group in hooks["PreToolUse"]
        if any(GUARD_SCRIPT in hook["command"] for hook in group["hooks"])
    ]
    assert group["matcher"] == ""
    assert all(
        GUARD_SCRIPT not in hook["command"]
        for group in hooks["PostToolUse"]
        for hook in group["hooks"]
    )
    guard = laid_out(
        artifacts, plugin, tmp_path / "plugin", GUARD_SCRIPT, RUNTIME_MODULE
    )
    repository = tmp_path / "repository"
    repository.mkdir()
    sh.git("init", "-q", str(repository))
    peers = RepositoryPeers(repository)
    peers.join("abc123", repository, cli_name="receiver")
    return guard, repository, peers


def invoke(guard: Path, repository: Path, extra: JsonObject | None = None) -> str:
    payload: JsonObject = {
        "hook_event_name": "PreToolUse",
        "session_id": "native-root",
        "cwd": str(repository),
        "tool_name": "mcp__store__read",
        "tool_input": {},
        **(extra or {}),
    }
    return str(
        sh.sh(
            str(guard),
            _in=json.dumps(payload),
            _cwd=str(repository),
            _env={**os.environ, MEMBER_ENV: "abc123"},
        )
    )


def test_native_guard_delivers_typed_mail_once_without_authorizing(
    native_delivery: tuple[Path, Path, RepositoryPeers],
) -> None:
    guard, repository, peers = native_delivery
    peers.cohort.mail.send(member_ref("abc123"), "review the complete result")
    result = json.loads(invoke(guard, repository))["hookSpecificOutput"]
    assert result["hookEventName"] == "PreToolUse"
    assert "review the complete result" in result["additionalContext"]
    assert "permissionDecision" not in result
    assert peers.cohort.mail.waiting(member_ref("abc123")).messages == []
    assert invoke(guard, repository) == ""


def test_redirect_also_carries_context_when_another_hook_denies(
    native_delivery: tuple[Path, Path, RepositoryPeers],
) -> None:
    guard, repository, peers = native_delivery
    peers.cohort.mail.send(
        member_ref("abc123"), "switch to the repaired branch", redirect=True
    )
    result = json.loads(invoke(guard, repository))["hookSpecificOutput"]
    assert result["permissionDecision"] == "deny"
    assert "switch to the repaired branch" in result["permissionDecisionReason"]
    assert "switch to the repaired branch" in result["additionalContext"]
    assert peers.cohort.mail.waiting(member_ref("abc123")).messages == []


@pytest.mark.parametrize(
    "extra",
    [
        {"agent_id": "child"},
        {"agent_type": "reviewer"},
        {"hook_event_name": "PermissionRequest"},
        {"session_id": ""},
    ],
)
def test_unrelated_or_child_events_leave_root_mail_pending(
    native_delivery: tuple[Path, Path, RepositoryPeers],
    extra: JsonObject,
) -> None:
    guard, repository, peers = native_delivery
    peers.cohort.mail.send(member_ref("abc123"), "root only")
    assert invoke(guard, repository, extra) == ""
    assert len(peers.cohort.mail.waiting(member_ref("abc123")).messages) == 1


def test_native_stdout_failure_leaves_mail_pending(
    native_delivery: tuple[Path, Path, RepositoryPeers],
) -> None:
    guard, repository, peers = native_delivery
    peers.cohort.mail.send(member_ref("abc123"), "retry after transport repair")
    errors: list[str] = []
    with Path("/dev/full").open("w") as output:
        sh.sh(
            str(guard),
            _in=json.dumps(
                {"hook_event_name": "PreToolUse", "session_id": "native-root"}
            ),
            _cwd=str(repository),
            _env={**os.environ, MEMBER_ENV: "abc123"},
            _out=output,
            _err=errors.append,
            _ok_code=[0, 120],
        )
    assert len(peers.cohort.mail.waiting(member_ref("abc123")).messages) == 1
    assert "Peer mail delivery failed" in "".join(errors)
