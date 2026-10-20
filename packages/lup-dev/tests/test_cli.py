"""The `lup-dev` command: hooks, the rule check, holds and verdicts."""

import json
import socketserver
import threading
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self

from typer.testing import CliRunner

from lup_dev import Rules, cli
from lup_dev.codescan.contract import Due
from lup_dev.codescan.directives import GitHubIssues, IssueRef, Issues
from lup_dev.codescan.engine import EngineChecker
from lup_dev.declaration.modules.code_rules import lup_default
from lup_dev.declaration.runner import Plain, Prefixed
from lup_dev.forge.protocol import IssueState, Stated
from lup_dev.host.client import RoomClient
from lup_dev.host.protocol import Refused, Reply
from lup_dev.policy.importers import Conversation, ImportersPass
from lup_dev.policy.verdicts import Verdict, VerdictLog
from lup_dev.stored import read_model

if TYPE_CHECKING:
    import pytest
    from conftest import FakeClock, Kit, Shell

    from lup_dev.layout import Layout

runner = CliRunner()


def test_verdicts_summarizes_this_repository(
    state: Layout,
    repo: Path,
    shell: Shell,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = Path(
        shell.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    monkeypatch.setattr(cli, "SystemClock", lambda: clock)
    now = clock.now()
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


def test_rules_fix_removes_each_ignore_keeping_nothing_and_rules_check_reports_it(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = repo / "src" / "pkg" / "core.py"
    core.write_text(
        'x = 1  # lup: ignore("regex", why="nothing fires")\n'
        '# lup: ignore("tuple-shape", why="nothing fires")\n'
        "y = 2\n"
        'z = (1, 2)  # BAD tuple-shape  # lup: ignore("tuple-shape", why="sh")\n'
    )
    monkeypatch.chdir(repo)
    checked = runner.invoke(cli.app, ["rules", "check"])
    assert checked.exit_code == 1
    assert sum("unused-ignore" in line for line in checked.output.splitlines()) == 2
    fixed = runner.invoke(cli.app, ["rules", "fix"])
    assert fixed.exit_code == 0
    assert core.read_text() == (
        "x = 1\n"
        "y = 2\n"
        'z = (1, 2)  # BAD tuple-shape  # lup: ignore("tuple-shape", why="sh")\n'
    )
    assert runner.invoke(cli.app, ["rules", "check"]).exit_code == 0


PLAIN = (
    "from lup_dev import Modules, Plain, Project, Python\n"
    "project = Project(modules=Modules.default().edit(Python(runner=Plain())))\n"
)
"""A declaration whose tools run as the `PATH` finds them."""


def test_rules_check_runs_the_engine_and_ruff_with_the_worktrees_runner(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "lup_project.py").write_text(PLAIN)
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "check"])
    assert result.exit_code == 0, result.output
    plain = Prefixed.of(Plain())
    assert fakes.engine.runners == [plain]
    assert fakes.linter.runners == [plain]


def test_the_importers_pass_asks_with_the_runner_the_judge_reads(
    fakes: Kit, state: Layout, repo: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    (repo / "lup_project.py").write_text(PLAIN)
    shell.commit(repo, "dev: no uv")
    (repo / "lup_project.py").write_text(
        "from lup_dev import Project\nproject = Project()\n"
    )
    pending = ImportersPass(layout=state.store(repo), root=repo)
    changed = Path("src/pkg/core.py")
    pending.request([changed], [Conversation(session="s1")], fakes.spawner)
    result = runner.invoke(cli.app, ["importers", str(repo)])
    assert result.exit_code == 0, result.output
    assert fakes.engine.importers_asked == [[changed]]
    assert fakes.engine.runners == [Prefixed.of(Plain())]


def test_rules_check_reads_protected_modules_with_lups_rules(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = repo / ".claude" / "hooks" / "check.py"
    hook.parent.mkdir(parents=True)
    hook.write_text("x = 1  # BAD regex\n")
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "check", ".claude/hooks/check.py"])
    assert result.exit_code == 1
    assert ".claude/hooks/check.py:1:8 - regex: regex fires here" in result.output


def test_rules_check_leaves_excluded_paths_out(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "lup_project.py").write_text(
        "from lup_dev import Core, Modules, Paths, Project\n"
        "excluding = Core(paths=Paths().add(excluded=['vendor/**']))\n"
        "project = Project(modules=Modules.default().edit(excluding))\n"
    )
    (repo / "vendor").mkdir()
    (repo / "vendor" / "lib.py").write_text("x = 1  # BAD regex\n")
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "check", "vendor/lib.py"])
    assert result.exit_code == 0
    assert result.output.strip() == "lup checked no files."


