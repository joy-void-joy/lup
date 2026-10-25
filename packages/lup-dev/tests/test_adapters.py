"""Each runtime's payloads in, its outputs out."""

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, get_args

import pytest
from pydantic import TypeAdapter

from lup import events
from lup.adapters.claude.terminal import spelled
from lup.sessions.terminal import Hook
from lup_dev import cli
from lup_dev.adapters import claude, codex
from lup_dev.codescan.contract import (
    Checker,
    Due,
    FileReport,
    Finding,
    Position,
    Rule,
    Source,
    Span,
)
from lup_dev.host.courier import (
    Conversation,
    Conversations,
    Failure,
    Heard,
    Spawned,
    Telling,
)
from lup_dev.host.protocol import Register
from lup_dev.host.workers import JudgeCalling
from lup_dev.inbox.store import Text
from lup_dev.policy.checkpoint import Bench, Running, Services, Worktree
from lup_dev.policy.holds import Response
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import Kit

    from lup.events import SessionEvent
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


def test_claude_holds_a_new_production_file_in_its_hook_and_lets_it_through_on_a_yes(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    raw = pre_tool_use(
        repo,
        "Write",
        {"file_path": str(repo / "src/pkg/new.py"), "content": '"""New."""\n'},
    )
    output = json.loads(claude.hook(raw, on_claude))
    [hold] = kit.announced.holds
    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "additionalContext": (
                f"lup held the write to {repo}/src/pkg/new.py for the operator's "
                "review, and they approved it."
            ),
        }
    }
    assert [each.asks for each in hold.files] == [
        ["src/pkg/new.py is a new production file"]
    ]
    assert kit.announced.runtimes == ["claude"]
    assert running(kit, repo) == ["t1"]


def test_claude_tells_a_held_writes_approval_and_comment_beside_the_call(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    """An `allow`'s `permissionDecisionReason` reaches only Claude Code's debug log, so the approval goes where the model reads it."""
    kit.announced.answering = Response(approved=True, comment="name it after the room")
    raw = pre_tool_use(
        repo,
        "Write",
        {"file_path": str(repo / "src/pkg/new.py"), "content": '"""New."""\n'},
    )
    output = json.loads(claude.hook(raw, on_claude))
    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "additionalContext": (
                f"lup held the write to {repo}/src/pkg/new.py for the operator's "
                "review, and they approved it: name it after the room"
            ),
        }
    }


