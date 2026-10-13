"""Each runtime's payloads in, its outputs out."""

import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter

from lup.sessions.terminal import Hook
from lup_dev.adapters import claude, codex
from lup_dev.codescan.contract import Checker, FileReport, Rule, Source
from lup_dev.policy.checkpoint import Bench, Running, Services
from lup_dev.policy.holds import Holds, Response, waiting
from lup_dev.stored import read_model

if TYPE_CHECKING:
    from conftest import Kit

    from lup_dev.declaration.resolve import Selected
    from lup_dev.declaration.runner import Runner

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


def test_claude_subagent_stop_doesnt_hold_on_the_subagents_own_files(
    on_claude: Bench, repo: Path
) -> None:
    claude_breaks_core(on_claude, repo, agent_id="sub")
    stop = payload(repo, "Stop", stop_hook_active=False)
    assert claude.hook(stop, on_claude) == ""
    subagent_stop = payload(
        repo, "SubagentStop", agent_id="sub", stop_hook_active=False
    )
    assert claude.hook(subagent_stop, on_claude) == ""
    assert claude.hook(stop, on_claude) == ""


def test_claude_subagent_stop_holds_once_on_a_refusal(
    on_claude: Bench, repo: Path
) -> None:
    claude.hook(
        payload(
            repo,
            "PreToolUse",
            tool_name="Bash",
            tool_input={"command": "touch"},
            tool_use_id="t1",
            agent_id="sub",
        ),
        on_claude,
    )
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    subagent_stop = payload(
        repo, "SubagentStop", agent_id="sub", stop_hook_active=False
    )
    first = json.loads(claude.hook(subagent_stop, on_claude))
    assert first["decision"] == "block"
    assert first["reason"].startswith("lup refused 1 file.")
    assert claude.hook(subagent_stop, on_claude) == ""


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

    def check(
        self,
        root: Path,
        sources: list[Source],
        selected: list[Selected],
        runner: Runner,
    ) -> list[FileReport]:
        crashed = "the engine crashed"
        raise RuntimeError(crashed)

    def importers(
        self, root: Path, changed: list[Path], runner: Runner
    ) -> list[FileReport]:
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
    subagent_stop = payload(
        repo, "SubagentStop", agent_id="sub", stop_hook_active=False
    )
    assert claude.hook(subagent_stop, bench) == ""


def test_claude_lets_a_subagents_turn_end_when_judging_fails_warning_once(
    broken: Services, repo: Path
) -> None:
    bench = Bench(runtime=claude.Claude(), services=broken)
    claude.hook(
        payload(
            repo,
            "PreToolUse",
            tool_name="Bash",
            tool_input={"command": "sed"},
            tool_use_id="t1",
            agent_id="sub",
        ),
        bench,
    )
    (repo / CORE).write_text((repo / CORE).read_text() + "z = 1\n")
    subagent_stop = payload(
        repo, "SubagentStop", agent_id="sub", stop_hook_active=False
    )
    output = json.loads(claude.hook(subagent_stop, bench))
    assert output["systemMessage"].startswith("lup's judge failed at a turn's end")
    assert "decision" not in output
    assert claude.hook(subagent_stop, bench) == ""


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


def codex_subagent_stop(repo: Path) -> str:
    return payload(
        repo,
        "SubagentStop",
        turn_id="u2",
        agent_id="019b",
        agent_type="default",
        agent_transcript_path=None,
        last_assistant_message=None,
        stop_hook_active=False,
    )


def test_codex_subagent_stop_doesnt_hold_on_the_subagents_own_files(
    on_codex: Bench, repo: Path
) -> None:
    codex_breaks_core(on_codex, repo, agent_id="019b")
    assert codex.hook(codex_stop(repo, after_block=False), on_codex) == ""
    assert codex.hook(codex_subagent_stop(repo), on_codex) == ""
    assert codex.hook(codex_stop(repo, after_block=False), on_codex) == ""


def test_codex_subagent_stop_holds_once_on_a_refusal(
    on_codex: Bench, repo: Path
) -> None:
    codex.hook(
        payload(
            repo,
            "PreToolUse",
            turn_id="u2",
            tool_name="Bash",
            tool_input={"command": "touch"},
            tool_use_id="b1",
            agent_id="019b",
        ),
        on_codex,
    )
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    first = json.loads(codex.hook(codex_subagent_stop(repo), on_codex))
    assert first["decision"] == "block"
    assert first["reason"].startswith("lup refused 1 file.")
    assert codex.hook(codex_subagent_stop(repo), on_codex) == ""


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


def test_codex_lets_a_subagents_turn_end_when_judging_fails_warning_once(
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
            agent_id="019b",
        ),
        bench,
    )
    (repo / CORE).write_text((repo / CORE).read_text() + "z = 1\n")
    subagent_stop = codex_subagent_stop(repo)
    output = json.loads(codex.hook(subagent_stop, bench))
    assert output["systemMessage"].startswith("lup's judge failed at a turn's end")
    assert "decision" not in output
    assert codex.hook(subagent_stop, bench) == ""


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