def test_rules_check_lists_every_file_on_disk_its_names_kept_whole(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "tests" / "test_core.py").unlink()
    (repo / "src" / "pkg" / 'odd "name".py').write_text("x = 1  # BAD regex\n")
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "check"])
    assert result.exit_code == 1
    assert 'src/pkg/odd "name".py:1:8 - regex: regex fires here' in result.output
    assert result.output.splitlines()[-1] == "lup checked 3 files: 1 findings."


def test_rules_check_lifts_an_exempt_rule_from_its_paths(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "lup_project.py").write_text(
        "from lup_dev import CodeRules, Exemption, Exemptions, Modules, Project\n"
        "lifted = Exemption(rule='regex', paths=['src/pkg/**'], why='a grammar')\n"
        "lifting = CodeRules(exempt=Exemptions().add(lifted))\n"
        "project = Project(modules=Modules.default().edit(lifting))\n"
    )
    (repo / "src" / "pkg" / "core.py").write_text(
        "x = 1  # BAD regex\ny = (1, 2)  # BAD tuple-shape\n"
    )
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "check", "src/pkg/core.py"])
    assert result.exit_code == 1
    assert "tuple-shape" in result.output
    assert "regex" not in result.output


def test_rules_check_sends_the_worktrees_rule_selection(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "lup_project.py").write_text(
        "from lup_dev import CodeRules, Modules, Project, Rules\n"
        "project = Project(\n"
        '    modules=Modules.default().edit(CodeRules(rules=Rules.only("regex"))),\n'
        ")\n"
    )
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "check", "src/pkg/core.py"])
    assert result.exit_code == 0
    [[code_rules]] = fakes.engine.selections
    assert (code_rules.module, code_rules.rules) == ("code-rules", Rules.only("regex"))
    assert code_rules.default == lup_default()


ONLY_TUPLES = (
    "from lup_dev import CodeRules, Modules, Project, Rules\n"
    "project = Project(\n"
    '    modules=Modules.default().edit(CodeRules(rules=Rules.only("tuple-shape"))),\n'
    ")\n"
)
"""A declaration whose code rules are `tuple-shape` alone."""


def test_rules_list_lists_the_rules_the_worktrees_selection_runs(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "lup_project.py").write_text(ONLY_TUPLES)
    fakes.engine.running = ["tuple-shape"]
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "list"])
    assert result.exit_code == 0
    assert result.output == (
        "tuple-shape: The mistake tuple-shape prevents.\n"
        "    steer: Where tuple-shape steers.\n"
    )
    [[code_rules]] = fakes.engine.listed_for
    assert (code_rules.module, code_rules.rules) == (
        "code-rules",
        Rules.only("tuple-shape"),
    )


def test_rules_list_all_lists_the_table_marking_what_the_project_leaves_out(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "lup_project.py").write_text(ONLY_TUPLES)
    fakes.engine.running = ["tuple-shape"]
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "list", "--all"])
    assert result.exit_code == 0
    assert result.output == (
        "regex (left out): The mistake regex prevents.\n"
        "    steer: Where regex steers.\n"
        "tuple-shape: The mistake tuple-shape prevents.\n"
        "    steer: Where tuple-shape steers.\n"
    )


class Closed(Issues):
    def state(self, issue: IssueRef) -> Literal["open", "closed"]:
        return "closed"

    def unreachable(self) -> str | None:
        return None


class Unreachable(Issues):
    def state(self, issue: IssueRef) -> Literal["open", "closed"]:
        message = "an unreachable tracker isn't asked"
        raise AssertionError(message)

    def unreachable(self) -> str | None:
        return "`gh` isn't installed here"