def test_claude_lets_a_flagged_write_through_putting_it_before_the_operator(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    kit.announced.holding_all = False
    raw = pre_tool_use(
        repo,
        "Write",
        {"file_path": str(repo / "src/pkg/new.py"), "content": '"""New."""\n'},
    )
    output = json.loads(claude.hook(raw, on_claude))
    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
    assert kit.announced.holds == []
    [asked] = kit.flags.asked
    assert (asked.sender.runtime, asked.sender.session, asked.call) == (
        "claude",
        "s1",
        "t1",
    )
    assert asked.flagged.path == Path("src/pkg/new.py")
    assert running(kit, repo) == ["t1"]


def test_claude_refreshes_a_flagged_item_with_an_edit_flagging_nothing(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    kit.announced.holding_all = False
    new = repo / "src" / "pkg" / "new.py"
    written: dict[str, object] = {"file_path": str(new), "content": '"""New."""\n'}
    claude.hook(pre_tool_use(repo, "Write", written), on_claude)
    new.write_text('"""New."""\n')
    claude.hook(
        payload(repo, "PostToolUse", tool_name="Write", tool_use_id="t1"), on_claude
    )
    edit: dict[str, object] = {
        "file_path": str(new),
        "old_string": '"""New."""\n',
        "new_string": "x = 1\n",
    }
    output = json.loads(claude.hook(pre_tool_use(repo, "Edit", edit, "t2"), on_claude))
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
    made, refreshed = kit.flags.asked
    assert (refreshed.joining, refreshed.refreshing, refreshed.call) == (1, True, "t2")
    assert refreshed.file.after == Text(text="x = 1\n")
    assert refreshed.flagged.summary == made.flagged.summary


def test_claude_denies_a_held_write_the_operator_declined(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    kit.announced.answering = Response(approved=False, comment="not that module")
    raw = pre_tool_use(
        repo,
        "Write",
        {"file_path": str(repo / "src/pkg/new.py"), "content": '"""New."""\n'},
    )
    output = json.loads(claude.hook(raw, on_claude))["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert output["permissionDecisionReason"].endswith(
        "  The operator declined it: not that module"
    )
    assert running(kit, repo) == []
    assert not (repo / "src/pkg/new.py").exists()


def test_claude_allows_an_edit_with_a_finding_telling_it_and_counts_it_running(
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
    assert output["permissionDecision"] == "allow"
    assert output["additionalContext"].startswith("lup's findings on the lines changed")
    assert " - regex: " in output["additionalContext"]
    assert running(kit, repo) != []


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
    assert output["additionalContext"].startswith("lup's findings on the lines changed")


def held_on(printed: str, event: str = "Stop") -> str:
    """What a Claude Code turn's end's answer holds it on: its `additionalContext`, for `event`, holding nothing else."""
    output = json.loads(printed)
    assert "decision" not in output
    told = output["hookSpecificOutput"]
    assert told["hookEventName"] == event
    return told["additionalContext"]


def test_claude_stop_holds_while_touched_files_have_type_errors(
    on_claude: Bench, repo: Path
) -> None:
    claude.hook(pre_tool_use(repo, "Bash", {"command": "sed"}), on_claude)
    (repo / CORE).write_text((repo / CORE).read_text() + "y: int = 'a'  # TYPE\n")
    claude.hook(
        payload(repo, "PostToolUse", tool_name="Bash", tool_use_id="t1"), on_claude
    )
    printed = claude.hook(payload(repo, "Stop", stop_hook_active=False), on_claude)
    assert held_on(printed).startswith("lup won't end the turn yet")


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


def test_claude_stop_says_nothing_of_a_file_a_subagent_at_work_touched_too(
    on_claude: Bench, repo: Path
) -> None:
    """What's left there may be the subagent's in progress; `systemMessage` would tell the operator alone."""
    claude_breaks_core(on_claude, repo)
    claude_breaks_core(on_claude, repo, agent_id="sub")
    stop = payload(repo, "Stop", stop_hook_active=False)
    assert claude.hook(stop, on_claude) == ""
    subagent_stop = payload(
        repo, "SubagentStop", agent_id="sub", stop_hook_active=False
    )
    claude.hook(subagent_stop, on_claude)
    assert held_on(claude.hook(stop, on_claude)).startswith(
        "lup won't end the turn yet"
    )


def test_claude_subagent_stop_holds_once_on_a_held_changes_answer(
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
    first = claude.hook(subagent_stop, on_claude)
    assert held_on(first, "SubagentStop").startswith("lup held the write to")
    assert claude.hook(subagent_stop, on_claude) == ""


def test_claude_a_failed_subagent_is_no_longer_at_work_and_its_hook_prints_nothing(
    on_claude: Bench, repo: Path
) -> None:
    """Its turn ended on an error from the model's API, so `StopFailure` runs and no `SubagentStop`: from then on, the session's end holds on the file it touched too."""
    claude_breaks_core(on_claude, repo)
    claude_breaks_core(on_claude, repo, agent_id="sub")
    stop = payload(repo, "Stop", stop_hook_active=False)
    assert claude.hook(stop, on_claude) == ""
    failed = payload(
        repo,
        "StopFailure",
        agent_id="sub",
        error="rate_limit",
        last_assistant_message="API Error: Rate limit reached",
    )
    assert claude.hook(failed, on_claude) == ""
    assert held_on(claude.hook(stop, on_claude)).startswith(
        "lup won't end the turn yet"
    )


def test_claude_a_stopped_subagent_is_no_longer_at_work_whatever_its_end_would_say(
    on_claude: Bench, repo: Path
) -> None:
    """Nothing reads what the `SubagentStop` of a subagent stopped answers, so what it would hold on doesn't keep it at work."""
    claude_breaks_core(on_claude, repo)
    claude_breaks_core(on_claude, repo, agent_id="sub")
    claude.hook(
        payload(
            repo,
            "PreToolUse",
            tool_name="Bash",
            tool_input={"command": "touch"},
            tool_use_id="t2",
            agent_id="sub",
        ),
        on_claude,
    )
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    stopped = payload(repo, "SubagentStop", agent_id="sub", stop_hook_active=False)
    assert held_on(claude.hook(stopped, on_claude), "SubagentStop").startswith(
        "lup held the write to"
    )
    stop = payload(repo, "Stop", stop_hook_active=False)
    assert "lup won't end the turn yet" in held_on(claude.hook(stop, on_claude))


def test_claude_a_failed_turns_hook_prints_nothing_and_a_judging_failure_is_raised(
    on_claude: Bench, broken: Services, repo: Path
) -> None:
    """Claude Code reads none of `StopFailure`'s answer, so a warning there would reach no one: the judge's failure is raised for the host service to say."""
    claude_breaks_core(on_claude, repo)
    assert (
        claude.hook(payload(repo, "StopFailure", error="overloaded"), on_claude) == ""
    )
    bench = Bench(runtime=claude.Claude(), services=broken)
    claude.hook(
        payload(
            repo,
            "PreToolUse",
            tool_name="Bash",
            tool_input={"command": "sed"},
            tool_use_id="t2",
            agent_id="sub",
        ),
        bench,
    )
    (repo / CORE).write_text((repo / CORE).read_text() + "z = 1\n")
    failed = payload(repo, "StopFailure", agent_id="sub", error="rate_limit")
    with pytest.raises(RuntimeError, match="the engine crashed"):
        claude.hook(failed, bench)


def test_claude_stop_after_a_block_on_the_same_findings_lets_the_turn_end_saying_nothing(
    on_claude: Bench, repo: Path
) -> None:
    """The agent was told them as the end held; `systemMessage` would tell the operator alone."""
    claude_breaks_core(on_claude, repo)
    first = claude.hook(payload(repo, "Stop", stop_hook_active=False), on_claude)
    assert held_on(first).startswith("lup won't end the turn yet")
    assert claude.hook(payload(repo, "Stop", stop_hook_active=True), on_claude) == ""


class Broken(Checker):
    def rules(self, selected: list[Selected] | None = None) -> list[Rule]:
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


def test_codex_hears_a_finding_beside_the_result(on_codex: Bench, repo: Path) -> None:
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
    assert said["additionalContext"].startswith("lup's findings on the lines changed")
    assert "decision" not in output


@pytest.mark.parametrize(
    ("comment", "said"),
    [("", "."), ("good name", ": good name")],
    ids=["bare", "commented"],
)
def test_codex_holds_an_ask_until_the_operator_answers(
    on_codex: Bench, repo: Path, kit: Kit, *, comment: str, said: str
) -> None:
    kit.announced.answering = Response(approved=True, comment=comment)
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
    output = json.loads(codex.hook(post(repo, {"output": "done"}), on_codex))
    [told, *_] = output["hookSpecificOutput"]["additionalContext"].split("\n\n")
    assert told == (
        f"lup held the write to {repo}/src/pkg/new.py for the operator's review, "
        f"and they approved it{said}"
    )
    assert (repo / "src" / "pkg" / "new.py").exists()


def test_codex_puts_a_flagged_patch_before_the_operator_after_its_call(
    on_codex: Bench, repo: Path, kit: Kit
) -> None:
    kit.announced.holding_all = False
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
    assert codex.hook(post(repo, {"output": "done"}), on_codex) == ""
    assert kit.announced.holds == []
    [asked] = kit.flags.asked
    assert (asked.sender.runtime, asked.sender.session, asked.call) == (
        "codex",
        "s1",
        "p1",
    )
    assert asked.flagged.path == Path("src/pkg/new.py")
    assert (repo / "src" / "pkg" / "new.py").exists()


def test_codex_refreshes_a_flagged_item_with_a_patch_flagging_nothing(
    on_codex: Bench, repo: Path, kit: Kit
) -> None:
    kit.announced.holding_all = False
    new = repo / "src" / "pkg" / "new.py"
    for call, text in [("p1", '"""New."""\n'), ("p2", "x = 1\n")]:
        codex.hook(
            payload(
                repo,
                "PreToolUse",
                turn_id="u1",
                tool_name="apply_patch",
                tool_input={},
                tool_use_id=call,
            ),
            on_codex,
        )
        new.write_text(text)
        codex.hook(post(repo, {"output": "done"}, call), on_codex)
    made, refreshed = kit.flags.asked
    assert (refreshed.joining, refreshed.refreshing, refreshed.call) == (1, True, "p2")
    assert refreshed.file.after == Text(text="x = 1\n")
    assert refreshed.flagged.summary == made.flagged.summary


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


def test_codex_stop_says_nothing_of_a_file_a_subagent_at_work_touched_too(
    on_codex: Bench, repo: Path
) -> None:
    """What's left there may be the subagent's in progress; `systemMessage` would tell the operator alone."""
    codex_breaks_core(on_codex, repo)
    codex_breaks_core(on_codex, repo, agent_id="019b")
    assert codex.hook(codex_stop(repo, after_block=False), on_codex) == ""
    codex.hook(codex_subagent_stop(repo), on_codex)
    output = json.loads(codex.hook(codex_stop(repo, after_block=False), on_codex))
    assert output["decision"] == "block"
    assert output["reason"].startswith("lup won't end the turn yet")


def test_codex_subagent_stop_holds_once_on_a_held_changes_answer(
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
    assert first["reason"].startswith("lup held the write to")
    assert codex.hook(codex_subagent_stop(repo), on_codex) == ""


def test_codex_stop_after_a_block_on_the_same_findings_lets_the_turn_end_saying_nothing(
    on_codex: Bench, repo: Path
) -> None:
    """The agent was told them as the end held; `systemMessage` would tell the operator alone."""
    codex_breaks_core(on_codex, repo)
    first = json.loads(codex.hook(codex_stop(repo, after_block=False), on_codex))
    assert first["decision"] == "block"
    assert codex.hook(codex_stop(repo, after_block=True), on_codex) == ""


def test_codex_agent_stops_is_told_an_item_and_stops_again_ending_at_once(
    on_codex: Bench, repo: Path
) -> None:
    """The judge's findings held a turn's end once; a later turn, after an item is told, ends at once."""
    codex_breaks_core(on_codex, repo)
    stop = codex_stop(repo, after_block=False)
    assert json.loads(codex.hook(stop, on_codex))["decision"] == "block"
    codex.hook(codex_stop(repo, after_block=True), on_codex)
    call = payload(
        repo,
        "PreToolUse",
        turn_id="u3",
        tool_name="Bash",
        tool_input={"command": "ls"},
        tool_use_id="b9",
    )
    item = "lup's inbox, item 1: a note from the operator:\nCarry on."
    told = codex.told(
        call, codex.hook(call, on_codex), Telling(caller="c", items=[item])
    )
    assert json.loads(told or "")["hookSpecificOutput"]["additionalContext"] == item
    codex.hook(post(repo, "", call="b9"), on_codex)
    assert codex.hook(codex_stop(repo, after_block=False), on_codex) == ""


def test_a_turns_end_following_a_hold_is_heard_so_on_both_runtimes() -> None:
    held = {"stop_hook_active": True, "last_assistant_message": None}
    subagent = {"agent_id": "a1", **held}
    assert claude.heard(payload(Path("/w"), "Stop", **held)).after_block
    assert claude.heard(payload(Path("/w"), "SubagentStop", **subagent)).after_block
    assert codex.heard(payload(Path("/w"), "Stop", **held)).after_block
    assert codex.heard(payload(Path("/w"), "SubagentStop", **subagent)).after_block
    assert not claude.heard(payload(Path("/w"), "Stop")).after_block


def test_claude_wakes_an_idle_session_naming_it_and_codex_cant() -> None:
    assert json.loads(claude.woken("s1", "Hello.")) == {
        "type": "user",
        "message": {"role": "user", "content": "Hello."},
        "session_id": "s1",
    }
    assert claude.adapter().woken is claude.woken
    assert codex.adapter().woken is None


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
    assert output["additionalContext"].startswith("lup's findings on the lines changed")
    assert f"{linked / CORE}:" in output["additionalContext"]


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


# What Codex 0.162.1 sent, captured from `codex exec` in a scratch repository
# (each `cwd` replaced by a neutral path): a patch adding `livecheck.py` holding
# `import subprocess`, a patch updating it, a shell `test -e livecheck.py`, a
# patch that fails to apply (a `PreToolUse` and no `PostToolUse`), then the
# turn's end.

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


def test_codex_0_162_1_patch_is_held_after_its_call_and_put_back_on_a_no(
    on_codex: Bench, repo: Path, kit: Kit
) -> None:
    kit.announced.answering = Response(approved=False, comment="not here")
    codex.hook(captured("1-session-start", repo), on_codex)
    assert codex.hook(captured("2-pre-tool-use-add", repo), on_codex) == ""
    (repo / "livecheck.py").write_text(LIVECHECK)
    output = json.loads(codex.hook(captured("3-post-tool-use-add", repo), on_codex))
    said = output["hookSpecificOutput"]["additionalContext"]
    assert said.startswith("lup refused 1 file.")
    assert f"{repo}/livecheck.py" in said
    assert "The operator declined it: not here" in said
    assert kit.announced.runtimes == ["codex"]
    assert not (repo / "livecheck.py").exists()
    assert running(kit, repo) == []


def test_codex_judges_a_patch_in_a_worktree_a_claude_write_was_allowed_in(
    on_codex: Bench, on_claude: Bench, repo: Path, kit: Kit
) -> None:
    """A Claude Code session hooked only on `PreToolUse` for `Edit|Write`, as a
    configuration that hooks no call's finish would be, leaves each write it allows
    counted, and no hook finishes it: another session's checkpoints don't wait on it."""

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
    assert (repo / "livecheck.py").exists()
    assert json.loads(output)["hookSpecificOutput"]["additionalContext"].startswith(
        "lup held the write to"
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
    assert output["reason"].startswith("lup held the write to")
    assert (repo / "livecheck.py").exists()
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
        "lup held the write to"
    )
    assert (repo / "livecheck.py").exists()


def with_fields(raw: str, **fields: object) -> str:
    return json.dumps({**json.loads(raw), **fields})


def test_codex_clears_a_call_of_an_earlier_turn_at_the_next_turns_start(
    on_codex: Bench, repo: Path, kit: Kit
) -> None:
    """A prompt carries its turn's id, as each call does: a call no hook
    finished in an earlier turn is over, and the turn's first call's finish
    judges what it wrote; a prompt arriving in the turn leaves its calls."""
    codex.hook(captured("1-session-start", repo), on_codex)
    lost = captured("6-pre-tool-use-bash", repo)
    turn = json.loads(lost)["turn_id"]
    codex.hook(lost, on_codex)
    (repo / "livecheck.py").write_text(LIVECHECK)
    steered = with_fields(CODEX_PROMPT, session_id=json.loads(lost)["session_id"])
    same = with_fields(steered, cwd=str(repo), turn_id=turn)
    assert codex.hook(same, on_codex) == ""
    assert running(kit, repo) == [json.loads(lost)["tool_use_id"]]
    assert codex.hook(with_fields(same, turn_id="next"), on_codex) == ""
    assert running(kit, repo) == []
    codex.hook(
        with_fields(captured("2-pre-tool-use-add", repo), turn_id="next"), on_codex
    )
    output = json.loads(codex.hook(captured("3-post-tool-use-add", repo), on_codex))
    assert output["hookSpecificOutput"]["additionalContext"].startswith(
        "lup held the write to"
    )


def test_codex_a_subagents_call_holds_back_the_main_conversations_checkpoint(
    on_codex: Bench, repo: Path, kit: Kit
) -> None:
    """Codex's hooks carry the session's working directory for every
    conversation, and no file tool says where it writes, so every conversation
    of a Codex session works in its one worktree: a subagent's running call holds
    back the main conversation's checkpoint there, as two conversations working
    in one worktree should, and its own finish runs it."""
    codex.hook(captured("1-session-start", repo), on_codex)
    subagent = with_fields(
        captured("6-pre-tool-use-bash", repo), agent_id="a1", tool_use_id="s1"
    )
    assert codex.hook(subagent, on_codex) == ""
    codex.hook(captured("2-pre-tool-use-add", repo), on_codex)
    (repo / "livecheck.py").write_text(LIVECHECK)
    assert codex.hook(captured("3-post-tool-use-add", repo), on_codex) == ""
    assert running(kit, repo) == ["s1"]
    finished = with_fields(
        captured("7-post-tool-use-bash", repo), agent_id="a1", tool_use_id="s1"
    )
    output = json.loads(codex.hook(finished, on_codex))
    assert output["hookSpecificOutput"]["additionalContext"].startswith(
        "lup held the write to"
    )


# In a launched room


def hook_at(event: type[SessionEvent]) -> list[str]:
    """The room's hook at `event`, as `piped` gives one for each."""
    return ["sh", "-c", f"socat … {event.named()}"]


HOLD = timedelta(hours=25)


def in_room(raw: str, bench: Bench) -> str:
    """Answer a Claude Code hook as a launched room does: the judge answers a hook the room runs (`claude.hooks`) and the judge reads (`claude.heard`); the host service answers every other as no decision."""
    hooked = [
        name for each in claude.hooks(hook_at, HOLD) for name in spelled(each.event)
    ]
    if json.loads(raw)["hook_event_name"] not in hooked:
        return ""
    return claude.hook(raw, bench) if claude.heard(raw).judged else ""


def finished(
    repo: Path, tool: str, tool_input: dict[str, object], call: str = "t1"
) -> str:
    return payload(
        repo,
        "PostToolUse",
        tool_name=tool,
        tool_input=tool_input,
        tool_use_id=call,
        tool_response={},
    )


def test_claude_a_second_edit_to_a_file_it_created_isnt_flagged_again_in_a_room(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    """#171: the room hears a file tool's end, which confirms its write, so the
    next edit to the file is judged against it rather than the session's start."""
    kit.announced.holding_all = False
    new = repo / "src" / "pkg" / "new.py"
    created = '"""New."""\n\n\nclass Room:\n    pass\n'
    write: dict[str, object] = {"file_path": str(new), "content": created}
    in_room(payload(repo, "SessionStart", source="startup"), on_claude)
    in_room(pre_tool_use(repo, "Write", write), on_claude)
    new.write_text(created)
    in_room(finished(repo, "Write", write), on_claude)
    kit.flags.read = [1]
    edit: dict[str, object] = {
        "file_path": str(new),
        "old_string": '"""New."""',
        "new_string": '"""A room."""',
    }
    in_room(pre_tool_use(repo, "Edit", edit, "t2"), on_claude)
    new.write_text(created.replace("New.", "A room."))
    in_room(finished(repo, "Edit", edit, "t2"), on_claude)
    assert list(kit.flags.items) == [1]
    verdicts = Worktree.at(repo, kit.layout).verdicts(kit.layout).read()
    assert [verdict.reasons for verdict in verdicts] == [
        ["new-file"],
        ["rules-pass"],
    ]


def shell(repo: Path, bench: Bench, call: str, wrote: Callable[[], None]) -> str:
    """A `Bash` call in a room that runs `wrote`, its writes; return what the agent is told beside its result."""
    command: dict[str, object] = {"command": "sed -i …"}
    started = in_room(pre_tool_use(repo, "Bash", command, call), bench)
    assert started == ""
    wrote()
    return in_room(finished(repo, "Bash", command, call), bench)


def beside(printed: str) -> str:
    """What a call's end tells the agent beside its result."""
    told = json.loads(printed)["hookSpecificOutput"]
    assert told["hookEventName"] == "PostToolUse"
    return told["additionalContext"]


MANIFEST = Path("pyproject.toml")
ADDED = "\n[tool.added]\nx = 1\n"


@pytest.mark.parametrize(
    ("comment", "said"), [("", "."), ("fine", ": fine")], ids=["bare", "commented"]
)
def test_claude_holds_a_shell_write_to_a_protected_file_and_keeps_it_on_a_yes(
    on_claude: Bench, repo: Path, kit: Kit, *, comment: str, said: str
) -> None:
    kit.announced.answering = Response(approved=True, comment=comment)
    was = (repo / MANIFEST).read_text()
    in_room(payload(repo, "SessionStart", source="startup"), on_claude)

    def append() -> None:
        (repo / MANIFEST).write_text(was + ADDED)

    told = beside(shell(repo, on_claude, "b1", append))
    [hold] = kit.announced.holds
    assert (hold.call, [each.path for each in hold.files]) == ("b1", [MANIFEST])
    assert told == (
        f"lup held the write to {repo / MANIFEST} for the operator's review, "
        f"and they approved it{said}"
    )
    assert (repo / MANIFEST).read_text() == was + ADDED
    assert running(kit, repo) == []


def test_claude_puts_back_a_declined_shell_write_saving_the_agents_version(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    kit.announced.answering = Response(approved=False, comment="not that tool")
    was = (repo / MANIFEST).read_text()
    in_room(payload(repo, "SessionStart", source="startup"), on_claude)

    def append() -> None:
        (repo / MANIFEST).write_text(was + ADDED)

    told = beside(shell(repo, on_claude, "b1", append))
    saved = repo / ".lup" / "saved" / "1" / MANIFEST
    assert told == (
        "lup refused 1 file. It is unchanged; your version is saved.\n\n"
        f"{repo / MANIFEST} (saved at {saved})\n"
        "  The operator declined it: not that tool"
    )
    assert (repo / MANIFEST).read_text() == was
    assert saved.read_text() == was + ADDED


def test_claude_tells_a_shell_writes_findings_beside_its_result(
    on_claude: Bench, repo: Path
) -> None:
    in_room(payload(repo, "SessionStart", source="startup"), on_claude)

    def regex() -> None:
        (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")

    told = beside(shell(repo, on_claude, "b1", regex))
    assert told.startswith("lup's findings on the lines changed")
    assert f"{repo / CORE}:11:8 - regex: regex fires here" in told


def test_claude_puts_a_flagged_shell_write_before_the_operator(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    kit.announced.holding_all = False
    in_room(payload(repo, "SessionStart", source="startup"), on_claude)

    def create() -> None:
        (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')

    assert shell(repo, on_claude, "b1", create) == ""
    assert kit.announced.holds == []
    [asked] = kit.flags.asked
    assert (asked.sender.runtime, asked.call) == ("claude", "b1")
    assert asked.flagged.path == Path("src/pkg/new.py")
    assert (repo / "src" / "pkg" / "new.py").read_text() == '"""New."""\n'


def test_claude_clears_an_interrupted_call_at_the_turns_end_and_judges_its_writes(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    """Claude Code reports no end of a call the operator interrupts (neither
    `PostToolUse` nor `PostToolUseFailure`), and runs no `Stop` for the turn it
    interrupted: where no record shows it over at the next turn's start, that
    turn's end clears it."""
    in_room(payload(repo, "SessionStart", source="startup"), on_claude)
    in_room(pre_tool_use(repo, "Bash", {"command": "sed -i …"}, "lost"), on_claude)
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    assert running(kit, repo) == ["lost"]

    def nothing() -> None:
        pass

    assert shell(repo, on_claude, "b2", nothing) == ""
    printed = in_room(payload(repo, "Stop", stop_hook_active=False), on_claude)
    assert held_on(printed).startswith("lup won't end the turn yet")
    assert "regex: regex fires here" in held_on(printed)
    assert running(kit, repo) == []


def results(record: Path, *calls: str) -> None:
    """Write a Claude Code record holding a result for each of `calls`, as it records an interrupted call's."""
    record.parent.mkdir(parents=True, exist_ok=True)
    refused = "The user doesn't want to proceed with this tool use."
    lines = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": call, "content": refused}
                ],
            },
        }
        for call in calls
    ]
    record.write_text("".join(f"{json.dumps(line)}\n" for line in lines))


def test_claude_clears_an_interrupted_call_at_the_next_turns_start(
    on_claude: Bench, repo: Path, kit: Kit, tmp_path: Path
) -> None:
    """The record holds an interrupted call's result, the session's own or a
    subagent's, though no hook reported its end, so the next prompt clears it,
    and the turn's first call's finish judges what it wrote."""
    transcript = tmp_path / "records" / "s1.jsonl"
    in_room(payload(repo, "SessionStart", source="startup"), on_claude)
    sed: dict[str, object] = {"command": "sed -i …"}
    in_room(pre_tool_use(repo, "Bash", sed, "lost"), on_claude)
    subagent = payload(
        repo,
        "PreToolUse",
        tool_name="Bash",
        tool_input=sed,
        tool_use_id="gone",
        agent_id="a1",
    )
    in_room(subagent, on_claude)
    regex_in(repo)
    results(transcript, "lost")
    results(transcript.with_suffix("") / "subagents" / "agent-a1.jsonl", "gone")
    prompt = payload(
        repo, "UserPromptSubmit", prompt="Go on.", transcript_path=str(transcript)
    )
    assert in_room(prompt, on_claude) == ""
    assert running(kit, repo) == []
    told = beside(shell(repo, on_claude, "b1", lambda: None))
    assert f"{repo / CORE}:11:8 - regex" in told


def test_claude_leaves_a_call_running_when_a_prompt_arrives_mid_turn(
    on_claude: Bench, repo: Path, kit: Kit, tmp_path: Path
) -> None:
    """A channel's message fires `UserPromptSubmit` while the call it waits on
    still runs (Claude Code 2.1.304, `docs/field-notes.md`, *Channels*): the
    record holds no result for it, so it stays counted."""
    transcript = tmp_path / "records" / "s1.jsonl"
    results(transcript)
    in_room(payload(repo, "SessionStart", source="startup"), on_claude)
    in_room(pre_tool_use(repo, "Bash", {"command": "sleep 10"}, "c1"), on_claude)
    channel = '<channel source="lup" wake="t1">\nHi.\n</channel>'
    prompt = payload(
        repo, "UserPromptSubmit", prompt=channel, transcript_path=str(transcript)
    )
    assert in_room(prompt, on_claude) == ""
    assert running(kit, repo) == ["c1"]


def test_claude_reads_without_reaching_the_judge(
    on_claude: Bench, repo: Path, kit: Kit
) -> None:
    in_room(payload(repo, "SessionStart", source="startup"), on_claude)
    read: dict[str, object] = {"file_path": str(repo / CORE)}
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    assert in_room(pre_tool_use(repo, "Read", read, "r1"), on_claude) == ""
    assert running(kit, repo) == []
    assert in_room(finished(repo, "Read", read, "r1"), on_claude) == ""
    store = Worktree.at(repo, kit.layout).store
    assert b"BAD regex" not in (store.content(store.accepted(), CORE) or b"")

    def nothing() -> None:
        pass

    assert " - regex: " in beside(shell(repo, on_claude, "b1", nothing))


def regex_in(root: Path) -> None:
    (root / CORE).write_text((root / CORE).read_text() + "y = 2  # BAD regex\n")


def edits_in_room(
    repo: Path, root: Path, bench: Bench, call: str, old: str, **subagent: str
) -> None:
    """An `Edit` of `old` in `CORE` in the worktree at `root`, its hooks reporting `repo`, as a subagent's report the session's worktree whatever it works on; `agent_id` makes it a subagent's."""
    edit: dict[str, object] = {
        "file_path": str(root / CORE),
        "old_string": old,
        "new_string": f"{old}_",
    }
    start = payload(
        repo,
        "PreToolUse",
        tool_name="Edit",
        tool_input=edit,
        tool_use_id=call,
        **subagent,
    )
    in_room(start, bench)
    (root / CORE).write_text((root / CORE).read_text().replace(old, f"{old}_"))
    end = payload(repo, "PostToolUse", tool_name="Edit", tool_use_id=call, **subagent)
    in_room(end, bench)


def test_claude_a_worker_busy_in_its_worktree_holds_back_checkpoints_there_alone(
    on_claude: Bench, repo: Path, linked: Path
) -> None:
    """A worker's hooks report the session's worktree (`linked` is its own,
    where its file tools write), as Claude Code's subagents' do: its running call
    holds back no checkpoint of the main conversation's in `repo`, and holds
    back one in `linked`, where the main conversation edits too."""
    in_room(payload(repo, "SessionStart", source="startup"), on_claude)
    edits_in_room(repo, linked, on_claude, "w1", "def helper", agent_id="w")
    busy = payload(
        repo,
        "PreToolUse",
        tool_name="Bash",
        tool_input={"command": "uv run pytest"},
        tool_use_id="w2",
        agent_id="w",
    )
    assert in_room(busy, on_claude) == ""
    told = beside(shell(repo, on_claude, "b1", lambda: regex_in(repo)))
    assert f"{repo / CORE}:11:8 - regex" in told
    edits_in_room(repo, linked, on_claude, "m1", "def ask")
    assert shell(repo, on_claude, "b2", lambda: regex_in(linked)) == ""
    done = payload(
        repo, "PostToolUse", tool_name="Bash", tool_use_id="w2", agent_id="w"
    )
    assert f"{linked / CORE}:11:8 - regex" in beside(in_room(done, on_claude))


def test_claude_hooks_every_call_and_each_turns_start_and_end_in_a_room() -> None:
    """Every hook waits as long as a hold may: a call's start for a file tool's
    write, its finish for the checkpoint's, a turn's end for its last checkpoint's."""
    assert claude.hooks(hook_at, HOLD) == [
        Hook(
            event=events.SessionStarted,
            command=hook_at(events.SessionStarted),
            timeout=HOLD,
        ),
        Hook(
            event=events.TurnStarted, command=hook_at(events.TurnStarted), timeout=HOLD
        ),
        Hook(
            event=events.CallStarted, command=hook_at(events.CallStarted), timeout=HOLD
        ),
        Hook(
            event=events.CallFinished,
            command=hook_at(events.CallFinished),
            timeout=HOLD,
        ),
        Hook(event=events.TurnEnded, command=hook_at(events.TurnEnded), timeout=HOLD),
        Hook(
            event=events.ConversationEnded,
            command=hook_at(events.ConversationEnded),
            timeout=HOLD,
        ),
    ]


def test_claudes_judge_proposes_the_file_tools_writes_and_reads_every_call(
    repo: Path,
) -> None:
    edit: dict[str, object] = {
        "file_path": "a.py",
        "old_string": "a",
        "new_string": "b",
    }
    write: dict[str, object] = {"file_path": "a.py", "content": "b"}
    inputs = {"Edit": edit, "Write": write}
    for tool in get_args(claude.Writing.__value__):
        raw = pre_tool_use(repo, tool, inputs[tool])
        assert claude.PreToolUse.model_validate_json(raw).proposal() is not None
        assert claude.heard(raw).judged
    for tool in ["Bash", "NotebookEdit", "mcp__other__write", "SomeNewTool"]:
        raw = pre_tool_use(repo, tool, {"command": "ls"})
        assert claude.PreToolUse.model_validate_json(raw).proposal() is None
        assert claude.heard(raw).judged
        assert claude.heard(finished(repo, tool, {"command": "ls"})).judged


def test_claudes_judge_reads_no_call_to_a_tool_that_only_reads_nor_to_lups(
    repo: Path,
) -> None:
    for tool in [*get_args(claude.Reading.__value__), "mcp__lup__ask"]:
        assert not claude.heard(pre_tool_use(repo, tool, {})).judged
        assert not claude.heard(finished(repo, tool, {})).judged


def test_codex_hooks_each_turns_start_and_the_judges_events_in_a_room() -> None:
    assert codex.hooks(hook_at, HOLD) == [
        Hook(
            event=events.SessionStarted,
            command=hook_at(events.SessionStarted),
            timeout=HOLD,
        ),
        Hook(
            event=events.TurnStarted, command=hook_at(events.TurnStarted), timeout=HOLD
        ),
        Hook(
            event=events.CallStarted, command=hook_at(events.CallStarted), timeout=HOLD
        ),
        Hook(
            event=events.CallFinished,
            command=hook_at(events.CallFinished),
            timeout=HOLD,
        ),
        Hook(event=events.TurnEnded, command=hook_at(events.TurnEnded), timeout=HOLD),
        Hook(
            event=events.ConversationEnded,
            command=hook_at(events.ConversationEnded),
            timeout=HOLD,
        ),
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


@pytest.mark.parametrize("event", ["PostToolUse", "PostToolUseFailure"])
def test_claude_tells_the_agent_of_a_checkpoint_its_judge_couldnt_answer(
    repo: Path, event: str
) -> None:
    raw = payload(repo, event, tool_name="Bash", tool_use_id="t1")

    answered = json.loads(claude.unanswered(raw, WHY))

    assert answered == {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": f"{SAID}. Tell the operator.",
        }
    }


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


# What the host service hears of each hook, and adds to its answer


TOLD = Telling(caller="c1")
ITEMS = Telling(caller="c1", items=["The operator answered.", "And again."])
BOTH = "The operator answered.\n\nAnd again."


@pytest.mark.parametrize(
    ("raw", "heard"),
    [
        (
            '{"session_id": "s1", "cwd": "/w", "hook_event_name": "SessionStart"}',
            Heard(
                fits=10_000, event=events.SessionStarted(), session="s1", judged=True
            ),
        ),
        (
            pre_tool_use(Path("/w"), "Write", {"file_path": "a", "content": "b"}),
            Heard(
                fits=10_000,
                event=events.CallStarted(call="t1", tool="Write"),
                session="s1",
                judged=True,
            ),
        ),
        (
            payload(
                Path("/w"),
                "PreToolUse",
                tool_name="Bash",
                tool_input={"command": "ls"},
                tool_use_id="t2",
                agent_id="a1",
            ),
            Heard(
                fits=10_000,
                event=events.CallStarted(call="t2", tool="Bash"),
                session="s1",
                agent="a1",
                judged=True,
            ),
        ),
        (
            pre_tool_use(Path("/w"), "Read", {"file_path": "/w/a.py"}, "t4"),
            Heard(
                fits=10_000,
                event=events.CallStarted(call="t4", tool="Read"),
                session="s1",
                judged=False,
            ),
        ),
        (
            pre_tool_use(Path("/w"), "mcp__lup__blocked", {"problem": "x"}, "t3"),
            Heard(
                fits=10_000,
                event=events.CallStarted(call="t3", tool="mcp__lup__blocked"),
                session="s1",
                served=True,
                judged=False,
            ),
        ),
        (
            payload(Path("/w"), "PostToolUse", tool_name="Bash", tool_use_id="t2"),
            Heard(
                fits=10_000,
                event=events.CallFinished(call="t2", tool="Bash"),
                session="s1",
                judged=True,
            ),
        ),
        (
            payload(
                Path("/w"), "PostToolUse", tool_name="mcp__lup__ask", tool_use_id="t3"
            ),
            Heard(
                fits=10_000,
                event=events.CallFinished(call="t3", tool="mcp__lup__ask"),
                session="s1",
                judged=False,
            ),
        ),
        (
            payload(Path("/w"), "Stop", stop_hook_active=False),
            Heard(fits=10_000, event=events.TurnEnded(), session="s1", judged=True),
        ),
        (
            payload(
                Path("/w"),
                "SubagentStop",
                agent_id="a1",
                last_assistant_message="Done.",
            ),
            Heard(
                fits=10_000,
                event=events.ConversationEnded(),
                session="s1",
                agent="a1",
                judged=True,
                said="Done.",
            ),
        ),
        (
            payload(Path("/w"), "SubagentStop", agent_id="a1"),
            Heard(
                fits=10_000,
                event=events.ConversationEnded(),
                session="s1",
                agent="a1",
                judged=True,
                stopped=True,
            ),
        ),
        (
            # A subagent's turn ending on an error from the model's API, as
            # 2.1.309 sent it: its last message is the error, not its words.
            payload(
                Path("/w"),
                "StopFailure",
                agent_id="a1",
                agent_type="general-purpose",
                prompt_id="p1",
                error="rate_limit",
                last_assistant_message="API Error: Request rejected (429)",
            ),
            Heard(
                fits=10_000,
                event=events.ConversationEnded(),
                session="s1",
                agent="a1",
                judged=True,
                failed=Failure(
                    kind="rate_limit", said="API Error: Request rejected (429)"
                ),
            ),
        ),
        (
            # The session's own: its turn's end, which the judge doesn't read.
            payload(
                Path("/w"),
                "StopFailure",
                error="server_error",
                last_assistant_message="API Error: 500",
            ),
            Heard(
                fits=10_000,
                event=events.TurnEnded(),
                session="s1",
                judged=False,
                failed=Failure(kind="server_error", said="API Error: 500"),
            ),
        ),
    ],
)
def test_claude_says_whos_speaking_and_whether_the_judge_reads_it(
    raw: str, heard: Heard
) -> None:
    assert claude.heard(raw) == heard


def test_claude_stamps_a_call_to_lups_tools_with_its_caller_and_no_decision() -> None:
    raw = pre_tool_use(Path("/w"), "mcp__lup__blocked", {"problem": "stuck"})

    assert json.loads(claude.told(raw, "", TOLD) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {"problem": "stuck", "caller": "c1", "call": "t1"},
        }
    }
    other = pre_tool_use(Path("/w"), "mcp__other__report", {"problem": "stuck"})
    assert claude.told(other, "", TOLD) is None
    refused = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "no",
            }
        }
    )
    assert claude.told(raw, refused, TOLD) is None


CLAUDE_PROMPT = json.dumps(
    {
        "session_id": "s1",
        "transcript_path": "/home/u/.claude/projects/-w/s1.jsonl",
        "cwd": "/w",
        "prompt_id": "p1",
        "permission_mode": "auto",
        "hook_event_name": "UserPromptSubmit",
        "prompt": '<channel source="lup" wake="t1">\nHi.\n</channel>',
    }
)
"""A turn's start as Claude Code 2.1.304 sent it for a channel's message, its paths shortened."""

CODEX_PROMPT = json.dumps(
    {
        "session_id": "t1",
        "turn_id": "u1",
        "transcript_path": None,
        "cwd": "/w",
        "hook_event_name": "UserPromptSubmit",
        "model": "gpt-5.5",
        "permission_mode": "default",
        "prompt": "Go on.",
    }
)
"""A turn's start with each field Codex's `user-prompt-submit.command.input` names."""


def test_each_runtime_hears_a_turns_start_with_its_prompt_and_tells_beside_it() -> None:
    for adapter, raw, session, prompt, titles in [
        (
            claude,
            CLAUDE_PROMPT,
            "s1",
            '<channel source="lup" wake="t1">\nHi.\n</channel>',
            True,
        ),
        (codex, CODEX_PROMPT, "t1", "Go on.", False),
    ]:
        assert adapter.heard(raw) == Heard(
            fits=10_000,
            event=events.TurnStarted(),
            session=session,
            judged=True,
            prompt=prompt,
            takes_title=titles,
        )
        assert adapter.told(raw, "", TOLD) is None
        assert json.loads(adapter.told(raw, "", ITEMS) or "") == {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": BOTH,
            }
        }


TITLE = Telling(caller="c1", title="parser-work")


def test_claude_hears_the_sessions_title_at_a_prompt_and_gives_it_one_where_told() -> (
    None
):
    titled = json.dumps({**json.loads(CLAUDE_PROMPT), "session_title": "dev"})
    heard = claude.heard(titled)
    assert (heard.title, heard.takes_title) == ("dev", True)
    subagent = json.dumps({**json.loads(titled), "agent_id": "a1"})
    assert not claude.heard(subagent).takes_title
    assert json.loads(claude.told(titled, "", TITLE) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "sessionTitle": "parser-work",
        }
    }
    both = Telling(caller="c1", items=ITEMS.items, title="parser-work")
    assert json.loads(claude.told(titled, "", both) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": BOTH,
            "sessionTitle": "parser-work",
        }
    }
    assert claude.told(titled, "", TOLD) is None


@pytest.mark.parametrize(
    ("source", "takes"),
    [
        ("startup", True),
        ("resume", True),
        ("fork", True),
        ("compact", False),
        ("clear", False),
    ],
)
def test_claude_takes_a_title_at_the_starts_sessiontitle_applies_at(
    source: str, *, takes: bool
) -> None:
    raw = payload(Path("/w"), "SessionStart", source=source, session_title="dev")
    heard = claude.heard(raw)
    assert (heard.title, heard.takes_title) == ("dev", takes)
    assert json.loads(claude.told(raw, "", TITLE) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "sessionTitle": "parser-work",
        }
    }


