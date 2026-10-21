"""The reports, in pyright's shape."""

from pathlib import Path

from lup_dev.codescan.contract import Finding, Position, Span
from lup_dev.policy.judge import Ask, RemovedNote
from lup_dev.policy.report import (
    Moved,
    MovedFile,
    Refused,
    information,
    moved,
    refusal,
    removed_notes,
    turn_end,
    unheld,
)

ROOT = Path("/work/lup")
PATH = ROOT / "src/lup/claude.py"


def found(
    place: Position, rule: str, message: str, *, steer: str = "", owner: str = "lup"
) -> Finding:
    return Finding.model_validate(
        {
            "path": PATH,
            "span": Span(start=place, end=place),
            "owner": owner,
            "rule": rule,
            "message": message,
            "steer": steer,
        }
    )


def documented() -> str:
    """Read the findings report `docs/judging-writes.md` shows, so the two agree."""
    doc = Path(__file__).parents[3] / "docs" / "judging-writes.md"
    text = doc.read_text()
    shown = text.index("```", text.index("The report, in pyright's shape:")) + len(
        "```\n"
    )
    return text[shown : text.index("```", shown)].rstrip("\n")


def at(line: int, column: int = 1) -> Position:
    return Position(line=line, column=column)


def test_the_findings_report_has_the_documented_shape() -> None:
    reported = [
        found(
            at(41, 12),
            "tuple-shape",
            "a fixed-length tuple[str, int] hides what each position means",
            steer="name the fields with a pydantic model",
        ),
        found(
            at(88, 5),
            "regex",
            "`import re` parses with a regular expression",
            steer="use the format's own parser (lup docs rules regex)",
        ),
    ]
    assert information(reported, [], [], []) == documented()


def test_a_refusal_lists_each_file_put_back_with_its_saved_copy() -> None:
    first = Refused(
        path=PATH,
        saved=ROOT / ".lup/saved/4/src/lup/claude.py",
        new=False,
        declined="not this way",
    )
    second = Refused(
        path=ROOT / "src/lup/new.py",
        saved=ROOT / ".lup/saved/4/src/lup/new.py",
        new=True,
        unanswered=True,
    )
    assert refusal([first, second]) == (
        "lup refused 2 files. They are unchanged; your versions are saved.\n\n"
        "/work/lup/src/lup/claude.py (saved at /work/lup/.lup/saved/4/src/lup/claude.py)\n"
        "  The operator declined it: not this way\n\n"
        "/work/lup/src/lup/new.py (saved at /work/lup/.lup/saved/4/src/lup/new.py)\n"
        "  Nobody answered in time; the hold stays open in the operator's inbox."
    )


def test_a_declined_or_unanswered_hold() -> None:
    declined = Refused(
        path=PATH, saved=Path("s"), new=True, declined="use the other module"
    )
    assert "  The operator declined it: use the other module" in refusal([declined])
    silent = Refused(path=PATH, saved=Path("s"), new=True, declined="")
    assert "  The operator declined it." in refusal([silent])
    unanswered = Refused(path=PATH, saved=Path("s"), new=True, unanswered=True)
    assert (
        "Nobody answered in time; the hold stays open in the operator's inbox."
        in refusal([unanswered])
    )


def test_nothing_refused_is_no_report() -> None:
    assert refusal([]) == ""
    assert information([], [], [], []) == ""
    assert removed_notes([]) == ""
    assert turn_end([]) == ""


def test_information_sections() -> None:
    report = information(
        [found(at(1, 1), "regex", "uses re", steer="parse it")],
        [found(at(3, 1), "reportCallIssue", "bad call", owner="pyright")],
        [found(at(5, 1), "regex", "uses re")],
        [found(at(7, 1), "reportCallIssue", "caller broke", owner="pyright")],
    )
    assert report.startswith(
        "lup's findings on the lines changed (clear each, or keep it with "
        '`# lup: ignore("<rule>", why="<reason>")` on its line or the line above, '
        "which the operator is asked about; they fail the gate):\n"
        "  /work/lup/src/lup/claude.py:1:1 - regex: uses re\n"
        "      steer: parse it\n\n"
        "Type errors and ruff's findings in the files changed "
        "(clean them before the turn ends):\n"
        "  /work/lup/src/lup/claude.py:3:1"
    )
    assert (
        "lup's findings on lines no change touched (they fail the gate too):" in report
    )
    assert "Type errors in files that import what changed" in report


def test_removed_notes_and_turn_end() -> None:
    assert removed_notes([RemovedNote(path=PATH, text="the limit")]).endswith(
        "  /work/lup/src/lup/claude.py: # lup: the limit"
    )
    assert turn_end([found(at(1, 1), "E501", "too long", owner="ruff")]).startswith(
        "lup won't end the turn yet"
    )


def test_what_doesnt_hold_the_turns_end() -> None:
    left = [found(at(2, 5), "reportCallIssue", "wrong arguments", owner="pyright")]
    assert unheld([], "working") == ""
    working = unheld(left, "working")
    assert working.startswith(
        "A subagent of this session at work touched these files too"
    )
    assert working.endswith(
        "  /work/lup/src/lup/claude.py:2:5 - reportCallIssue: wrong arguments"
    )
    assert "they fail the gate until cleared" in unheld(left, "repeated")


def test_a_move_of_head_is_told_as_its_commits() -> None:
    told = moved(
        [
            Moved(
                worktree=ROOT,
                head="1a2b3c",
                files=[
                    MovedFile(
                        path=PATH,
                        findings=[found(at(3, 1), "regex", "uses re")],
                        asks=[Ask(kind="new-file", reason=f"{PATH} is new")],
                    ),
                    MovedFile(path=ROOT / "README.md"),
                ],
                hold="ab12cd",
            )
        ]
    )
    assert told == (
        "HEAD moved to 1a2b3c in /work/lup, bringing content no checkpoint judged. "
        "It was judged once, as its commits', and stays as committed:\n"
        "/work/lup/src/lup/claude.py\n"
        "  /work/lup/src/lup/claude.py:3:1 - regex: uses re\n"
        "  asks: /work/lup/src/lup/claude.py is new\n"
        "lup's findings in them fail the gate: fix them in a later commit.\n"
        "The operator is asked about the rest after the fact, in their inbox "
        "(hold ab12cd)."
    )
    quiet = Moved(worktree=ROOT, head="1a2b3c", files=[MovedFile(path=PATH)])
    assert moved([quiet]) == ""