def test_rules_check_lists_a_deferral_whose_issue_closed_without_failing(
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
    assert result.exit_code == 0, result.output
    assert (
        "Work deferred in this repository came due, as the gate last found it (it "
        "doesn't fail the gate):\n- src/pkg/core.py:1: issue #12 is closed; finish "
        "the work here, or point at the issue tracking what's left\n"
    ) in result.output
    assert result.output.endswith("lup checked 1 files: 0 findings.\n")
    assert "weren't checked" not in result.output
    common = repo / ".git"
    assert not (common / "lup" / "due.json").exists()


def test_rules_check_over_every_file_keeps_what_came_due_for_a_session(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "src" / "pkg" / "core.py").write_text(
        'x = 1  # lup: defer(issue=12, why="retry on reset")\n'
    )

    def issues(root: Path) -> Issues:
        return Closed()

    monkeypatch.setattr(cli, "GitHubIssues", issues)
    monkeypatch.chdir(repo)
    first = runner.invoke(cli.app, ["rules", "check"])
    kept = read_model(repo / ".git" / "lup" / "due.json", Due)
    (repo / "src" / "pkg" / "core.py").write_text("x = 1\n")
    second = runner.invoke(cli.app, ["rules", "check"])
    cleared = read_model(repo / ".git" / "lup" / "due.json", Due)

    assert (first.exit_code, second.exit_code) == (0, 0)
    assert kept is not None
    assert [each.rule for each in kept.reminders] == ["defer-closed"]
    assert cleared == Due()


def test_rules_check_says_it_left_issues_unchecked_where_the_tracker_is_out_of_reach(
    fakes: Kit, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "src" / "pkg" / "core.py").write_text(
        'x = 1  # lup: defer(issue=12, why="retry on reset")\n'
    )

    def issues(root: Path) -> Issues:
        return Unreachable()

    monkeypatch.setattr(cli, "GitHubIssues", issues)
    monkeypatch.chdir(repo)
    result = runner.invoke(cli.app, ["rules", "check", "src/pkg/core.py"])
    assert result.exit_code == 0
    assert (
        "Deferrals' issues weren't checked: `gh` isn't installed here." in result.output
    )


class Host:
    """A launch's request socket, the host answering every request with one reply, each request kept."""

    def __init__(self, path: Path, reply: Reply) -> None:
        self.requests: list[str] = []
        recorded = self.requests

        class Handled(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                recorded.append(self.rfile.read().decode())
                self.wfile.write(reply.model_dump_json().encode())

        self.server = socketserver.UnixStreamServer(str(path), Handled)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> Self:
        self.thread.start()
        return self

    def __exit__(self, *exited: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=60)


def test_rules_check_in_a_room_asks_the_host_for_each_issues_state(
    fakes: Kit, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "src" / "pkg" / "core.py").write_text(
        'x = 1  # lup: defer(issue="cli/cli#12", why="retry on reset")\n'
    )
    socket = tmp_path / "request.sock"

    def room() -> RoomClient:
        return RoomClient(socket=socket)

    monkeypatch.setattr(cli, "RoomClient", room)
    monkeypatch.chdir(repo)
    with Host(socket, Stated(state="closed")) as host:
        result = runner.invoke(cli.app, ["rules", "check", "src/pkg/core.py"])
    assert result.exit_code == 0
    assert "- src/pkg/core.py:1: issue cli/cli#12 is closed;" in result.output
    assert [IssueState.model_validate_json(each) for each in host.requests] == [
        IssueState(repository="cli/cli", number=12)
    ]


def test_rules_check_in_a_room_says_an_issue_the_host_didnt_answer_went_unchecked(
    fakes: Kit, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "src" / "pkg" / "core.py").write_text(
        'x = 1  # lup: defer(issue=12, why="retry on reset")\n'
    )
    socket = tmp_path / "request.sock"

    def room() -> RoomClient:
        return RoomClient(socket=socket)

    monkeypatch.setattr(cli, "RoomClient", room)
    monkeypatch.chdir(repo)
    older = Refused(
        error="no handler for `issue-state`; a room's request socket answers git-list"
    )
    with Host(socket, older):
        result = runner.invoke(cli.app, ["rules", "check", "src/pkg/core.py"])
    assert result.exit_code == 0
    assert (
        "Issue #12 went unchecked: the host service said no handler for "
        "`issue-state`; a room's request socket answers git-list."
    ) in result.output


def test_github_is_out_of_reach_without_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()
    monkeypatch.setenv("PATH", str(tmp_path))
    assert GitHubIssues(root=tmp_path).unreachable() == "`gh` isn't installed here"


def test_github_is_out_of_reach_where_gh_has_no_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\nexit 1\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    reason = GitHubIssues(root=tmp_path).unreachable()
    assert reason is not None
    assert reason.startswith("`gh auth status` ended with status 1")


def test_the_engine_is_the_worktree_engine_as_settings_place_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("LUP_ENGINE_IDLE", "PT90S")
    engine = cli.engine()
    assert isinstance(engine, EngineChecker)
    assert engine.layout.runtime == tmp_path / "run" / "lup"
    assert engine.idle == timedelta(seconds=90)
