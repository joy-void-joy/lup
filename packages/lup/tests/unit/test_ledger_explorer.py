"""The explorer: the log served as routes over the view models, or written as
one page that carries the log and the bundle with it.

Exercised over a bundle written by hand where a built one is not the point,
and over the package's own bundle for the export, which is what a reader
opens.
"""

from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path

import pytest
import typer
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import lup.devtools.ledger.app as ledger_app
from lup.coordination.refs import ActorRef
from lup.coordination.tasks import Blocks, Task
from lup.ledger.explorer import export_explorer, explorer_app
from lup.ledger.journal import LedgerStore
from lup.ledger.views import ExportView

URL = "http://127.0.0.1:1"


def handmade(root: Path) -> Path:
    """A bundle the way Vite lays one out, without Vite."""
    home = root / "bundles" / "explorer"
    (home / "assets").mkdir(parents=True)
    (home / "index.html").write_text(
        '<!doctype html><div id="root"></div>'
        '<script type="module" src="./assets/index-1.js"></script>\n',
        encoding="utf-8",
    )
    # Escaped the way the build leaves a bundle, so an export carries it as is.
    (home / "assets" / "index-1.js").write_text(
        'console.log("x", "<\\/script>", "<\\!--");\n', encoding="utf-8"
    )
    (home / "assets" / "index-1.css").write_text("body{margin:0}\n", encoding="utf-8")
    return root / "bundles"


def store(root: Path) -> LedgerStore:
    return LedgerStore(root, ActorRef(kind="test", id="t"))


def client(root: Path) -> TestClient:
    return TestClient(
        explorer_app(URL, root, [Task], [Blocks], handmade(root)), base_url=URL
    )


def test_the_routes_serve_the_graph_one_node_and_the_kinds(tmp_path: Path) -> None:
    held = store(tmp_path)
    first = held.record(Task, "first", slug="first")
    second = held.record(Task, "second")
    held.relate(Blocks, first, second)
    http = client(tmp_path)

    graph = http.get("/api/graph").json()
    node = http.get("/api/node/first").json()
    kinds = http.get("/api/kinds").json()

    assert {each["id"] for each in graph["nodes"]} == {first.id, second.id}
    assert graph["edges"] == [
        {"kind": "coordination:blocks", "source": first.id, "target": second.id}
    ]
    assert graph["kinds"] == ["coordination:task"]
    assert node["node"]["id"] == first.id
    assert node["edges_out"][0]["target"] == second.id
    assert [each["kind"] for each in kinds["nodes"]] == ["coordination:task"]
    assert [each["kind"] for each in kinds["edges"]] == ["coordination:blocks"]
    assert http.get("/api/node/nobody").status_code == 404
    assert http.get("/").status_code == 200


def test_the_graph_narrows_by_standing_and_by_when_a_node_moved(tmp_path: Path) -> None:
    held = store(tmp_path)
    earlier = datetime.now(UTC) - timedelta(days=2)
    old = held.record(Task, "old", at=earlier)
    fresh = held.record(Task, "fresh")
    http = client(tmp_path)
    marker = (datetime.now(UTC) - timedelta(days=1)).isoformat()

    blocked = http.get("/api/graph", params={"standing": "blocked"}).json()
    recent = http.get("/api/graph", params={"since": marker}).json()

    assert blocked["nodes"] == [] and blocked["standings"] == ["open"]
    assert [each["id"] for each in recent["nodes"]] == [fresh.id]
    assert http.get("/api/graph", params={"since": "yesterday"}).status_code == 422

    # An edge drawn now moves both its ends, so the old node reads as moved.
    held.relate(Blocks, old, fresh)
    moved = http.get("/api/graph", params={"since": marker}).json()
    assert {each["id"] for each in moved["nodes"]} == {old.id, fresh.id}
    by_id = {each["id"]: each for each in moved["nodes"]}
    assert datetime.fromisoformat(by_id[old.id]["moved"]) > earlier


def test_a_reading_of_when_a_node_moved_is_the_latest_touch(tmp_path: Path) -> None:
    held = store(tmp_path)
    node = held.record(Task, "one", at=datetime.now(UTC) - timedelta(hours=3))
    other = held.record(Task, "two", at=datetime.now(UTC) - timedelta(hours=2))
    edge = held.relate(Blocks, other, node, at=datetime.now(UTC) - timedelta(hours=1))

    assert held.movements() == {node.id: edge.at, other.id: edge.at}


def test_an_export_carries_the_log_escaped_and_the_bundle_inline(
    tmp_path: Path,
) -> None:
    """One module script and one style element, each the served asset's
    bytes, and the log in an attribute the app reads before it would fetch."""
    held = store(tmp_path)
    held.record(Task, 'closing</div><script>alert("x")</script>', slug="tricky")
    bundles = handmade(tmp_path)
    served = TestClient(
        explorer_app(URL, tmp_path, [Task], [Blocks], bundles), base_url=URL
    )

    written = export_explorer(
        tmp_path, [Task], [Blocks], tmp_path / "out" / "ledger.html", bundles
    )
    page = written.read_text(encoding="utf-8")

    assert (
        "</div><script>" not in page.split('data-lup-export="', 1)[1].split('"', 1)[0]
    )
    carried = unescape(page.split('data-lup-export="', 1)[1].split('"', 1)[0])
    view = ExportView.model_validate_json(carried)
    assert view.graph.nodes[0].slug == "tricky"
    assert view.details[0].node.title.startswith("closing</div>")
    assert view.kinds.nodes[0].kind == "coordination:task"
    assert "data:" not in page
    assert page.count('<script type="module">') == 1 and page.count("<style>") == 1
    script = page.split('<script type="module">', 1)[1].split("</script>", 1)[0]
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert script == served.get("/assets/index-1.js").text
    assert style == served.get("/assets/index-1.css").text
    assert script == 'console.log("x", "<\\/script>", "<\\!--");\n'


def test_the_explore_command_writes_an_export_from_the_package_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger_app, "project_root", lambda: tmp_path)
    store(tmp_path).record(Task, "kept")
    app: typer.Typer = ledger_app.create_ledger_app([Task], [Blocks])

    result = CliRunner().invoke(
        app, ["explore", "--export", str(tmp_path / "ledger.html")]
    )

    assert result.exit_code == 0, result.output
    page = (tmp_path / "ledger.html").read_text(encoding="utf-8")
    assert "kept" in page and 'data-lup-export="' in page
    assert page.count('<script type="module">') == 1 and page.count("<style>") == 1
    assert 'src="data:' not in page and 'href="data:' not in page
