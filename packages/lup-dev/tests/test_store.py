"""The store: snapshots, comparing trees, setting aside what was committed elsewhere."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.layout import Layout
from lup_dev.policy.store import Changed, Elsewhere, Store

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
    tree = store.unstage(accepted, [CORE], [])
    assert store.changed(accepted, tree) == [
        Changed(path=Path("README.md"), kind="modified")
    ]


def test_unstage_puts_a_path_as_a_commit_has_it(
    repo: Path, store: Store, shell: Shell
) -> None:
    accepted = store.snapshot()
    (repo / CORE).write_text("committed\n")
    shell.commit(repo, "a commit")
    (repo / CORE).write_text("changed after\n")
    (repo / "README.md").unlink()
    store.snapshot()
    head = store.head()
    tree = store.unstage(
        accepted, [], [store.entry(head, CORE), store.entry(head, Path("gone.py"))]
    )
    assert store.content(tree, CORE) == b"committed\n"
    assert store.content(tree, Path("README.md")) is None


def test_the_files_a_move_of_head_changed(
    repo: Path, store: Store, shell: Shell
) -> None:
    before = store.head()
    (repo / CORE).write_text("changed\n")
    (repo / "src" / "pkg" / "new.py").write_text("new\n")
    shell.commit(repo, "a commit")
    assert store.moved(before, store.head()) == [CORE, Path("src/pkg/new.py")]
    assert Path("README.md") in store.moved(None, store.head())


def test_a_commits_modules_and_project_files_are_exported(
    repo: Path, store: Store, tmp_path: Path
) -> None:
    (repo / "uncommitted.py").write_text("x = 1\n")
    into = tmp_path / "export"
    head = store.head()
    assert head is not None
    store.export(head, into)
    exported = sorted(
        each.relative_to(into).as_posix() for each in into.rglob("*") if each.is_file()
    )
    assert exported == [
        "pyproject.toml",
        "src/pkg/__init__.py",
        "src/pkg/core.py",
        "tests/test_core.py",
    ]


def test_saved_versions_go_under_the_worktrees_lup_directory(
    repo: Path, store: Store
) -> None:
    saved = store.save(3, CORE, b"mine\n")
    assert saved == repo / ".lup/saved/3/src/pkg/core.py"
    assert saved.read_text() == "mine\n"


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
    tips = store.tips(store.head())
    shell.git(repo, "checkout", "-q", "other")
    taken = store.snapshot()
    assert store.committed(CORE, store.blob(taken, CORE), tips)


def test_an_old_commits_content_is_set_aside_too(
    repo: Path, store: Store, shell: Shell
) -> None:
    original = (repo / CORE).read_text()
    (repo / CORE).write_text("later\n")
    shell.commit(repo, "later")
    tips = store.tips(store.head())
    (repo / CORE).write_text(original)
    assert store.committed(CORE, store.blob(store.snapshot(), CORE), tips)


def test_a_commit_made_since_the_last_checkpoint_doesnt_launder_its_files(
    repo: Path, store: Store, shell: Shell
) -> None:
    tips = store.tips(store.head())
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
    tips = store.tips(store.head())
    shell.git(repo, "pull", "-q", "--ff-only", "origin", "main")
    taken = store.snapshot()
    assert store.committed(CORE, store.blob(taken, CORE), [*tips, *store.remote_tips()])


def test_conflict_markers_match_no_commit(repo: Path, store: Store) -> None:
    tips = store.tips(store.head())
    (repo / CORE).write_text("<<<<<<< ours\na\n=======\nb\n>>>>>>> theirs\n")
    assert not store.committed(CORE, store.blob(store.snapshot(), CORE), tips)


def test_a_file_a_branch_switch_removes_is_set_aside(
    repo: Path, store: Store, shell: Shell
) -> None:
    shell.git(repo, "branch", "bare")
    extra = Path("src/pkg/extra.py")
    (repo / extra).write_text("extra\n")
    shell.commit(repo, "extra")
    tips = store.tips(store.head())
    shell.git(repo, "checkout", "-q", "bare")
    assert store.committed(extra, None, tips)


def test_a_file_removed_by_hand_isnt_set_aside(repo: Path, store: Store) -> None:
    tips = store.tips(store.head())
    (repo / CORE).unlink()
    assert not store.committed(CORE, None, tips)


def diverge(repo: Path, shell: Shell) -> None:
    """Change `CORE` on a branch `feature` and on `main`, in different places."""
    shell.git(repo, "switch", "-q", "-c", "feature")
    (repo / CORE).write_text(
        (repo / CORE).read_text() + "\n\nclass Adapter:\n    pass\n"
    )
    shell.commit(repo, "feature: a class")
    shell.git(repo, "switch", "-q", "main")
    (repo / CORE).write_text(
        (repo / CORE).read_text().replace('"""Core."""', '"""Core, on main."""')
    )
    shell.commit(repo, "main: its docstring")


def test_gits_merge_of_judged_commits_is_set_aside(
    repo: Path, store: Store, shell: Shell
) -> None:
    diverge(repo, shell)
    tips = store.tips(store.head())
    shell.git(repo, "merge", "-q", "--no-edit", "feature")
    merged = store.blob(store.snapshot(), CORE)
    assert not store.committed(CORE, merged, tips)
    assert Elsewhere(store=store, commits=tips).holds(CORE, merged)


def test_a_merge_with_a_parent_made_since_isnt_set_aside(
    repo: Path, store: Store, shell: Shell
) -> None:
    diverge(repo, shell)
    tips = store.tips(store.head())
    (repo / "README.md").write_text("# Later\n")
    shell.commit(repo, "main: made since")
    shell.git(repo, "merge", "-q", "--no-edit", "feature")
    merged = store.blob(store.snapshot(), CORE)
    assert not Elsewhere(store=store, commits=tips).holds(CORE, merged)
