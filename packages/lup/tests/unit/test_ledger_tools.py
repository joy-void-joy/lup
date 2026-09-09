"""The ledger's verbs as tools, over kinds a project declared.

Written against what an agent needs from them: to learn the kinds before
recording, to record with the type validating, to relate and be refused in
words, to read a node's standing fresh, and to open on what moved.
"""

from pathlib import Path
from typing import Literal

import pytest
from pydantic import Field

from lup.coordination.identity import mint_member_id
from lup.coordination.refs import ActorRef
from lup.coordination.tasks import Blocks, Task
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerEdge, LedgerNode
from lup.ledger.tools import (
    AmendInput,
    CiteInput,
    ListInput,
    NoInput,
    RecordInput,
    RelateInput,
    ShowInput,
    create_ledger_tools,
)
from lup.tools.mcp import LupMcpTool, ToolError


class Cites(LedgerEdge, frozen=True):
    """A test relation that refuses a node citing itself."""

    kind: Literal["test:cites"] = "test:cites"
    note: str = Field(min_length=1)

    def refusal(self, source: LedgerNode, target: LedgerNode) -> str:
        return "a node cannot cite itself" if source.id == target.id else ""


def tools(root: Path) -> dict[str, LupMcpTool]:
    author = ActorRef(kind="session", id=mint_member_id())
    return {
        tool.name: tool
        for tool in create_ledger_tools(root, author, [Task], [Blocks, Cites])
    }


def latest[N: LedgerNode](root: Path, kind: type[N]) -> N:
    return LedgerStore(root, ActorRef(kind="test", id="t")).read(kind)[-1]


async def test_types_names_each_kind_with_the_fields_it_accepts(tmp_path: Path) -> None:
    served = tools(tmp_path)

    listed = await served["ledger_types"](NoInput())

    assert [kind.kind for kind in listed.nodes] == ["coordination:task"]
    assert "needs" in " ".join(listed.nodes[0].fields)
    assert [kind.kind for kind in listed.edges] == ["coordination:blocks", "test:cites"]
    assert "author" not in " ".join(listed.edges[1].fields)


async def test_record_validates_through_the_kind_and_stamps_the_author(
    tmp_path: Path,
) -> None:
    served = tools(tmp_path)

    recorded = await served["ledger_record"](
        RecordInput(
            kind="coordination:task",
            title="finish it",
            slug="finish",
            fields={"needs": "review", "priority": 2},
        )
    )

    assert recorded.standing == "waiting" and recorded.slug == "finish"
    task = latest(tmp_path, Task)
    assert task.priority == 2 and task.author.kind == "session"
    with pytest.raises(ToolError, match="not a declared node kind"):
        await served["ledger_record"](RecordInput(kind="nope", title="x"))
    with pytest.raises(ToolError, match="needs"):
        await served["ledger_record"](
            RecordInput(
                kind="coordination:task", title="x", fields={"needs": "sideways"}
            )
        )
    with pytest.raises(ToolError, match="already names"):
        await served["ledger_record"](
            RecordInput(kind="coordination:task", title="y", slug="finish")
        )


async def test_relate_draws_an_edge_by_slug_and_the_edge_may_refuse(
    tmp_path: Path,
) -> None:
    served = tools(tmp_path)
    for title in ("first", "second"):
        await served["ledger_record"](
            RecordInput(kind="coordination:task", title=title, slug=title)
        )

    drawn = await served["ledger_relate"](
        RelateInput(
            kind="test:cites", source="second", target="first", fields={"note": "see"}
        )
    )
    shown = await served["ledger_show"](ShowInput(node="first"))

    assert drawn.kind == "test:cites"
    assert [(count.kind, count.count) for count in shown.incoming] == [
        ("test:cites", 1)
    ]
    with pytest.raises(ToolError, match="itself"):
        await served["ledger_relate"](
            RelateInput(
                kind="test:cites", source="first", target="first", fields={"note": "me"}
            )
        )
    with pytest.raises(ToolError, match="note"):
        await served["ledger_relate"](
            RelateInput(kind="test:cites", source="second", target="first")
        )


async def test_amend_and_list_read_standing_fresh(tmp_path: Path) -> None:
    served = tools(tmp_path)
    await served["ledger_record"](
        RecordInput(kind="coordination:task", title="old", slug="old")
    )
    old = latest(tmp_path, Task)
    await served["ledger_record"](
        RecordInput(kind="coordination:task", title="new", slug="new")
    )

    amended = await served["ledger_amend"](
        AmendInput(node="new", fields={"done": True})
    )
    done = await served["ledger_list"](ListInput(standing="done"))
    moved = await served["ledger_list"](ListInput(since=old.at.isoformat()))

    assert amended.standing == "done"
    assert [node.slug for node in done.nodes] == ["new"]
    assert [node.slug for node in moved.nodes] == ["new"]
    with pytest.raises(ToolError, match="ISO 8601"):
        await served["ledger_list"](ListInput(since="yesterday"))


async def test_cite_holds_a_document_to_its_nodes(tmp_path: Path) -> None:
    served = tools(tmp_path)
    await served["ledger_record"](
        RecordInput(kind="coordination:task", title="depth", slug="depth")
    )
    (tmp_path / "note.md").write_text(
        "Depth is [known](lup:depth) and [x](lup:nope).\n", encoding="utf-8"
    )

    result = await served["ledger_cite"](CiteInput(path="note.md"))

    assert result.checked == 2
    assert [problem.node for problem in result.failing] == ["nope"]
