"""Real hook order and explicit review of complete document replacements."""

import importlib.util
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import sh

from lup.policy.relay import QuestionRelay
from lup.types import JsonObject


def hook(
    root: Path,
    command: str,
    *,
    tool: str = "apply_patch",
    event: str = "PreToolUse",
    session: str = "requester",
    call_id: str = "call-one",
) -> sh.RunningCommand:
    payload: JsonObject = {
        "session_id": session,
        "turn_id": "turn-one",
        "cwd": str(root),
        "hook_event_name": event,
        "tool_name": tool,
        "tool_input": {"command": command},
    }
    if call_id:
        payload["tool_use_id"] = call_id
    script = Path(".codex/plugins/lup/hooks/scripts/policy.py").resolve()
    result = sh.Command(str(script))(
        _in=json.dumps(payload),
        _ok_code=[0, 2],
        _return_cmd=True,
        _env={**os.environ, "PLUGIN_DATA": str(root / "plugin-data")},
    )
    assert isinstance(result, sh.RunningCommand)
    return result


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text("ref: refs/heads/feature\n")
    (tmp_path / "DESIGN.md").write_text("# Previous design\n")
    return tmp_path


def replacement() -> str:
    return "*** Begin Patch\n*** Add File: DESIGN.md\n+# Agreed design\n+\n+All decisions.\n*** End Patch"


@pytest.mark.parametrize("shell", [False, True])
def test_document_replacement_waits_for_review_then_runs_once(
    root: Path, shell: bool
) -> None:
    command = replacement()
    if shell:
        command = f"# lup: escalate[decision]: replace the agreed design\napply_patch <<'PATCH'\n{command}\nPATCH"
    tool = "Bash" if shell else "apply_patch"
    stopped = hook(root, command, tool=tool)
    assert stopped.exit_code == 2
    assert b"not classified" not in stopped.stderr
    store = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = store.pending()
    assert question.operation.requester == "requester"
    assert question.preconditions == {root / "DESIGN.md": "# Previous design\n"}
    assert question.id.encode() in stopped.stderr
    assert hook(root, command, tool=tool).exit_code == 2
    assert len(store.pending()) == 1
    store.answer(question.id, "operator", True)
    assert hook(root, command, tool=tool).exit_code == 0
    dispatched = store.find(question.id)
    assert dispatched is not None and dispatched.state == "dispatched"
    assert hook(root, command, tool=tool).exit_code == 2


def test_pending_native_prompt_is_never_an_approval(root: Path) -> None:
    response = hook(root, replacement(), event="PermissionRequest")
    assert response.exit_code == 0
    decision = json.loads(response.stdout)["hookSpecificOutput"]["decision"]
    assert decision["behavior"] == "deny"
    (question,) = QuestionRelay(root / ".lup/questions.jsonl").pending()
    assert question.id in decision["message"]
    assert hook(root, replacement()).exit_code == 2


@pytest.mark.parametrize("approved", [False, True])
def test_real_sandbox_escalation_requires_explicit_permission_review(
    root: Path, approved: bool
) -> None:
    command = "# lup: escalate[sandbox]: inspect the host\nls"
    store = QuestionRelay(root / ".lup/questions.jsonl")
    assert hook(root, command, tool="Bash").exit_code == 2
    pending = hook(root, command, tool="Bash", event="PermissionRequest")
    decision = json.loads(pending.stdout)["hookSpecificOutput"]["decision"]
    assert decision["behavior"] == "deny"
    (question,) = store.pending()
    assert question.id in decision["message"]
    store.answer(question.id, "operator", approved)
    assert hook(root, command, tool="Bash").exit_code == (0 if approved else 2)
    retried = hook(root, command, tool="Bash", event="PermissionRequest")
    assert json.loads(retried.stdout)["hookSpecificOutput"]["decision"]["behavior"] == (
        "allow" if approved else "deny"
    )
    replay = hook(root, command, tool="Bash", event="PermissionRequest")
    assert (
        json.loads(replay.stdout)["hookSpecificOutput"]["decision"]["behavior"]
        == "deny"
    )


