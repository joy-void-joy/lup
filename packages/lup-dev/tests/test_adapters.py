"""Each runtime's payloads in, its outputs out."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.adapters import claude, codex
from lup_dev.codescan.contract import Checker, FileReport, Source
from lup_dev.policy.checkpoint import Bench, Running, Services
from lup_dev.policy.holds import Holds, Response, waiting
from lup_dev.policy.store import read_model

if TYPE_CHECKING:
    from conftest import Kit

CORE = Path("src/pkg/core.py")


def payload(repo: Path, event: str, **fields: object) -> str:
    return json.dumps(
        {"session_id": "s1", "cwd": str(repo), "hook_event_name": event, **fields}
    )


def running(kit: Kit, repo: Path) -> list[str]:
    calls = read_model(kit.layout.store(repo).calls, Running)
    return [] if calls is None else [call.key for call in calls.calls]


@pytest.fixture
def on_claude(kit: Kit) -> Bench:
    return Bench(runtime=claude.Claude(), services=kit.bench.services)


@pytest.fixture
def on_codex(kit: Kit) -> Bench:
    return Bench(runtime=codex.Codex(), services=kit.bench.services)


def test_claude_session_start_prints_nothing(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    assert claude.hook(payload(repo, "SessionStart", source="startup"), on_claude) == ""
    assert kit.layout.store(repo).snapshots.is_dir()


def pre_tool_use(
    repo: Path, tool: str, tool_input: dict[str, object], call: str = "t1"
) -> str:
    return payload(
        repo, "PreToolUse", tool_name=tool, tool_input=tool_input, tool_use_id=call
    )


def test_claude_asks_before_a_new_production_file(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    raw = pre_tool_use(
        repo,
        "Write",
        {"file_path": str(repo / "src/pkg/new.py"), "content": '"""New."""\n'},
    )
    output = json.loads(claude.hook(raw, on_claude))
    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": (
                "lup asks: src/pkg/new.py is a new production file"
            ),
        }
    }
    assert running(kit, repo) == ["t1"]


def test_claude_refuses_an_edit_with_a_finding_before_it_lands(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    raw = pre_tool_use(
        repo,
        "Edit",
        {
            "file_path": str(repo / CORE),
            "old_string": "return x\n",
            "new_string": "return x  # BAD regex\n",
        },
    )
    output = json.loads(claude.hook(raw, on_claude))["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert output["permissionDecisionReason"].startswith("lup refused 1 file.")
    assert running(kit, repo) == []


def test_claude_allows_a_docs_write_and_relative_paths(
    on_claude: Bench, repo: Path
) -> None:
    raw = pre_tool_use(
        repo, "Write", {"file_path": "docs/new.md", "content": "# New\n"}
    )
    output = json.loads(claude.hook(raw, on_claude))
    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }


def test_claude_leaves_other_tools_to_its_own_permission_mode(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    assert claude.hook(pre_tool_use(repo, "Bash", {"command": "ls"}), on_claude) == ""
    assert running(kit, repo) == ["t1"]


def test_claude_doesnt_count_a_subagents_call(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    assert claude.hook(pre_tool_use(repo, "Agent", {"prompt": "go"}), on_claude) == ""
    assert running(kit, repo) == []


@pytest.mark.parametrize("event", ["PostToolUse", "PostToolUseFailure"])
def test_claude_hears_a_checkpoint_beside_the_result(
    on_claude: Bench, repo: Path, event: str
) -> None:
    claude.hook(pre_tool_use(repo, "Bash", {"command": "sed"}), on_claude)
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    raw = payload(
        repo,
        event,
        tool_name="Bash",
        tool_input={"command": "sed"},
        tool_use_id="t1",
        tool_response={},
    )
    output = json.loads(claude.hook(raw, on_claude))["hookSpecificOutput"]
    assert output["hookEventName"] == event
    assert output["additionalContext"].startswith("lup refused 1 file.")


def test_claude_stop_blocks_while_touched_files_have_type_errors(
    on_claude: Bench, repo: Path
) -> None:
    claude.hook(pre_tool_use(repo, "Bash", {"command": "sed"}), on_claude)
    (repo / CORE).write_text((repo / CORE).read_text() + "y: int = 'a'  # TYPE\n")
    claude.hook(
        payload(repo, "PostToolUse", tool_name="Bash", tool_use_id="t1"), on_claude
    )
    output = json.loads(
        claude.hook(payload(repo, "Stop", stop_hook_active=False), on_claude)
    )
    assert output["decision"] == "block"
    assert output["reason"].startswith("lup won't end the turn yet")


def test_claude_subagent_stop(on_claude: Bench, repo: Path) -> None:
    assert claude.hook(payload(repo, "SubagentStop", agent_id="sub"), on_claude) == ""


class Broken(Checker):
    def check(self, root: Path, sources: list[Source]) -> list[FileReport]:
        crashed = "the engine crashed"
        raise RuntimeError(crashed)

    def importers(self, root: Path, changed: list[Path]) -> list[FileReport]:
        crashed = "the engine crashed"
        raise RuntimeError(crashed)


@pytest.fixture
def broken(kit: Kit) -> Services:
    return kit.bench.services.model_copy(update={"checker": Broken()})


def test_claude_refuses_a_file_tools_write_when_judging_fails(
    broken: Services, repo: Path
) -> None:
    raw = pre_tool_use(
        repo,
        "Edit",
        {
            "file_path": str(repo / CORE),
            "old_string": "return x\n",
            "new_string": "return 2\n",
        },
    )
    output = json.loads(
        claude.hook(raw, Bench(runtime=claude.Claude(), services=broken))
    )["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "lup's judge failed" in output["permissionDecisionReason"]


def test_claude_tells_the_agent_when_a_checkpoint_fails(
    broken: Services, repo: Path
) -> None:
    bench = Bench(runtime=claude.Claude(), services=broken)
    claude.hook(pre_tool_use(repo, "Bash", {"command": "sed"}), bench)
    (repo / CORE).write_text((repo / CORE).read_text() + "z = 1\n")
    output = json.loads(
        claude.hook(
            payload(repo, "PostToolUse", tool_name="Bash", tool_use_id="t1"), bench
        )
    )
    assert "lup's judge failed" in output["hookSpecificOutput"]["additionalContext"]


def test_claude_lets_a_turn_end_once_when_judging_keeps_failing() -> None:
    stop = claude.Stop(
        session_id="s1", cwd=Path(), hook_event_name="Stop", stop_hook_active=True
    )
    assert stop.failed(RuntimeError("x")) is None


def test_claude_knows_its_own_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    assert claude.Claude().inside()
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION")
    assert not claude.Claude().inside()
    assert claude.Claude().asks_before()


def test_codex_pre_tool_use_counts_the_call_and_prints_nothing(
    on_codex: Bench, repo: Path, kit: Kit
) -> None:
    raw = payload(
        repo,
        "PreToolUse",
        turn_id="u1",
        tool_name="apply_patch",
        tool_input={"command": "*** Begin Patch"},
        tool_use_id="p1",
    )
    assert codex.hook(raw, on_codex) == ""
    assert running(kit, repo) == ["p1"]


def post(repo: Path, response: object, call: str = "p1") -> str:
    return payload(
        repo,
        "PostToolUse",
        turn_id="u1",
        tool_name="apply_patch",
        tool_input={"command": "patch"},
        tool_use_id=call,
        tool_response=response,
    )


def test_codex_hears_a_refusal_after_the_original_result(
    on_codex: Bench, repo: Path
) -> None:
    codex.hook(
        payload(
            repo,
            "PreToolUse",
            turn_id="u1",
            tool_name="apply_patch",
            tool_input={},
            tool_use_id="p1",
        ),
        on_codex,
    )
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    output = json.loads(
        codex.hook(
            post(repo, "Success. Updated the following files:\nM src/pkg/core.py"),
            on_codex,
        )
    )
    assert output["decision"] == "block"
    assert output["reason"].startswith(
        "Success. Updated the following files:\nM src/pkg/core.py\n\n"
        "lup refused 1 file."
    )


def test_codex_holds_an_ask_until_the_operator_answers(
    on_codex: Bench, repo: Path, kit: Kit
) -> None:
    codex.hook(
        payload(
            repo,
            "PreToolUse",
            turn_id="u1",
            tool_name="apply_patch",
            tool_input={},
            tool_use_id="p1",
        ),
        on_codex,
    )
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')

    def approve() -> None:
        [hold] = waiting(kit.layout)
        Holds(layout=kit.layout.store(repo)).answer(
            hold.key, Response(approved=True), kit.clock
        )

    kit.clock.on_sleep.append(approve)
    output = json.loads(codex.hook(post(repo, {"output": "done"}), on_codex))
    assert output["reason"].startswith(
        '{"output": "done"}\n\nThe operator approved the held change to src/pkg/new.py.'
    )
    assert (repo / "src" / "pkg" / "new.py").exists()


def test_codex_prints_nothing_when_theres_nothing_to_say(
    on_codex: Bench, repo: Path
) -> None:
    codex.hook(
        payload(
            repo,
            "PreToolUse",
            turn_id="u1",
            tool_name="Bash",
            tool_input={"command": "ls"},
            tool_use_id="b1",
        ),
        on_codex,
    )
    assert codex.hook(post(repo, "listing", call="b1"), on_codex) == ""


def test_codex_stop_blocks_while_touched_files_have_type_errors(
    on_codex: Bench, repo: Path
) -> None:
    codex.hook(
        payload(
            repo,
            "PreToolUse",
            turn_id="u1",
            tool_name="Bash",
            tool_input={},
            tool_use_id="b1",
        ),
        on_codex,
    )
    (repo / CORE).write_text((repo / CORE).read_text() + "y: int = 'a'  # TYPE\n")
    codex.hook(post(repo, "", call="b1"), on_codex)
    raw = payload(
        repo, "Stop", turn_id="u1", stop_hook_active=False, last_assistant_message=None
    )
    output = json.loads(codex.hook(raw, on_codex))
    assert output["decision"] == "block"
    assert output["reason"].startswith("lup won't end the turn yet")


def test_codex_knows_its_own_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "019a")
    assert codex.Codex().inside()
    monkeypatch.delenv("CODEX_THREAD_ID")
    assert not codex.Codex().inside()
    assert not codex.Codex().asks_before()
