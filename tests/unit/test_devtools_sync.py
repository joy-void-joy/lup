"""Registry resolution tests for `lup-devtools sync`.

The sync registry contract: sync.json(.local) is the canonical pair, and a
repo still carrying the legacy downstream.json(.local) names is read as a
fallback with a deprecation warning that tells the user to rename the file.
"""

import json
import logging
from pathlib import Path

import pytest
import typer

from lup.devtools import sync
from tests.unit.repos import commit_file, initialized_repo


def write_registry(path: Path) -> None:
    path.write_text(json.dumps({"projects": [{"name": "lup"}]}) + "\n")


@pytest.fixture
def registry_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(sync, "project_root", lambda: tmp_path)
    return tmp_path


def test_registry_prefers_sync_json_over_legacy(registry_root: Path) -> None:
    write_registry(registry_root / "sync.json")
    write_registry(registry_root / "downstream.json")

    assert sync.sync_file() == registry_root / "sync.json"


def test_registry_falls_back_to_legacy_name_with_deprecation_warning(
    registry_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_registry(registry_root / "downstream.json")

    with caplog.at_level(logging.WARNING):
        resolved = sync.sync_file()

    assert resolved == registry_root / "downstream.json"
    assert "downstream.json is deprecated; rename it to sync.json" in caplog.text


def test_local_registry_falls_back_to_legacy_name(
    registry_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_registry(registry_root / "downstream.json.local")

    with caplog.at_level(logging.WARNING):
        resolved = sync.local_file()

    assert resolved == registry_root / "downstream.json.local"
    assert "rename it to sync.json.local" in caplog.text


def test_missing_registries_resolve_to_sync_names(registry_root: Path) -> None:
    assert sync.sync_file() == registry_root / "sync.json"
    assert sync.local_file() == registry_root / "sync.json.local"
    assert sync.load_projects() == []


def test_local_entries_override_tracked_entries_by_name(registry_root: Path) -> None:
    (registry_root / "sync.json").write_text(
        json.dumps({"projects": [{"name": "lup", "url": "https://example.test/lup"}]})
    )
    (registry_root / "sync.json.local").write_text(
        json.dumps({"projects": [{"name": "lup", "ignore": True}]})
    )

    projects = sync.load_projects()

    assert projects == [
        {"name": "lup", "url": "https://example.test/lup", "ignore": True}
    ]


@pytest.fixture
def upstream(tmp_path: Path) -> tuple[str, list[str]]:
    """An upstream checkout with three commits, newest last."""
    work = tmp_path / "upstream"
    git = initialized_repo(work, tmp_path / "hooks")
    for index in range(3):
        commit_file(git, work, "file.txt", f"revision {index}\n", f"commit {index}")
    log = git("log", "--format=%H", "--reverse").strip().splitlines()
    return str(work), [line.strip() for line in log]


def test_a_checkpoint_defaults_to_the_upstream_head(
    upstream: tuple[str, list[str]],
) -> None:
    """What a finished review means: everything up to now was considered."""
    path, commits = upstream

    assert sync.resolved_checkpoint(path, "") == commits[-1]


def test_a_checkpoint_can_record_a_commit_already_consumed(
    upstream: tuple[str, list[str]],
) -> None:
    """A project adopting a library mid-stream knows which commit it took.

    Without this the only reachable checkpoint is the upstream's HEAD, which
    silently claims every commit landed since as reviewed — the opposite of
    what the record is for.
    """
    path, commits = upstream

    assert sync.resolved_checkpoint(path, commits[0]) == commits[0]
    assert sync.resolved_checkpoint(path, commits[0][:8]) == commits[0]


def test_a_checkpoint_that_names_no_commit_is_refused_rather_than_recorded(
    upstream: tuple[str, list[str]],
) -> None:
    """Refused where the caller can still fix it.

    A checkpoint nothing can resolve is one no later range can be computed
    from, and it fails at the next review rather than at the typo.
    """
    path, _commits = upstream

    with pytest.raises(typer.BadParameter):
        sync.resolved_checkpoint(path, "no-such-ref")
