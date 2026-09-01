"""The surface a reviewer answers a parked question through.

Every final ask is written to the relay before anybody sees it, which is what
makes a detached run answerable at all — but a durable record with no way to
read it is a queue that silently grows. So this is the other half: list what
is waiting, show one in full, and answer, reject, or cancel it.

The requester can read its own question's status here and cannot answer it.
That is enforced on the record rather than by leaving the command out of an
agent's tool list: a policy whose reviewer is "whoever could reach the
command" is one that changes when somebody adds a tool.
"""

from pathlib import Path

import typer
from pydantic import BaseModel

from lup.devtools.utils import output_json
from lup.policy.relay import PersistentQuestion, QuestionRelay


class QuestionView(BaseModel, frozen=True):
    """One question as a reader sees it, without the operation's whole payload.

    The payload is in the record and reaching it is what ``show`` is for. A
    listing that printed it would bury the one line a reviewer triages on.
    """

    id: str
    state: str
    reviewer: str
    requester: str
    reason: str
    operation: str
    rule: str
    answered_by: str = ""
    note: str = ""

    @classmethod
    def of(cls, question: PersistentQuestion) -> "QuestionView":
        return cls(
            id=question.id,
            state=question.state,
            reviewer=question.requirement,
            requester=question.operation.requester,
            reason=question.reason,
            operation=question.operation.summary(),
            rule=question.rule,
            answered_by=question.answer.principal if question.answer else "",
            note=question.answer.note if question.answer else "",
        )


def relay(root: Path, log: Path = Path(".lup/questions.jsonl")) -> QuestionRelay:
    """The relay for one checkout, at the path that checkout keeps it in.

    Under ``.lup`` by default because a parked question is managed
    active-session state: excluded from ordinary captures, and not something
    an ordinary destructive shell operation is authorized to remove just
    because a snapshot exists. A deployment that keeps it elsewhere passes
    its own path rather than editing this one.
    """
    return QuestionRelay(root / log)


def listing(root: Path, principal: str, everything: bool, as_json: bool) -> None:
    """Print what is waiting, narrowed to what this principal may answer.

    Narrowed by eligibility rather than by ownership, because a supervisor
    shown a question it may not answer is a supervisor about to try — and the
    refusal it then gets teaches it nothing about which questions are its.
    """
    store = relay(root)
    questions = store.questions() if everything else store.pending(principal)
    if as_json:
        output_json([QuestionView.of(entry).model_dump() for entry in questions])
        return
    if not questions:
        typer.echo("nothing is waiting")
        return
    for entry in questions:
        typer.echo(entry.summary())


def show(root: Path, question: str, as_json: bool) -> None:
    """Print one question whole, including the operation it would resume.

    The operation whole rather than summarized, because what an approval binds
    to is what a reviewer should have been able to read: an approval given
    against a summary is an approval of the summary.
    """
    entry = relay(root).find(question)
    if entry is None:
        typer.echo(f"no question {question!r} is recorded", err=True)
        raise typer.Exit(2)
    if as_json:
        output_json(entry.model_dump(mode="json"))
        return
    typer.echo(entry.summary())
    typer.echo(f"  requester   {entry.operation.requester}")
    typer.echo(f"  eligible    {', '.join(entry.eligible) or 'nobody'}")
    typer.echo(f"  purpose     {entry.purpose or 'unclassified'}")
    typer.echo(f"  rule        {entry.rule or 'unattributed'}")
    typer.echo(f"  fingerprint {entry.fingerprint}")
    if entry.escalation:
        typer.echo(f"  escalated   {entry.escalation}")
    if entry.checkpoint_failure:
        typer.echo(f"  capture     failed: {entry.checkpoint_failure}")
    typer.echo(f"  payload     {entry.operation.payload}")
    if entry.answer is not None:
        typer.echo(
            f"  answered    {'yes' if entry.answer.approved else 'no'}"
            f" by {entry.answer.principal} ({entry.answer.receipt})"
        )
        if entry.answer.note:
            typer.echo(f"  note        {entry.answer.note}")


def answer(
    root: Path, question: str, principal: str, approved: bool, note: str
) -> None:
    """Record one decision, and say what it means for the operation.

    The refusal path prints the relay's own message rather than a generic
    one, because every way this can fail is a distinct thing the reviewer
    needs to know: the question is gone, already answered, expired, or theirs
    to read and not to answer.
    """
    try:
        settled = relay(root).answer(question, principal, approved, note)
    except ValueError as refusal:
        typer.echo(str(refusal), err=True)
        raise typer.Exit(2) from refusal
    verb = {"approved": "approved", "rejected": "rejected"}
    typer.echo(
        f"{settled.id}: {verb[settled.state] if settled.state in verb else settled.state}"
    )
    if settled.state == "approved":
        typer.echo(
            "the coordinator revalidates and resumes it — the requester does"
            " not reissue it, and this approval is spent once"
        )


def cancel(root: Path, question: str, reason: str) -> None:
    """Withdraw a question nobody needs answered any more."""
    try:
        settled = relay(root).cancel(question, reason)
    except ValueError as refusal:
        typer.echo(str(refusal), err=True)
        raise typer.Exit(2) from refusal
    typer.echo(f"{settled.id}: cancelled")


def create_questions_app(root: Path) -> typer.Typer:
    """Wire the reviewer's surface over one checkout's relay."""
    app = typer.Typer(no_args_is_help=True)

    @app.command("list")
    def list_cmd(
        principal: str = typer.Option(
            "", "--as", help="Show only what this principal may answer"
        ),
        everything: bool = typer.Option(
            False, "--all", help="Include answered, expired, and cancelled questions"
        ),
        as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
    ) -> None:
        """List the questions this run has parked, and what each is waiting on."""
        listing(root, principal, everything, as_json)

    @app.command("show")
    def show_cmd(
        question: str = typer.Argument(help="The question id"),
        as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
    ) -> None:
        """Show one question whole, including the operation it would resume."""
        show(root, question, as_json)

    @app.command("answer")
    def answer_cmd(
        question: str = typer.Argument(help="The question id"),
        principal: str = typer.Option(..., "--as", help="Who is answering"),
        note: str = typer.Option(
            "", "--note", help="What the agent should know alongside the answer"
        ),
    ) -> None:
        """Approve one question, optionally with a note for the agent."""
        answer(root, question, principal, True, note)

    @app.command("reject")
    def reject_cmd(
        question: str = typer.Argument(help="The question id"),
        principal: str = typer.Option(..., "--as", help="Who is answering"),
        note: str = typer.Option("", "--note", help="What the agent should do instead"),
    ) -> None:
        """Refuse one question, optionally saying what to do instead."""
        answer(root, question, principal, False, note)

    @app.command("cancel")
    def cancel_cmd(
        question: str = typer.Argument(help="The question id"),
        reason: str = typer.Option("", "--reason", help="Why it is being withdrawn"),
    ) -> None:
        """Withdraw a question nobody needs answered any more."""
        cancel(root, question, reason)

    return app