def test_codex_hears_no_title_and_gives_none() -> None:
    started = (CAPTURED / "1-session-start.json").read_text()
    for raw in [started, CODEX_PROMPT]:
        heard = codex.heard(raw)
        assert (heard.title, heard.takes_title) == (None, False)
        assert codex.told(raw, "", TITLE) is None
    both = Telling(caller="c1", items=ITEMS.items, title="parser-work")
    assert json.loads(codex.told(CODEX_PROMPT, "", both) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": BOTH,
        }
    }


def test_claude_pushes_through_a_channel_and_codex_takes_no_push() -> None:
    pushing = claude.adapter().pushing
    assert pushing is not None
    assert pushing.capabilities == {"claude/channel": {}}
    notice = pushing.notice("Hi.", "t1")
    assert (notice.method, notice.params) == (
        "notifications/claude/channel",
        {"content": "Hi.", "meta": {"wake": "t1"}},
    )
    assert codex.adapter().pushing is None


def test_claude_adds_what_a_conversation_is_told_to_every_answer() -> None:
    started = '{"session_id": "s1", "cwd": "/w", "hook_event_name": "SessionStart"}'
    assert json.loads(claude.told(started, "", ITEMS) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": BOTH,
        }
    }
    write = pre_tool_use(Path("/w"), "Write", {"file_path": "a", "content": "b"})
    for decision in ["allow", "deny"]:
        judged = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": "why",
                }
            }
        )
        assert json.loads(claude.told(write, judged, ITEMS) or "") == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": "why",
                "additionalContext": BOTH,
            }
        }
    stop = payload(Path("/w"), "Stop", stop_hook_active=False)
    assert claude.told(stop, "", TOLD) is None
    assert json.loads(claude.told(stop, "", ITEMS) or "") == {
        "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": BOTH}
    }
    noted = json.dumps({"systemMessage": "a note", "suppressOutput": True})
    assert json.loads(claude.told(stop, noted, ITEMS) or "") == {
        "systemMessage": "a note",
        "suppressOutput": True,
        "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": BOTH},
    }
    findings = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": "lup won't end the turn yet.",
            }
        }
    )
    assert json.loads(claude.told(stop, findings, ITEMS) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": f"lup won't end the turn yet.\n\n{BOTH}",
        }
    }
    subagent = payload(Path("/w"), "SubagentStop", agent_id="a1")
    assert json.loads(claude.told(subagent, "", ITEMS) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "additionalContext": BOTH,
        }
    }


