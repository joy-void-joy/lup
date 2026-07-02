"""Behavior tests for `lup-devtools dev comments` scanning and clearing.

Runs against a throwaway git repo: `scan_feedback` must report tracked
notes with their read-context window, and `clear_markers` must strip
exactly the targeted spans — inline markers keep their code, standalone
blocks vanish whole — and only ever on a `resolve/*` branch.
"""

from pathlib import Path

import pytest
import sh
import typer

from lup_template.devtools.dev import comments

PY_SOURCE = """\
alpha = 1
beta = 2
# lup: rework this section
# it also drags in the lines below
gamma = 3
delta = 4  # lup: rename delta
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "repo"
    work.mkdir()
    hooks = tmp_path / "no-hooks"
    hooks.mkdir()
    git = sh.Command("git").bake(
        "-C",
        str(work),
        "-c",
        "commit.gpgsign=false",
        "-c",
        f"core.hooksPath={hooks}",
        _tty_out=False,
    )
    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (work / "code.py").write_text(PY_SOURCE, encoding="utf-8")
    git("add", "code.py")
    git("commit", "-m", "chore: base")
    monkeypatch.chdir(work)
    return work


def test_scan_reports_notes_with_read_context(repo: Path) -> None:
    found = comments.scan_feedback()

    assert [(c.file, c.start_line, c.end_line) for c in found] == [
        ("code.py", 3, 4),
        ("code.py", 6, 6),
    ]
    block, inline = found
    # The continuation comment line is merged into the note text.
    assert block.text == "rework this section it also drags in the lines below"
    # The context window is the actual read span cut from the file.
    assert block.read_start == 1
    assert block.context.splitlines()[0] == "alpha = 1"
    assert "gamma = 3" in block.context
    assert inline.text == "rename delta"


def test_scan_ignores_untracked_files(repo: Path) -> None:
    (repo / "scratch.py").write_text("# lup: never committed\n", encoding="utf-8")
    found = comments.scan_feedback()
    assert all(c.file != "scratch.py" for c in found)


def test_clear_refuses_outside_a_resolve_branch(repo: Path) -> None:
    before = (repo / "code.py").read_text(encoding="utf-8")
    with pytest.raises(typer.Exit):
        comments.clear_markers(["code.py:6"])
    assert (repo / "code.py").read_text(encoding="utf-8") == before


def test_clear_inline_marker_keeps_the_code(repo: Path) -> None:
    sh.Command("git")("-C", str(repo), "checkout", "-b", "resolve/x", _tty_out=False)

    comments.clear_markers(["code.py:6"])

    text = (repo / "code.py").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[5] == "delta = 4"  # code survives, comment is gone
    assert lines[2] == "# lup: rework this section"  # untargeted note stays
    assert text.endswith("\n")  # trailing newline preserved


def test_clear_standalone_block_removes_the_whole_span(repo: Path) -> None:
    sh.Command("git")("-C", str(repo), "checkout", "-b", "resolve/x", _tty_out=False)

    comments.clear_markers(["code.py:3"])

    lines = (repo / "code.py").read_text(encoding="utf-8").splitlines()
    assert lines == [
        "alpha = 1",
        "beta = 2",
        "gamma = 3",
        "delta = 4  # lup: rename delta",
    ]


def test_clear_skips_malformed_and_missing_targets(repo: Path) -> None:
    sh.Command("git")("-C", str(repo), "checkout", "-b", "resolve/x", _tty_out=False)
    before = (repo / "code.py").read_text(encoding="utf-8")

    comments.clear_markers(["no-line-part", "code.py:99"])

    assert (repo / "code.py").read_text(encoding="utf-8") == before
