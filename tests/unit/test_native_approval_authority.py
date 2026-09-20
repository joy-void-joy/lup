"""Native execution never turns an ask or a single-use answer into a grant."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import pytest
import sh

from lup.policy.assets.host import approval_fingerprint, approvals_log
from lup.policy.relay import QuestionRelay, ReceiptKind
from lup.types import JsonObject


def native_call(
    root: Path,
    runtime: str,
    event: str = "PreToolUse",
    *,
    tool: str = "Bash",
    arguments: JsonObject | None = None,
) -> str:
    payload: JsonObject = {
        "session_id": "requester",
        "cwd": str(root),
        "hook_event_name": event,
        "tool_name": tool,
        "tool_input": arguments
        if arguments is not None
        else {
            "command": "git push origin --delete probe-compound probe-excluded-prefix 2>&1 | tail -5"
        },
    }
    script = Path(f".{runtime}/plugins/lup/hooks/scripts/policy.py").resolve()
    result = sh.Command(str(script))(
        _in=json.dumps(payload),
        _ok_code=[0, 2],
        _return_cmd=True,
        _env={
            **os.environ,
            "PLUGIN_DATA": str(root / "plugin-data"),
            "CLAUDE_PLUGIN_DATA": str(root / "plugin-data"),
        },
    )
    assert isinstance(result, sh.RunningCommand)
    if event == "PostToolUse":
        return "observed"
    if runtime == "codex":
        return "deny" if result.exit_code == 2 else "allow"
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text("ref: refs/heads/feature\n")
    return tmp_path


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_unexpected_execution_never_authorizes_retry(root: Path, runtime: str) -> None:
    before = native_call(root, runtime)
    assert before in ("ask", "deny")
    native_call(root, runtime, "PostToolUse")
    (question,) = QuestionRelay(root / ".lup/questions.jsonl").questions()
    assert question.state == "in_doubt"
    assert "without a consumed approval receipt" in question.outcome
    assert native_call(root, runtime) == before


@pytest.mark.parametrize("runtime", ["claude", "codex"])
@pytest.mark.parametrize("state", ["approved", "observed"])
def test_unproven_legacy_record_never_authorizes(
    root: Path, runtime: str, state: Literal["approved", "observed"]
) -> None:
    command = (
        "git push origin --delete probe-compound probe-excluded-prefix 2>&1 | tail -5"
    )
    path = approvals_log(root)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "fingerprint": approval_fingerprint("shell", command, root),
                "state": state,
                "kind": "shell",
                "subject": command,
                "cwd": str(root),
                "at": "2026-09-20T00:00:00+00:00",
            }
        )
        + "\n"
    )
    assert native_call(root, runtime) in ("ask", "deny")


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_exact_answer_cannot_be_reused_after_execution(
    root: Path, runtime: str
) -> None:
    assert native_call(root, runtime) == "deny"
    relay = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = relay.pending()
    relay.answer(question.id, "operator", True)
    assert native_call(root, runtime) == "allow"
    native_call(root, runtime, "PostToolUse")
    completed = relay.find(question.id)
    assert completed is not None and completed.state == "completed"
    assert native_call(root, runtime) == "deny"


def test_claude_document_review_is_bound_to_the_preimage(root: Path) -> None:
    path = root / "README.md"
    path.write_text("Original document.\n")
    arguments: JsonObject = {"file_path": str(path), "content": "Replacement.\n"}
    assert native_call(root, "claude", tool="Write", arguments=arguments) == "deny"
    relay = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = relay.pending()
    assert question.preconditions == {path: "Original document.\n"}
    relay.answer(question.id, "operator", True)
    path.write_text("Another writer's document.\n")
    assert native_call(root, "claude", tool="Write", arguments=arguments) == "deny"
    assert len(relay.questions()) == 2


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_simultaneous_native_retries_consume_only_one_answer(
    root: Path, runtime: str
) -> None:
    assert native_call(root, runtime) == "deny"
    relay = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = relay.pending()
    relay.answer(question.id, "operator", True)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: native_call(root, runtime), range(2)))
    assert sorted(results) == ["allow", "deny"]


@pytest.mark.parametrize("runtime", ["claude", "codex"])
@pytest.mark.parametrize("receipt", ["observed", "inferred"])
def test_unrecorded_answer_does_not_release_a_native_retry(
    root: Path, runtime: str, receipt: ReceiptKind
) -> None:
    assert native_call(root, runtime) == "deny"
    relay = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = relay.pending()
    relay.answer(question.id, "operator", True, receipt=receipt)
    assert native_call(root, runtime) == "deny"
