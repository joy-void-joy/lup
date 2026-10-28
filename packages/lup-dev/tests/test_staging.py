"""`lup-dev stage`: a file's hunks listed, numbered, and those chosen staged, never committed."""

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup.programs import run
from lup_dev import cli
from lup_dev.staging import Changed, Lines, StagingError

if TYPE_CHECKING:
    from conftest import Shell

runner = CliRunner()

BEFORE = """import os


def foo():
    a = 1
    b = 2
    return a + b


def gone():
    pass


def tail():
    return 0
"""

AFTER = """import os
import sys


def foo():
    a = 10
    b = 20
    c = 30
    return a + b + c


def bar():
    return 1


def tail():
    return 0
"""
"""Three hunks against `BEFORE`: an import added at line 2, `foo`'s body edited
with a line inserted at lines 6-9, and `gone` replaced by `bar` at lines 12-13."""


def indexed(root: Path, path: str) -> str:
    """Return what the index holds for `path`, whole."""
    return run("git", "show", f":{path}", cwd=root).output.decode()


def edited(repo: Path, shell: Shell, before: str = BEFORE, after: str = AFTER) -> Path:
    """Commit `before` as `app.py`, then write `after` over it, unstaged."""
    path = repo / "app.py"
    path.write_text(before)
    shell.commit(repo, "app")
    path.write_text(after)
    return path


def test_the_listing_numbers_each_hunk_with_its_lines_and_its_first_changes(
    repo: Path, shell: Shell
) -> None:
    listed = Changed.of(edited(repo, shell)).listed(shown=2)
    assert listed == (
        "app.py: 3 hunks to stage.\n"
        "1  line 2 · +1\n"
        "     2 + import sys\n"
        "2  lines 6-9 · +4 -3\n"
        "       -     a = 1\n"
        "       -     b = 2\n"
        "         … 1 more\n"
        "     6 +     a = 10\n"
        "     7 +     b = 20\n"
        "         … 2 more\n"
        "3  lines 12-13 · +2 -2\n"
        "       - def gone():\n"
        "       -     pass\n"
        "    12 + def bar():\n"
        "    13 +     return 1"
    )
    whole = Changed.of(repo / "app.py").listed(whole=True)
    assert "     9 +     return a + b + c" in whole
    assert "more" not in whole


def test_hunks_staged_by_number_are_staged_alone_and_nothing_is_committed(
    repo: Path, shell: Shell
) -> None:
    path = edited(repo, shell)
    head = shell.git(repo, "rev-parse", "HEAD")
    staged = Changed.of(path).stage([1, 3])
    assert indexed(repo, "app.py") == BEFORE.replace(
        "import os\n", "import os\nimport sys\n"
    ).replace("def gone():\n    pass\n", "def bar():\n    return 1\n")
    assert path.read_text() == AFTER
    assert shell.git(repo, "rev-parse", "HEAD") == head
    assert staged.left == 1
    said = staged.said()
    assert said.startswith("Staged in app.py, numbered as in the index:\n")
    assert "     2 + import sys" in said
    assert said.endswith("1 hunk left, numbered afresh.")
    assert (
        Changed.of(path).listed().startswith("app.py: 1 hunk to stage.\n1  lines 6-9")
    )


def test_a_range_takes_an_edited_line_with_the_line_it_was(
    repo: Path, shell: Shell
) -> None:
    path = edited(repo, shell)
    Changed.of(path).stage([], Lines(first=9, last=9))
    assert "    a = 1\n    b = 2\n    return a + b + c\n" in indexed(repo, "app.py")
    assert "return a + b\n" not in indexed(repo, "app.py")


def test_a_range_taking_an_inserted_line_takes_nothing_removed(
    repo: Path, shell: Shell
) -> None:
    path = edited(repo, shell)
    Changed.of(path).stage([], Lines(first=8, last=8))
    assert "    a = 1\n    b = 2\n    c = 30\n    return a + b\n" in indexed(
        repo, "app.py"
    )