@pytest.mark.parametrize("approved", [False, True])
def test_host_executor_deferral_reaches_explicit_permission_review(
    root: Path,
    approved: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = Path(".codex/plugins/lup/hooks/scripts/policy.py").resolve()
    spec = importlib.util.spec_from_file_location("codex_permission_policy", path)
    assert spec is not None and spec.loader is not None
    dispatcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dispatcher)
    monkeypatch.setenv("PLUGIN_DATA", str(root / "plugin-data"))
    monkeypatch.setattr(
        dispatcher,
        "bash_decision",
        lambda *_args, **_kwargs: dispatcher.KernelDecision(
            "ask", "Host execution needs review", capability="host_executor"
        ),
    )

    def invoke(event: str) -> str:
        payload = {
            "session_id": "requester",
            "tool_use_id": "host-call",
            "cwd": str(root),
            "hook_event_name": event,
            "tool_name": "Bash",
            "tool_input": {"command": "declared-host-operation"},
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        dispatcher.main()
        return capsys.readouterr().out

    store = QuestionRelay(root / ".lup/questions.jsonl")
    assert invoke("PreToolUse") == ""
    assert store.questions() == []
    pending = json.loads(invoke("PermissionRequest"))["hookSpecificOutput"]
    assert pending["hookEventName"] == "PermissionRequest"
    assert pending["decision"]["behavior"] == "deny"
    (question,) = store.pending()
    assert question.id in pending["decision"]["message"]
    store.answer(question.id, "operator", approved)
    assert invoke("PreToolUse") == ""
    retried = json.loads(invoke("PermissionRequest"))
    assert retried["hookSpecificOutput"]["decision"]["behavior"] == (
        "allow" if approved else "deny"
    )
    replay = json.loads(invoke("PermissionRequest"))
    assert replay["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_one_review_covers_both_events_for_one_identified_invocation(
    root: Path,
) -> None:
    assert hook(root, replacement()).exit_code == 2
    store = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = store.pending()
    store.answer(question.id, "operator", True)
    assert hook(root, replacement()).exit_code == 0
    response = hook(root, replacement(), event="PermissionRequest")
    assert response.exit_code == 0
    assert json.loads(response.stdout) == {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"},
        }
    }
    assert len(store.questions()) == 1
    replay = hook(root, replacement(), event="PermissionRequest")
    assert (
        json.loads(replay.stdout)["hookSpecificOutput"]["decision"]["behavior"]
        == "deny"
    )
    assert hook(root, replacement()).exit_code == 2


@pytest.mark.parametrize("preapproved", [False, True])
def test_concurrent_permission_events_cannot_spend_an_answer_twice(
    root: Path, preapproved: bool
) -> None:
    hook(root, replacement())
    store = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = store.pending()
    store.answer(question.id, "operator", True)
    if preapproved:
        assert hook(root, replacement()).exit_code == 0
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(
            workers.map(
                lambda _: hook(root, replacement(), event="PermissionRequest"),
                range(2),
            )
        )
    assert sorted(
        json.loads(response.stdout)["hookSpecificOutput"]["decision"]["behavior"]
        for response in responses
    ) == ["allow", "deny"]


@pytest.mark.parametrize(
    "change", ["missing-id", "id", "preimage", "payload", "session"]
)
def test_event_handoff_requires_the_same_identified_exact_operation(
    root: Path, change: str
) -> None:
    hook(root, replacement())
    store = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = store.pending()
    store.answer(question.id, "operator", True)
    assert hook(root, replacement()).exit_code == 0
    command = replacement()
    session = "requester"
    call_id = "call-one"
    if change == "missing-id":
        call_id = ""
    if change == "id":
        call_id = "call-two"
    if change == "preimage":
        (root / "DESIGN.md").write_text("# Another writer's design\n")
    if change == "payload":
        command = command.replace("All decisions.", "Different decisions.")
    if change == "session":
        session = "another-requester"
    response = hook(
        root, command, event="PermissionRequest", session=session, call_id=call_id
    )
    assert (
        json.loads(response.stdout)["hookSpecificOutput"]["decision"]["behavior"]
        == "deny"
    )


