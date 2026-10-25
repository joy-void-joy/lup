"""The reports, in pyright's shape: each finding told once, and a long report fitted to a hook."""

from pathlib import Path
from typing import TYPE_CHECKING

from lup_dev.codescan.contract import Finding, Position, Span
from lup_dev.layout import GitDirectoryLayout
from lup_dev.policy.judge import Ask, RemovedNote
from lup_dev.policy.report import (
    Look,
    Moved,
    MovedFile,
    Part,
    Refused,
    Reports,
    fitted,
    information,
    moved,
    news,
    refusal,
    removed_notes,
    text,
    turn_end,
)

if TYPE_CHECKING:
    from conftest import FakeClock

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
    assert text(information(reported, [], [], [])) == documented()


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
    assert information([], [], [], []) == []
    assert removed_notes([]) == ""
    assert turn_end([]) == []


def test_information_sections() -> None:
    report = text(
        information(
            [found(at(1, 1), "regex", "uses re", steer="parse it")],
            [found(at(3, 1), "reportCallIssue", "bad call", owner="pyright")],
            [found(at(5, 1), "regex", "uses re")],
            [found(at(7, 1), "reportCallIssue", "caller broke", owner="pyright")],
        )
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
    assert text(
        turn_end([found(at(1, 1), "E501", "too long", owner="ruff")])
    ).startswith("lup won't end the turn yet")


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


def pyright(line: int, message: str = "bad call", path: Path = Path("a.py")) -> Finding:
    where = Position(line=line, column=1)
    return Finding(
        path=path,
        span=Span(start=where, end=where),
        owner="pyright",
        rule="reportCallIssue",
        message=message,
    )


def look(content: str, *found: Finding, path: Path = Path("a.py")) -> Look:
    return Look(path=path, owners=["pyright"], findings=list(found), content=content)


def test_a_finding_is_told_once_while_it_stands() -> None:
    first = news([], [look("call()\n", pyright(1))])
    assert first.findings == [pyright(1)]
    again = news(first.known, [look("call()\n", pyright(1))])
    assert again.findings == []


def test_a_finding_moved_by_an_edit_above_is_not_new() -> None:
    first = news([], [look("call()\n", pyright(1))])
    moved_down = news(first.known, [look("import x\n\ncall()\n", pyright(3))])
    assert moved_down.findings == []


def test_a_finding_on_a_changed_line_is_new() -> None:
    first = news([], [look("call()\n", pyright(1))])
    assert news(first.known, [look("call(2)\n", pyright(1))]).findings == [pyright(1)]


def test_a_finding_gone_and_back_is_told_again() -> None:
    first = news([], [look("call()\n", pyright(1))])
    gone = news(first.known, [look("call()\n")])
    assert gone.known == []
    assert news(gone.known, [look("call()\n", pyright(1))]).findings == [pyright(1)]


def test_what_no_look_read_stays_known() -> None:
    other = Path("b.py")
    first = news([], [look("call()\n", pyright(1, path=other), path=other)])
    unrelated = news(first.known, [look("call()\n", pyright(1))])
    assert unrelated.findings == [pyright(1)]
    assert (
        news(
            unrelated.known, [look("call()\n", pyright(1, path=other), path=other)]
        ).findings
        == []
    )


def test_a_look_forgets_only_the_owners_it_read() -> None:
    lup = pyright(1).model_copy(update={"owner": "lup", "rule": "regex"})
    first = news(
        [],
        [
            Look(
                path=Path("a.py"),
                owners=["lup", "pyright"],
                findings=[lup, pyright(1)],
                content="call()\n",
            )
        ],
    )
    importers = news(first.known, [look("call()\n")])
    assert (
        news(
            importers.known,
            [
                Look(
                    path=Path("a.py"),
                    owners=["lup"],
                    findings=[lup],
                    content="call()\n",
                )
            ],
        ).findings
        == []
    )


def reports(tmp_path: Path, clock: FakeClock) -> Reports:
    return Reports(layout=GitDirectoryLayout(common=tmp_path), clock=clock)


def test_a_report_that_fits_is_told_whole(tmp_path: Path, clock: FakeClock) -> None:
    parts = [Part(whole="refused"), Part(whole="findings", short="short")]
    assert fitted(parts, 100, reports(tmp_path, clock)) == "refused\n\nfindings"
    assert not (tmp_path / "lup" / "reports").exists()


def test_a_long_report_is_kept_whole_and_told_short(
    tmp_path: Path, clock: FakeClock
) -> None:
    long = "x" * 500
    parts = [
        Part(whole="lup refused 1 file."),
        Part(whole=f"rules\n{long}", short="rules: 1 file"),
        Part(whole="types\n  a.py:1:1", short="types: 1 file"),
        Part(whole=f"importers\n{long}", short="importers: 3 files"),
    ]
    said = fitted(parts, 400, reports(tmp_path, clock))
    [kept] = (tmp_path / "lup" / "reports").iterdir()
    assert kept.read_text() == text(parts)
    assert f"kept whole at {kept}" in said
    assert "lup refused 1 file." in said
    assert "rules: 1 file" in said
    assert "types\n  a.py:1:1" in said
    assert "importers: 3 files" in said
    assert long not in said


def test_only_the_latest_reports_are_kept(tmp_path: Path, clock: FakeClock) -> None:
    keeper = Reports(layout=GitDirectoryLayout(common=tmp_path), clock=clock, kept=2)
    for each in ["first", "second", "third"]:
        keeper.keep(each)
        clock.sleep(1)
    kept = sorted((tmp_path / "lup" / "reports").iterdir())
    assert [path.read_text() for path in kept] == ["second", "third"]


def test_a_section_told_short_counts_each_files_findings_by_rule() -> None:
    found = [
        pyright(1, path=PATH),
        pyright(2, path=PATH),
        pyright(3, path=ROOT / "b.py").model_copy(
            update={"rule": "reportAttributeAccessIssue"}
        ),
    ]
    [part] = information([], [], [], found)
    assert part.short == (
        "Type errors in files that import what changed (clean them before the turn ends):\n"
        "  /work/lup/src/lup/claude.py: 2 (reportCallIssue 2)\n"
        "  /work/lup/b.py: 1 (reportAttributeAccessIssue 1)"
    )


def test_a_value_never_published_is_always_told_whole() -> None:
    private = pyright(1, path=PATH).model_copy(
        update={"owner": "lup", "rule": "private"}
    )
    [part] = information([private], [], [], [])
    assert part.short is None
