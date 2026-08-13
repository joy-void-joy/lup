"""Putting one prompt to one actor, and taking its typed submission back.

A worker revising its own code, a reviewer reading what that worker wrote,
and a merger settling a join are three spellings of one thing: address an
actor, hand it a prompt built from what the run knows, and receive a
submission. The differences that look structural are not — which factory
opens the session, which declared skill is rendered into the prompt, which
model the submission validates against.

What a prompt is built from is the other half of this. An actor is told what
the run has settled: the allowances its concern was granted, the answers a
human gave it, and — for a merger — the joins it has already made and what
the tree it is joining into is carrying. That last is why the merge ledger
lives here rather than with the phase that drives the joins: it is the
merger's memory across its own turns, and only the thing that takes those
turns can keep it.
"""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.harness.contracts import SkillInvocationRenderer
from lup.harness.models import ResolveSpec
from lup.policy.identity import ConcernAllowance
from lup.resolver.actors import ActorSession, ActorSessions
from lup.resolver.mailbox import QuestionMailbox
from lup.resolver.models import (
    ActorRef,
    Concern,
    DropCandidate,
    MergeReport,
    ReviewReport,
    WorkAssignment,
    WorkerContext,
    WorkerReport,
    WritableRootLease,
    ALLOWANCE_GRANTED,
    allowance_question_id,
)
from lup.resolver.run import ResolveRun, ResolverInvariantError
from lup.resolver.tools import WAIT_CONTRACT
from lup.runtime.factory import SessionFactory
from lup.runtime.models import TurnInput, turn_request
from lup.runtime.wrappers import CorrectionConfig, decorated_session_factory

type WorkerFactoryRecipe = Callable[[WorkerContext], SessionFactory]
type ReviewerFactoryRecipe = Callable[[Path], SessionFactory]


def corrective[T](
    recipe: Callable[[T], SessionFactory],
) -> Callable[[T], SessionFactory]:
    """Give each opened session corrective structured-output reprompts.

    Every resolver turn ends in a typed submission; a model that answers in
    prose instead of calling the submission tool would otherwise fail the
    whole run on its first miss.
    """

    def factory(argument: T) -> SessionFactory:
        return decorated_session_factory(
            recipe(argument), correction=CorrectionConfig(cycles=2)
        )

    return factory


ASK_PREAMBLE = (
    "When a decision is not yours to make, ask through the resolver's question "
    "tools — queue_questions, await_answers, ask_questions — rather than "
    "guessing or ending your turn to report it. " + WAIT_CONTRACT
)

DECLARATION_PREAMBLE = (
    "Before you submit, put the file account you are about to report through "
    "check_declaration and act on what it says. It runs the same reading that "
    "judges the account, so one it settles is one that passes. Declaring is "
    "the only part of your turn you cannot verify by looking — you have no "
    "git of your own here — and an account the gate rejects costs a whole "
    "session to correct."
)


def format_paths(paths: list[Path]) -> str:
    return "\n".join(f"- {path.as_posix()}" for path in paths) or "- (none)"


def format_candidates(owed: list[DropCandidate]) -> str:
    """Show each parent's unaccounted content, capped so the list stays read.

    A merger handed four hundred lines reads none of them, and the obligation
    is per path rather than per line — the sample is enough to recognize what
    went missing and find the rest.

    Lost definitions lead, and are named in full rather than sampled. Lines go
    missing whenever a resolution rewrites them, so that list is long and
    mostly benign; a definition that existed and now does not is the shape a
    regression takes, and there are never so many that naming them all costs
    the reader anything.
    """
    return (
        "\n".join(
            f"- {candidate.path.as_posix()} (from {candidate.parent[:12]})"
            + (
                "\n  definitions no longer present: "
                + ", ".join(
                    f"{symbol.name} (parent line {symbol.line})"
                    for symbol in candidate.lost_symbols
                )
                if candidate.lost_symbols
                else ""
            )
            + (
                f"\n  {len(candidate.missing)} lines, first: "
                + " / ".join(candidate.missing[:3])
                if candidate.missing
                else ""
            )
            for candidate in owed
        )
        or "- (none)"
    )


class LedgerEntry(BaseModel):
    """One join, as the merger accounted for it."""

    model_config = ConfigDict(frozen=True)

    parent: str
    summary: str
    merge: MergeReport


