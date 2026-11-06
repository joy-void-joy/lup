"""What the host writes and removes in a place a room writes stays there, whatever that place holds as it does so."""

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.confined import Confined
from lup_dev.git import Git
from lup_dev.layout import GitDirectoryLayout, Layout
from lup_dev.policy.before import Overwrite, before
from lup_dev.policy.checkpoint import (
    CallFinished,
    CallStarted,
    SessionStarted,
)
from lup_dev.policy.holds import Response, answer, waiting
from lup_dev.policy.landing import local_deleted, tracked
from lup_dev.policy.report import Reports
from lup_dev.policy.store import Store

if TYPE_CHECKING:
    from conftest import Dying, FakeClock, Kit, Shell

AGENTS = Path("AGENTS.md")
SESSION = "s1"


def begin(kit: Kit, repo: Path, key: str) -> None:
    CallStarted(session=SESSION, cwd=repo, call=key, tool="Bash").apply(kit.bench)


def finish(kit: Kit, repo: Path, key: str) -> str:
    return (
        CallFinished(session=SESSION, cwd=repo, call=key, tool="Bash")
        .apply(kit.bench)
        .context
    )


def everything(place: Path) -> dict[str, str]:
    """Each file under `place`, by its path from there, with its text."""
    return {
        str(each.relative_to(place)): each.read_text()
        for each in place.rglob("*")
        if each.is_file()
    }


def _layout(tmp_path: Path) -> Layout:
    return Layout(state=tmp_path / "state", runtime=tmp_path / "run")


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A directory of the host's, holding files of its own."""
    place = tmp_path / "outside"
    place.mkdir()
    (place / "own.txt").write_text("the host's own\n")
    (place / "AGENTS.md").write_text("the host's own\n")
    return place


def held_declined(kit: Kit, repo: Path, shell: Shell, change: str = "# More\n") -> str:
    """Hold a write to `AGENTS.md` and have the operator decline it as the call waits; return what's told."""
    (repo / AGENTS).write_text("# Agents\n")
    shell.commit(repo, "the operator's document")
    SessionStarted(session=SESSION, cwd=repo).apply(kit.bench)
    begin(kit, repo, "c1")
    (repo / AGENTS).write_text(change)
    kit.announced.answering = Response(approved=False)
    return finish(kit, repo, "c1")


# A version saved.


@pytest.mark.parametrize(
    "link",
    [
        ".lup",
        ".lup/saved",
        ".lup/saved/1",
    ],
)
def test_a_version_saved_is_saved_in_the_worktree_whatever_stands_on_its_way(
    holding_kit: Kit, repo: Path, shell: Shell, outside: Path, link: str
) -> None:
    before_there = everything(outside)
    (repo / link).parent.mkdir(parents=True, exist_ok=True)
    (repo / link).symlink_to(outside)
    held_declined(holding_kit, repo, shell)
    assert everything(outside) == before_there
    saved = repo / ".lup" / "saved" / "1" / AGENTS
    assert not saved.is_symlink()
    assert saved.read_text() == "# More\n"
    assert not (repo / link).is_symlink()


def test_a_version_saved_over_a_link_at_its_own_name_replaces_the_link(
    holding_kit: Kit, repo: Path, shell: Shell, outside: Path
) -> None:
    before_there = everything(outside)
    place = repo / ".lup" / "saved" / "1"
    place.mkdir(parents=True)
    (place / AGENTS).symlink_to(outside / "AGENTS.md")
    held_declined(holding_kit, repo, shell)
    assert everything(outside) == before_there
    assert not (place / AGENTS).is_symlink()
    assert (place / AGENTS).read_text() == "# More\n"


# A file put back.


def test_a_file_put_back_over_a_link_at_its_name_replaces_the_link(
    holding_kit: Kit, repo: Path, shell: Shell, outside: Path
) -> None:
    kit = holding_kit
    before_there = everything(outside)
    (repo / AGENTS).write_text("# Agents\n")
    shell.commit(repo, "the operator's document")
    SessionStarted(session=SESSION, cwd=repo).apply(kit.bench)
    begin(kit, repo, "c1")
    (repo / AGENTS).write_text("# More\n")

    def swapped_and_declined() -> None:
        (repo / AGENTS).unlink()
        (repo / AGENTS).symlink_to(outside / "AGENTS.md")
        [hold] = waiting(kit.layout)
        answer(kit.layout, hold.key, Response(approved=False), [], kit.clock)

    kit.clock.on_sleep.append(swapped_and_declined)
    finish(kit, repo, "c1")
    assert everything(outside) == before_there
    assert not (repo / AGENTS).is_symlink()
    assert (repo / AGENTS).read_text() == "# Agents\n"


