"""A merge the host computes: from what it hash-checked, in a store of its own."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.composing import Composed, Unmerged, apart
from lup_dev.git import Git, GitError

if TYPE_CHECKING:
    from conftest import Shell

AT = datetime(2026, 11, 6, tzinfo=UTC)


def branch(shell: Shell, root: Path, name: str, files: dict[str, str]) -> str:
    """Make `name` from `dev` in the checkout at `root`, with a commit writing `files`, leave `dev` checked out, and return its tip."""
    shell.git(root, "switch", "-q", "-c", name, "dev")
    for path, content in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(content)
    shell.commit(root, f"write {name}")
    tip = shell.git(root, "rev-parse", "HEAD")
    shell.git(root, "switch", "-q", "dev")
    return tip


@pytest.fixture
def checkout(tmp_path: Path, shell: Shell) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    shell.git(root, "init", "-q", "-b", "dev")
    shell.git(root, "config", "user.email", "t@example.com")
    shell.git(root, "config", "user.name", "t")
    (root / "shared.txt").write_text("one\ntwo\nthree\n")
    shell.commit(root, "start")
    return root


def pinned(root: Path) -> Git:
    """git pinned to the repository of the checkout at `root`."""
    return Git.pinned(root / ".git")


def test_branches_merge_onto_dev_each_side_s_changes_in_the_tree(
    checkout: Path, shell: Shell
) -> None:
    dev = shell.git(checkout, "rev-parse", "dev")
    first = branch(shell, checkout, "a", {"shared.txt": "ONE\ntwo\nthree\n"})
    second = branch(
        shell, checkout, "b", {"shared.txt": "one\ntwo\nTHREE\n", "b.txt": "b\n"}
    )
    git = pinned(checkout)
    with apart(git) as store:
        merged = store.merged(dev, {"a": first, "b": second})
        assert isinstance(merged, Composed)
        commit = store.committed(merged.tree, [dev, first, second], "m", AT)
    assert shell.git(checkout, "show", f"{commit}:shared.txt") == "ONE\ntwo\nTHREE"
    assert shell.git(checkout, "show", f"{commit}:b.txt") == "b"
    assert shell.git(checkout, "show", "-s", "--format=%P", commit).split() == [
        dev,
        first,
        second,
    ]


def test_the_same_branches_come_to_the_same_tree_however_they_are_given(
    checkout: Path, shell: Shell
) -> None:
    dev = shell.git(checkout, "rev-parse", "dev")
    first = branch(shell, checkout, "a", {"a.txt": "a\n"})
    second = branch(shell, checkout, "b", {"b.txt": "b\n"})
    with apart(pinned(checkout)) as store:
        assert store.merged(dev, {"a": first, "b": second}) == store.merged(
            dev, {"b": second, "a": first}
        )


def test_a_conflict_names_the_branch_and_its_files_and_writes_nothing_the_repository_keeps(
    checkout: Path, shell: Shell
) -> None:
    dev = shell.git(checkout, "rev-parse", "dev")
    first = branch(shell, checkout, "a", {"shared.txt": "ONE\ntwo\nthree\n"})
    second = branch(shell, checkout, "b", {"shared.txt": "uno\ntwo\nthree\n"})
    before = shell.git(checkout, "count-objects")
    with apart(pinned(checkout)) as store:
        merged = store.merged(dev, {"a": first, "b": second})
    assert merged == Unmerged(branch="b", files=[Path("shared.txt")])
    assert shell.git(checkout, "count-objects") == before


def test_a_branch_dev_holds_brings_nothing(checkout: Path, shell: Shell) -> None:
    first = branch(shell, checkout, "a", {"a.txt": "a\n"})
    shell.git(checkout, "merge", "-q", "--no-ff", "--no-edit", "a")
    dev = shell.git(checkout, "rev-parse", "dev")
    with apart(pinned(checkout)) as store:
        merged = store.merged(dev, {"a": first})
        assert merged == Composed(tree=store.tree(dev))


def test_a_branch_stacked_on_another_merges_from_where_it_left_it(
    checkout: Path, shell: Shell
) -> None:
    dev = shell.git(checkout, "rev-parse", "dev")
    first = branch(shell, checkout, "a", {"shared.txt": "ONE\ntwo\nthree\n"})
    shell.git(checkout, "switch", "-q", "-c", "b", "a")
    (checkout / "shared.txt").write_text("ONE\nTWO\nthree\n")
    shell.commit(checkout, "on a")
    second = shell.git(checkout, "rev-parse", "HEAD")
    shell.git(checkout, "switch", "-q", "dev")
    with apart(pinned(checkout)) as store:
        merged = store.merged(dev, {"a": first, "b": second})
        assert isinstance(merged, Composed)
        commit = store.committed(merged.tree, [dev, first, second], "m", AT)
    assert shell.git(checkout, "show", f"{commit}:shared.txt") == "ONE\nTWO\nthree"


def test_no_history_in_common_doesn_t_merge(checkout: Path, shell: Shell) -> None:
    dev = shell.git(checkout, "rev-parse", "dev")
    shell.git(checkout, "switch", "-q", "--orphan", "alone")
    (checkout / "alone.txt").write_text("alone\n")
    shell.commit(checkout, "alone")
    tip = shell.git(checkout, "rev-parse", "HEAD")
    with apart(pinned(checkout)) as store:
        assert store.merged(dev, {"alone": tip}) == Unmerged(branch="alone")


def test_a_tree_s_own_attributes_name_no_merge_driver_here(
    checkout: Path, shell: Shell
) -> None:
    """A room writes the branch: a driver its `.gitattributes` names would run a command, if git here read it and the repository's `config` named one."""
    dev = shell.git(checkout, "rev-parse", "dev")
    shell.git(checkout, "config", "merge.evil.driver", "touch /nonexistent/ran; false")
    first = branch(
        shell,
        checkout,
        "a",
        {
            ".gitattributes": "shared.txt merge=evil\n",
            "shared.txt": "ONE\ntwo\nthree\n",
        },
    )
    second = branch(shell, checkout, "b", {"shared.txt": "one\ntwo\nTHREE\n"})
    with apart(pinned(checkout)) as store:
        merged = store.merged(dev, {"a": first, "b": second})
    assert isinstance(merged, Composed)