class TurnRunner:
    """Every actor this run addresses, and the prompts it puts to them."""

    def __init__(
        self,
        spec: ResolveSpec,
        run: ResolveRun,
        actors: ActorSessions,
        mailbox: QuestionMailbox,
        worker_factory: WorkerFactoryRecipe,
        reviewer_factory: ReviewerFactoryRecipe,
        invocation_renderer: SkillInvocationRenderer,
    ) -> None:
        self.spec = spec
        self.run = run
        self.actors = actors
        self.mailbox = mailbox
        self.worker_factory = corrective(worker_factory)
        self.reviewer_factory = corrective(reviewer_factory)
        self.invocation_renderer = invocation_renderer
        self.ledger: list[LedgerEntry] = []

    def worker_session(
        self, actor: ActorRef, root: Path, allowances: list[ConcernAllowance]
    ) -> ActorSession:
        """One writing actor's session, authorized for the gates it was granted."""
        return self.actors.session(
            actor,
            self.worker_factory(
                WorkerContext(
                    root=root,
                    concern_id=actor.id,
                    actor=actor,
                    allowances=allowances,
                )
            ),
        )

    def reviewer_session(self, actor: ActorRef, worktree: Path) -> ActorSession:
        """One reading actor's session, opened over the tree it judges."""
        return self.actors.session(actor, self.reviewer_factory(worktree))

    def worker_invocation(self) -> str:
        """The rendered call for this run's declared worker skill."""
        return self.invocation_renderer.render(self.spec.worker_skill)

    async def worker_turn(
        self, assignment: WorkAssignment, feedback: str, round_number: int
    ) -> WorkerReport:
        prompt = (
            "Execute the portable worker skill below. You may edit only the assigned "
            "writable root. Do not create branches or commits; the orchestrator owns "
            "that authority. Resolve every acceptance criterion. Your concern's "
            "review-note markers are already gone from this worktree — the "
            "orchestrator removed them before you started, so the spec is the whole "
            "of the feedback. Do not re-introduce a marker, and do not leave an "
            "explanatory comment where one stood. Every `# lup:` marker still "
            "present belongs to another concern or is `defer:` parked work you "
            "were not asked to wake: leave it in place. If resolving your concern "
            "means deleting or moving code that carries one, do so and name it in "
            "your summary.\n\n"
            f"{ASK_PREAMBLE}\n\n"
            f"{DECLARATION_PREAMBLE}\n\n"
            f"{assignment.rendered_skill_invocation}\n\n"
            f"Assignment:\n{assignment.model_dump_json(indent=2)}"
        )
        if round_number > 1:
            # The worker holds the session that produced the work under
            # review, so the assignment and its own reasoning are already in
            # front of it. Restating both would invite it to start over
            # instead of revising what a reviewer just read.
            prompt = (
                "Your submitted work was reviewed and did not pass. Revise it in "
                "the same worktree and submit an updated report.\n\n"
                f"Review feedback:\n{feedback}"
            )
        result = await self.worker_session(
            ActorRef(kind="worker", id=assignment.concern.id, round=round_number),
            assignment.lease.root,
            self.granted_for(assignment.concern),
        ).turn(turn_request(TurnInput(text=prompt), WorkerReport))
        if result.output.concern_id != assignment.concern.id:
            raise ResolverInvariantError("worker returned a foreign concern id")
        return result.output

    async def review_turn(
        self,
        concern: Concern,
        worker: WorkerReport,
        base: str,
        commit: str,
        worktree: Path,
        round_number: int,
    ) -> ReviewReport:
        invocation = self.invocation_renderer.render(self.spec.review_skill)
        # The whole range, not the head: a round's work regularly spans
        # several commits, and a reviewer handed one spent its round
        # discovering the others.
        span = f"Commits under review: {base[:12]}..{commit[:12]} — every one."
        rulings = self.rulings_for(concern.id)
        answered = (
            f"\n\nQuestions this concern has had answered:\n{rulings}"
            if rulings
            else ""
        )
        prompt = (
            "Independently review the committed concern against every persisted "
            "acceptance criterion.\n\n"
            f"{invocation}\n\nConcern:\n{concern.model_dump_json(indent=2)}\n\n"
            f"Worker report:\n{worker.model_dump_json(indent=2)}\n\n"
            f"{span}{answered}"
        )
        if round_number > 1:
            # This reviewer wrote the criticism the worker was revising, so
            # it knows what it asked for. Re-reading its own concern cold on
            # every round was one of the costs of a one-shot session.
            prompt = (
                "The worker revised in response to your review. Review the "
                "updated work against the same acceptance criteria, and say "
                "explicitly whether each point you raised was addressed.\n\n"
                f"Worker report:\n{worker.model_dump_json(indent=2)}\n\n"
                f"{span}{answered}"
            )
        result = await self.reviewer_session(
            ActorRef(kind="reviewer", id=concern.id, round=round_number), worktree
        ).turn(turn_request(TurnInput(text=prompt), ReviewReport))
        if result.output.concern_id != concern.id:
            raise ResolverInvariantError("reviewer returned a foreign concern id")
        return result.output

    async def merge_turn(
        self,
        lease: WritableRootLease,
        parent: str,
        purpose: str,
        conflicted: list[Path],
        owed: list[DropCandidate],
        problems: list[str] | None = None,
    ) -> MergeReport:
        """Put one join to the merger, with what each side meant by it.

        The merger used to receive a purpose string, a worktree and two
        shas, so it could read what changed but not which behaviour was a
        deliberate decision. The argument against telling it more is that a
        merger who knows what each side intended can rationalize a bad merge
        as intended; what settled it the other way is that the observed
        failure was declining to classify something it had no basis for,
        which is missing context rather than misused context.
        """
        if problems is not None:
            return await self.merge_retry(lease, problems)
        prompt = (
            "Resolve the prepared semantic merge in the assigned worktree. Stage "
            "every resolution with `git add` — settling the index is your work "
            "and the merge cannot complete without it. Do not commit and do not "
            "change branches; the orchestrator owns commit authority, which "
            "covers committing only. If you resolve the content but cannot "
            "stage it, say so in `blocked` rather than reporting completion.\n\n"
            "Two things you must account for. Every candidate below is content "
            "one parent contributed that this tree no longer holds — disposition "
            "each as kept, rewritten, superseded or dropped, with a reason. A "
            "rewrite is a legitimate answer; silence is not. Where a candidate "
            "names definitions no longer present, read those first: a function "
            "or class one parent defined and this tree does not is the shape a "
            "regression takes, and 'rewritten' is only true if you can name "
            "where the behaviour landed. And any file you "
            "edit that is not in the conflict set must be declared, with a "
            "reason: fixing a caller whose file merged clean is correct and "
            "expected, and is exactly what has to be visible.\n\n"
            + f"{self.invocation_renderer.render(self.spec.merge_skill)}\n\n"
            + f"Purpose: {purpose}\nWorktree: {lease.root}\nJoining: {parent}\n\n"
            + self.merge_context(parent)
            + f"Conflicted paths:\n{format_paths(conflicted)}\n\n"
            + f"Unaccounted content:\n{format_candidates(owed)}"
        )
        result = await self.merger_session(lease).turn(
            turn_request(TurnInput(text=prompt), MergeReport)
        )
        return result.output

    async def merge_retry(
        self, lease: WritableRootLease, problems: list[str]
    ) -> MergeReport:
        """Name what the last report left unmet, on the session that wrote it."""
        result = await self.merger_session(lease).turn(
            turn_request(
                TurnInput(
                    text=(
                        "Your merge report did not account for everything this "
                        "join changed:\n- " + "\n- ".join(problems) + "\n\nFix "
                        "the tree where it is wrong and resubmit a report that "
                        "accounts for each item. Declaring a rewrite or a "
                        "deliberate supersession with a reason is a complete "
                        "answer; leaving one unmentioned is not."
                    )
                ),
                MergeReport,
            )
        )
        return result.output

    def merger_session(self, lease: WritableRootLease) -> ActorSession:
        """The one merger conversation this lease's joins are settled in."""
        return self.worker_session(
            ActorRef(kind="merger", id=lease.concern_id),
            lease.root,
            self.merge_allowances(),
        )

    def record_join(self, parent: str, merge: MergeReport) -> None:
        """Keep one settled join, so later ones are decided consistently with it."""
        self.ledger.append(
            LedgerEntry(parent=parent, summary=merge.summary, merge=merge)
        )

    def merge_context(self, parent: str) -> str:
        """What the concern behind this parent was for, and what it decided.

        A merger that knows only the diff can tell what changed but not what
        was deliberate. What it gets is the concern's own specification, the
        criteria it had to meet, the answers a human gave it, and the merge
        notes its worker left for whoever would join it — the last being the
        one thing only that worker could know.
        """
        state = self.run.state
        if state is None:
            return ""
        owner = next(
            (
                outcome.concern_id
                for outcome in state.outcomes
                if outcome.commit == parent
            ),
            None,
        )
        if owner is None:
            return ""
        concern = next(
            (item for item in state.concerns if item.id == owner),
            None,
        )
        if concern is None:
            return ""
        answers = [
            f"- {record.answer.question_id}: {record.answer.value}"
            for record in self.mailbox.answers()
            for item in self.mailbox.questions()
            if item.question.id == record.answer.question_id
            and item.question.concern_id == owner
        ]
        notes = [
            note
            for outcome in state.outcomes
            if outcome.concern_id == owner
            for round_record in outcome.rounds
            for note in round_record.worker.merge_notes
        ]
        return (
            f"Concern behind this parent:\n{concern.model_dump_json(indent=2)}\n\n"
            + (
                "Answers this concern was given:\n" + "\n".join(answers) + "\n\n"
                if answers
                else ""
            )
            + (
                "Merge notes its worker left for whoever joins it — these are "
                "consequences only that worker could know:\n- "
                + "\n- ".join(notes)
                + "\n\n"
                if notes
                else ""
            )
            + self.ledger_recital()
            + self.accumulated_recital()
        )

    def ledger_recital(self) -> str:
        """What this merger has already settled, carried forward as a record.

        The accumulating session means it was there for all of them, but
        attention is not memory: by parent ten the earliest joins are far
        behind, and a decision it made at join two is exactly what it needs
        at join nine to stay consistent.
        """
        if not self.ledger:
            return ""
        return (
            "Joins you have already settled in this run:\n"
            + "\n".join(
                f"- {entry.parent[:12]}: {entry.summary}" for entry in self.ledger
            )
            + "\n\n"
        )

    def accumulated_recital(self) -> str:
        """What the tree being joined into is already carrying, and why.

        The incoming parent arrived with its concern, its answers and its
        merge notes; the side it is being joined into had only one-line
        summaries. That asymmetry is what produces the characteristic bad
        join — the incoming change is legible and the standing one is not, so
        the resolution favours what the merger can read, and an earlier
        concern is quietly reverted by someone who never saw what it was for.
        """
        state = self.run.state
        if state is None or not self.ledger:
            return ""
        joined = {entry.parent for entry in self.ledger}
        concerns = {
            outcome.concern_id: outcome.commit
            for outcome in state.outcomes
            if outcome.commit in joined
        }
        recited = [
            f"- {concern.id}: {concern.title}\n"
            + "".join(
                f"    criterion: {criterion.description}\n"
                for criterion in concern.criteria
            )
            for concern in state.concerns
            if concern.id in concerns
        ]
        if not recited:
            return ""
        return (
            "Already in the tree you are joining into. These are settled, and "
            "a resolution that stops one of them holding is a regression "
            "however reasonable the incoming change looks:\n"
            + "\n".join(recited)
            + "\n"
        )

    def rulings_for(self, concern_id: str) -> str:
        """The concern's mid-run Q&A, rendered for an actor's prompt.

        Workers cite rulings in their reports; a reviewer that cannot read
        the ruling can only take the citation on faith or spend its round
        disputing settled questions. The record travels with the prompt.
        """
        state = self.run.state
        if state is None or state.questions is None:
            return ""
        prompts = {
            question.id: question.prompt
            for question in state.questions.questions
            if question.concern_id == concern_id
        }
        return "\n".join(
            f"- {answer.question_id}: {prompts[answer.question_id]}\n"
            f"  answered: {answer.value}"
            for answer in (state.answers.answers if state.answers else [])
            if answer.question_id in prompts
        )

    def granted_for(self, concern: Concern) -> list[ConcernAllowance]:
        """Every gate this concern may pass: planned grants plus mid-run ones.

        A `request_allowance` question a human answered "grant" extends the
        concern's authority from that answer on: the next session launched
        for the concern — a revision round, a merge, a remediation — carries
        it in its environment and its in-process judge. Without this reader,
        the tool's question had no machinery behind either answer.
        """
        granted = list(concern.allowances)
        state = self.run.state
        if state is None or state.answers is None:
            return granted
        answered = {
            answer.question_id: answer.value for answer in state.answers.answers
        }
        for allowance in ConcernAllowance:
            if allowance in granted:
                continue
            key = allowance_question_id(concern.id, allowance)
            if key in answered and answered[key] == ALLOWANCE_GRANTED:
                granted.append(allowance)
        return granted

    def merge_allowances(self) -> list[ConcernAllowance]:
        """Every gate the joined concerns were approved to pass.

        A join can newly require a suppression that neither parent needed: a
        rule one branch adds first meets a constant another branch adds only
        once the two are together. Nobody could have declared that at plan
        time, and a merge session carrying no allowance at all had no route
        to it except failing.
        """
        state = self.run.state
        if state is None:
            return []
        return list(
            dict.fromkeys(
                allowance
                for concern in state.concerns
                for allowance in self.granted_for(concern)
            )
        )
