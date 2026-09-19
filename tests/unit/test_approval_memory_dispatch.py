"""Both compiled dispatchers remember a question answered yes, the same way.

The runtime's prompt exposes its answer to no hook, so each dispatcher reads
it off the two events it does see: PreToolUse asked, PostToolUse ran. Driven
through the generated scripts rather than the modules they are compiled from,
because the script is the only thing a live session runs.
"""

import json
import os
from pathlib import Path

import pytest
import sh

from lup.policy.assets.host import approvals_log
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


def test_codex_remembers_the_same_way(repo: Path) -> None:
    """Asked is a parked question and exit 2; remembered is exit 0."""
    assert codex("PreToolUse", repo).exit_code == 2

    assert codex("PostToolUse", repo).exit_code == 0

    assert codex("PreToolUse", repo).exit_code == 0
