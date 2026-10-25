"""Paths hidden from a room: what's found as the room starts, what appears after, and the host's removal, which follows no link the room could swap in."""

from pathlib import Path

from lup.rooms.container import Mount
from lup_dev.launch.hidden import Hidden, removed, status
from lup_dev.layout import Layout

VENV = Path(".venv")


def tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A repository's tree holding two worktrees, the first with its own environment."""
    root = tmp_path / "repo.git"
    main = root / "tree" / "main"
    feat = root / "tree" / "feat"
    (main / ".venv" / "bin").mkdir(parents=True)
    (main / ".venv" / "bin" / "python").write_text("")
    feat.mkdir(parents=True)
    return root, main, feat


def test_each_path_there_as_the_room_starts_is_hidden_by_something_empty_and_read_only(
    tmp_path: Path,
) -> None:
    root, main, feat = tree(tmp_path)
    (feat / "secret").write_text("kept")
    launch = Layout(state=tmp_path / "state").launch("0f3a")

    hidden = Hidden.of(root, [main, feat], [VENV, Path("secret")])
    hidden.write(launch)

    assert hidden.mounts(launch) == [
        Mount(source=launch.empty_directory, target=main / ".venv", read_only=True),
        Mount(source=launch.empty_file, target=feat / "secret", read_only=True),
    ]
    assert list(launch.empty_directory.iterdir()) == []
    assert launch.empty_file.read_text() == ""


def test_a_link_isnt_hidden_since_podman_would_follow_it(tmp_path: Path) -> None:
    root, _, feat = tree(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (feat / ".venv").symlink_to(elsewhere)
    assert Hidden.of(root, [feat], [VENV]).found == []


def test_what_appeared_while_the_room_ran_is_told_from_what_was_there(
    tmp_path: Path,
) -> None:
    root, main, feat = tree(tmp_path)
    hidden = Hidden.of(root, [main, feat], [VENV])
    added = root / "tree" / "added"

    # The room makes one in a worktree that had none, and in one it adds; it
    # moves a worktree aside, its hidden environment moving with the mount, and
    # makes another where it was.
    (feat / ".venv").mkdir()
    (added / ".venv").mkdir(parents=True)
    main.rename(root / "tree" / "aside")
    (main / ".venv").mkdir(parents=True)

    listed = [main, feat, added, root / "tree" / "aside"]
    assert hidden.appeared(listed) == [main / ".venv", feat / ".venv", added / ".venv"]


def test_nothing_outside_the_tree_is_looked_at(tmp_path: Path) -> None:
    root, main, _ = tree(tmp_path)
    outside = tmp_path / "outside"
    (outside / ".venv").mkdir(parents=True)
    hidden = Hidden.of(root, [main, outside], [VENV])
    assert [each.path for each in hidden.found] == [main / ".venv"]
    assert hidden.appeared([outside]) == []


def test_removing_takes_a_directory_whole_and_a_link_itself(tmp_path: Path) -> None:
    root, main, feat = tree(tmp_path)
    kept = tmp_path / "kept"
    kept.mkdir()
    (kept / "file").write_text("the operator's")
    (feat / ".venv").symlink_to(kept)

    assert removed(root, main / ".venv")
    assert removed(root, feat / ".venv")

    assert not (main / ".venv").exists()
    assert not (feat / ".venv").is_symlink()
    assert (kept / "file").read_text() == "the operator's"
    assert not removed(root, main / ".venv")


def test_removing_through_a_directory_swapped_for_a_link_removes_nothing(
    tmp_path: Path,
) -> None:
    root, main, _ = tree(tmp_path)
    kept = tmp_path / "kept"
    (kept / ".venv").mkdir(parents=True)
    (kept / ".venv" / "file").write_text("the operator's")
    # The room swaps the worktree for a link to a directory elsewhere, whose
    # own environment the host would otherwise remove.
    main.rename(root / "tree" / "gone")
    main.symlink_to(kept)

    assert status(root, main / ".venv") is None
    assert not removed(root, main / ".venv")
    assert (kept / ".venv" / "file").read_text() == "the operator's"


def test_removing_outside_the_tree_or_the_tree_itself_removes_nothing(
    tmp_path: Path,
) -> None:
    root, _, _ = tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    assert not removed(root, outside)
    assert not removed(root, root)
    assert outside.is_dir()
    assert root.is_dir()