def test_an_object_that_isn_t_what_its_id_says_refuses_the_merge(
    checkout: Path, shell: Shell
) -> None:
    dev = shell.git(checkout, "rev-parse", "dev")
    tip = branch(shell, checkout, "a", {"a.txt": "a\n"})
    blob = shell.git(checkout, "rev-parse", f"{tip}:a.txt")
    shell.planted(checkout / ".git" / "objects", blob, "blob", b"something else\n")
    with apart(pinned(checkout)) as store, pytest.raises(GitError, match=blob):
        store.merged(dev, {"a": tip})


def test_a_commit_refuses_to_read_back_as_a_tree_already_held_as_something_else(
    checkout: Path, shell: Shell
) -> None:
    """A room can plant a tree under the id it knows a merge will make: what reads it after hashes it, so it's refused here, before anything names the commit."""
    dev = shell.git(checkout, "rev-parse", "dev")
    first = branch(shell, checkout, "a", {"a.txt": "a\n"})
    second = branch(shell, checkout, "b", {"b.txt": "b\n"})
    with apart(pinned(checkout)) as store:
        merged = store.merged(dev, {"a": first, "b": second})
        assert isinstance(merged, Composed)
        shell.planted(
            checkout / ".git" / "objects", merged.tree, "tree", b"not that tree"
        )
        with pytest.raises(GitError):
            store.committed(merged.tree, [dev, first, second], "m", AT)


def test_a_store_reading_objects_from_elsewhere_computes_nothing(
    checkout: Path,
) -> None:
    alternates = checkout / ".git" / "objects" / "info" / "alternates"
    alternates.parent.mkdir(exist_ok=True)
    alternates.write_text("/elsewhere\n")
    with pytest.raises(GitError, match="from outside it"), apart(pinned(checkout)):
        pass


def test_git_not_pinned_computes_nothing(checkout: Path) -> None:
    with pytest.raises(GitError, match="pinned"), apart(Git(cwd=checkout)):
        pass


def test_the_commit_is_git_s_own_reading_of_it(checkout: Path, shell: Shell) -> None:
    dev = shell.git(checkout, "rev-parse", "dev")
    tip = branch(shell, checkout, "a", {"a.txt": "a\n"})
    with apart(pinned(checkout)) as store:
        merged = store.merged(dev, {"a": tip})
        assert isinstance(merged, Composed)
        commit = store.committed(merged.tree, [dev, tip], "the message", AT)
    subprocess.run(
        ["git", "-C", str(checkout), "fsck", "--no-dangling", "--strict", commit],
        check=True,
        capture_output=True,
    )
    assert shell.git(checkout, "show", "-s", "--format=%an %s", commit) == (
        "lup the message"
    )
