"""A claim about a file: the edge is ordinary, and the file rots on its own.

Declared here the way an adopter turning the corpus on would declare it —
the library's `File` beside the scaffold's `Claim`, joined by `About` — since
this repository's own declaration carries neither.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import lup.devtools.ledger.app as ledger_app
from lup.coordination.refs import ActorRef
from lup.ledger.files import File
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerEdge, LedgerNode
from lup.ledger.views import graph_view
from lup_template.corpus import About, Claim

NODE_KINDS: list[type[LedgerNode]] = [File, Claim]
EDGE_KINDS: list[type[LedgerEdge]] = [About]


def test_a_claim_about_a_file_is_drawn_and_the_file_goes_stale_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger_app, "project_root", lambda: tmp_path)
    (tmp_path / "notes.md").write_text("a", encoding="utf-8")
    app = ledger_app.create_ledger_app(NODE_KINDS, EDGE_KINDS)
    runner = CliRunner()

    recorded = runner.invoke(
        app,
        [
            "record",
            "ledger:file",
            "",
            "--json",
            '{"path": "notes.md"}',
            "--slug",
            "notes",
        ],
    )
    claimed = runner.invoke(
        app, ["record", "corpus:claim", "the notes are short", "--slug", "short"]
    )
    related = runner.invoke(app, ["relate", "corpus:about", "short", "notes"])
    types = runner.invoke(app, ["types"])

    assert recorded.exit_code == 0, recorded.output
    assert claimed.exit_code == 0 and related.exit_code == 0, related.output
    assert "ledger:file" in types.output and "corpus:about" in types.output
    store = LedgerStore(tmp_path, ActorRef(kind="test", id="t"))
    graph = graph_view(store, NODE_KINDS)
    by_slug = {node.slug: node for node in graph.nodes}
    assert graph.edges[0].kind == "corpus:about"
    assert by_slug["notes"].standing == "fresh" and by_slug["notes"].title == "notes.md"

    (tmp_path / "notes.md").write_text("longer", encoding="utf-8")
    moved = {node.slug: node for node in graph_view(store, NODE_KINDS).nodes}

    assert moved["notes"].standing == "stale" and not moved["notes"].sound
    assert moved["short"].standing == "unsupported"
    assert [found.path for found in store.read(File)] == ["notes.md"]
    assert store.read(Claim)[0].slug == "short"