@pytest.mark.parametrize("damage", ["missing", "incomplete"])
def test_event_handoff_never_infers_a_missing_or_corrupt_primary_claim(
    root: Path, damage: str
) -> None:
    hook(root, replacement())
    store = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = store.pending()
    store.answer(question.id, "operator", True)
    assert hook(root, replacement()).exit_code == 0
    claim = root / ".lup/review-claims" / question.id
    if damage == "missing":
        claim.unlink()
    else:
        claim.write_text('{"fingerprint":')
    response = hook(root, replacement(), event="PermissionRequest")
    decision = json.loads(response.stdout)["hookSpecificOutput"]["decision"]
    assert decision["behavior"] == "deny"
    assert "Malformed hook input" in decision["message"]


def test_rejection_does_not_create_another_question(root: Path) -> None:
    hook(root, replacement())
    store = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = store.pending()
    store.answer(question.id, "operator", False)
    refused = hook(root, replacement())
    assert refused.exit_code == 2
    assert b"rejected" in refused.stderr
    assert len(store.questions()) == 1


@pytest.mark.parametrize("change", ["preimage", "payload", "session"])
def test_approval_does_not_follow_a_changed_operation(root: Path, change: str) -> None:
    hook(root, replacement())
    store = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = store.pending()
    store.answer(question.id, "operator", True)
    command = replacement()
    session = "requester"
    if change == "preimage":
        (root / "DESIGN.md").write_text("# Another writer's design\n")
    if change == "payload":
        command = command.replace("All decisions.", "Different decisions.")
    if change == "session":
        session = "another-requester"
    assert hook(root, command, session=session).exit_code == 2
    approved = store.find(question.id)
    assert approved is not None and approved.state == "approved"


def test_requester_cannot_answer_its_own_question(root: Path) -> None:
    hook(root, replacement())
    store = QuestionRelay(root / ".lup/questions.jsonl")
    (question,) = store.pending()
    with pytest.raises(ValueError, match="may not answer"):
        store.answer(question.id, "requester", True)
    for prefix in ("", "# lup: escalate[decision]: user agreed\n"):
        refused = hook(
            root,
            prefix
            + f"uv run lup-devtools dev questions answer {question.id} --as operator",
            tool="Bash",
        )
        assert refused.exit_code == 2
        assert b"cannot approve" in refused.stderr


def test_malformed_patch_and_marker_deletion_are_not_queued(root: Path) -> None:
    assert hook(root, "not a patch").exit_code == 2
    (root / "DESIGN.md").write_text("# lup: preserve this decision\n")
    assert hook(root, replacement()).exit_code == 2
    assert not QuestionRelay(root / ".lup/questions.jsonl").pending()


def test_relative_patch_uses_payload_cwd_not_hook_process_cwd(root: Path) -> None:
    command = "*** Begin Patch\n*** Update File: DESIGN.md\n@@\n-# Previous design\n+# Revised design\n*** End Patch"
    assert hook(root, command).exit_code == 0


@pytest.mark.parametrize("suffix", ["\necho extra", "\nrm -rf /", " &"])
def test_shell_patch_recognition_never_hides_other_commands(
    root: Path, suffix: str
) -> None:
    command = f"apply_patch <<'PATCH'\n{replacement()}\nPATCH{suffix}"
    assert hook(root, command, tool="Bash").exit_code == 2


def test_unquoted_shell_patch_is_not_interpreted_as_literal(root: Path) -> None:
    command = f"apply_patch <<PATCH\n{replacement()}\nPATCH"
    assert hook(root, command, tool="Bash").exit_code == 2
