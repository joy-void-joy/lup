"""The generic ledger commands, over kinds a project declared.

Written against the shape the corpus design settled on: one `record` and one
`relate` over declared kinds, with the type validating the fields, rather than
a command per kind that goes stale the moment a project adds one. The kinds
here are the library's own plus two declared by the test, because the library
ships no knowledge types — what a project records is the project's.
"""

from pathlib import Path
from typing import Literal, Self

import pytest
import typer
from pydantic import Field
from typer.testing import CliRunner

import lup.devtools.ledger.app as ledger_app
from lup.coordination.handoffs import Handoff, Transfers
from lup.coordination.refs import ActorRef
from lup.coordination.tasks import Blocks, Task
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerEdge, LedgerNode, Standing, Surroundings


class Pinned(LedgerNode, frozen=True):
    """A test kind that derives a field from the working tree as it is recorded."""

    kind: Literal["test:pinned"] = "test:pinned"
    watched: str = Field(min_length=1)
    size: int = -1

    def prepared(self, root: Path) -> Self:
        return self.model_copy(update={"size": len((root / self.watched).read_bytes())})

    def standing(self, around: Surroundings) -> Standing:
        if around.root is None:
            return Standing(label="unchecked")
        current = len((around.root / self.watched).read_bytes())
        if current != self.size:
            return Standing(label="stale", reason=f"{self.watched} grew", sound=False)
        return Standing(label="fresh")


class Cites(LedgerEdge, frozen=True):
    """A test relation that refuses a node citing itself."""

    kind: Literal["test:cites"] = "test:cites"
    note: str = Field(min_length=1)

    def refusal(self, source: LedgerNode, target: LedgerNode) -> str:
        return "a node cannot cite itself" if source.id == target.id else ""


def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> typer.Typer:
    monkeypatch.setattr(ledger_app, "project_root", lambda: tmp_path)
    return ledger_app.create_ledger_app(
        [Task, Handoff, Pinned], [Blocks, Transfers, Cites]
    )


def run(cli: typer.Typer, *args: str):
    return CliRunner().invoke(cli, list(args))


def latest[N: LedgerNode](root: Path, kind: type[N]) -> N:
    """The most recently recorded node of one kind, read back through the store."""
    return LedgerStore(root, ActorRef(kind="test", id="t")).read(kind)[-1]


def test_types_lists_kinds_with_the_fields_record_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run(app(tmp_path, monkeypatch), "types")

    assert result.exit_code == 0, result.output
    assert "coordination:task" in result.output and "needs" in result.output
    assert "test:cites" in result.output and "note" in result.output
    assert "author" not in result.output


def test_record_validates_through_the_declared_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = app(tmp_path, monkeypatch)

    recorded = run(
        cli,
        "record",
        "coordination:task",
        "finish it",
        "--text",
        "today",
        "--slug",
        "finish",
        "--json",
        '{"needs": "review", "priority": 3}',
    )
    assert recorded.exit_code == 0, recorded.output
    task = latest(tmp_path, Task)
    assert task.needs == "review" and task.priority == 3 and task.slug == "finish"
    assert "finish it" in run(cli, "show", "finish").output

    refused = run(
        cli, "record", "coordination:task", "x", "--json", '{"needs": "sideways"}'
    )
    assert refused.exit_code != 0
    taken = run(cli, "record", "coordination:task", "y", "--slug", "finish")
    assert taken.exit_code != 0 and "already names" in taken.output
    unknown = run(cli, "record", "nope:kind", "x")
    assert unknown.exit_code != 0 and "ledger types" in unknown.output


def test_a_type_pins_what_it_derives_from_the_tree_as_it_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller names the file; the type takes the measurement at record time,
    and its standing reads the tree again on every look.
    """
    (tmp_path / "parser.py").write_text("v1", encoding="utf-8")
    cli = app(tmp_path, monkeypatch)

    recorded = run(
        cli, "record", "test:pinned", "size", "--json", '{"watched": "parser.py"}'
    )

    assert recorded.exit_code == 0, recorded.output
    assert latest(tmp_path, Pinned).size == 2
    assert "fresh" in run(cli, "list", "--kind", "test:pinned").output
    (tmp_path / "parser.py").write_text("v2 grew", encoding="utf-8")
    assert "stale" in run(cli, "list", "--kind", "test:pinned").output


def test_relate_draws_a_declared_edge_and_the_edge_may_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = app(tmp_path, monkeypatch)
    run(cli, "record", "coordination:task", "first", "--slug", "first")
    run(cli, "record", "coordination:task", "second", "--slug", "second")

    related = run(
        cli, "relate", "test:cites", "second", "first", "--json", '{"note": "see"}'
    )
    assert related.exit_code == 0, related.output
    shown = run(cli, "show", "first")
    assert "1 incoming test:cites" in shown.output

    empty = run(cli, "relate", "test:cites", "second", "first", "--json", "{}")
    assert empty.exit_code != 0
    assert run(cli, "relate", "nope", "first", "second").exit_code != 0
    assert run(cli, "relate", "coordination:blocks", "first", "first").exit_code == 0
    selfcite = run(
        cli, "relate", "test:cites", "first", "first", "--json", '{"note": "me"}'
    )
    assert selfcite.exit_code != 0 and "itself" in selfcite.output


def test_show_asks_a_neighbour_its_own_answer_and_not_the_base_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blocker that finished stops blocking on the next look, which only
    holds when the neighbourhood is resolved through the declared kinds: a
    base node never finishes, so a listing over base nodes would keep the
    task blocked forever.
    """
    cli = app(tmp_path, monkeypatch)
    run(cli, "record", "coordination:task", "first", "--slug", "first")
    run(cli, "record", "coordination:task", "second", "--slug", "second")
    run(cli, "relate", "coordination:blocks", "first", "second")

    assert "blocked" in run(cli, "show", "second").output

    assert run(cli, "done", "first").exit_code == 0

    assert "blocked" not in run(cli, "show", "second").output
    assert "blocked" not in run(cli, "list", "--kind", "coordination:task").output


def test_amend_records_the_node_again_validated_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = app(tmp_path, monkeypatch)
    run(cli, "record", "coordination:task", "finish it")
    task = latest(tmp_path, Task)

    assert run(cli, "amend", task.id, "--json", '{"done": true}').exit_code == 0
    assert latest(tmp_path, Task).done
    assert run(cli, "amend", task.id, "--json", '{"needs": "sideways"}').exit_code != 0


def test_list_since_shows_what_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = app(tmp_path, monkeypatch)
    run(cli, "record", "coordination:task", "old", "--slug", "old")
    old = latest(tmp_path, Task)
    run(cli, "record", "coordination:task", "new", "--slug", "new")

    listed = run(cli, "list", "--since", old.at.isoformat())

    assert listed.exit_code == 0, listed.output
    assert "new" in listed.output and "old" not in listed.output


def test_cite_holds_a_document_to_its_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = app(tmp_path, monkeypatch)
    run(cli, "record", "coordination:task", "depth", "--slug", "depth")
    document = tmp_path / "note.md"
    document.write_text(
        "Depth is [known](lup:depth) and [x](lup:nope).\n", encoding="utf-8"
    )

    result = run(cli, "cite", str(document))

    assert result.exit_code == 1
    assert "1 of 2 cite(s) hold" in result.output and "'nope'" in result.output
