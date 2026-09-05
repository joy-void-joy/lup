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
import sh
import typer

from lup.devtools import sync
from tests.unit.repos import commit_file, git_in, initialized_repo


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


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The per-user clone cache, moved somewhere a test may write."""
    root = tmp_path / "cache"
    monkeypatch.setattr(sync, "cache_dir", lambda: root)
    return root


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A repository to clone from, carrying a history and a second branch."""
    work = tmp_path / "remote"
    git = initialized_repo(work, tmp_path / "hooks")
    for index in range(3):
        commit_file(git, work, "file.txt", f"revision {index}\n", f"commit {index}")
    git("branch", "sidecar")
    return work


def materialize(name: str = "up") -> sync.Upstream:
    """Locate one registration, silencing the progress a test does not read."""
    return sync.ensure_local(sync.find_project(name), lambda said: None)


def test_a_url_registration_materializes_as_a_bare_repository_with_a_worktree(
    registry_root: Path, cache: Path, remote: Path
) -> None:
    """The layout a registration naming a local path already points at.

    Parity is the whole subject: a session opens either kind on the same
    terms, so a URL cannot resolve to something a session cannot work in.
    """
    registered(registry_root, {"name": "up", "url": str(remote)})

    found = materialize()

    assert sync.bare_repository(cache / "up.git")
    assert found.checkout == cache / "up.git" / "tree" / "main"
    assert (found.checkout / "file.txt").read_text() == "revision 2\n"


def test_a_materialized_clone_carries_the_whole_history_and_every_branch(
    registry_root: Path, cache: Path, remote: Path
) -> None:
    """What ``--depth=200`` could not give a session to work in.

    A shallow single-branch clone is a review window that quietly ends and a
    checkout that can be cut no other branch, which is two of the three
    reasons a URL registration used to be worth less than a path one.
    """
    registered(registry_root, {"name": "up", "url": str(remote)})
    materialize()
    bare = str(cache / "up.git")

    assert sync.git_in(bare, "rev-list", "--count", "main") == "3"
    assert sync.git_in(bare, "rev-parse", "--is-shallow-repository") == "false"
    assert sync.git_in(bare, "branch", "--format=%(refname:short)").split() == [
        "main",
        "sidecar",
    ]


def test_refreshing_a_clone_leaves_work_in_it_exactly_where_it_stands(
    registry_root: Path, cache: Path, remote: Path, tmp_path: Path
) -> None:
    """The third reason, and the one that lost work rather than opportunity.

    The refresh used to be a fetch followed by a hard reset onto the
    upstream, so a branch cut in the clone, a commit made on it and every
    uncommitted file beside it went with the next review — silently, because
    a reset says nothing about what it wrote over.
    """
    registered(registry_root, {"name": "up", "url": str(remote)})
    checkout = materialize().checkout
    worker = git_in(checkout, tmp_path / "hooks")
    worker("checkout", "-b", "feature")
    commit_file(worker, checkout, "mine.txt", "kept\n", "work in progress")
    standing = worker("rev-parse", "HEAD").strip()
    (checkout / "dirty.txt").write_text("uncommitted\n")

    commit_file(
        git_in(remote, tmp_path / "hooks"), remote, "file.txt", "later\n", "commit 3"
    )
    again = materialize()

    assert worker("rev-parse", "HEAD").strip() == standing
    assert worker("branch", "--show-current").strip() == "feature"
    assert (checkout / "mine.txt").read_text() == "kept\n"
    assert (checkout / "dirty.txt").read_text() == "uncommitted\n"
    assert sync.commit_count(str(again.checkout), "", again.tip) == 4


def test_work_done_in_a_clone_is_not_read_back_as_the_upstream_s_own(
    registry_root: Path, cache: Path, remote: Path, tmp_path: Path
) -> None:
    """The other half of leaving the branch alone.

    A review that read ``HEAD`` in a checkout sessions work in would hand
    ``/lup:update`` this project's own commits to consider porting from
    itself. Reading the remote-tracking ref is what makes both halves true at
    once.
    """
    registered(registry_root, {"name": "up", "url": str(remote)})
    checkout = materialize().checkout
    worker = git_in(checkout, tmp_path / "hooks")
    commit_file(worker, checkout, "mine.txt", "mine\n", "not the upstream's")

    found = materialize()

    assert sync.commit_count(str(found.checkout), "", found.tip) == 3


def test_a_url_registration_is_mounted_at_its_worktree_not_its_bare_half(
    registry_root: Path, cache: Path, remote: Path
) -> None:
    """A mount has to land on a working tree.

    ``lease_for`` reads a bare directory as a repository whose every worktree
    belongs to somebody else and holds all of them read-only, so a session
    handed one gets a checkout it cannot work in and siblings it cannot
    write — a boundary nobody declared rather than the mode that was named.
    """
    registered(registry_root, {"name": "up", "url": str(remote), "mount": "rw"})

    roots = sync.accessible_roots(lambda said: None)

    assert [(root.path, root.writable) for root in roots] == [
        (cache / "up.git" / "tree" / "main", True)
    ]


def test_a_clone_registered_under_one_name_at_two_urls_is_refused(
    registry_root: Path, cache: Path, remote: Path, tmp_path: Path
) -> None:
    """The cache is per user and keyed by the registered name.

    Two projects on this machine naming different repositories ``lup`` would
    otherwise share one clone, and the second would review, mount and commit
    into the first one's history under its own name.
    """
    registered(registry_root, {"name": "up", "url": str(remote)})
    materialize()
    registered(registry_root, {"name": "up", "url": str(tmp_path / "elsewhere")})
    said: list[str] = []

    with pytest.raises(typer.Exit):
        sync.ensure_local(sync.find_project("up"), said.append)

    assert "elsewhere" in "\n".join(said)


def test_a_clone_at_the_old_location_is_used_where_it_stands(
    registry_root: Path, cache: Path, remote: Path
) -> None:
    """Moving the cache must not abandon what was left in the old one.

    A clone under the project root was writable with the checkout, so a
    session could commit in one — and re-cloning beside it would leave that
    work where nothing looks again, which is the failure this whole change
    is about.
    """
    legacy = registry_root / ".cache" / "sync" / "up"
    legacy.parent.mkdir(parents=True)
    sh.Command("git")("clone", str(remote), str(legacy), _tty_out=False)
    registered(registry_root, {"name": "up", "url": str(remote)})

    found = materialize()

    assert found.checkout == legacy
    assert found.tip == "refs/remotes/origin/main"
    assert not (cache / "up.git").exists()
