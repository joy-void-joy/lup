"""The command tree a person reaches the repository's other sessions through.

A headless agent has tools; a person has this. They drive the same roster over
the same files, so what a console says is here is what a session addressing it
will reach — and a message a person sends arrives by the path an agent's
message arrives by, rather than by a second one that agrees until it does not.

Every command reads the shared git directory rather than a worktree, so any
checkout of the repository answers and none of them owns the answer. None of
them holds a lock either: a listing folds an append-only record, so a session
running flat out does not delay a console reading it, and a console cannot
wedge a session.
"""

from pathlib import Path
from typing import Annotated

import typer

from lup.channels.models import Door
from lup.coordination.identity import mint_member_id
from lup.coordination.repository import PeerView, RepositoryPeers
from lup.coordination.roster import Delivery
from lup.coordination.touches import Claim
from lup.workspace.paths import project_root


def peer_line(view: PeerView) -> str:
    """One roster row as a person reads it: who, where, and what they are on."""
    where = Path(view.member.worktree).name if view.member.worktree else ""
    state = "" if view.member.running else " [gone]"
    return " — ".join(
        part
        for part in (f"{view.address}{state}", where, view.doing, view.member.delivery)
        if part
    )


def claim_line(claim: Claim) -> str:
    """One holding as a person reads it: what, who, and whether anyone is sure.

    The holders are spelled out in full where there is more than one, because
    that row means something different from the others — nothing could tell
    who made the change — and a reader skimming for whom to ask has to see
    that it is a question rather than an answer.
    """
    holders = ", ".join(holder.id for holder in claim.holders)
    return " — ".join(
        part
        for part in (
            f"{'under' if claim.prefix else 'at'} {claim.path}",
            f"contested by {holders}" if len(claim.holders) > 1 else holders,
        )
        if part
    )


def create_coordination_app() -> typer.Typer:
    """Wire the command tree for reaching this repository's other sessions."""
    app = typer.Typer(no_args_is_help=True)

    def peers() -> RepositoryPeers:
        return RepositoryPeers(project_root())

    @app.command("roster")
    def roster_cmd() -> None:
        """List every session working in this repository, the live ones first.

        The whole roster rather than the live half, because a session that has
        stopped is what a person is often looking for: whether the peer they
        sent something to is still there is exactly the question the listing
        has to answer, and hiding the dead rows answers it by omission.
        """
        listing = peers().listing()
        if not listing:
            typer.echo("No session has joined this repository.")
            return
        for view in listing:
            typer.echo(peer_line(view))

    @app.command("join")
    def join_cmd(
        name: Annotated[
            str,
            typer.Option("--name", help="What to call this session on the roster"),
        ] = "",
        member_id: Annotated[
            str,
            typer.Option("--id", help="A durable id to join under, minted if omitted"),
        ] = "",
        worktree: Annotated[
            Path | None,
            typer.Option("--worktree", help="Where it works; defaults to this tree"),
        ] = None,
    ) -> None:
        """Put a session on the roster and print the id it answers to.

        The id is printed because it is what the session has to carry: a
        launcher exports it, and a session that self-minted has no other way
        to learn what it was given.
        """
        chosen = member_id or mint_member_id()
        tree = worktree or project_root()
        peers().join(chosen, tree, cli_name=name, delivery=Delivery.MAILBOX)
        typer.echo(chosen)

    @app.command("describe")
    def describe_cmd(
        description: Annotated[str, typer.Argument(help="What it is working on now")],
        member_id: Annotated[
            str, typer.Option("--id", help="Which session, by its durable id")
        ],
    ) -> None:
        """Record what one session is doing, for whoever reads the roster next."""
        peers().describe(member_id, description)

    @app.command("rename")
    def rename_cmd(
        name: Annotated[str, typer.Argument(help="What to call it from now on")],
        member_id: Annotated[
            str, typer.Option("--id", help="Which session, by its durable id")
        ],
    ) -> None:
        """Rename one session, leaving the old name resolving to it."""
        peers().rename(member_id, name)

    @app.command("leave")
    def leave_cmd(
        member_id: Annotated[
            str, typer.Option("--id", help="Which session, by its durable id")
        ],
        summary: Annotated[
            str, typer.Option("--summary", help="What it concluded, if anything")
        ] = "",
    ) -> None:
        """Record that a session has stopped, so nothing addresses it again."""
        peers().leave(member_id, summary=summary)

    @app.command("send")
    def send_cmd(
        text: Annotated[str, typer.Argument(help="What the peer should read")],
        to: Annotated[
            str, typer.Option("--to", help="A name, an id, or a printed address")
        ],
        redirect: Annotated[
            bool,
            typer.Option("--redirect", help="Stop the peer rather than inform it"),
        ] = False,
    ) -> None:
        """Send one message to a peer, and say what will carry it there.

        Reporting what carries it rather than that it sent, because those are
        different claims and only the first is knowable here: the mailbox
        accepting a message says nothing about anyone reading it, and a sender
        told "sent" goes on believing a peer was informed.
        """
        found = peers().send(to, text, redirect=redirect, door=Door.CONSOLE)
        if found is None:
            raise typer.BadParameter(
                f"no session answers to {to!r}; "
                "`dev coordination roster` lists who is here"
            )
        carries = peers().cohort.delivery(found)
        typer.echo(f"queued for {found.label()}, carried by {carries}")

    @app.command("inbox")
    def inbox_cmd(
        member_id: Annotated[
            str, typer.Option("--id", help="Which session's inbox to read")
        ],
        take: Annotated[
            bool,
            typer.Option("--take", help="Consume what is read, rather than peek"),
        ] = False,
    ) -> None:
        """Read what is queued for one session, consuming it only when asked.

        Peeking by default, because reading an inbox is how a person finds out
        whether a peer has been reached — and a read that consumed would be a
        read that stopped the peer ever seeing it.
        """
        found = peers()
        delivery = found.take(member_id) if take else found.waiting(member_id)
        for message in delivery.messages:
            kind = "redirect" if message.redirect else "message"
            typer.echo(f"[{kind} by {message.door}] {message.text}")

    return app

    @app.command("holdings")
    def holdings_cmd() -> None:
        """List what each live session in this repository is holding.

        Nobody declared any of it. A row is either a file some session's calls
        actually changed or a prefix one of them took deliberately, and a row
        naming more than one session is a change nothing could attribute —
        which is worth reading as it is rather than as a guess.
        """
        listing = peers().held()
        if not listing:
            typer.echo("No session is holding anything in this repository.")
            return
        for claim in listing:
            typer.echo(claim_line(claim))

    @app.command("lock")
    def lock_cmd(
        prefix: Annotated[Path, typer.Argument(help="What to take, as a path")],
        member_id: Annotated[
            str, typer.Option("--id", help="Which session, by its durable id")
        ],
    ) -> None:
        """Take everything beneath a prefix, before having touched any of it."""
        peers().lock(member_id, prefix.resolve())

    @app.command("release")
    def release_cmd(
        prefix: Annotated[Path, typer.Argument(help="What to give back, as a path")],
        member_id: Annotated[
            str, typer.Option("--id", help="Which session, by its durable id")
        ],
    ) -> None:
        """Give a prefix back, which does nothing unless this session held it."""
        peers().release(member_id, prefix.resolve())