def codex_lups(arguments: object) -> str:
    """The shell call Codex 0.162.1 sent, as a call to one of lup's tools: an MCP tool's hook carries its arguments as `tool_input`."""
    sent = json.loads((CAPTURED / "6-pre-tool-use-bash.json").read_text())
    return json.dumps(
        {**sent, "tool_name": "mcp__lup__blocked", "tool_input": arguments}
    )


def test_codex_says_whos_speaking_and_that_the_judge_reads_every_hook() -> None:
    sent = {
        name: (CAPTURED / f"{name}.json").read_text()
        for name in ["1-session-start", "2-pre-tool-use-add", "3-post-tool-use-add"]
    }
    session = json.loads(sent["1-session-start"])["session_id"]
    patch = json.loads(sent["2-pre-tool-use-add"])["tool_use_id"]

    assert [codex.heard(raw) for raw in sent.values()] == [
        Heard(
            fits=10_000,
            event=events.SessionStarted(),
            session=session,
            judged=True,
            fresh=True,
        ),
        Heard(
            fits=10_000,
            event=events.CallStarted(call=patch, tool="apply_patch"),
            session=session,
            judged=True,
        ),
        Heard(
            fits=10_000,
            event=events.CallFinished(call=patch, tool="apply_patch"),
            session=session,
            judged=True,
        ),
    ]
    stop = codex.heard((CAPTURED / "9-stop.json").read_text())
    assert stop == Heard(
        fits=10_000, event=events.TurnEnded(), session=session, judged=True, said="done"
    )
    subagent = codex.heard(
        json.dumps(
            {
                "session_id": session,
                "cwd": "/w",
                "hook_event_name": "SubagentStop",
                "agent_id": "a1",
                "last_assistant_message": "Found three.",
            }
        )
    )
    assert subagent == Heard(
        fits=10_000,
        event=events.ConversationEnded(),
        session=session,
        agent="a1",
        judged=True,
        said="Found three.",
    )


