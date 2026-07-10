# lup: ignore[empty-collection, string-replace, tuple-shape]
# Test fixtures and assertions construct these shapes deliberately.
"""Smoke and behavior tests for the lup-devtools CLI.

The smoke test walks the root typer app's full command tree (sub-apps and
nested groups) and invokes ``--help`` on every command. This catches
import-time crashes (e.g. a module-level ``sh.Command`` for a missing
binary) and option wiring errors, entirely offline.

The pr tests pin output behavior with a stubbed gh: ``pr merge`` must
print its MergeResult even when the tree-dir lookup raises ``typer.Exit``.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from lup_template.devtools.dev import pr
from lup_template.devtools.main import app

runner = CliRunner()


def iter_command_paths(
    current: typer.Typer, prefix: tuple[str, ...] = ()
) -> Iterator[tuple[str, ...]]:
    """Yield the CLI path of every group and command, depth-first."""
    yield prefix
    for command in current.registered_commands:
        if command.name:
            name = command.name
        elif command.callback:
            name = command.callback.__name__.lower().replace("_", "-")
        else:
            continue
        yield (*prefix, name)
    for group in current.registered_groups:
        sub_app = group.typer_instance
        if sub_app is None or not isinstance(group.name, str):
            continue
        yield from iter_command_paths(sub_app, (*prefix, group.name))


COMMAND_PATHS = sorted(iter_command_paths(app))


def test_command_tree_is_walked() -> None:
    flattened = {" ".join(path) for path in COMMAND_PATHS}
    assert "trace list" in flattened
    assert "dev pr merge" in flattened
    assert "dev worktree create" in flattened


@pytest.mark.parametrize(
    "path", COMMAND_PATHS, ids=[" ".join(p) or "(root)" for p in COMMAND_PATHS]
)
def test_help_succeeds_for_every_command(path: tuple[str, ...]) -> None:
    result = runner.invoke(app, [*path, "--help"])
    assert result.exit_code == 0, result.output


READONLY_COMMANDS: list[list[str]] = [
    ["version"],
    ["version", "changelog"],
    ["trace", "list"],
    ["feedback", "status"],
    ["setup", "status"],
    ["setup", "profile", "list"],
    ["sync", "status"],
]


@pytest.mark.parametrize("args", READONLY_COMMANDS, ids=lambda args: " ".join(args))
def test_readonly_command_exits_cleanly(args: list[str]) -> None:
    """--help only proves wiring; a runtime crash in a callback (the version
    sub-app once crashed on every real invocation) needs a real run."""
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


class FakeGh:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        return ""


def raise_typer_exit() -> Path:
    raise typer.Exit(1)


@pytest.fixture
def merge_stubs(monkeypatch: pytest.MonkeyPatch) -> FakeGh:
    fake = FakeGh()
    monkeypatch.setattr(pr, "gh", fake)
    monkeypatch.setattr(pr, "get_integration_branch", lambda: "dev")
    monkeypatch.setattr(pr, "get_tree_dir", raise_typer_exit)
    return fake


def test_merge_prints_json_result_when_tree_dir_lookup_exits(
    merge_stubs: FakeGh,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pr.merge(42, dry_run=False, as_json=True)

    out = capsys.readouterr().out
    assert '"pr_number": 42' in out
    assert '"merged": true' in out
    assert '"pulled": false' in out
    assert merge_stubs.calls[0][:2] == ("pr", "merge")


def test_merge_prints_text_result_when_tree_dir_lookup_exits(
    merge_stubs: FakeGh,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pr.merge(7, dry_run=False, as_json=False)

    out = capsys.readouterr().out
    assert "merged: True" in out
    assert "integration_branch: dev" in out
