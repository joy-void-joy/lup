"""Documents generated from the ledger, declared as parts.

Written against the failure the worked example produced: a document whose
figures went stale behind a register nobody applied. Here a figure is the
node's, cited, with its standing; a figure that stopped standing is struck
through; and one log renders one document, so verifying against it means
something.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest

from lup.coordination.identity import mint_member_id
from lup.coordination.refs import ActorRef
from lup.coordination.tasks import Blocks, Task
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerNode, Standing, Surroundings
from lup.ledger.writeup import (
    Band,
    Listing,
    NeedsPerson,
    Placeholder,
    Prose,
    Stamp,
    Timeline,
    Writeup,
    WriteupError,
    render_writeup,
    write_writeup,
)


class Doubt(LedgerNode, frozen=True):
    """A test kind that never stands, so a struck-through figure can be seen."""

    kind: Literal["test:doubt"] = "test:doubt"

    def standing(self, around: Surroundings) -> Standing:
        del around
        return Standing(label="doubted", reason="by construction", sound=False)


CLASSES: list[type[LedgerNode]] = [Task, Doubt]


def store(root: Path) -> LedgerStore:
    return LedgerStore(root, ActorRef(kind="session", id=mint_member_id()))


def rows_of(lines: list[str]) -> list[str]:
    """The table rows of a rendered listing, header and rule left out."""
    return [line for line in lines if line.startswith("| ") and "`" in line]


def test_prose_fills_a_placeholder_with_a_cited_figure_and_strikes_an_unsound_one(
    tmp_path: Path,
) -> None:
    held = store(tmp_path)
    held.record(Task, "depth", text="two", slug="depth")
    held.record(Doubt, "guess", text="nine", slug="guess")
    part = Prose(
        text="Depth is {depth}; the guess was {guess}. Braces stay: {{literal}}.",
        figures=[
            Placeholder(name="depth", node="depth"),
            Placeholder(name="guess", node="guess"),
        ],
    )

    [line, _blank] = part.render(held, CLASSES)

    assert "**[two](lup:depth)**" in line
    assert "~~[nine](lup:guess)~~ (doubted: by construction)" in line
    assert "{literal}" in line
    with pytest.raises(WriteupError, match="placeholder"):
        Prose(
            text="{missing}", figures=[Placeholder(name="depth", node="depth")]
        ).render(held, CLASSES)
    with pytest.raises(WriteupError, match="nope"):
        Prose(text="{x}", figures=[Placeholder(name="x", node="nope")]).render(
            held, CLASSES
        )


def test_a_listing_selects_by_kind_standing_relation_and_name_in_priority_order(
    tmp_path: Path,
) -> None:
    held = store(tmp_path)
    low = held.record(Task, "low", slug="low", priority=1)
    high = held.record(Task, "high", slug="high", priority=5)
    done = held.record(Task, "done", slug="done")
    held.amend(done.completed())
    held.relate(Blocks, low, high)

    by_kind = "\n".join(
        Listing(heading="Tasks", of="coordination:task").render(held, CLASSES)
    )
    open_only = Listing(heading="Open", of="coordination:task", standing="open").render(
        held, CLASSES
    )
    blockers = "\n".join(
        Listing(heading="Blockers", into="high", via="coordination:blocks").render(
            held, CLASSES
        )
    )
    named = Listing(heading="Named", nodes=["done", "low"], numbered=True).render(
        held, CLASSES
    )
    nothing = Listing(heading="None", of="test:doubt", empty="Not a one.").render(
        held, CLASSES
    )

    assert by_kind.index("`high`") < by_kind.index("`low`") < by_kind.index("`done`")
    assert "| blocked | `high` |" in by_kind
    # `high` is blocked by `low` and `done` is done, so one task is open.
    assert [row for row in rows_of(open_only) if "`low`" in row] == rows_of(open_only)
    assert "`low`" in blockers and "`high`" not in blockers
    assert [row.startswith("| 1 |") for row in rows_of(named)] == [True, False]
    assert "`done`" in rows_of(named)[0] and "`low`" in rows_of(named)[1]
    assert "Not a one." in nothing


def test_a_listing_excluding_one_standing_keeps_every_other_label(
    tmp_path: Path,
) -> None:
    held = store(tmp_path)
    low = held.record(Task, "low", slug="low", priority=1)
    high = held.record(Task, "high", slug="high", priority=5)
    done = held.record(Task, "done", slug="done")
    held.amend(done.completed())
    held.relate(Blocks, low, high)
    unfinished = Listing(heading="Open", of="coordination:task", excluding="done")

    rendered = "\n".join(unfinished.render(held, CLASSES))
    contradictory = Listing(
        heading="None", of="coordination:task", standing="open", excluding="open"
    ).render(held, CLASSES)

    assert "`done`" not in rendered
    assert "| blocked | `high` |" in rendered and "| open | `low` |" in rendered
    assert rows_of(contradictory) == []
    assert unfinished.kinds() == ["coordination:task"]


def test_needs_person_and_stamp_render_from_the_log_deterministically(
    tmp_path: Path,
) -> None:
    held = store(tmp_path)
    held.record(Task, "paste this", holder="user", needs="command")
    held.record(Task, "decide that", holder="user", needs="judgement")
    writeup = Writeup(
        name="status",
        path="docs/status.md",
        source="tests",
        parts=[NeedsPerson(heading="For you"), Stamp(counting=["coordination:task"])],
    )

    first = render_writeup(held, CLASSES, writeup)
    second = render_writeup(held, CLASSES, writeup)

    assert first == second
    assert first.index("Commands to run") < first.index("Judgements to make")
    assert "2 node(s), 0 edge(s); 2 coordination:task; newest record" in first
    assert first.endswith("\n") and not first.endswith("\n\n")


def test_write_writeup_writes_with_a_banner_and_check_reports_a_stale_file(
    tmp_path: Path,
) -> None:
    held = store(tmp_path)
    held.record(Task, "first", slug="first")
    writeup = Writeup(
        name="status",
        path="docs/status.md",
        source="tests.writeups",
        parts=[Listing(heading="Tasks", of="coordination:task"), Stamp()],
    )

    written = write_writeup(writeup, CLASSES, tmp_path)

    assert written == tmp_path / "docs" / "status.md"
    body = written.read_text(encoding="utf-8")
    assert "tests.writeups" in body and "ledger writeup" in body and "`first`" in body
    assert write_writeup(writeup, CLASSES, tmp_path, check=True) == written
    held.record(Task, "second", slug="second")
    with pytest.raises(RuntimeError, match="stale"):
        write_writeup(writeup, CLASSES, tmp_path, check=True)


class Happening(LedgerNode, frozen=True):
    """A test kind dated on two clocks, the way a trace kind is."""

    kind: Literal["test:happening"] = "test:happening"
    happened: datetime | None = None
    before: datetime | None = None
    seen: datetime | None = None


class Window(LedgerNode, frozen=True):
    """A test kind framing a stretch of time, the way an incident does."""

    kind: Literal["test:window"] = "test:window"
    opens: datetime | None = None
    closes: datetime | None = None


def test_a_timeline_orders_by_the_named_clock_and_places_bounds_bands_and_undated_rows(
    tmp_path: Path,
) -> None:
    """Event time orders the rows; a bound says `before`; the second clock is
    shown and never ordered by; a band opens before and closes after the rows
    at its edges; what no clock places goes last under its own heading."""
    held = store(tmp_path)
    classes: list[type[LedgerNode]] = [Happening, Window, Task]
    june = datetime(2026, 6, 16, 9, 29, 53, tzinfo=UTC)
    held.record(
        Happening,
        "grammar switches on",
        slug="onset",
        happened=june.isoformat(),
        seen=datetime(2026, 9, 4, 15, 0, tzinfo=UTC).isoformat(),
    )
    held.record(
        Happening,
        "first link",
        slug="first",
        happened=datetime(2026, 5, 11, 12, 43, tzinfo=UTC).isoformat(),
    )
    held.record(
        Happening,
        "deleted page",
        slug="deleted",
        before=datetime(2026, 6, 19, 13, 33, 49, tzinfo=UTC).isoformat(),
    )
    held.record(Happening, "undated paste", slug="paste")
    held.record(
        Window,
        "dsewiki-2026",
        slug="dsewiki",
        opens=datetime(2026, 5, 11, 12, 43, tzinfo=UTC).isoformat(),
        closes=datetime(2026, 7, 2, tzinfo=UTC).isoformat(),
    )
    part = Timeline(
        heading="Timeline",
        of=["test:happening"],
        moment="happened",
        bound="before",
        beside="seen",
        bands=Band(of="test:window", start="opens", end="closes"),
    )

    rendered = "\n".join(part.render(held, classes))
    rows = rows_of(part.render(held, classes))

    assert rows[0].startswith(
        "| 2026-05-11 12:43:00Z | **[dsewiki-2026](lup:dsewiki)** opens |"
    )
    assert rows[1].startswith("| 2026-05-11 12:43:00Z | **[first link](lup:first)** |")
    assert rows[2].startswith(
        "| 2026-06-16 09:29:53Z | **[grammar switches on](lup:onset)** | 2026-09-04 15:00:00Z |"
    )
    assert rows[3].startswith(
        "| before 2026-06-19 13:33:49Z | **[deleted page](lup:deleted)** |"
    )
    assert rows[4].startswith(
        "| 2026-07-02 00:00:00Z | **[dsewiki-2026](lup:dsewiki)** closes |"
    )
    assert rendered.index("### Undated") > rendered.index("closes")
    assert rows[5].startswith("| **[undated paste](lup:paste)** |")
    assert "| happened | What | seen | Standing | Node |" in rendered
    assert part.kinds() == ["test:happening", "test:window"]


def test_a_timeline_takes_the_fallback_clock_and_says_which_it_took(
    tmp_path: Path,
) -> None:
    """A discovery timeline orders by when a thing was seen and falls back on
    when it was recorded, saying so on the row."""
    held = store(tmp_path)
    classes: list[type[LedgerNode]] = [Happening]
    held.record(Happening, "recorded only", slug="only")
    part = Timeline(
        heading="Discovery", of=["test:happening"], moment="seen", fallback="at"
    )

    [row] = rows_of(part.render(held, classes))
    nothing = Timeline(heading="None", of=["test:window"], moment="opens").render(
        held, classes
    )

    assert "(at) | **[recorded only](lup:only)** |" in row
    assert "Nothing is dated." in nothing