def test_a_file_put_back_under_a_directory_swapped_for_a_link_goes_back_in_the_worktree(
    holding_kit: Kit, repo: Path, shell: Shell, outside: Path
) -> None:
    kit = holding_kit
    before_there = everything(outside)
    guarded = repo / ".github"
    guarded.mkdir()
    (guarded / "AGENTS.md").write_text("as accepted\n")
    shell.commit(repo, "a protected file")
    SessionStarted(session=SESSION, cwd=repo).apply(kit.bench)
    begin(kit, repo, "c1")
    (guarded / "AGENTS.md").write_text("changed\n")

    def swapped_and_declined() -> None:
        (guarded / "AGENTS.md").unlink()
        guarded.rmdir()
        guarded.symlink_to(outside)
        [hold] = waiting(kit.layout)
        answer(kit.layout, hold.key, Response(approved=False), [], kit.clock)

    kit.clock.on_sleep.append(swapped_and_declined)
    finish(kit, repo, "c1")
    assert everything(outside) == before_there
    assert not guarded.is_symlink()
    assert (guarded / "AGENTS.md").read_text() == "as accepted\n"


def test_a_new_file_put_back_under_a_directory_swapped_for_a_link_removes_nothing_there(
    holding_kit: Kit, repo: Path, shell: Shell, outside: Path
) -> None:
    kit = holding_kit
    before_there = everything(outside)
    guarded = repo / ".github"
    guarded.mkdir()
    SessionStarted(session=SESSION, cwd=repo).apply(kit.bench)
    begin(kit, repo, "c1")
    (guarded / "own.txt").write_text("new\n")

    def swapped_and_declined() -> None:
        (guarded / "own.txt").unlink()
        guarded.rmdir()
        guarded.symlink_to(outside)
        [hold] = waiting(kit.layout)
        answer(kit.layout, hold.key, Response(approved=False), [], kit.clock)

    kit.clock.on_sleep.append(swapped_and_declined)
    finish(kit, repo, "c1")
    assert everything(outside) == before_there


def test_a_hold_past_its_patience_puts_back_and_saves_in_the_worktree_alone(
    holding_kit: Kit, repo: Path, shell: Shell, outside: Path, dying: Dying
) -> None:
    kit = holding_kit
    before_there = everything(outside)
    (repo / AGENTS).write_text("# Agents\n")
    shell.commit(repo, "the operator's document")
    SessionStarted(session=SESSION, cwd=repo).apply(kit.bench)
    begin(kit, repo, "c1")
    (repo / AGENTS).write_text("# More\n")
    dying.at_next_wait(kit.clock)
    with pytest.raises(dying.died):
        finish(kit, repo, "c1")
    (repo / ".lup" / "saved").mkdir(parents=True)
    (repo / ".lup" / "saved" / "1").symlink_to(outside)
    kit.clock.sleep(timedelta(hours=25).total_seconds())
    begin(kit, repo, "c2")
    finish(kit, repo, "c2")
    assert everything(outside) == before_there
    assert (repo / ".lup" / "saved" / "1" / AGENTS).read_text() == "# More\n"
    assert (repo / AGENTS).read_text() == "# Agents\n"


