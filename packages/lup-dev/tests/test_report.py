"""The reports, in pyright's shape: each finding told once, the standing words around them once, and a long report fitted to a hook."""

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
    Words,
    fitted,
    heard,
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
    place: Position,
    rule: str,
    message: str,
    *,
    steer: str = "",
    owner: str = "lup",
    detail: str = "",
) -> Finding:
    return Finding.model_validate(
        {
            "path": PATH,
            "span": Span(start=place, end=place),
            "owner": owner,
            "rule": rule,
            "message": message,
            "steer": steer,
            "detail": detail,
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
    assert text(information(reported, [], [], [], Words())) == documented()


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
    assert information([], [], [], [], Words()) == []
    assert removed_notes([]) == ""
    assert turn_end([]) == []


def test_information_sections() -> None:
    report = text(
        information(
            [found(at(1, 1), "regex", "uses re", steer="parse it")],
            [found(at(3, 1), "reportCallIssue", "bad call", owner="pyright")],
            [found(at(5, 1), "regex", "uses re")],
            [found(at(7, 1), "reportCallIssue", "caller broke", owner="pyright")],
            Words(),
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
        ],
        Words(),
    )
    assert text(told) == (
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
    assert moved([quiet], Words()) == []


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
    assert fitted(parts, 100, reports(tmp_path, clock)).text == "refused\n\nfindings"
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
    said = fitted(parts, 400, reports(tmp_path, clock)).text
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
    [part] = information([], [], [], found, Words())
    assert part.short == (
        "Type errors in files that import what changed (clean them before the turn ends):\n"
        "  /work/lup/src/lup/claude.py: 2 (reportCallIssue 2)\n"
        "  /work/lup/b.py: 1 (reportAttributeAccessIssue 1)"
    )


def test_a_value_never_published_is_always_told_whole() -> None:
    private = pyright(1, path=PATH).model_copy(
        update={"owner": "lup", "rule": "private"}
    )
    [part] = information([private], [], [], [], Words())
    assert part.short is None


# The standing words: a section's instructions, and a lup rule's mistake and
# steer, told once to each conversation.

SETS = "A set keeps only membership."
"""A rule's mistake, which the engine adds to what its check saw."""


def a_set(line: int, what: str = "`set()` builds a set") -> Finding:
    """A lup finding as the engine sends it: what its check saw, then the rule's mistake, with the rule's steer, and what it saw apart."""
    return found(
        at(line),
        "set-shape",
        f"{what}. {SETS}",
        steer="use a dict keyed by the members",
        detail=what,
    )


def test_a_rules_mistake_and_steer_come_with_its_first_finding_alone() -> None:
    parts = information([a_set(3)], [], [a_set(9, "`{1}` builds a set")], [], Words())
    assert text(parts).endswith(
        "  /work/lup/src/lup/claude.py:3:1 - set-shape: `set()` builds a set. "
        "A set keeps only membership.\n"
        "      steer: use a dict keyed by the members\n\n"
        "lup's findings on lines no change touched (they fail the gate too):\n"
        "  /work/lup/src/lup/claude.py:9:1 - set-shape: `{1}` builds a set"
    )
    assert [part.words.rules for part in parts] == [["set-shape"], []]


def test_a_later_report_says_each_section_told_before_by_its_title_and_each_rule_in_a_line() -> (
    None
):
    first = information([a_set(3)], [], [], [], Words())
    later = information([a_set(5, "`{1}` builds a set")], [], [], [], heard(first))
    assert text(later) == (
        "lup's findings on the lines changed:\n"
        "  /work/lup/src/lup/claude.py:5:1 - set-shape: `{1}` builds a set"
    )


def test_a_finding_with_nothing_apart_is_told_whole_each_time() -> None:
    known = Words(rules=["set-shape", "malformed-directive", "reportCallIssue"])
    directive = found(
        at(2), "malformed-directive", "`ignore` names no rule", steer="name one"
    )
    typed = found(at(4), "reportCallIssue", "bad call", owner="pyright")
    told = text(information([directive], [typed], [], [], known))
    assert "malformed-directive: `ignore` names no rule\n      steer: name one" in told
    assert "reportCallIssue: bad call" in told


def test_a_part_told_short_tells_its_header_and_not_its_rules_words(
    tmp_path: Path, clock: FakeClock
) -> None:
    many = [a_set(line) for line in range(1, 60)]
    parts = information(many, [], [], [], Words())
    told = fitted(parts, 400, reports(tmp_path, clock))
    assert "/work/lup/src/lup/claude.py: 59 (set-shape 59)" in told.text
    assert told.words.rules == []
    assert told.words.headers == parts[0].words.headers
    whole = fitted(parts, 100_000, reports(tmp_path, clock))
    assert whole.words.rules == ["set-shape"]


def test_the_turns_end_tells_every_finding_whole_and_its_words_are_then_known() -> None:
    [part] = turn_end([a_set(3), a_set(5)])
    assert part.whole.count("steer: use a dict keyed by the members") == 2
    assert part.words.rules == ["set-shape"]


def test_a_move_of_head_tells_a_rule_told_before_in_a_line() -> None:
    files = [MovedFile(path=PATH, findings=[a_set(3)])]
    [part] = moved(
        [Moved(worktree=ROOT, head="1a2b3c", files=files)],
        Words(rules=["set-shape"]),
    )
    assert "  /work/lup/src/lup/claude.py:3:1 - set-shape: `set()` builds a set\n" in (
        part.whole
    )
    assert "steer:" not in part.whole
