"""Updating a pin preserves the explicitly configured framework repository."""

from pathlib import Path

import pytest
import typer

from lup.devtools.dev import library, scaffold, update


def test_a_revision_uses_the_selected_scaffold_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text(
        '[project]\nname = "consumer"\ndependencies = ["lup"]\n'
        "[tool.uv.sources]\nlup = { workspace = true }\n"
    )
    (tmp_path / "sync.json.local").write_text(
        '{"projects":[{"name":"framework","url":"https://forge.example/team/library"}]}'
    )
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(update, "uv", lambda *args, **_kwargs: calls.append(args))
    monkeypatch.setattr(scaffold, "pinned_commit", lambda *_args: "resolved")

    assert (
        update.resolved_pin(
            tmp_path, "lup", "revision", lambda _line: None, project="framework"
        )
        == "resolved"
    )
    assert library.read_git_source(tmp_path) == library.GitSource(
        url="https://forge.example/team/library", ref_kind="rev", ref="revision"
    )
    assert calls == [("lock", "--upgrade-package", "lup")]


def test_an_unconfigured_revision_refuses_before_mutating_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "pyproject.toml"
    original = '[project]\nname = "consumer"\ndependencies = ["lup"]\n'
    manifest.write_text(original)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(update, "uv", lambda *args, **_kwargs: calls.append(args))

    with pytest.raises(typer.BadParameter, match="No repository is configured"):
        update.resolved_pin(tmp_path, "lup", "revision", lambda _line: None)
    assert manifest.read_text() == original
    assert calls == []
