"""Registry resolution and reachability tests for `lup-devtools sync`.

The sync registry contract: sync.json(.local) is the canonical pair, and a
registration says a project may be *reviewed*. What says it may be *opened*
is a `mount` written on the entry, which is a separate claim and is never
defaulted — sync.json is committed scaffold, so a default there would decide
what every project adopting this template can reach.
"""

import json
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


def registered(registry_root: Path, *projects: dict) -> None:
    """Write these entries as this project's personal registrations."""
    (registry_root / "sync.json.local").write_text(
        json.dumps({"projects": list(projects)})
    )


def test_a_registration_is_not_reachable_until_it_says_so(
    registry_root: Path, tmp_path: Path
) -> None:
    """The whole of the opt-in: tracked is not the same claim as open."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    registered(registry_root, {"name": "other", "path": str(elsewhere)})

    assert sync.accessible_roots(lambda said: None) == []


def test_a_declared_mount_reaches_the_lease_at_the_mode_it_names(
    registry_root: Path, tmp_path: Path
) -> None:
    open_wide = tmp_path / "open"
    read_only = tmp_path / "readable"
    open_wide.mkdir()
    read_only.mkdir()
    registered(
        registry_root,
        {"name": "open", "path": str(open_wide), "mount": "rw"},
        {"name": "readable", "path": str(read_only), "mount": "ro"},
    )

    roots = sync.accessible_roots(lambda said: None)

    assert [(root.path, root.writable) for root in roots] == [
        (open_wide, True),
        (read_only, False),
    ]


def test_a_mount_nobody_can_locate_is_reported_rather_than_raised(
    registry_root: Path,
) -> None:
    """A launch does not fail over an unfinished note in a gitignored file."""
    registered(registry_root, {"name": "gone", "mount": "rw"})
    said: list[str] = []

    assert sync.accessible_roots(said.append) == []
    assert "gone" in "\n".join(said)


def test_a_misspelled_mode_is_refused_by_the_registry_rather_than_ignored(
    registry_root: Path, tmp_path: Path
) -> None:
    """The reason the key is a literal: a typo is an error, not silence."""
    registered(registry_root, {"name": "other", "path": str(tmp_path), "mount": "rwx"})

    with pytest.raises(Exception):
        sync.load_projects()


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