def test_codex_stamps_each_call_of_one_conversation_with_one_id_beside_allow() -> None:
    conversations = Conversations()

    def stamped(problem: str) -> dict[str, object]:
        raw = codex_lups({"problem": problem})
        heard = codex.heard(raw)
        caller = conversations.named(heard.session, heard.agent).id
        output = json.loads(codex.told(raw, "", Telling(caller=caller)) or "")
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
        return output["hookSpecificOutput"]["updatedInput"]

    first, second = stamped("stuck"), stamped("still stuck")
    call = json.loads(codex_lups({}))["tool_use_id"]
    assert first == {"problem": "stuck", "caller": first["caller"], "call": call}
    assert second == {"problem": "still stuck", "caller": first["caller"], "call": call}
    assert codex.told(codex_lups("not json"), "", TOLD) is None
    bash = (CAPTURED / "6-pre-tool-use-bash.json").read_text()
    assert codex.told(bash, "", TOLD) is None


def test_codex_stamps_a_call_its_judge_couldnt_answer_and_keeps_the_warning() -> None:
    raw = codex_lups({"problem": "stuck"})

    output = json.loads(codex.told(raw, codex.unanswered(raw, WHY), TOLD) or "")

    assert output == {
        "systemMessage": SAID,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {
                "problem": "stuck",
                "caller": "c1",
                "call": json.loads(raw)["tool_use_id"],
            },
        },
    }


