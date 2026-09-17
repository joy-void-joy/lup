"""Real hook order and explicit review of complete document replacements."""

import json
import os
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
) -> sh.RunningCommand:
    payload: JsonObject = {
        "session_id": session,
        "turn_id": "turn-one",
        "cwd": str(root),
        "hook_event_name": event,
        "tool_name": tool,
        "tool_input": {"command": command},
    }
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
    assert hook(root, replacement(), event="PermissionRequest").exit_code == 0
    assert hook(root, replacement()).exit_code == 2


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
