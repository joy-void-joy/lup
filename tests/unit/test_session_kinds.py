"""This repository declares sessions and outputs among its ledger kinds.

The console, the tool group and the explorer all read one list, so the
assertion is that the list carries both kinds and that the composition
builds a recorder over it — the writers themselves are the library's, tested
where they live.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import lup.devtools.ledger.app as ledger_app
from lup.coordination.refs import ActorRef
from lup.ledger.tools import NoInput, create_ledger_tools
from lup.ledger.views import kinds_view
from lup.observability.sessions import session_recorder
from lup_template.corpus import About
from lup_template.kinds import EDGE_KINDS, NODE_KINDS, PLACEMENT

SESSION_KINDS = {"observability:session", "observability:output"}


def test_the_console_lists_both_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger_app, "project_root", lambda: tmp_path)
    app = ledger_app.create_ledger_app(NODE_KINDS, EDGE_KINDS)

    types = CliRunner().invoke(app, ["types"])

    assert types.exit_code == 0, types.output
    assert all(kind in types.output for kind in SESSION_KINDS)


async def test_the_explorer_and_the_tools_read_the_same_kinds(tmp_path: Path) -> None:
    served = {
        tool.name: tool
        for tool in create_ledger_tools(
            tmp_path, ActorRef(kind="session", id="s"), NODE_KINDS, EDGE_KINDS
        )
    }

    listed = await served["ledger_types"](NoInput())
    drawn = kinds_view(NODE_KINDS, EDGE_KINDS)

    assert SESSION_KINDS <= {kind.kind for kind in listed.nodes}
    assert [kind.kind for kind in drawn.nodes] == [kind.kind for kind in listed.nodes]
    by_kind = {kind.kind: kind for kind in drawn.nodes}
    assert any(
        "journal_digest" in field for field in by_kind["observability:session"].fields
    )
    assert any("session" in field for field in by_kind["observability:output"].fields)
    assert "attachments" not in " ".join(by_kind["observability:session"].fields)


def test_the_composition_builds_a_recorder_over_the_declared_kinds(
    tmp_lup_project: Path,
) -> None:
    recorder = session_recorder(
        tmp_lup_project,
        ActorRef(kind="session", id="s"),
        NODE_KINDS,
        PLACEMENT,
        about=About,
    )

    assert recorder is not None and recorder.about is About
    assert recorder.checkout == tmp_lup_project