def test_codex_adds_what_a_conversation_is_told_to_every_answer() -> None:
    started = (CAPTURED / "1-session-start.json").read_text()
    assert json.loads(codex.told(started, "", ITEMS) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": BOTH,
        }
    }
    finished = (CAPTURED / "3-post-tool-use-add.json").read_text()
    reported = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "lup refused 1 file.",
            }
        }
    )
    assert json.loads(codex.told(finished, reported, ITEMS) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"lup refused 1 file.\n\n{BOTH}",
        }
    }
    stop = (CAPTURED / "9-stop.json").read_text()
    assert codex.told(stop, "", TOLD) is None
    held = json.dumps({"decision": "block", "reason": "Type errors left."})
    assert json.loads(codex.told(stop, held, ITEMS) or "") == {
        "decision": "block",
        "reason": f"Type errors left.\n\n{BOTH}",
    }
    noted = json.dumps({"systemMessage": "The judge failed."})
    assert json.loads(codex.told(stop, noted, ITEMS) or "") == {
        "systemMessage": "The judge failed.",
        "decision": "block",
        "reason": BOTH,
    }


DUE = (
    "Work deferred in this repository came due, as the gate last found it (it "
    "doesn't fail the gate):\n- src/pkg/core.py:3: issue #12 is closed; finish the "
    "work here"
)