def test_a_range_still_holds_after_another_staging_renumbers_the_hunks(
    repo: Path, shell: Shell
) -> None:
    path = edited(repo, shell)
    Changed.of(path).stage([1])
    Changed.of(path).stage([], Lines(first=12, last=13))
    assert "def bar():\n    return 1\n" in indexed(repo, "app.py")
    assert "def gone" not in indexed(repo, "app.py")
    assert "a = 1\n" in indexed(repo, "app.py")


def test_a_range_takes_lines_removed_between_two_of_its_lines_and_no_others(
    repo: Path, shell: Shell
) -> None:
    before = "a\nb\ngone\nc\nd\nalso gone\n"
    path = edited(repo, shell, before, "a\nb\nc\nd\n")
    with pytest.raises(StagingError, match="hold nothing to stage"):
        Changed.of(path).stage([], Lines(first=1, last=2))
    Changed.of(path).stage([], Lines(first=1, last=4))
    assert indexed(repo, "app.py") == "a\nb\nc\nd\nalso gone\n"
    assert Changed.of(path).listed() == (
        "app.py: 1 hunk to stage.\n1  after line 4 · -1\n      - also gone"
    )


def test_a_file_the_index_lacks_is_staged_in_part_with_its_mode(
    repo: Path, shell: Shell
) -> None:
    path = repo / "run.sh"
    path.write_text("#!/bin/sh\necho one\n\necho two\n")
    path.chmod(0o755)
    listed = Changed.of(path).listed()
    assert listed.startswith("run.sh: 1 hunk to stage.\n1  lines 1-4 · +4")
    Changed.of(path).stage([], Lines(first=1, last=2))
    assert indexed(repo, "run.sh") == "#!/bin/sh\necho one\n"
    assert shell.git(repo, "ls-files", "-s", "run.sh").startswith("100755 ")


def test_staging_keeps_the_entrys_mode_and_the_listing_says_its_change(
    repo: Path, shell: Shell
) -> None:
    path = edited(repo, shell)
    path.chmod(0o755)
    changed = Changed.of(path)
    assert (
        "Its mode changes to 100755, which `git update-index --chmod=+x app.py` stages."
    ) in changed.listed()
    changed.stage([1])
    assert shell.git(repo, "ls-files", "-s", "app.py").startswith("100644 ")


def test_the_file_is_read_as_git_add_would_store_it(repo: Path, shell: Shell) -> None:
    (repo / ".gitattributes").write_text("*.txt text eol=lf\n")
    path = edited(repo, shell)
    notes = repo / "notes.txt"
    notes.write_text("one\ntwo\nthree\n")
    shell.commit(repo, "notes")
    notes.write_bytes(b"one\r\ntwo\r\nTHREE\r\n")
    changed = Changed.of(notes)
    assert changed.listed() == (
        "notes.txt: 1 hunk to stage.\n1  line 3 · +1 -1\n      - three\n    3 + THREE"
    )
    changed.stage([1])
    assert indexed(repo, "notes.txt") == "one\ntwo\nTHREE\n"
    assert path.read_text() == AFTER


def test_a_last_line_without_a_newline_is_said_and_kept(
    repo: Path, shell: Shell
) -> None:
    path = edited(repo, shell, "a\nb\n", "a\nB\nc")
    assert "c  (no newline at the end)" in Changed.of(path).listed()
    Changed.of(path).stage([], Lines(first=3, last=3))
    assert indexed(repo, "app.py") == "a\nb\nc"


def test_a_path_is_read_from_where_it_is_given_in_any_worktree(
    repo: Path, linked: Path, shell: Shell, monkeypatch: pytest.MonkeyPatch
) -> None:
    (linked / "src" / "pkg" / "core.py").write_text('"""Core, edited."""\n')
    monkeypatch.chdir(repo / "src")
    changed = Changed.of(linked / "src" / "pkg" / "core.py")
    assert changed.listed().startswith("src/pkg/core.py: 1 hunk to stage.")
    changed.stage([1])
    assert indexed(linked, "src/pkg/core.py") == '"""Core, edited."""\n'
    assert shell.git(repo, "diff", "--cached", "--name-only") == ""
    monkeypatch.chdir(linked / "src")
    assert Changed.of(Path("pkg/core.py")).listed() == (
        "src/pkg/core.py: nothing to stage, the index holds it as it is."
    )


