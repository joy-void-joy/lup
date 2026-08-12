"""Taking one concern from its dependency base to a verified commit.

This is the run's inner loop, and every concern in a topological batch is in
it at once. It builds the tree the concern starts from, strips the concern's
own review markers so the spec is the whole of the feedback, and then spends
bounded rounds of worker-then-reviewer until the work is accepted or the
allowance is gone. A question the worker could not answer for itself parks
the concern rather than failing it, so the answer lands on a run that still
holds everything it had.

Acceptance is checked against what was declared, not against what the
reviewer says it checked: a report that accepts while its ``criteria_met``
does not match the persisted criteria is turned back with the exact ids
named, because the alternative is a concern that passes on criteria nobody
wrote down.
"""

from lup.resolver.contracts import ResolverAwaitingAnswers
from lup.resolver.joins import Joiner
from lup.resolver.journal import Journal, ReviewResidualEvent
from lup.resolver.models import (
    AgentRound,
    Concern,
    ConcernExecution,
    ConcernOutcome,
    ConcernStatus,
    ResolverConfig,
    ReviewReport,
    WorkAssignment,
    WritableRootLease,
)
from lup.resolver.orchestrator import (
    DependencyBaseBuilder,
    WorktreeOrchestrator,
    WritableRootLeases,
)
from lup.resolver.questions import QuestionBroker
from lup.resolver.run import ResolveRun
from lup.resolver.state import ResolverStateRepository
from lup.resolver.turns import TurnRunner
from lup.resolver.verification import Verifier


