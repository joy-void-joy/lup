"""The ledger's verbs as tools, so an agent records and reads without a shell.

The console serves a person; these serve the session. Same store, same kinds,
same generic shape — one `record` and one `relate` over whatever the project
declared, with the type validating the fields — because an agent that has to
shell out to write down what it learned writes it down less often, and a
corpus nobody records into answers nothing.

**The author is bound, not passed.** The tools are built for one session's
identity and stamp every record with it, for the reason a resolver worker's
concern is: a session that could name itself in a call could record another
session's claim as its own, and provenance a writer cannot spell is provenance
a writer cannot get wrong.

**The descriptions are the documentation.** An agent never sees this module;
what each tool says about itself is the whole of what it knows, so each one
says when to reach for it and what comes back.
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from lup.coordination.refs import ActorRef
from lup.ledger.cite import read_cites
from lup.ledger.journal import LedgerRefusal, LedgerStore
from lup.ledger.kinds import by_kind
from lup.ledger.models import LedgerEdge, LedgerNode
from lup.ledger.views import (
    EdgeView,
    KindsView,
    NodeDetail,
    NodeView,
    kinds_view,
    node_detail,
    node_view,
)
from lup.tools.mcp import LupMcpTool, ToolError, lup_tool
from lup.types import JsonObject


class NoInput(BaseModel):
    """A tool that asks the log about itself takes no arguments."""


class RecordInput(BaseModel):
    kind: str = Field(description="A declared node kind, as `ledger_types` spells it")
    title: str = Field(description="What it is, in one line")
    text: str = Field(default="", description="What it says — the figure, the finding")
    slug: str = Field(
        default="",
        description="A readable handle, unique in this log, accepted wherever an id is",
    )
    fields: JsonObject = Field(
        default={},
        description="The kind's other fields, as `ledger_types` lists them",
    )
    attach: list[str] = Field(
        default=[],
        description="Files under the working tree whose bytes this node carries",
    )


class RelateInput(BaseModel):
    kind: str = Field(description="A declared edge kind, as `ledger_types` spells it")
    source: str = Field(description="The node the relation runs from, by id or slug")
    target: str = Field(description="The node it runs to, by id or slug")
    fields: JsonObject = Field(default={}, description="The kind's other fields")


class AmendInput(BaseModel):
    node: str = Field(description="The node to change, by id or slug")
    fields: JsonObject = Field(description="The fields to change; the rest stay")


class ShowInput(BaseModel):
    node: str = Field(description="The node to read, by id or slug")


class ListInput(BaseModel):
    kind: str = Field(default="", description="Only nodes of this kind")
    standing: str = Field(
        default="", description="Only nodes whose standing has this label right now"
    )
    since: str = Field(
        default="",
        description="Only nodes with a record newer than this ISO 8601 moment",
    )


class ListOutput(BaseModel, frozen=True):
    nodes: list[NodeView]


class CiteInput(BaseModel):
    path: str = Field(description="A markdown file under the working tree")


class CiteProblem(BaseModel, frozen=True):
    line: int
    node: str
    problem: str


class CiteOutput(BaseModel, frozen=True):
    checked: int
    failing: list[CiteProblem]


def attached(root: Path, path: str) -> bytes:
    """The bytes of one file named relative to the tree, or a refusal a caller reads."""
    target = (root / path).resolve()
    try:
        return target.read_bytes()
    except OSError as missing:
        raise ToolError(f"cannot attach {path!r}: {missing}") from missing


def create_ledger_tools(
    root: Path,
    author: ActorRef,
    classes: list[type[LedgerNode]],
    edges: list[type[LedgerEdge]],
) -> list[LupMcpTool]:
    """The ledger verbs, bound to one working tree, one author, and its kinds."""
    node_kinds = by_kind(classes)
    edge_kinds = by_kind(edges)

    def store() -> LedgerStore:
        return LedgerStore(root, author)

    def found(held: LedgerStore, spelling: str) -> LedgerNode:
        node = held.resolve(spelling, classes)
        if node is None:
            raise ToolError(
                f"no node in this repository has the id or slug {spelling!r};"
                " `ledger_list` shows what is here"
            )
        return node

    def view(held: LedgerStore, node: LedgerNode) -> NodeView:
        return node_view(held, classes, node)

    @lup_tool(
        "List the node and edge kinds this repository records, each with the "
        "fields `ledger_record` and `ledger_relate` accept for it. Call it once "
        "before recording anything: the kinds are the project's, not a fixed "
        "vocabulary, and the fields are read off the types so the listing "
        "cannot disagree with what is validated. Returns {nodes: [{kind, name, "
        "summary, fields}], edges: [...]}.",
        name="ledger_types",
    )
    async def ledger_types(_params: NoInput) -> KindsView:
        return kinds_view(classes, edges)

    @lup_tool(
        "Record one node of a declared kind — a claim you can be held to, a "
        "question still open, evidence with the files it was checked against, "
        "a task, a correction. Do it when you learn something worth a later "
        "session finding, not at the end: a note in your reply outlives nothing. "
        "The kind validates the fields; a slug makes the node citable by name. "
        "Evidence pins the digests of the files in its scope as it is recorded, "
        "so name paths and never compute a digest. Returns the node with its "
        "standing read now.",
        name="ledger_record",
    )
    async def ledger_record(params: RecordInput) -> NodeView:
        declared = node_kinds.get(params.kind)
        if declared is None:
            raise ToolError(
                f"{params.kind!r} is not a declared node kind; declared: "
                + ", ".join(node_kinds)
            )
        fields = (
            {**params.fields, "slug": params.slug} if params.slug else params.fields
        )
        attachments = [attached(root, path) for path in params.attach]
        held = store()
        try:
            node = held.record_fields(
                declared,
                params.title,
                fields,
                text=params.text,
                attachments=attachments,
            )
        except ValidationError as invalid:
            raise ToolError(str(invalid)) from invalid
        except LedgerRefusal as refused:
            raise ToolError(str(refused)) from refused
        return view(held, node)

    @lup_tool(
        "Draw one edge of a declared kind between two nodes: this evidence "
        "supports that claim, this claim rests on that one, this claim answers "
        "that question, this task blocks that one, this correction supersedes "
        "that node. Relations are what standing is read from, so a claim with "
        "no edges is a claim nothing can weigh. The edge may refuse the pair — "
        "a verification of your own work is not one — and says why. Returns "
        "{kind, source, target}.",
        name="ledger_relate",
    )
    async def ledger_relate(params: RelateInput) -> EdgeView:
        declared = edge_kinds.get(params.kind)
        if declared is None:
            raise ToolError(
                f"{params.kind!r} is not a declared edge kind; declared: "
                + ", ".join(edge_kinds)
            )
        held = store()
        try:
            edge = held.relate_fields(
                declared,
                found(held, params.source),
                found(held, params.target),
                params.fields,
            )
        except ValidationError as invalid:
            raise ToolError(str(invalid)) from invalid
        except LedgerRefusal as refused:
            raise ToolError(str(refused)) from refused
        return EdgeView(kind=edge.kind, source=edge.source, target=edge.target)

    @lup_tool(
        "Record a node again with some fields changed — a task done, a question "
        "closed with a reason, a priority moved. Nothing is overwritten: the "
        "earlier record stays readable and the log shows who changed what. "
        "Validated as the whole node, so a change that would leave it invalid "
        "is refused the way a fresh one is. Returns the node as it now stands.",
        name="ledger_amend",
    )
    async def ledger_amend(params: AmendInput) -> NodeView:
        held = store()
        node = found(held, params.node)
        try:
            rebuilt = type(node).model_validate({**node.model_dump(), **params.fields})
        except ValidationError as invalid:
            raise ToolError(str(invalid)) from invalid
        try:
            amended = held.amend(rebuilt)
        except LedgerRefusal as refused:
            raise ToolError(str(refused)) from refused
        return view(held, amended)

    @lup_tool(
        "Read one node in full: its kind-specific fields, where it stands right "
        "now and why, the edges pointing at it counted by kind — how much rests "
        "on a claim, how many claims address a question — and every edge in and "
        "out. Reach for it before building on a claim: the standing is read "
        "fresh, and a claim whose evidence went stale or whose premise was "
        "refuted says so here first.",
        name="ledger_show",
    )
    async def ledger_show(params: ShowInput) -> NodeDetail:
        held = store()
        return node_detail(held, classes, found(held, params.node))

    @lup_tool(
        "List what the repository has recorded, each node with its standing "
        "read now. Narrow by kind, by standing label — `open` questions, "
        "`unsupported` or `stale` claims, `held` tasks — or by `since`, an ISO "
        "8601 moment, to see only what moved after you last looked: nodes with "
        "a newer record of their own or a newer edge touching them. This is how "
        "a session opens on a corpus: what is open, what is important, what "
        "changed. Returns {nodes: [{id, kind, title, slug, text, standing, "
        "reason, sound}]}.",
        name="ledger_list",
    )
    async def ledger_list(params: ListInput) -> ListOutput:
        held = store()
        try:
            moment = datetime.fromisoformat(params.since) if params.since else None
        except ValueError as invalid:
            raise ToolError(f"since must be ISO 8601: {invalid}") from invalid
        moved = held.moved_since(moment) if moment is not None else None
        rows = [
            view(held, node)
            for node in held.all_nodes(classes)
            if (not params.kind or node.kind == params.kind)
            and (moved is None or node.id in moved)
        ]
        return ListOutput(
            nodes=[
                row
                for row in rows
                if not params.standing or row.standing == params.standing
            ]
        )

    @lup_tool(
        "Hold one hand-written markdown file to the nodes it cites: every "
        "`[text](lup:<id or slug>)` link is resolved and its node asked where it "
        "stands. A cite of a missing node, or of one that is no longer sound — "
        "superseded, refuted, stale, a premise regressed — is reported with its "
        "line and the reason. `dev check` runs the same reading over every "
        "tracked document and fails on what this reports. Returns {checked, "
        "failing: [{line, node, problem}]}.",
        name="ledger_cite",
    )
    async def ledger_cite(params: CiteInput) -> CiteOutput:
        target = (root / params.path).resolve()
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as missing:
            raise ToolError(f"cannot read {params.path!r}: {missing}") from missing
        readings = read_cites(text, store(), classes)
        return CiteOutput(
            checked=len(readings),
            failing=[
                CiteProblem(
                    line=reading.cite.line,
                    node=reading.cite.node_id,
                    problem=reading.problem(),
                )
                for reading in readings
                if not reading.holds()
            ],
        )

    return [
        ledger_types,
        ledger_record,
        ledger_relate,
        ledger_amend,
        ledger_show,
        ledger_list,
        ledger_cite,
    ]