@pytest.mark.parametrize(
    ("made", "refused"),
    [
        ("binary", "is binary: `git add data.bin` stages it whole"),
        ("deleted", "is gone from the worktree: `git rm --cached README.md`"),
        ("ignored", "is ignored, and the index doesn't hold it"),
        ("link", "is a link: `git add link` stages it"),
        ("directory", "is a directory: name one of its files"),
        ("missing", "is in neither the worktree nor the index"),
    ],
)
def test_what_hunks_cant_stage_is_refused_saying_what_does(
    repo: Path, shell: Shell, made: str, refused: str
) -> None:
    match made:
        case "binary":
            given = repo / "data.bin"
            given.write_bytes(b"\0\1")
        case "deleted":
            given = repo / "README.md"
            given.unlink()
        case "ignored":
            given = repo / ".lup" / "kept.txt"
            given.parent.mkdir()
            given.write_text("kept\n")
        case "link":
            given = repo / "link"
            given.symlink_to("README.md")
        case "directory":
            given = repo / "src"
        case _:
            given = repo / "nothing.txt"
    with pytest.raises(StagingError, match=re.escape(refused)):
        Changed.of(given)


def test_a_file_in_conflict_is_refused(repo: Path, shell: Shell) -> None:
    readme = repo / "README.md"
    shell.git(repo, "checkout", "-q", "-b", "side")
    readme.write_text("# Side\n")
    shell.commit(repo, "side")
    shell.git(repo, "checkout", "-q", "main")
    readme.write_text("# Main\n")
    shell.commit(repo, "main")
    run("git", "merge", "-q", "side", cwd=repo, ok=[1])
    with pytest.raises(StagingError, match="in conflict"):
        Changed.of(readme)


def test_a_choice_naming_nothing_to_stage_stages_nothing(
    repo: Path, shell: Shell
) -> None:
    path = edited(repo, shell)
    changed = Changed.of(path)
    with pytest.raises(StagingError, match="has 3 hunks, so no hunk 4, 0"):
        changed.stage([1, 4, 0])
    with pytest.raises(StagingError, match=r"aren't a range of app\.py, which has 17"):
        changed.stage([], Lines(first=16, last=18))
    with pytest.raises(StagingError, match=r"Lines 3-4 of app\.py hold nothing"):
        changed.stage([], Lines(first=3, last=4))
    assert indexed(repo, "app.py") == BEFORE


def test_an_index_entry_changed_since_it_was_read_stages_nothing(
    repo: Path, shell: Shell
) -> None:
    path = edited(repo, shell)
    changed = Changed.of(path)
    shell.git(repo, "add", "app.py")
    with pytest.raises(StagingError, match="changed since it was read"):
        changed.stage([1])
    assert indexed(repo, "app.py") == AFTER


def test_the_command_lists_then_stages_what_it_names(repo: Path, shell: Shell) -> None:
    path = edited(repo, shell)
    listed = runner.invoke(cli.app, ["stage", str(path)])
    assert listed.exit_code == 0, listed.output
    assert listed.output.startswith("app.py: 3 hunks to stage.\n")
    staged = runner.invoke(
        cli.app, ["stage", str(path), "2", "--from", "12", "--to", "13"]
    )
    assert staged.exit_code == 0, staged.output
    assert staged.output.endswith("1 hunk left, numbered afresh.\n")
    alone = runner.invoke(cli.app, ["stage", str(path), "--from", "2"])
    assert alone.exit_code == 0, alone.output
    assert indexed(repo, "app.py") == AFTER
    unended = runner.invoke(cli.app, ["stage", str(path), "--to", "3"])
    assert isinstance(unended.exception, StagingError)
