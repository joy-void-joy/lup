"""The store: snapshots, comparing trees, setting aside what was committed elsewhere."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.changes import Changed, Store
from lup_dev.layout import Layout

if TYPE_CHECKING:
    from conftest import Shell

CORE = Path("src/pkg/core.py")


@pytest.fixture
def store(repo: Path, tmp_path: Path) -> Store:
    return Store(layout=Layout(state=tmp_path / "state").store(repo), worktree=repo)


def test_a_snapshot_leaves_out_ignored_files_and_saved_versions(
    repo: Path, store: Store
) -> None:
    (repo / ".venv").mkdir()
    (repo / ".venv" / "lib.py").write_text("x = 1\n")
    (repo / ".lup" / "saved" / "1").mkdir(parents=True)
    (repo / ".lup" / "saved" / "1" / "a.py").write_text("x = 1\n")
    tree = store.snapshot()
    assert store.content(tree, Path(".venv/lib.py")) is None
    assert store.content(tree, Path(".lup/saved/1/a.py")) is None
    assert store.content(tree, CORE) == (repo / CORE).read_bytes()


def test_the_store_lives_outside_the_worktree(
    repo: Path, store: Store, shell: Shell
) -> None:
    store.snapshot()
    assert not store.layout.snapshots.is_relative_to(repo)
    assert shell.git(repo, "status", "--porcelain") == ""


def test_changes_between_trees(repo: Path, store: Store) -> None:
    before = store.snapshot()
    (repo / CORE).write_text("changed\n")
    (repo / "src" / "pkg" / "new.py").write_text("new\n")
    (repo / "README.md").unlink()
    after = store.snapshot()
    assert store.changed(before, after) == [
        Changed(path=Path("README.md"), kind="deleted"),
        Changed(path=CORE, kind="modified"),
        Changed(path=Path("src/pkg/new.py"), kind="added"),
    ]


def test_restore_puts_files_back_and_removes_new_ones(repo: Path, store: Store) -> None:
    accepted = store.snapshot()
    original = (repo / CORE).read_text()
    (repo / CORE).write_text("changed\n")
    (repo / "src" / "pkg" / "new.py").write_text("new\n")
    store.restore(accepted, [CORE, Path("src/pkg/new.py")])
    assert (repo / CORE).read_text() == original
    assert not (repo / "src" / "pkg" / "new.py").exists()


def test_unstage_keeps_paths_as_the_accepted_tree_has_them(
    repo: Path, store: Store
) -> None:
    accepted = store.snapshot()
    (repo / CORE).write_text("changed\n")
    (repo / "README.md").write_text("# Changed\n")
    store.snapshot()
    tree = store.unstage(accepted, [CORE])
    assert store.changed(accepted, tree) == [
        Changed(path=Path("README.md"), kind="modified")
    ]


def test_saved_versions_go_under_the_worktrees_lup_directory(
    repo: Path, store: Store
) -> None:
    saved = store.save(3, CORE, b"mine\n")
    assert saved == Path(".lup/saved/3/src/pkg/core.py")
    assert (repo / saved).read_text() == "mine\n"


def test_stored_objects_can_be_read_back(store: Store) -> None:
    blob = store.keep(b"would-be content\n")
    assert store.object(blob) == b"would-be content\n"
    assert store.object("0" * 40) is None


def test_content_of_a_commit_from_the_last_checkpoint_is_set_aside(
    repo: Path, store: Store, shell: Shell
) -> None:
    shell.git(repo, "checkout", "-q", "-b", "other")
    (repo / CORE).write_text("x = 1  # BAD regex\n")
    shell.commit(repo, "other")
    shell.git(repo, "checkout", "-q", "main")
    tips = store.tips()
    shell.git(repo, "checkout", "-q", "other")
    taken = store.snapshot()
    assert store.committed(CORE, store.blob(taken, CORE), tips)


def test_an_old_commits_content_is_set_aside_too(
    repo: Path, store: Store, shell: Shell
) -> None:
    original = (repo / CORE).read_text()
    (repo / CORE).write_text("later\n")
    shell.commit(repo, "later")
    tips = store.tips()
    (repo / CORE).write_text(original)
    assert store.committed(CORE, store.blob(store.snapshot(), CORE), tips)


def test_a_commit_made_since_the_last_checkpoint_doesnt_launder_its_files(
    repo: Path, store: Store, shell: Shell
) -> None:
    tips = store.tips()
    (repo / CORE).write_text("x = 1  # BAD regex\n")
    shell.commit(repo, "write and commit in one call")
    assert not store.committed(CORE, store.blob(store.snapshot(), CORE), tips)


def test_content_arrived_from_a_remote_is_set_aside(
    repo: Path, store: Store, tmp_path: Path, shell: Shell
) -> None:
    remote = tmp_path / "remote.git"
    shell.git(tmp_path, "clone", "-q", "--bare", str(repo), str(remote))
    other = tmp_path / "other"
    shell.git(tmp_path, "clone", "-q", str(remote), str(other))
    shell.git(other, "config", "user.email", "o@example.com")
    shell.git(other, "config", "user.name", "Other")
    (other / CORE).write_text("theirs\n")
    shell.commit(other, "theirs")
    shell.git(other, "push", "-q", "origin", "main")
    shell.git(repo, "remote", "add", "origin", str(remote))
    tips = store.tips()
    shell.git(repo, "pull", "-q", "--ff-only", "origin", "main")
    taken = store.snapshot()
    assert store.committed(CORE, store.blob(taken, CORE), [*tips, *store.remote_tips()])


def test_conflict_markers_match_no_commit(repo: Path, store: Store) -> None:
    tips = store.tips()
    (repo / CORE).write_text("<<<<<<< ours\na\n=======\nb\n>>>>>>> theirs\n")
    assert not store.committed(CORE, store.blob(store.snapshot(), CORE), tips)


def test_a_file_a_branch_switch_removes_is_set_aside(
    repo: Path, store: Store, shell: Shell
) -> None:
    shell.git(repo, "branch", "bare")
    extra = Path("src/pkg/extra.py")
    (repo / extra).write_text("extra\n")
    shell.commit(repo, "extra")
    tips = store.tips()
    shell.git(repo, "checkout", "-q", "bare")
    assert store.committed(extra, None, tips)


def test_a_file_removed_by_hand_isnt_set_aside(repo: Path, store: Store) -> None:
    tips = store.tips()
    (repo / CORE).unlink()
    assert not store.committed(CORE, None, tips)
