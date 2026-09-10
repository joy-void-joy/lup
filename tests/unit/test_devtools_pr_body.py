"""What ``dev pr-body`` says about a branch, against what the branch holds.

A generated body is pasted into a pull request and read there as a
description of the change, so a summary naming one of two commits and a test
plan nobody wrote are both claims the branch does not support. These pin the
three: every commit appears, the English is the project's own, and the test
plan is derived from the diff or absent.
"""

import pytest

from lup.devtools.dev import branches


COMMITS = [
    "66f3fe1e fix(harness): say that a bridged sign-in ends on a browser error",
    "a6ad379b fix(harness): re-seed a contained login that can no longer be renewed",
]


class StubGit:
    """A git answering one log and one diff, whichever order they are asked in."""

    def __init__(self, log: list[str], diff: list[str]) -> None:
        self.log = log
        self.diff = diff

    def lines(self, *arguments: str, **options: object) -> list[str]:
        return self.log if arguments[0] == "log" else self.diff


def body(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    log: list[str],
    diff: list[str],
) -> str:
    monkeypatch.setattr(branches, "git", StubGit(log, diff))
    branches.pr_body(base_override="feat-boundary")
    return capsys.readouterr().out


def test_every_commit_reaches_the_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The second commit is the substantive one, and it was the one folded away."""
    rendered = body(monkeypatch, capsys, COMMITS, [])

    assert "- say that a bridged sign-in ends on a browser error" in rendered
    assert "- re-seed a contained login that can no longer be renewed" in rendered
    assert "more)" not in rendered


def test_the_type_stands_over_its_commits_rather_than_opening_a_sentence(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A declarative subject reads under a noun phrase and not after a verb."""
    rendered = body(monkeypatch, capsys, COMMITS, [])

    assert "**Fixes**" in rendered
    assert "Fixed say" not in rendered


def test_the_test_plan_names_the_tests_the_branch_touches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    changed = [
        "packages/lup/src/lup/devtools/dev/pr.py",
        "tests/unit/test_devtools_check_state.py",
    ]

    rendered = body(monkeypatch, capsys, COMMITS, changed)

    assert "## Test plan" in rendered
    assert "- [ ] `tests/unit/test_devtools_check_state.py`" in rendered
    assert "pr.py`" not in rendered


def test_a_branch_touching_no_test_claims_no_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An absent section is what the branch supports; a checklist is not."""
    rendered = body(monkeypatch, capsys, COMMITS, ["docs/commands.md"])

    assert "## Test plan" not in rendered
    assert "Verify changes" not in rendered


def test_a_path_is_read_for_the_conventions_a_test_is_named_by() -> None:
    assert branches.names_a_test("tests/unit/test_devtools_pr_body.py")
    assert branches.names_a_test("src/thing/thing_test.go")
    assert branches.names_a_test("web/components/Button.test.tsx")
    assert not branches.names_a_test("packages/lup/src/lup/devtools/dev/pr.py")
    assert not branches.names_a_test("src/greatest.py")