def test_what_a_store_puts_back_is_as_the_tree_has_it(
    repo: Path, tmp_path: Path, shell: Shell
) -> None:
    """A file's bytes and its mode, a link as a link, and what the tree lacks removed."""
    (repo / "run.sh").write_text("#!/bin/sh\n")
    (repo / "run.sh").chmod(0o755)
    (repo / "pointing").symlink_to("README.md")
    (repo / "deep").mkdir()
    (repo / "deep" / "er.txt").write_bytes(b"\xff\r\nbytes\n")
    shell.commit(repo, "more")
    store = Store(layout=_layout(tmp_path).store(repo), worktree=repo)
    tree = store.snapshot()
    (repo / "run.sh").write_text("changed\n")
    (repo / "run.sh").chmod(0o644)
    (repo / "pointing").unlink()
    (repo / "pointing").write_text("no longer a link\n")
    (repo / "deep" / "er.txt").unlink()
    (repo / "deep").rmdir()
    (repo / "deep").write_text("a file now\n")
    (repo / "fresh.txt").write_text("new\n")
    paths = [Path("run.sh"), Path("pointing"), Path("deep/er.txt"), Path("fresh.txt")]
    store.restore(tree, paths)
    assert (repo / "run.sh").read_text() == "#!/bin/sh\n"
    assert (repo / "run.sh").stat().st_mode & 0o100
    assert (repo / "pointing").readlink() == Path("README.md")
    assert (repo / "deep" / "er.txt").read_bytes() == b"\xff\r\nbytes\n"
    assert not (repo / "fresh.txt").exists()
    assert store.snapshot() == tree
    assert shell.git(repo, "status", "--porcelain") == ""


def test_nothing_is_written_where_the_worktree_itself_was_swapped_for_a_link(
    bare: Path, tmp_path: Path, outside: Path
) -> None:
    """A room moves what's inside the git directory it mounts, `tree/` and each worktree among it."""
    before_there = everything(outside)
    root = bare / "tree" / "main"
    store = Store(layout=_layout(tmp_path).store(root), worktree=root, within=bare)
    tree = store.snapshot()
    moved = bare / "tree" / "moved"
    root.rename(moved)
    (outside / "main").mkdir()
    root.symlink_to(outside / "main")
    with pytest.raises(OSError, match="main"):
        store.save(1, AGENTS, b"written\n")
    with pytest.raises(OSError, match="main"):
        store.restore(tree, [Path("pyproject.toml")])
    assert everything(outside) == before_there
    assert list((outside / "main").iterdir()) == []


# An approved write made.


@pytest.mark.parametrize("swap", ["directory", "name"])
def test_an_approved_write_made_after_its_call_ended_is_made_in_the_worktree_or_not_at_all(
    kit: Kit, repo: Path, shell: Shell, outside: Path, *, dying: Dying, swap: str
) -> None:
    before_there = everything(outside)
    kit.announced.answering = None
    guarded = repo / ".github"
    guarded.mkdir()
    (guarded / "AGENTS.md").write_text("as accepted\n")
    shell.commit(repo, "a protected file")
    SessionStarted(session=SESSION, cwd=repo).apply(kit.bench)
    write = Overwrite(
        call="w1", tool="Write", path=guarded / "AGENTS.md", text="approved\n"
    )
    dying.at_next_wait(kit.clock)
    with pytest.raises(dying.died):
        before(kit.bench, write, SESSION, repo)
    [hold] = waiting(kit.layout)
    if swap == "directory":
        (guarded / "AGENTS.md").unlink()
        guarded.rmdir()
        guarded.symlink_to(outside)
    else:
        (guarded / "AGENTS.md").unlink()
        (guarded / "AGENTS.md").symlink_to(outside / "AGENTS.md")
    answer(kit.layout, hold.key, Response(approved=True), [], kit.clock)
    begin(kit, repo, "c1")
    finish(kit, repo, "c1")
    assert everything(outside) == before_there


# A report kept.


@pytest.mark.parametrize("link", ["lup", "lup/reports"])
def test_a_report_is_kept_in_the_git_directory_and_forgets_none_elsewhere(
    bare: Path, clock: FakeClock, outside: Path, link: str
) -> None:
    for number in range(5):
        (outside / f"{number}.txt").write_text("the host's own\n")
    before_there = everything(outside)
    (bare / link).parent.mkdir(exist_ok=True)
    (bare / link).symlink_to(outside)
    reports = Reports(layout=GitDirectoryLayout(common=bare), clock=clock, kept=2)
    kept = reports.keep("A report.\n")
    assert everything(outside) == before_there
    assert kept.read_text() == "A report.\n"
    assert kept.is_relative_to(bare / "lup" / "reports")
    assert not (bare / link).is_symlink()