# What Codex 0.162.1 sent, captured from `codex exec` in a scratch repository: a
# patch adding `livecheck.py` holding `import subprocess`, a patch updating it, a
# shell `test -e livecheck.py`, a patch that fails to apply (a `PreToolUse` and no
# `PostToolUse`), then the turn's end.

CAPTURED = Path(__file__).parent / "payloads" / "codex-0.162.1"
LIVECHECK = "import subprocess  # BAD subprocess\n"
"""What the captured patch writes, `import subprocess`, with the fake engine's marker for lup's `subprocess` rule."""


def captured(name: str, repo: Path) -> str:
    """Return a payload Codex 0.162.1 sent, its working directory moved to `repo`."""
    sent = json.loads((CAPTURED / f"{name}.json").read_text())
    return json.dumps({**sent, "cwd": str(repo)})


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("1-session-start", codex.SessionStart),
        ("2-pre-tool-use-add", codex.PreToolUse),
        ("3-post-tool-use-add", codex.PostToolUse),
        ("4-pre-tool-use-update", codex.PreToolUse),
        ("5-post-tool-use-update", codex.PostToolUse),
        ("6-pre-tool-use-bash", codex.PreToolUse),
        ("7-post-tool-use-bash", codex.PostToolUse),
        ("8-pre-tool-use-failed-patch", codex.PreToolUse),
        ("9-stop", codex.Stop),
    ],
)
def test_codex_reads_each_hook_0_162_1_sent(
    name: str, kind: type[codex.Payload]
) -> None:
    raw = (CAPTURED / f"{name}.json").read_text()
    received = TypeAdapter[codex.Received](codex.Received).validate_json(raw)
    assert isinstance(received, kind)


def test_codex_0_162_1_patch_is_refused_after_its_call(
    on_codex: Bench, repo: Path, kit: Kit
) -> None:
    codex.hook(captured("1-session-start", repo), on_codex)
    assert codex.hook(captured("2-pre-tool-use-add", repo), on_codex) == ""
    (repo / "livecheck.py").write_text(LIVECHECK)
    output = json.loads(codex.hook(captured("3-post-tool-use-add", repo), on_codex))
    said = output["hookSpecificOutput"]["additionalContext"]
    assert said.startswith("lup refused 1 file.")
    assert f"{repo}/livecheck.py" in said
    assert not (repo / "livecheck.py").exists()
    assert running(kit, repo) == []


def test_codex_judges_a_patch_in_a_worktree_a_claude_write_was_allowed_in(
    on_codex: Bench, on_claude: Bench, repo: Path, kit: Kit
) -> None:
    """A Claude Code session hooked only on `PreToolUse` for `Edit|Write` (lup's own
    settings, a launched Claude Code room) leaves each write it allows counted, and
    no hook finishes it: another session's checkpoints don't wait on it."""

    def from_claude(event: str, **fields: object) -> str:
        sent = {"session_id": "c1", "cwd": str(repo), "hook_event_name": event}
        return json.dumps({**sent, **fields})

    claude.hook(from_claude("SessionStart", source="startup"), on_claude)
    write = {"file_path": "notes.md", "content": "Notes.\n"}
    raw = from_claude(
        "PreToolUse", tool_name="Write", tool_input=write, tool_use_id="toolu_1"
    )
    allowed = json.loads(claude.hook(raw, on_claude))
    assert allowed["hookSpecificOutput"]["permissionDecision"] == "allow"
    (repo / "notes.md").write_text("Notes.\n")
    codex.hook(captured("1-session-start", repo), on_codex)
    codex.hook(captured("2-pre-tool-use-add", repo), on_codex)
    (repo / "livecheck.py").write_text(LIVECHECK)
    output = codex.hook(captured("3-post-tool-use-add", repo), on_codex)
    assert not (repo / "livecheck.py").exists()
    assert json.loads(output)["hookSpecificOutput"]["additionalContext"].startswith(
        "lup refused 1 file."
    )
    assert running(kit, repo) == ["toolu_1"]


FAILED_PATCH = "exec-b983ecfa-5dea-4c4e-bc2b-98ce1477eed1"
"""The call of the captured patch that failed to apply, which no `PostToolUse` finishes."""


def test_codex_judges_a_patch_after_one_that_failed_at_the_turns_end(
    on_codex: Bench, repo: Path, kit: Kit
) -> None:
    """Codex 0.162.1 runs `PostToolUse` only for a call that succeeded: the failed
    patch's call stays counted, so its session's checkpoints wait for the turn's
    end, which clears it and judges what the turn left."""
    codex.hook(captured("1-session-start", repo), on_codex)
    codex.hook(captured("8-pre-tool-use-failed-patch", repo), on_codex)
    codex.hook(captured("2-pre-tool-use-add", repo), on_codex)
    (repo / "livecheck.py").write_text(LIVECHECK)
    assert codex.hook(captured("3-post-tool-use-add", repo), on_codex) == ""
    assert running(kit, repo) == [FAILED_PATCH]
    output = json.loads(codex.hook(captured("9-stop", repo), on_codex))
    assert output["decision"] == "block"
    assert output["reason"].startswith("lup refused 1 file.")
    assert not (repo / "livecheck.py").exists()
    assert running(kit, repo) == []


