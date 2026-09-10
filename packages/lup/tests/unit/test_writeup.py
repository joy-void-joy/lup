"""Documents generated from the ledger, declared as parts.

Written against the failure the worked example produced: a document whose
figures went stale behind a register nobody applied. Here a figure is the
node's, cited, with its standing; a figure that stopped standing is struck
through; and one log renders one document, so verifying against it means
something.
"""

from pathlib import Path
from typing import Literal

import pytest

from lup.coordination.identity import mint_member_id
from lup.coordination.refs import ActorRef
from lup.coordination.tasks import Blocks, Task
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerNode, Standing, Surroundings
from lup.ledger.writeup import (
    Listing,
    NeedsPerson,
    Placeholder,
    Prose,
    Stamp,
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
