"""Console doors onto a resolver run's question mailbox.

Each of these is a handful of lines because the mailbox is just files, and
each is strictly better than a prompt on the run's own stdin ever was: they
work from another shell, or another host, *while the run is still waiting*.

None of them may take :meth:`ResolverStateRepository.exclusive`. A run holds
that lock for its whole life, so a door that reached for it could only ever
serve runs that had already finished — which is exactly the class of runs a
door is useless for.
"""

from pathlib import Path

import typer

from lup.channels.models import utc_now
from lup.resolver.journal import Journal
from lup.resolver.models import VerificationAcceptance
from lup.resolver.state import ResolverStateRepository
from lup.resolver.status import run_status
from lup.resolver.mailbox import (
    AnswerDoor,
    AnswerOffer,
    MailboxConflictError,
    ParkRequest,
    QuestionMailbox,
    new_message,
)
from lup.workspace.paths import project_root
from lup.devtools.harness.resolve import parse_answer_flags
from lup.devtools.supervisor.projection import PendingQuestionView


def resolve_state_root() -> Path:
    return project_root() / ".lup" / "resolve"


def open_mailbox(run_id: str) -> QuestionMailbox:
    """The mailbox for one run, refusing a run that was never recorded."""
    root = resolve_state_root() / run_id
    if not root.is_dir():
        raise typer.BadParameter(f"no resolver run {run_id!r} under {root.parent}")
    return QuestionMailbox(root)


def pending_views(mailbox: QuestionMailbox) -> list[PendingQuestionView]:
    """Every question a run has asked, straight from its mailbox.

    The state file is never read here: a moving run's ``state.json`` lags
    its mailbox by design, and the mailbox alone is authoritative for
    anything still pending.
    """
    answered = {
        record.answer.question_id: record.answer.value for record in mailbox.answers()
    }
    offered = {offer.question_id: offer.value for offer in mailbox.offers()}
    return [
        PendingQuestionView(
            question=item.question,
            asked_by=item.asked_by,
            answered=(
                answered[item.question.id] if item.question.id in answered else None
            ),
            offer=offered[item.question.id] if item.question.id in offered else None,
        )
        for item in mailbox.questions()
    ]


def describe(view: PendingQuestionView) -> list[str]:
    """Render one question the way an operator needs to answer it cold."""
    question = view.question
    lines = [f"{question.id} (concern {question.concern_id})", f"  {question.prompt}"]
    if question.choices:
        lines.append("  choices: " + " | ".join(question.choices))
    if question.recommendation is not None:
        lines.append(f"  recommendation: {question.recommendation}")
    if view.answered is not None:
        lines.append(f"  answered: {view.answered}")
    elif view.offer is not None:
        lines.append(f"  offered, not yet promoted: {view.offer}")
    return lines


def queued(run_id: str, to: str) -> list[str]:
    """Say what a just-posted message is waiting on, rather than that it sent.

    Reporting `sent` on the strength of having written the mailbox is what
    let a redirect read as successful while reaching nobody at all. The
    honest report is that it is queued, for whom, and — when the address
    matches no actor the run has recorded — that nobody it can name will
    read it. Not a refusal: a message may legitimately be posted for a
    concern that has not started, and it waits at that actor's first turn.
    """
    reached = [
        actor
        for actor in Journal(resolve_state_root() / run_id).actors()
        if to in actor.addresses()
    ]
    if not reached:
        return [
            f"queued for {to or 'every actor'}, which names no actor this run "
            "has recorded yet; it waits until one by that address takes a turn",
        ]
    return [
        f"queued for {actor.label()}; it arrives at that actor's next tool call or turn"
        for actor in reached
    ]


app = typer.Typer(help="Read and answer resolver runs from the console")


@app.command("questions")
def list_questions(
    run_id: str = typer.Option(..., "--run-id", help="Run whose mailbox to read"),
    pending_only: bool = typer.Option(
        False, "--pending", help="Show only questions still waiting on you"
    ),
) -> None:
    """List a run's questions and what each one has been answered.

    ``--pending`` is what a human reads after answering, so it means what
    they mean by it: still waiting on you. A question already offered is
    waiting on the run to take it, not on another answer — listed as
    pending it read as though nothing had been recorded, and the only way
    to tell was to go and count files on disk.
    """
    views = pending_views(open_mailbox(run_id))
    waiting = [view for view in views if view.answered is None and view.offer is None]
    offered = [view for view in views if view.answered is None and view.offer]
    selected = waiting if pending_only else views
    if not selected:
        typer.echo("No questions." if not views else "Nothing waiting on you.")
        return
    for view in selected:
        for line in describe(view):
            typer.echo(line)
    if pending_only and offered:
        typer.echo(
            f"{len(offered)} answered and awaiting promotion; "
            "the run takes them when it next advances"
        )


@app.command("answer")
def answer_questions(
    pairs: list[str] = typer.Argument(..., help="<question-id>=<value>, repeatable"),
    run_id: str = typer.Option(..., "--run-id", help="Run whose mailbox to write"),
) -> None:
    """Offer an answer to one or more of a run's questions.

    Offers stay correctable right up until a promoter takes one, so a
    mistyped free-text value is fixed by offering again rather than being
    permanent — nothing under ``.lup/resolve`` is ever unlinked.
    """
    mailbox = open_mailbox(run_id)
    known = {view.question.id: view for view in pending_views(mailbox)}
    for identifier, value in parse_answer_flags(pairs).items():
        if identifier not in known:
            raise typer.BadParameter(
                f"{identifier!r} names no question this run asked; "
                f"run `harness resolve questions --run-id {run_id}`"
            )
        question = known[identifier].question
        if question.closed_choices and value not in question.choices:
            raise typer.BadParameter(
                f"{identifier!r} accepts only: " + ", ".join(question.choices)
            )
        try:
            mailbox.offer(
                AnswerOffer(
                    run_id=run_id,
                    question_id=identifier,
                    value=value,
                    door=AnswerDoor.CONSOLE,
                    offered_at=utc_now(),
                )
            )
        except MailboxConflictError as error:
            raise typer.BadParameter(str(error)) from error
        typer.echo(f"offered {identifier}={value}")


