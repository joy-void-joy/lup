"""The command tree a person reads and preserves this repository's notes through.

An agent records nodes as it works, and the record is worth nothing if the
person the work is for cannot read it. This is that half: what is in the DAG,
where each node stands *right now* rather than where it was labelled, and the
one command that puts a copy somewhere git will keep.

It is the reader whose subject is the log rather than any one type, so it is
also the one place a list of node classes is needed: a record names its type
and not the class that reads it, so something has to try. Everything else in
the codebase asks the store for the type it actually wants.

Every command reads the shared git directory, so any checkout answers and none
of them owns the answer. Nothing holds a lock: a listing folds an append-only
file, which is why a session recording flat out does not delay a console
reading it, and a console cannot wedge a session.
"""

from typing import Annotated

import typer

from lup.coordination.identity import mint_member_id
from lup.coordination.refs import ActorRef
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerNode
from lup.ledger.snapshot import snapshot
from lup.ledger.store import ledger_root
from lup.workspace.edition import shared_git_directory
from lup.workspace.paths import project_root

SNAPSHOT_BRANCH = "lup/ledger"
"""The branch a snapshot lands on: the record's own, never the code's.

Nodes accumulate as work happens, and one per turn in the history of the code
would make that history unreadable. On a branch nothing merges, the record is
preserved and shares no history with what it is about.
"""


def node_line(store: LedgerStore, node: LedgerNode) -> str:
    """One node as a person reads it: what it is, where it stands, who said so."""
    where = store.standing(node)
    label = f"{where.label}: {where.reason}" if where.reason else where.label
    return " — ".join(
        part
        for part in (
            f"{node.id}  [{node.kind}] {node.title}",
            label,
            node.author.id,
        )
        if part
    )


def create_ledger_app(classes: list[type[LedgerNode]]) -> typer.Typer:
    """Wire the command tree for this repository's notes, over these node types.

    The types are the project's and arrive here rather than being looked up,
    which is the same inversion every other sub-app takes: the library ships
    the commands and the project ships what they are about. A project that
    declares none still reads the DAG — every record is listed, each as the
    base class, which is the honest answer for a log a later build may hold
    types for.
    """
    app = typer.Typer(no_args_is_help=True)

    def store() -> LedgerStore:
        return LedgerStore(
            project_root(), ActorRef(kind="console", id=mint_member_id())
        )

    @app.command("types")
    def types_cmd() -> None:
        """List the node types this project declares."""
        if not classes:
            typer.echo("This project declares no ledger node types.")
            return
        for declared in classes:
            summary = (declared.__doc__ or "").strip().splitlines()
            typer.echo(f"{declared.__name__} — {summary[0] if summary else ''}")

    @app.command("list")
    def list_cmd(
        kind: Annotated[
            str, typer.Option("--kind", help="Show only nodes of this kind")
        ] = "",
    ) -> None:
        """Show every node in this repository, with its standing read now.

        The whole DAG rather than one type's share of it, because a person
        reading the record wants what is there — and a node whose type this
        build does not declare is exactly the row worth seeing, since it means
        another session recorded something. It reads as the base class and
        says its kind, rather than being hidden.
        """
        held = store()
        rows = [
            node for node in held.all_nodes(classes) if not kind or node.kind == kind
        ]
        if not rows:
            typer.echo(
                f"No node of kind {kind!r} is recorded."
                if kind
                else "This repository has recorded no nodes."
            )
            return
        for node in rows:
            typer.echo(node_line(held, node))

    @app.command("show")
    def show_cmd(
        node_id: Annotated[str, typer.Argument(help="The node to read, by id")],
    ) -> None:
        """Print one node in full, with its edges and what it attaches."""
        held = store()
        found = held.resolve(node_id, classes)
        if found is None:
            typer.echo(f"No node in this repository has the id {node_id!r}.")
            raise typer.Exit(1)
        typer.echo(node_line(held, found))
        if found.text:
            typer.echo(found.text)
        for edge in held.out_of(found.id):
            typer.echo(f"  out  {edge.kind} -> {edge.target}")
        for edge in held.into(found.id):
            typer.echo(f"  in   {edge.kind} <- {edge.source}")
        for digest in found.attachments:
            missing = "" if held.blobs.holds(digest) else "  (not on this machine)"
            typer.echo(f"  blob {digest}{missing}")

    @app.command("snapshot")
    def snapshot_cmd(
        branch: Annotated[
            str, typer.Option("--branch", help="Where the copy is committed")
        ] = SNAPSHOT_BRANCH,
    ) -> None:
        """Commit the store to a branch of its own, for a record worth keeping.

        The store is live untracked state the rest of the time, which is what
        keeps a node per turn out of the history of the code. This is the
        deliberate act that preserves it, and it is somebody asking rather
        than something happening on every write.
        """
        root = project_root()
        held = ledger_root(root)
        if not held.exists():
            typer.echo("This repository has recorded nothing to snapshot.")
            raise typer.Exit(1)
        commit = snapshot(
            held,
            shared_git_directory(root),
            branch,
            f"snapshot({branch}): the ledger as it stands",
        )
        typer.echo(f"{branch} at {commit[:12]}: {held}")

    return app