def test_codex_clears_a_failed_patchs_call_at_the_turns_end(
    on_codex: Bench, repo: Path, kit: Kit
) -> None:
    codex.hook(captured("1-session-start", repo), on_codex)
    codex.hook(captured("8-pre-tool-use-failed-patch", repo), on_codex)
    assert running(kit, repo) == [FAILED_PATCH]
    assert codex.hook(captured("9-stop", repo), on_codex) == ""
    assert running(kit, repo) == []
    codex.hook(captured("2-pre-tool-use-add", repo), on_codex)
    (repo / "livecheck.py").write_text(LIVECHECK)
    output = json.loads(codex.hook(captured("3-post-tool-use-add", repo), on_codex))
    assert output["hookSpecificOutput"]["additionalContext"].startswith(
        "lup refused 1 file."
    )
    assert not (repo / "livecheck.py").exists()


# In a launched room


HOOK = ["sh", "-c", "socat …"]


def test_claude_hooks_the_judges_events_in_a_room() -> None:
    hold = timedelta(hours=25)

    assert claude.hooks(HOOK, hold) == [
        Hook(event="session-started", command=HOOK, timeout=hold),
        Hook(event="call-started", matcher="Edit|Write", command=HOOK, timeout=hold),
    ]


def test_claudes_hook_matches_the_tools_whose_writes_it_reads(repo: Path) -> None:
    edit: dict[str, object] = {
        "file_path": "a.py",
        "old_string": "a",
        "new_string": "b",
    }
    write: dict[str, object] = {"file_path": "a.py", "content": "b"}
    inputs = {"Edit": edit, "Write": write}
    for tool in claude.WRITING:
        read = claude.PreToolUse.model_validate_json(
            pre_tool_use(repo, tool, inputs[tool])
        )
        assert read.proposal() is not None
    bash = claude.PreToolUse.model_validate_json(
        pre_tool_use(repo, "Bash", {"command": "ls"})
    )
    assert bash.proposal() is None


def test_codex_hooks_the_judges_events_in_a_room() -> None:
    hold = timedelta(hours=25)

    assert codex.hooks(HOOK, hold) == [
        Hook(event="session-started", command=HOOK, timeout=hold),
        Hook(event="call-started", command=HOOK, timeout=hold),
        Hook(event="call-finished", command=HOOK, timeout=hold),
        Hook(event="turn-ended", command=HOOK, timeout=hold),
        Hook(event="conversation-ended", command=HOOK, timeout=hold),
    ]


WHY = "`lup-dev hook` ended with status 1"
SAID = f"lup's judge couldn't answer this hook, so it wasn't judged: {WHY}"


def test_claude_refuses_a_write_its_judge_couldnt_answer(repo: Path) -> None:
    raw = pre_tool_use(repo, "Write", {"file_path": "a.py", "content": "b"})

    answered = json.loads(claude.unanswered(raw, WHY))

    assert answered == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"{SAID}. Tell the operator.",
        }
    }


@pytest.mark.parametrize(
    "raw",
    [
        '{"session_id": "s1", "cwd": "/w", "hook_event_name": "SessionStart"}',
        (
            '{"session_id": "s1", "cwd": "/w", "hook_event_name": "PreToolUse", '
            '"tool_name": "Bash", "tool_input": {}, "tool_use_id": "t1"}'
        ),
        "not a payload",
    ],
)
def test_claude_warns_the_operator_of_anything_else_its_judge_couldnt_answer(
    raw: str,
) -> None:
    assert json.loads(claude.unanswered(raw, WHY)) == {"systemMessage": SAID}


def test_codex_tells_the_agent_of_a_checkpoint_its_judge_couldnt_answer(
    repo: Path,
) -> None:
    raw = payload(repo, "PostToolUse", tool_name="Bash", tool_use_id="t1")

    answered = json.loads(codex.unanswered(raw, WHY))

    assert answered == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"{SAID}. Tell the operator.",
        }
    }


@pytest.mark.parametrize(
    "raw",
    [
        '{"session_id": "s1", "cwd": "/w", "hook_event_name": "SessionStart"}',
        (
            '{"session_id": "s1", "cwd": "/w", "hook_event_name": "PreToolUse", '
            '"tool_name": "Bash", "tool_use_id": "t1"}'
        ),
        "{}",
    ],
)
def test_codex_warns_the_operator_of_anything_else_its_judge_couldnt_answer(
    raw: str,
) -> None:
    assert json.loads(codex.unanswered(raw, WHY)) == {"systemMessage": SAID}


def test_a_launched_session_names_no_model_so_the_operators_holds() -> None:
    assert claude.agent().model is None
    assert codex.agent().model is None