@app.command("actors")
def list_actors(
    run_id: str = typer.Option(..., "--run-id", help="Run whose record to read"),
) -> None:
    """List every actor this run has recorded, and what each has not read yet.

    Undelivered mail is shown because sending is not delivering: a door
    writes the stream and the actor reads it at its next tool call or turn,
    and nothing between those two moments used to say which had happened.
    A redirect sitting here through a whole concern is that concern being
    worked on the instructions it was supposed to abandon.
    """
    actors = Journal(resolve_state_root() / run_id).actors()
    if not actors:
        typer.echo("No actor has recorded anything yet.")
        return
    mailbox = open_mailbox(run_id)
    for actor in actors:
        typer.echo(actor.label())
        waiting = mailbox.waiting(actor)
        for message in waiting.messages:
            kind = "redirect" if message.redirect else "message"
            typer.echo(f"  undelivered {kind} from {message.door}: {message.text}")


@app.command("say")
def say_to_actor(
    text: str = typer.Argument(..., help="What to tell the actor"),
    run_id: str = typer.Option(..., "--run-id", help="Run whose mailbox to write"),
    to: str = typer.Option(
        "", "--to", help="Actor label from `actors`, or empty to reach every actor"
    ),
    in_reply_to: str = typer.Option(
        "", "--in-reply-to", help="Question or message id this answers, if any"
    ),
) -> None:
    """Tell an actor something. It reads this and keeps going."""
    open_mailbox(run_id).send(
        new_message(run_id, to, text, AnswerDoor.AGENT, in_reply_to)
    )
    for line in queued(run_id, to):
        typer.echo(line)


@app.command("accept")
def accept_verification(
    reason: str = typer.Argument(..., help="Why this failure is accepted"),
    run_id: str = typer.Option(..., "--run-id", help="Run whose state to write"),
    concern: str = typer.Option(..., "--concern", help="Concern to accept"),
    verification: str = typer.Option(
        ..., "--verification", help="The failing verification, by name"
    ),
) -> None:
    """Accept one concern over one failing verification, on the human's word.

    A verdict is an exit code, and some failures are true but unfixable from
    inside the lease that meets them — a finding the worker did not
    introduce and cannot converge on. Resubmitting into it spends a revision
    round each time until the concern fails with its criteria never read.

    The reason is required because this is what review sees in place of a
    green check that was never green.
    """
    root = resolve_state_root() / run_id
    if not root.is_dir():
        raise typer.BadParameter(f"no resolver run {run_id!r} under {root.parent}")
    ResolverStateRepository(resolve_state_root(), run_id).accept(
        VerificationAcceptance(
            concern_id=concern, verification=verification, reason=reason
        )
    )
    typer.echo(f"accepted {concern} over {verification}: {reason}")


@app.command("redirect")
def redirect_actor(
    text: str = typer.Argument(..., help="What the actor should do instead"),
    run_id: str = typer.Option(..., "--run-id", help="Run whose mailbox to write"),
    to: str = typer.Option(
        "", "--to", help="Actor label from `actors`, or empty to reach every actor"
    ),
) -> None:
    """Stop an actor and put it on something else.

    Where `say` rides alongside the actor's next tool call, this refuses that
    call and hands back this text as the reason — so an actor going the wrong
    way cannot take one more step down it before reading why it was stopped.
    """
    open_mailbox(run_id).send(
        new_message(run_id, to, text, AnswerDoor.AGENT, redirect=True)
    )
    for line in queued(run_id, to):
        typer.echo(line)


@app.command("park")
def park_run(
    run_id: str = typer.Option(..., "--run-id", help="Run to park"),
    reason: str = typer.Option(
        "parked from the console", "--reason", help="Why the run is being parked"
    ),
) -> None:
    """Ask every open wait in this run to give up now."""
    open_mailbox(run_id).park(ParkRequest(run_id=run_id, reason=reason))
    typer.echo(f"parked {run_id}: {reason}")


def show_status(
    run_id: str = typer.Option(..., "--run-id", help="Run to report on"),
) -> None:
    """Say whether a run is alive, where it stands, and what it last did.

    The liveness answer comes from the run's own lock rather than from the
    process table, because under a sandbox `/proc` is PID-isolated: `ps` and
    `pgrep` list nothing outside the current shell, so a healthy run looks
    exactly like one that died. That ambiguity has produced confident wrong
    conclusions in both directions, and the run directory is the only thing
    a reader is guaranteed to be able to see.
    """
    root = resolve_state_root()
    repository = ResolverStateRepository(root, run_id)
    status = run_status(repository, run_id)
    if not status.exists:
        raise typer.BadParameter(f"no resolver run {run_id!r} under {root}")
    typer.echo(status.verdict())
    typer.echo(f"  phase: {status.phase}")
    for count in status.counts:
        typer.echo(f"  {count.concerns:>3} {count.status}")
    if status.unanswered:
        typer.echo(f"  {status.unanswered} question(s) waiting on you")
    if status.last is not None:
        typer.echo(
            f"  last: {status.last.event} by {status.last.actor} "
            f"at {status.last.at:%Y-%m-%d %H:%M:%S}Z"
        )
