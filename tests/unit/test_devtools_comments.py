"""Behavior tests for `lup-devtools dev comments` scanning and clearing.

Runs against a throwaway git repo: `scan_tracked(find_feedback)` must report
tracked notes with their read-context window, and `clear_markers` must strip
exactly the targeted spans — inline markers keep their code, standalone
blocks vanish whole — only ever on a `resolve/*` branch, and never a
`defer[...]` note without `--wake`. The `dev check` comments gate and the
listing renderer must keep deferred notes visible in their own section.
"""

from pathlib import Path

import pytest
import sh
import typer

from lup.codescan.markers import NoteKind
from lup_template.devtools.dev import comments
from lup_template.devtools.dev.check import comments_gate_lines

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
    found = comments.scan_tracked(comments.find_feedback)

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
    found = comments.scan_tracked(comments.find_feedback)
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


DEFER_SOURCE = """\
epsilon = 5
# lup: defer[until the cache rework lands]: revisit epsilon
zeta = 6
"""


def tracked_defer_file(repo: Path) -> Path:
    git = sh.Command("git").bake("-C", str(repo), _tty_out=False)
    path = repo / "parked.py"
    path.write_text(DEFER_SOURCE, encoding="utf-8")
    git("add", "parked.py")
    git("commit", "-m", "chore: park work")
    git("checkout", "-b", "resolve/x")
    return path


def test_clear_skips_a_deferred_note_without_wake(repo: Path) -> None:
    path = tracked_defer_file(repo)

    comments.clear_markers(["parked.py:2"])

    assert (
        path.read_text(encoding="utf-8") == DEFER_SOURCE
    )  # parked work survives an ordinary sweep


def test_clear_strips_a_deferred_note_with_wake(repo: Path) -> None:
    path = tracked_defer_file(repo)

    comments.clear_markers(["parked.py:2"], wake=True)

    assert path.read_text(encoding="utf-8").splitlines() == ["epsilon = 5", "zeta = 6"]


def note_at(
    file: str,
    line: int,
    text: str = "fix it",
    kind: NoteKind = "note",
    condition: str | None = None,
) -> comments.FoundComment:
    return comments.FoundComment(
        file=file,
        start_line=line,
        end_line=line,
        read_start=max(1, line - 2),
        read_end=line + 2,
        text=text,
        kind=kind,
        condition=condition,
        context="",
    )


def test_comments_gate_lists_deferred_after_unresolved() -> None:
    lines = comments_gate_lines(
        [
            note_at("a.py", 3),
            note_at(
                ".gitignore",
                9,
                kind="defer",
                condition="until branches merge",
                text="purge notes history",
            ),
        ]
    )

    assert lines == [
        "claude comments: FAIL (1 unresolved, 1 deferred)",
        "  a.py:3-3",
        "  deferred[until branches merge] .gitignore:9-9",
    ]


def test_comments_gate_stays_red_on_defers_alone() -> None:
    lines = comments_gate_lines(
        [note_at("a.py", 3, kind="defer", condition="until v2", text="parked")]
    )

    assert lines[0] == "claude comments: FAIL (0 unresolved, 1 deferred)"


def test_render_separates_the_deferred_section(
    capsys: pytest.CaptureFixture[str],
) -> None:
    comments.render(
        [
            note_at("a.py", 3, kind="defer", condition="until v2", text="parked work"),
            note_at("b.py", 7, text="open feedback"),
        ],
        as_json=False,
        empty="none",
    )

    out = capsys.readouterr().out
    assert "Deferred — parked until each wake condition is met:" in out
    assert out.index("open feedback") < out.index("defer[until v2] parked work")
    assert "2 comment(s) in 2 file(s) (1 deferred)" in out
