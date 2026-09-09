"""The generic ledger commands, over kinds a project declared.

Written against the shape the corpus design settled on: one `record` and one
`relate` over declared kinds, with the type validating the fields, rather than
a command per kind that goes stale the moment a project adds one.
"""

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import lup.devtools.ledger.app as ledger_app
from lup.coordination.refs import ActorRef
from lup.coordination.tasks import Blocks, Task
from lup.corpus.models import (
    Artifact,
    Claim,
    Correction,
    Refutes,
    Supersedes,
    Supports,
)
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerNode


def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> typer.Typer:
    monkeypatch.setattr(ledger_app, "project_root", lambda: tmp_path)
    return ledger_app.create_ledger_app(
        [Task, Claim, Artifact, Correction], [Blocks, Supports, Refutes, Supersedes]
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
    assert "corpus:claim" in result.output and "grade" in result.output
    assert "corpus:supports" in result.output
    assert "author" not in result.output


def test_record_validates_through_the_declared_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = app(tmp_path, monkeypatch)

    recorded = run(
        cli,
        "record",
        "corpus:claim",
        "depth is two",
        "--text",
        "2",
        "--json",
        '{"grade": "measured"}',
    )
    assert recorded.exit_code == 0, recorded.output
    claim = latest(tmp_path, Claim)
    assert claim.grade == "measured" and claim.text == "2"
    assert "depth is two" in run(cli, "show", claim.id).output

    refused = run(cli, "record", "corpus:claim", "x", "--json", '{"grade": 5}')
    assert refused.exit_code != 0
    unknown = run(cli, "record", "nope:kind", "x")
    assert unknown.exit_code != 0 and "ledger types" in unknown.output


def test_evidence_pins_its_scope_as_it_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller names the files; the type takes the digests at record time."""
    (tmp_path / "parser.py").write_text("v1", encoding="utf-8")
    (tmp_path / "run.log").write_text("ok", encoding="utf-8")
    cli = app(tmp_path, monkeypatch)
    payload = json.dumps(
        {
            "validation": {
                "schema_id": "pytest",
                "subject_digest": "abc",
                "scope": [{"path": "parser.py", "digest": ""}],
            }
        }
    )

    recorded = run(
        cli,
        "record",
        "corpus:artifact",
        "run.log",
        "--attach",
        str(tmp_path / "run.log"),
        "--json",
        payload,
    )

    assert recorded.exit_code == 0, recorded.output
    pinned = latest(tmp_path, Artifact)
    assert pinned.validation.scope[0].digest
    assert "fresh" in run(cli, "list", "--kind", "corpus:artifact").output
    (tmp_path / "parser.py").write_text("v2", encoding="utf-8")
    assert "stale" in run(cli, "list", "--kind", "corpus:artifact").output


def test_relate_draws_a_declared_edge_and_the_edge_may_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = app(tmp_path, monkeypatch)
    run(cli, "record", "corpus:claim", "depth")
    claim = latest(tmp_path, Claim)
    run(
        cli,
        "record",
        "corpus:correction",
        "three",
        "--json",
        '{"where": "doc", "wrong": "two"}',
    )
    correction = latest(tmp_path, Correction)

    related = run(
        cli,
        "relate",
        "corpus:supersedes",
        correction.id,
        claim.id,
        "--json",
        '{"changes": ["the figure"]}',
    )

    assert related.exit_code == 0, related.output
    assert "superseded" in run(cli, "show", claim.id).output
    empty = run(
        cli,
        "relate",
        "corpus:supersedes",
        correction.id,
        claim.id,
        "--json",
        '{"changes": []}',
    )
    assert empty.exit_code != 0
    assert run(cli, "relate", "nope", claim.id, claim.id).exit_code != 0


def test_amend_records_the_node_again_validated_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = app(tmp_path, monkeypatch)
    run(cli, "record", "coordination:task", "finish it")
    task = latest(tmp_path, Task)

    assert run(cli, "amend", task.id, "--json", '{"done": true}').exit_code == 0
    assert latest(tmp_path, Task).done
    assert run(cli, "amend", task.id, "--json", '{"needs": "sideways"}').exit_code != 0


def test_cite_holds_a_document_to_its_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = app(tmp_path, monkeypatch)
    run(cli, "record", "corpus:claim", "depth", "--text", "2")
    claim = latest(tmp_path, Claim)
    document = tmp_path / "note.md"
    document.write_text(
        f"Depth is [two](lup:{claim.id}) and [x](lup:nope).\n", encoding="utf-8"
    )

    result = run(cli, "cite", str(document))

    assert result.exit_code == 1
    assert "1 of 2 cite(s) hold" in result.output and "'nope'" in result.output
