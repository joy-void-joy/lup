"""Native approval memory preserves each runtime's authorization boundaries."""

import json
import os
from pathlib import Path

import pytest
import sh

from lup.policy.assets.host import (
    approvals_log,
    approval_fingerprint,
    note_asked,
    note_ran,
)
from tests.unit.repos import commit_file, initialized_repo

CLAUDE = Path(".claude/plugins/lup/hooks/scripts/policy.py")
CODEX = Path(".codex/plugins/lup/hooks/scripts/policy.py")
COMMAND = "git push --delete origin topic"
"""A command the offered vocabulary asks about wherever it runs."""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "file.txt", "base\n", "chore: base")
    return work


def payload(event: str, root: Path, command: str) -> str:
    return json.dumps(
        {
            "hook_event_name": event,
            "session_id": "requester",
            "turn_id": "turn-one",
            "cwd": str(root),
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )


# lup: ignore[dict-str-payload]
def claude(event: str, root: Path, command: str = COMMAND) -> dict[str, object]:
    """Run the Claude dispatcher over one event, returning what it answered."""
    answered = str(
        sh.Command("python3")(
            "-I", "-S", str(CLAUDE), _in=payload(event, root, command)
        )
    )
    return json.loads(answered)


def codex(event: str, root: Path, command: str = COMMAND) -> sh.RunningCommand:
    """Run the Codex dispatcher over one event, returning the finished command."""
    result = sh.Command(str(CODEX.resolve()))(
        _in=payload(event, root, command),
        _ok_code=[0, 2],
        _return_cmd=True,
        _env={**os.environ, "PLUGIN_DATA": str(root / "plugin-data")},
    )
    assert isinstance(result, sh.RunningCommand)
    return result


# lup: ignore[dict-str-payload]
def decision(answered: dict[str, object]) -> dict[str, object]:
    specific = answered["hookSpecificOutput"]
    assert isinstance(specific, dict)
    return specific


def test_claude_remembers_a_question_answered_yes(repo: Path) -> None:
    assert decision(claude("PreToolUse", repo))["permissionDecision"] == "ask"

    assert claude("PostToolUse", repo) == {}

    again = decision(claude("PreToolUse", repo))
    assert again["permissionDecision"] == "allow"
    assert str(again["permissionDecisionReason"]).startswith("approved ")


def test_a_call_that_ran_without_asking_leaves_no_memory(repo: Path) -> None:
    assert decision(claude("PreToolUse", repo, "git status"))["permissionDecision"] == (
        "allow"
    )
    claude("PostToolUse", repo, "git status")

    assert not approvals_log(repo).exists()


def test_a_call_changed_on_the_way_through_approves_nothing(repo: Path) -> None:
    """The memory is keyed on what ran, not on what was judged."""
    assert decision(claude("PreToolUse", repo))["permissionDecision"] == "ask"
    claude("PostToolUse", repo, f"{COMMAND} --dry-run")

    assert decision(claude("PreToolUse", repo))["permissionDecision"] == "ask"


def test_codex_never_turns_a_queue_retry_into_persistent_approval(repo: Path) -> None:
    refused = codex("PreToolUse", repo)
    assert (
        json.loads(refused.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    )

    assert codex("PostToolUse", repo).exit_code == 0

    again = codex("PreToolUse", repo)
    assert (
        json.loads(again.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    )
    assert not approvals_log(repo).exists()


def test_codex_does_not_consume_legacy_approval_memory(repo: Path) -> None:
    fingerprint = approval_fingerprint("shell", COMMAND, repo)
    note_asked(repo, fingerprint, "shell", COMMAND)
    note_ran(repo, fingerprint)
    refused = codex("PreToolUse", repo)
    assert (
        json.loads(refused.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    )


@pytest.mark.parametrize(
    "command",
    [
        "cp proposal.md DESIGN.md",
        "printf 'new\\n' > DESIGN.md",
        "sed -i 's/old/new/' DESIGN.md",
    ],
)
def test_claude_never_reuses_approval_memory_for_file_writes(
    repo: Path, command: str
) -> None:
    before = "# lup: old\n" if command.startswith("sed ") else "old\n"
    command = f"# lup: escalate[decision]: review this file write\n{command}"
    (repo / "DESIGN.md").write_text(before)
    (repo / "proposal.md").write_text("new\n")
    assert decision(claude("PreToolUse", repo, command))["permissionDecision"] == "ask"
    fingerprint = approval_fingerprint("shell", command, repo)
    note_asked(repo, fingerprint, "shell", command)
    note_ran(repo, fingerprint)
    refused = decision(claude("PreToolUse", repo, command))
    assert refused["permissionDecision"] in ("ask", "deny")
    assert not str(refused["permissionDecisionReason"]).startswith("approved ")