class ConcernExecutor:
    """One concern's revision loop, from dependency base to verified commit."""

    def __init__(
        self,
        config: ResolverConfig,
        run: ResolveRun,
        runner: TurnRunner,
        questions: QuestionBroker,
        joiner: Joiner,
        verifier: Verifier,
        worktrees: WorktreeOrchestrator,
        leases: WritableRootLeases,
        repository: ResolverStateRepository,
        journal: Journal,
    ) -> None:
        self.config = config
        self.run = run
        self.runner = runner
        self.questions = questions
        self.joiner = joiner
        self.verifier = verifier
        self.worktrees = worktrees
        self.leases = leases
        self.repository = repository
        self.journal = journal

    async def execute_concern(
        self,
        concern: Concern,
        lease: WritableRootLease,
        commits: dict[str, str],  # lup: ignore[dict-str-payload] — concern-id index
        builder: DependencyBaseBuilder,
    ) -> ConcernExecution:
        """Execute one concern while persisting a terminal failure on exceptions."""
        try:
            return await self.execute_concern_inner(concern, lease, commits, builder)
        except ResolverAwaitingAnswers:
            await self.run.transition_concern(
                concern.id,
                ConcernStatus.WAITING_FOR_ANSWERS,
                "parked on material questions",
            )
            raise
        except Exception as error:
            await self.run.transition_concern(
                concern.id, ConcernStatus.FAILED, str(error)
            )
            raise

    async def execute_concern_inner(
        self,
        concern: Concern,
        lease: WritableRootLease,
        commits: dict[str, str],  # lup: ignore[dict-str-payload] — concern-id index
        builder: DependencyBaseBuilder,
    ) -> ConcernExecution:
        """Build dependencies, run bounded revisions, and verify one concern."""
        parent_commits = [commits[parent] for parent in concern.dependencies]
        if len(parent_commits) > 1:
            joined = await self.joiner.join_commits(
                lease,
                parent_commits,
                f"dependency base for {concern.id}",
                f"resolve: join dependencies for {concern.title}",
            )
            base = builder.build(concern, commits, joined_commit=joined)
            base = await self.run.record_dependency_base(base)
        else:
            base = builder.build(concern, commits)
            base = await self.run.record_dependency_base(base)
            if not lease.root.exists():
                self.worktrees.create(lease, base.commit)

        cleared = self.worktrees.clear_notes(lease, concern, base.commit)
        base = await self.run.record_note_clearance(base, cleared.commit)
        answers = self.questions.answers_for(concern.id)
        assignment = WorkAssignment(
            run_id=self.config.run_id,
            concern=concern,
            lease=lease,
            dependency_base=base,
            rendered_skill_invocation=self.runner.worker_invocation(),
            answers=answers,
        )
        rounds: list[AgentRound] = []  # lup: ignore[empty-collection]
        feedback = ""
        maximum_round = self.config.max_revision_rounds + 1
        # Every attempt is a round on disk, because each one is a real worker
        # turn and its record is keyed by that number. What differs is which
        # allowance it spends: only a round the reviewer could have judged
        # counts against the revision budget.
        charged = 0
        attempts = maximum_round + self.config.max_declaration_attempts
        for round_number in range(1, attempts + 1):
            await self.run.transition_concern(concern.id, ConcernStatus.RUNNING)
            # The commit a turn is measured from is the lease's own head at the
            # moment the turn opens, read rather than carried. A carried value
            # is derived from the clearance while the check compares against
            # the worktree, so the two can disagree the instant anything but
            # this loop advances the branch — a concern resumed in a second
            # process re-entered at the clearance and failed for the commit the
            # first process had itself made.
            round_base = self.worktrees.head(lease)
            worker = await self.runner.worker_turn(assignment, feedback, round_number)
            outstanding = await self.questions.unanswered_for(concern.id)
            if outstanding:
                raise ResolverAwaitingAnswers(outstanding, [])
            await self.run.transition_concern(concern.id, ConcernStatus.VALIDATING)
            diff = self.worktrees.validate_and_commit(
                concern, worker, lease, round_base, self.leases, base.commit
            )
            if not diff.valid or diff.commit is None:
                review = ReviewReport(
                    concern_id=concern.id,
                    accepted=False,
                    generalized=False,
                    reason=diff.reason,
                )
            else:
                await self.run.transition_concern(concern.id, ConcernStatus.REVIEWING)
                # Verification ran exactly once in a run, over the fully
                # integrated tree, so a concern could reach VERIFIED with a
                # red suite and the breakage surfaced after every join with
                # nothing to attribute it to.
                # A failure a human has accepted for this concern is not a
                # verdict the worker can act on: it accepted one it had
                # already judged unfixable from inside the lease, and
                # rejecting again would spend a revision round to reach the
                # same place.
                accepted = [
                    acceptance.verification
                    for acceptance in self.run.require().acceptances
                    if acceptance.concern_id == concern.id
                ]
                broke = [
                    record.name
                    for record in self.verifier.verify(lease.root, base.commit)
                    if not record.passed and record.name not in accepted
                ]
                review = (
                    ReviewReport(
                        concern_id=concern.id,
                        accepted=False,
                        generalized=False,
                        reason="verification failed: " + ", ".join(broke),
                    )
                    if broke
                    else await self.runner.review_turn(
                        concern,
                        worker,
                        round_base,
                        diff.commit,
                        lease.root,
                        round_number,
                    )
                )
                declared = {criterion.id: True for criterion in concern.criteria}
                met = {identifier: True for identifier in review.criteria_met}
                unaccounted = [
                    identifier for identifier in declared if identifier not in met
                ]
                undeclared = [
                    label for label in review.criteria_met if label not in declared
                ]
                if review.accepted and (unaccounted or undeclared):
                    # The reviewer's own reason survives — the guard's
                    # complaint is appended, never substituted, and it names
                    # the exact ids so the next round can close the gap
                    # instead of re-deriving it.
                    complaint = (
                        "criteria_met does not match the persisted acceptance criteria"
                    )
                    if unaccounted:
                        complaint += "; unaccounted: " + ", ".join(unaccounted)
                    if undeclared:
                        complaint += "; never declared: " + ", ".join(undeclared)
                    review = review.model_copy(
                        update={
                            "accepted": False,
                            "reason": review.reason + "\n\n" + complaint,
                        }
                    )
            rounds.append(
                AgentRound(
                    concern_id=concern.id,
                    round=round_number,
                    worker=worker,
                    diff=diff,
                    review=review,
                )
            )
            self.repository.write_round(rounds[-1])
            if review.accepted and diff.commit is not None:
                if review.residual:
                    # A residual on a rejection re-enters the worker's
                    # feedback below; on an acceptance it used to reach
                    # nobody, and this run's residuals carried real findings.
                    self.journal.record(
                        ReviewResidualEvent(
                            concern_id=concern.id,
                            round=round_number,
                            residual=list(review.residual),
                        )
                    )
                await self.run.transition_concern(concern.id, ConcernStatus.VERIFIED)
                return ConcernExecution(
                    base=base,
                    outcome=ConcernOutcome(
                        concern_id=concern.id,
                        branch=lease.branch,
                        commit=diff.commit,
                        head=diff.commit,
                        verified=True,
                        rounds=rounds,
                        notes_cleared=cleared.clearance.cleared,
                        notes_missing=cleared.clearance.missing,
                    ),
                )
            await self.run.transition_concern(
                concern.id, ConcernStatus.REVISING, review.reason
            )
            feedback = review.reason + "\n" + "\n".join(review.residual)
            charged += 0 if diff.declaration else 1
            if charged == maximum_round:
                break
        # A concern that never spent a revision round never had its work
        # judged at all: every attempt died on the declaration contract. That
        # is the harness failing to let the work be evaluated rather than the
        # work failing to hold up, and the two should not read alike.
        failure = (
            "revision limit exhausted"
            if charged
            else "declaration contract unmet: no round reached the criteria"
        )
        await self.run.transition_concern(concern.id, ConcernStatus.FAILED, failure)
        return ConcernExecution(
            base=base,
            outcome=ConcernOutcome(
                concern_id=concern.id,
                branch=lease.branch,
                commit=rounds[-1].diff.commit if rounds else None,
                head=self.worktrees.head(lease),
                verified=False,
                rounds=rounds,
                failure=failure,
                notes_cleared=cleared.clearance.cleared,
                notes_missing=cleared.clearance.missing,
            ),
        )