def came_due(repo: Path) -> None:
    """Keep a deferral the gate found due, as `lup-dev rules check` over every file does."""
    reminder = Finding(
        path=CORE,
        span=Span(start=Position(line=3, column=1), end=Position(line=3, column=1)),
        owner="lup",
        rule="defer-closed",
        message="issue #12 is closed",
        steer="finish the work here",
        reminder=True,
    )
    write_model(repo / ".git" / "lup" / "due.json", Due(reminders=[reminder]))


def test_claude_tells_what_came_due_as_a_session_starts_before_its_items_and_titles_it(
    on_claude: Bench, repo: Path
) -> None:
    came_due(repo)
    raw = payload(repo, "SessionStart", source="startup")

    answer = claude.hook(raw, on_claude)
    both = Telling(caller="c1", items=ITEMS.items, title="parser-work")

    assert json.loads(answer) == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": DUE,
        }
    }
    assert json.loads(claude.told(raw, answer, both) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": f"{DUE}\n\n{BOTH}",
            "sessionTitle": "parser-work",
        }
    }
    subagent = payload(repo, "SessionStart", source="startup", agent_id="a1")
    assert claude.hook(subagent, on_claude) == ""


def test_codex_tells_what_came_due_as_a_session_starts_before_its_items(
    on_codex: Bench, repo: Path
) -> None:
    came_due(repo)
    raw = payload(repo, "SessionStart", source="startup")

    answer = codex.hook(raw, on_codex)

    assert json.loads(answer) == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": DUE,
        }
    }
    assert json.loads(codex.told(raw, answer, ITEMS) or "") == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": f"{DUE}\n\n{BOTH}",
        }
    }
    subagent = payload(repo, "SessionStart", source="startup", agent_id="a1")
    assert codex.hook(subagent, on_codex) == ""