def test_a_report_keeps_the_latest_of_them(bare: Path, clock: FakeClock) -> None:
    reports = Reports(layout=GitDirectoryLayout(common=bare), clock=clock, kept=2)
    made: list[Path] = []
    for number in range(4):
        clock.sleep(1)
        made.append(reports.keep(f"Report {number}.\n"))
    assert sorted(each.name for each in (bare / "lup" / "reports").iterdir()) == sorted(
        each.name for each in made[-2:]
    )


# A ref moved.


def test_git_on_the_host_writes_no_ref_through_a_link_under_refs(
    bare: Path, shell: Shell, outside: Path
) -> None:
    before_there = everything(outside)
    (bare / "refs" / "remotes").mkdir(exist_ok=True)
    (bare / "refs" / "remotes" / "origin").symlink_to(outside)
    tip = shell.git(bare, "rev-parse", "main")
    said = tracked(Git.pinned(bare), "origin", "refs/heads/dev", tip)
    assert everything(outside) == before_there
    [line] = said
    assert "`origin/dev` here still names what it did: its refs hold a link" in line
    (outside / "main").write_text(f"{tip}\n")
    kept = local_deleted(Git.pinned(bare), "refs/remotes/origin/main", tip)
    assert (outside / "main").read_text() == f"{tip}\n"
    assert "its refs hold a link" in kept.left[0]


def test_git_on_the_host_moves_a_ref_where_no_link_is_on_the_way(
    bare: Path, shell: Shell
) -> None:
    tip = shell.git(bare, "rev-parse", "main")
    assert tracked(Git.pinned(bare), "origin", "refs/heads/dev", tip) == []
    assert shell.git(bare, "rev-parse", "refs/remotes/origin/dev") == tip
    done = local_deleted(Git.pinned(bare), "refs/remotes/origin/dev", tip)
    assert done.left == []


# What each of it rests on.


def test_confined_keeps_a_path_going_outside_it_out(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    confined = Confined(root=root)
    for path in [Path("../out.txt"), Path("a/../../out.txt"), Path("/etc/out.txt")]:
        with pytest.raises(ValueError, match="isn't a path inside"):
            confined.laid(path, b"x")
        assert confined.written(path, b"x") is False
        assert confined.removed(path) is False
    assert not (tmp_path / "out.txt").exists()


def test_written_refuses_what_laid_replaces(tmp_path: Path, outside: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "away").symlink_to(outside)
    (root / "file").write_text("a file\n")
    (root / "link").symlink_to(outside / "own.txt")
    confined = Confined(root=root)
    assert confined.written(Path("away/new.txt"), b"x") is False
    assert confined.written(Path("file/new.txt"), b"x") is False
    assert confined.written(Path("link"), b"x") is False
    assert confined.written(Path("made/on/the/way.txt"), b"x") is True
    assert (root / "made" / "on" / "the" / "way.txt").read_bytes() == b"x"
    assert (outside / "own.txt").read_text() == "the host's own\n"
    assert not (outside / "new.txt").exists()
    confined.laid(Path("away/new.txt"), b"y")
    assert (root / "away" / "new.txt").read_bytes() == b"y"
    assert not (outside / "new.txt").exists()


def test_removed_removes_what_s_there_and_nothing_through_a_link(
    tmp_path: Path, outside: Path
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "away").symlink_to(outside)
    (root / "link").symlink_to(outside / "own.txt")
    (root / "file").write_text("a file\n")
    (root / "dir").mkdir()
    (root / "dir" / "inner").symlink_to(outside)
    (root / "other").write_text("in the way\n")
    confined = Confined(root=root)
    assert confined.removed(Path("away/own.txt")) is False
    assert (outside / "own.txt").exists()
    assert confined.removed(Path("link")) is True
    assert not (root / "link").is_symlink()
    assert (outside / "own.txt").exists()
    assert confined.removed(Path("file")) is True
    assert confined.removed(Path("dir")) is True
    assert not (root / "dir").exists()
    assert (outside / "own.txt").exists()
    assert confined.removed(Path("missing")) is True
    assert confined.removed(Path("other/under")) is False
    assert (root / "other").exists()
