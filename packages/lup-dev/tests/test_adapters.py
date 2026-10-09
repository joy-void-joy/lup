"""Each runtime's payloads in, its outputs out."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.adapters import claude, codex
from lup_dev.codescan.contract import Checker, FileReport, Rule, Source
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
                f"lup asks: {repo}/src/pkg/new.py is a new production file"
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


def claude_breaks_core(bench: Bench, repo: Path, **subagent: str) -> None:
    """A shell call leaves a type error in `CORE`; `agent_id` makes it a subagent's."""
    claude.hook(
        payload(
            repo,
            "PreToolUse",
            tool_name="Bash",
            tool_input={"command": "sed"},
            tool_use_id="t1",
            **subagent,
        ),
        bench,
    )
    (repo / CORE).write_text((repo / CORE).read_text() + "y: int = 'a'  # TYPE\n")
    claude.hook(
        payload(repo, "PostToolUse", tool_name="Bash", tool_use_id="t1", **subagent),
        bench,
    )


def test_claude_stop_tells_the_operator_while_a_subagent_works(
    on_claude: Bench, repo: Path
) -> None:
    claude_breaks_core(on_claude, repo, agent_id="sub")
    stop = payload(repo, "Stop", stop_hook_active=False)
    output = json.loads(claude.hook(stop, on_claude))
    assert "decision" not in output
    assert output["systemMessage"].startswith("A subagent of this session is at work")
    subagent_stop = payload(
        repo, "SubagentStop", agent_id="sub", stop_hook_active=False
    )
    assert claude.hook(subagent_stop, on_claude) == ""
    assert json.loads(claude.hook(stop, on_claude))["decision"] == "block"


def test_claude_stop_after_a_block_on_the_same_findings_lets_the_turn_end(
    on_claude: Bench, repo: Path
) -> None:
    claude_breaks_core(on_claude, repo)
    first = json.loads(
        claude.hook(payload(repo, "Stop", stop_hook_active=False), on_claude)
    )
    assert first["decision"] == "block"
    again = json.loads(
        claude.hook(payload(repo, "Stop", stop_hook_active=True), on_claude)
    )
    assert "decision" not in again
    assert again["systemMessage"].startswith(
        "lup held the turn's end on these just before"
    )


class Broken(Checker):
    def rules(self) -> list[Rule]:
        crashed = "the engine crashed"
        raise RuntimeError(crashed)

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


def test_claude_lets_a_turn_end_when_judging_fails_warning_the_operator_once(
    broken: Services, repo: Path
) -> None:
    bench = Bench(runtime=claude.Claude(), services=broken)
    claude.hook(pre_tool_use(repo, "Bash", {"command": "sed"}), bench)
    (repo / CORE).write_text((repo / CORE).read_text() + "z = 1\n")
    stop = payload(repo, "Stop", stop_hook_active=False)
    output = json.loads(claude.hook(stop, bench))
    assert output["systemMessage"].startswith("lup's judge failed at a turn's end")
    assert "decision" not in output
    assert claude.hook(stop, bench) == ""


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