def test_claude_reads_a_subagents_name_kind_and_spawn_from_its_record(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "s1.jsonl"
    records = tmp_path / "s1" / "subagents"
    records.mkdir(parents=True)
    (records / "agent-a1.meta.json").write_text(
        json.dumps(
            {
                "agentType": "Explore",
                "description": "Find the auth code",
                "name": "explore-auth",
                "toolUseId": "toolu_1",
                "spawnDepth": 1,
            }
        )
    )
    (records / "agent-a2.meta.json").write_text(
        json.dumps(
            {
                "agentType": "general-purpose",
                "description": "Nested probe",
                "toolUseId": "toolu_2",
                "parentAgentId": "a1",
                "spawnDepth": 2,
            }
        )
    )

    def subagent(agent: str, kind: str) -> str:
        return payload(
            Path("/w"),
            "PreToolUse",
            tool_name="Bash",
            tool_input={"command": "ls"},
            tool_use_id="c1",
            agent_id=agent,
            agent_type=kind,
            transcript_path=str(transcript),
        )

    assert claude.spawned(subagent("a1", "Explore")) == Spawned(
        name="explore-auth", kind="Explore", handed=True
    )
    assert claude.spawned(subagent("a2", "general-purpose")) == Spawned(
        parent="a1", kind="general-purpose", handed=True
    )
    assert claude.spawned(subagent("a3", "Plan")) == Spawned(kind="Plan", handed=True)
    assert claude.spawned(subagent("a4", "fork")) == Spawned(
        kind="fork", guided=True, handed=True
    )
    # Claude Code's own agents, a prompt's suggestion among them: no type, no record.
    assert claude.spawned(subagent("a5", "")) == Spawned(internal=True, handed=True)
    # A progress summary's fork calling a tool, as 2.1.309 hooks it: no type at all.
    fork = payload(
        Path("/w"),
        "PreToolUse",
        tool_name="Bash",
        tool_input={"command": "ls"},
        tool_use_id="c2",
        agent_id="a6",
        transcript_path=str(transcript),
    )
    assert claude.spawned(fork) == Spawned(internal=True, handed=True)
    assert claude.spawned(pre_tool_use(Path("/w"), "Bash", {"command": "ls"})) is None


def test_codex_reads_a_subagents_name_parent_and_role_from_its_rollout(
    tmp_path: Path,
) -> None:
    def rollout(thread: str, parent: str, path: str | None) -> Path:
        meta: dict[str, object] = {
            "id": thread,
            "session_id": "root",
            "parent_thread_id": parent,
            "agent_role": "explorer",
        }
        if path is not None:
            meta["agent_path"] = path
        written = tmp_path / f"rollout-{thread}.jsonl"
        lines = [
            json.dumps({"type": "session_meta", "payload": meta}),
            json.dumps({"type": "turn_context", "payload": {}}),
        ]
        written.write_text("\n".join(lines) + "\n")
        return written

    def subagent(thread: str, transcript: Path | None) -> str:
        return json.dumps(
            {
                "session_id": "root",
                "cwd": "/w",
                "hook_event_name": "PreToolUse",
                "agent_id": thread,
                "agent_type": "explorer",
                "transcript_path": None if transcript is None else str(transcript),
            }
        )

    def ended(thread: str, own: Path, parent: Path) -> str:
        return json.dumps(
            {
                "session_id": "root",
                "cwd": "/w",
                "hook_event_name": "SubagentStop",
                "agent_id": thread,
                "agent_type": "explorer",
                "transcript_path": str(parent),
                "agent_transcript_path": str(own),
                "last_assistant_message": "Done.",
            }
        )

    child = rollout("th-a1", "root", "/root/explore_auth")
    grandchild = rollout("th-a2", "th-a1", "/root/explore_auth/grep_tokens")
    unnamed = rollout("th-a3", "root", None)
    roots = tmp_path / "rollout-root.jsonl"
    roots.write_text(
        json.dumps(
            {"type": "session_meta", "payload": {"id": "root", "session_id": "root"}}
        )
        + "\n"
    )

    assert codex.spawned(subagent("th-a1", child)) == Spawned(
        name="explore_auth", kind="explorer", guided=True, handed=True
    )
    grandchilds = Spawned(
        name="grep_tokens", parent="th-a1", kind="explorer", guided=True, handed=True
    )
    assert codex.spawned(subagent("th-a2", grandchild)) == grandchilds
    # First heard at its end, which names its parent's rollout and its own.
    assert codex.spawned(ended("th-a2", grandchild, child)) == grandchilds
    explorer = Spawned(kind="explorer", guided=True)
    assert codex.spawned(subagent("th-a3", unnamed)) == explorer
    assert codex.spawned(subagent("th-a4", None)) == explorer
    assert codex.spawned(subagent("th-a1", roots)) == explorer
    assert codex.spawned((CAPTURED / "6-pre-tool-use-bash.json").read_text()) is None


@pytest.mark.parametrize(
    ("source", "fresh"),
    [
        ("startup", True),
        ("clear", True),
        ("resume", False),
        ("compact", False),
        ("fork", False),
    ],
)
def test_each_runtime_hears_whether_a_sessions_own_conversation_starts_empty(
    source: str, *, fresh: bool
) -> None:
    from_claude = payload(Path("/w"), "SessionStart", source=source)
    started = json.loads((CAPTURED / "1-session-start.json").read_text())
    from_codex = json.dumps({**started, "source": source})
    assert claude.heard(from_claude).fresh is fresh
    assert codex.heard(from_codex).fresh is fresh
    subagent = json.dumps({**json.loads(from_claude), "agent_id": "a1"})
    assert not claude.heard(subagent).fresh


# Quiet on each runtime: `quiet` runs as a repository's process runs it, with
# the launch's runtime, and each runtime's hooks tell what it doesn't hold.


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_each_runtime_tells_nothing_a_quiet_holds_and_tells_it_as_it_lifts(
    kit: Kit, repo: Path, runtime: str
) -> None:
    known = cli.Adapters(known=cli.adapters())
    adapter = known.named(runtime)
    bench = Bench(runtime=adapter.runtime, services=kit.bench.services)
    launch = Register.model_construct(
        launch="one", runtime=runtime, repository=repo / ".git"
    )

    def quiet(*kinds: str) -> str:
        calling = JudgeCalling(
            launch=launch,
            name="quiet",
            arguments={"kinds": list(kinds)},
            caller=Conversation(id="c", session="s1"),
        )
        answer = asyncio.run(known.called(calling, kit.bench.services))
        assert not answer.error, answer.text
        return answer.text

    def shell(call: str, write: str) -> str:
        """A shell call that writes `CORE`, as the runtime's hooks report it: what its finish prints."""
        fields: dict[str, object] = {
            "turn_id": "u1",
            "tool_name": "Bash",
            "tool_input": {"command": "sed"},
            "tool_use_id": call,
        }
        adapter.hook(payload(repo, "PreToolUse", **fields), bench)
        (repo / CORE).write_text(write)
        finished = payload(repo, "PostToolUse", **fields, tool_response={})
        return adapter.hook(finished, bench)

    adapter.hook(payload(repo, "SessionStart", source="startup"), bench)
    quiet("changed")
    broken = (repo / CORE).read_text() + "z: str = 1  # TYPE\n"
    assert shell("t1", broken) == ""
    compacted = adapter.hook(payload(repo, "SessionStart", source="compact"), bench)
    reminded = json.loads(compacted)["hookSpecificOutput"]["additionalContext"]
    assert reminded.startswith("This conversation is still quiet: lup doesn't tell it")
    assert shell("t2", broken + "\n") == ""
    lifted = quiet()
    assert f"{repo}/src/pkg/core.py:11:" in lifted
    told = shell("t3", broken + "\nw: str = 2  # TYPE\n")
    said = json.loads(told)["hookSpecificOutput"]["additionalContext"]
    assert f"{repo}/src/pkg/core.py:13:" in said
    assert "core.py:11:" not in said
