"""The `lup-dev` command: hooks, the rule check, holds and verdicts."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pytest
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.directives import IssueRef, Issues
from lup_dev.holds import HeldFile, HoldError, Holds, waiting
from lup_dev.layout import Layout
from lup_dev.verdicts import Verdict, VerdictLog

if TYPE_CHECKING:
    from conftest import Kit, Shell

    from lup_dev.checker import Checker
    from lup_dev.checkpoint import Services
    from lup_dev.ruff import Linter

runner = CliRunner()


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Layout:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    return Layout(state=tmp_path / "xdg" / "lup")


@pytest.fixture
def fakes(kit: Kit, state: Layout, monkeypatch: pytest.MonkeyPatch) -> Kit:
    services = kit.bench.services.model_copy(update={"layout": state})

    def engine() -> Checker:
        return kit.engine

    def linter() -> Linter:
        return kit.linter

    def configured() -> Services:
        return services

    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr(cli, "Ruff", linter)
    monkeypatch.setattr(cli, "services", configured)
    return kit


def hold(state: Layout, kit: Kit, worktree: Path) -> str:
    files = [
        HeldFile(
            path=Path("src/new.py"),
            role="production",
            blob="abc",
            reasons=["new-file"],
            asks=["src/new.py is a new production file"],
        )
    ]
    return (
        Holds(layout=state.store(worktree))
        .create(worktree, "s1", files, "+new\n", kit.clock)
        .key
    )


def test_holds_lists_whats_waiting_with_its_diff(
    state: Layout, kit: Kit, tmp_path: Path
) -> None:
    key = hold(state, kit, tmp_path)
    result = runner.invoke(cli.app, ["holds"])
    assert result.exit_code == 0
    assert key in result.output
    assert "src/new.py: src/new.py is a new production file" in result.output
    assert "+new" in result.output


def test_holds_approve_and_decline(state: Layout, kit: Kit, tmp_path: Path) -> None:
    first = hold(state, kit, tmp_path)
    second = hold(state, kit, tmp_path)
    assert (
        runner.invoke(
            cli.app, ["holds", "approve", first, "--comment", "fine"]
        ).exit_code
        == 0
    )
    assert runner.invoke(cli.app, ["holds", "decline", second]).exit_code != 0
    assert (
        runner.invoke(
            cli.app, ["holds", "decline", second, "--comment", "no"]
        ).exit_code
        == 0
    )
    assert waiting(state) == []


def test_holds_arent_answered_from_inside_a_session(
    state: Layout, kit: Kit, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = hold(state, kit, tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    result = runner.invoke(cli.app, ["holds", "approve", key])
    assert isinstance(result.exception, HoldError)
    assert [each.key for each in waiting(state)] == [key]


def test_verdicts_summarizes_this_repository(
    state: Layout, repo: Path, shell: Shell, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = Path(
        shell.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    now = datetime.now(UTC)
    VerdictLog(path=state.verdicts(common)).append(
        [
            Verdict(
                key="1",
                time=now,
                session="s",
                runtime="claude",
                tool="Write",
                path=Path("a.py"),
                role="production",
                outcome="ask",
                reasons=["new-file"],
                answer="approved",
            ),
            Verdict(
                key="2",
                time=now,
                session="s",
                runtime="claude",
                tool="Edit",
                path=Path("a.py"),
                role="production",
                outcome="refuse",
                reasons=["regex"],
            ),
        ]
    )
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["verdicts"])
    assert result.exit_code == 0
    assert "ask     new-file  (approved 1, declined 0, unanswered 0)" in result.output
    assert "refuse  regex" in result.output


def test_the_hook_commands_answer_on_stdout(fakes: Kit, repo: Path) -> None:
    raw = json.dumps(
        {
            "session_id": "s1",
            "cwd": str(repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "README.md", "content": "# New\n"},
            "tool_use_id": "t1",
        }
    )
    result = runner.invoke(cli.app, ["hook", "claude"], input=raw)
    assert (
        json.loads(result.output)["hookSpecificOutput"]["permissionDecision"] == "allow"
    )
    codex_raw = json.dumps(
        {**json.loads(raw), "turn_id": "u1", "tool_name": "Bash", "tool_use_id": "b1"}
    )
    assert runner.invoke(cli.app, ["hook", "codex"], input=codex_raw).output == ""


def test_rules_check_reports_every_owner_through_lups_ignore(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "src" / "pkg" / "core.py").write_text(
        "x = 1  # BAD regex\n"
        'y = (1, 2)  # BAD tuple-shape  # lup: ignore("tuple-shape", why="sh")\n'
        "z: int = 'a'  # TYPE\n"
    )
    (repo / "tests" / "test_core.py").write_text(
        "w = 1  # BAD regex\nv: int = 'a'  # TYPE\n"
    )
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "check"])
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert "src/pkg/core.py:1:8 - regex: regex fires here" in lines
    assert not any("tuple-shape" in line for line in lines)
    assert any(line.startswith("src/pkg/core.py:3:") for line in lines)
    assert any(line.startswith("tests/test_core.py:2:") for line in lines)
    assert not any(line.startswith("tests/test_core.py:1:") for line in lines)
    assert lines[-1] == "lup checked 3 files: 3 findings."


class Closed(Issues):
    def state(self, issue: IssueRef) -> Literal["open", "closed"]:
        return "closed"


def test_rules_check_fails_on_a_deferral_whose_issue_closed(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "src" / "pkg" / "core.py").write_text(
        'x = 1  # lup: defer(issue=12, why="retry on reset")\n'
    )

    def issues(root: Path) -> Issues:
        return Closed()

    monkeypatch.setattr(cli, "GitHubIssues", issues)
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "check", "src/pkg/core.py"])
    assert result.exit_code == 1
    assert "src/pkg/core.py:1:1 - defer-closed: issue #12 is closed" in result.output


def test_the_engine_is_missing_until_it_lands() -> None:
    with pytest.raises(cli.EngineMissingError):
        cli.engine()