def test_codex_hears_a_refusal_beside_the_result(on_codex: Bench, repo: Path) -> None:
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
    said = output["hookSpecificOutput"]
    assert said["hookEventName"] == "PostToolUse"
    assert said["additionalContext"].startswith("lup refused 1 file.")
    assert "decision" not in output


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
    assert output["hookSpecificOutput"]["additionalContext"].startswith(
        f"The operator approved the held change to {repo}/src/pkg/new.py."
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


def codex_breaks_core(bench: Bench, repo: Path, **subagent: str) -> None:
    """A shell call leaves a type error in `CORE`; `agent_id` makes it a subagent's."""
    codex.hook(
        payload(
            repo,
            "PreToolUse",
            turn_id="u1",
            tool_name="Bash",
            tool_input={"command": "sed"},
            tool_use_id="b1",
            **subagent,
        ),
        bench,
    )
    (repo / CORE).write_text((repo / CORE).read_text() + "y: int = 'a'  # TYPE\n")
    codex.hook(
        payload(
            repo,
            "PostToolUse",
            turn_id="u1",
            tool_name="Bash",
            tool_input={"command": "sed"},
            tool_use_id="b1",
            tool_response="",
            **subagent,
        ),
        bench,
    )


def codex_stop(repo: Path, *, after_block: bool) -> str:
    return payload(
        repo,
        "Stop",
        turn_id="u1",
        stop_hook_active=after_block,
        last_assistant_message=None,
    )


def test_codex_stop_tells_the_operator_while_a_subagent_works(
    on_codex: Bench, repo: Path
) -> None:
    codex_breaks_core(on_codex, repo, agent_id="019b")
    output = json.loads(codex.hook(codex_stop(repo, after_block=False), on_codex))
    assert "decision" not in output
    assert output["systemMessage"].startswith("A subagent of this session is at work")
    subagent_stop = payload(
        repo,
        "SubagentStop",
        turn_id="u2",
        agent_id="019b",
        agent_type="default",
        stop_hook_active=False,
    )
    assert codex.hook(subagent_stop, on_codex) == ""
    stop = json.loads(codex.hook(codex_stop(repo, after_block=False), on_codex))
    assert stop["decision"] == "block"


def test_codex_stop_after_a_block_on_the_same_findings_lets_the_turn_end(
    on_codex: Bench, repo: Path
) -> None:
    codex_breaks_core(on_codex, repo)
    first = json.loads(codex.hook(codex_stop(repo, after_block=False), on_codex))
    assert first["decision"] == "block"
    again = json.loads(codex.hook(codex_stop(repo, after_block=True), on_codex))
    assert "decision" not in again
    assert again["systemMessage"].startswith(
        "lup held the turn's end on these just before"
    )


def test_codex_tells_the_agent_when_a_checkpoint_fails(
    broken: Services, repo: Path
) -> None:
    bench = Bench(runtime=codex.Codex(), services=broken)
    codex.hook(
        payload(
            repo,
            "PreToolUse",
            turn_id="u1",
            tool_name="Bash",
            tool_input={},
            tool_use_id="b1",
        ),
        bench,
    )
    (repo / CORE).write_text((repo / CORE).read_text() + "z = 1\n")
    output = json.loads(codex.hook(post(repo, "", call="b1"), bench))
    assert "lup's judge failed" in output["hookSpecificOutput"]["additionalContext"]


def test_codex_lets_a_turn_end_when_judging_fails_warning_the_operator_once(
    broken: Services, repo: Path
) -> None:
    bench = Bench(runtime=codex.Codex(), services=broken)
    codex.hook(
        payload(
            repo,
            "PreToolUse",
            turn_id="u1",
            tool_name="Bash",
            tool_input={},
            tool_use_id="b1",
        ),
        bench,
    )
    (repo / CORE).write_text((repo / CORE).read_text() + "z = 1\n")
    stop = payload(repo, "Stop", turn_id="u1", stop_hook_active=False)
    output = json.loads(codex.hook(stop, bench))
    assert output["systemMessage"].startswith("lup's judge failed at a turn's end")
    assert "decision" not in output
    assert codex.hook(stop, bench) == ""


def test_codex_knows_its_own_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "019a")
    assert codex.Codex().inside()
    monkeypatch.delenv("CODEX_THREAD_ID")
    assert not codex.Codex().inside()
    assert not codex.Codex().asks_before()


def test_claude_judges_a_worktree_its_working_directory_moves_to(
    on_claude: Bench, repo: Path, linked: Path
) -> None:
    claude.hook(payload(repo, "SessionStart", source="startup"), on_claude)
    claude.hook(
        pre_tool_use(linked, "Bash", {"command": "cd ../feat && sed"}), on_claude
    )
    (linked / CORE).write_text((linked / CORE).read_text() + "y = 2  # BAD regex\n")
    raw = payload(linked, "PostToolUse", tool_name="Bash", tool_use_id="t1")
    output = json.loads(claude.hook(raw, on_claude))["hookSpecificOutput"]
    assert output["additionalContext"].startswith("lup refused 1 file.")
    assert "# BAD" not in (linked / CORE).read_text()


def test_codex_holds_only_the_worktree_it_started_in(
    on_codex: Bench, repo: Path, linked: Path
) -> None:
    codex.hook(payload(repo, "SessionStart", source="startup"), on_codex)
    codex.hook(
        payload(
            repo,
            "PreToolUse",
            turn_id="u1",
            tool_name="apply_patch",
            tool_input={"command": "*** Begin Patch"},
            tool_use_id="p1",
        ),
        on_codex,
    )
    (linked / CORE).write_text((linked / CORE).read_text() + "y = 2  # BAD regex\n")
    assert codex.hook(post(repo, "done"), on_codex) == ""
    assert "# BAD regex" in (linked / CORE).read_text()
