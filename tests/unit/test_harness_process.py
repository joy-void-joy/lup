"""Behavioral tests for the local process launcher's capture contract."""

from pathlib import Path

from lup.harness.models import LaunchRequest
from lup.harness.process import LocalProcessLauncher


def test_captured_stdout_is_not_a_terminal(tmp_path: Path) -> None:
    status = LocalProcessLauncher().launch(
        LaunchRequest(arguments=["test", "-t", "1"], cwd=tmp_path)
    )
    assert status.code == 1


def test_git_output_stays_plain_under_pager_environments(tmp_path: Path) -> None:
    launcher = LocalProcessLauncher()

    def git(*arguments: str) -> None:
        status = launcher.launch(
            LaunchRequest(arguments=["git", *arguments], cwd=tmp_path)
        )
        assert status.code == 0, status.stderr

    git("init", "-b", "main")
    git("config", "user.email", "launcher@example.test")
    git("config", "user.name", "Launcher Test")
    (tmp_path / "tracked.txt").write_text("base\n", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-m", "base")
    (tmp_path / "tracked.txt").write_text("changed\n", encoding="utf-8")
    named = launcher.launch(
        LaunchRequest(
            arguments=["git", "diff", "--name-only", "HEAD"],
            cwd=tmp_path,
            environment={"GIT_PAGER": "less", "LESS": ""},
        )
    )
    assert named.code == 0
    assert "\x1b" not in named.stdout
    assert named.stdout.split() == ["tracked.txt"]
