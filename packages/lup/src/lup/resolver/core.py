"""One provider-neutral, persisted resolver state machine."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.harness.contracts import SkillInvocationRenderer
from lup.harness.models import ResolveSpec
from lup.harness.process import LaunchRequest, ProcessLauncher
from lup.resolver.contracts import (
    ResolverAwaitingAnswers,
    ResolverObserver,
    WorktreePreparer,
)
from lup.resolver.dag import ConcernGraph
from lup.resolver.mailbox import (
    ANSWER_POLL_SECONDS,
    PendingQuestion,
    QuestionMailbox,
    RecordedAnswer,
    utc_now,
    wait_for_answers,
)
from lup.resolver.models import (
    ACCEPT,
    ACCEPTANCE_CONCERN_ID,
    AgentRound,
    AnswerBatch,
    CleanupRecord,
    acceptance_question,
    Concern,
    ConcernEligibility,
    ConcernInventory,
    ConcernProgress,
    ConcernStatus,
    ConcernExecution,
    ConcernOutcome,
    DependencyBase,
    FinalReview,
    IntegrationRecord,
    MaterialQuestion,
    MergeReport,
    QuestionAnswer,
    QuestionBatch,
    ResolveInventory,
    ResolveManifest,
    ResolvePhase,
    ResolveRequest,
    ReviewNote,
    ResolverConfig,
    ResolveState,
    ReviewReport,
    VerificationRecord,
    WorkAssignment,
    WorkerContext,
    WorkerReport,
    WritableRootLease,
)
from lup.resolver.orchestrator import (
    DependencyBaseBuilder,
    WorktreeOrchestrator,
    WritableRootLeases,
)
from lup.resolver.state import PHASE_ORDER, ResolverStateRepository
from lup.resolver.tools import WAIT_CONTRACT
from lup.runtime.contracts import SessionFactory
from lup.runtime.models import TurnInput, turn_request
from lup.runtime.query import query
from lup.runtime.wrappers import CorrectionConfig, DecoratingSessionFactory


class ResolverInvariantError(RuntimeError):
    """A native result or persisted transition violated resolver semantics."""


type WorkerFactoryRecipe = Callable[[WorkerContext], SessionFactory]
type ReviewerFactoryRecipe = Callable[[Path], SessionFactory]
type ResolverInput = ResolveRequest | ResolveInventory


def corrective[T](
    recipe: Callable[[T], SessionFactory],
) -> Callable[[T], SessionFactory]:
    """Give each opened session corrective structured-output reprompts.

    Every resolver turn ends in a typed submission; a model that answers in
    prose instead of calling the submission tool would otherwise fail the
    whole run on its first miss.
    """

    def factory(argument: T) -> SessionFactory:
        return DecoratingSessionFactory(
            recipe(argument), correction=CorrectionConfig(cycles=2)
        )

    return factory


APPROVE = "approve"
DEFER = "defer"

ASK_PREAMBLE = (
    "When a decision is not yours to make, ask through the resolver's question "
    "tools — queue_questions, await_answers, ask_questions — rather than "
    "guessing or ending your turn to report it. " + WAIT_CONTRACT
)


class ApprovalDecisions(BaseModel):
    """Persisted direct choices and their dependency-safe eligible subset."""

    model_config = ConfigDict(frozen=True)

    directly_approved: list[str]
    eligible: list[str]


def resolver_config_digest(config: ResolverConfig) -> str:
    """Bind resumed state to the exact injected resolver composition inputs."""
    encoded = config.model_dump_json().encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def failure_messages(error: BaseException) -> list[str]:
    """Flatten parallel failures so no sibling evidence is discarded."""
    if isinstance(error, BaseExceptionGroup):
        return [
            message
            for nested in error.exceptions
            for message in failure_messages(nested)
        ]
    return [str(error)]


INVENTORY_PLAN_ATTEMPTS = 3


def coverage_complaint(referenced: list[int], total: int) -> str | None:
    """Name the notes a plan ignored and the evidence it invented.

    A note is not a unit of work: one can raise several concerns and several
    can raise one, so concerns reference notes rather than partitioning them.
    What still cannot happen is a note no concern claims, because that note
    goes unresolved with nothing to show for it.
    """
    faults = [
        ("no concern references", [i for i in range(total) if i not in referenced]),
        ("outside the evidence", [i for i in referenced if i not in range(total)]),
    ]
    named = [f"{label}: {sorted(indexes)}" for label, indexes in faults if indexes]
    return "; ".join(named) if named else None


def merge_parked(parked: list[ResolverAwaitingAnswers]) -> ResolverAwaitingAnswers:
    """Combine sibling parks so one rerun can answer every pending question."""
    pending = {question.id: question for park in parked for question in park.pending}
    problems = [problem for park in parked for problem in park.problems]
    return ResolverAwaitingAnswers(list(pending.values()), problems)


def approval_question(concern: Concern) -> MaterialQuestion:
    """Build the persisted human integration gate for one planned concern.

    A concern's declared allowances are named in the prompt rather than asked
    separately: approving the concern is approving the edit gates its own
    plan requires, decided once with the title and spec in view.
    """
    grants = "".join(f"\nGrants: {allowance}" for allowance in concern.allowances)
    return MaterialQuestion(
        id=f"integration-approval-{concern.id}",
        concern_id=concern.id,
        prompt=f"Include {concern.title!r} in this resolver run?{grants}",
        choices=[APPROVE, DEFER],
        recommendation=APPROVE,
        closed_choices=True,
    )


def approval_decisions(
    concerns: list[Concern], answers: AnswerBatch
) -> ApprovalDecisions:
    """Return direct and dependency-safe approvals from persisted answers."""
    answer_values = {answer.question_id: answer.value for answer in answers.answers}
    gated = [
        concern
        for concern in concerns
        if concern.eligible and concern.integration_approved
    ]
    missing = [
        concern.id
        for concern in gated
        if approval_question(concern).id not in answer_values
    ]
    if missing:
        raise ResolverInvariantError(
            "no persisted approval answer for " + ", ".join(sorted(missing))
        )
    direct = {
        concern.id
        for concern in gated
        if answer_values[approval_question(concern).id] == APPROVE
    }
    approved = ConcernGraph(concerns).transitively_approved(direct)
    return ApprovalDecisions(
        directly_approved=[concern.id for concern in concerns if concern.id in direct],
        eligible=[concern.id for concern in approved],
    )


class ResolverCore:
    """Own all resolver phases while composing only portable capabilities."""

    def __init__(
        self,
        config: ResolverConfig,
        spec: ResolveSpec,
        worker_factory: WorkerFactoryRecipe,
        reviewer_factory: ReviewerFactoryRecipe,
        invocation_renderer: SkillInvocationRenderer,
        process_launcher: ProcessLauncher,
        observer: ResolverObserver | None = None,
        worktree_preparer: WorktreePreparer | None = None,
        answer_wait_seconds: float = 0.0,
        poll_interval_seconds: float = ANSWER_POLL_SECONDS,
    ) -> None:
        self.config = config
        self.spec = spec
        self.worker_factory = corrective(worker_factory)
        self.reviewer_factory = corrective(reviewer_factory)
        self.invocation_renderer = invocation_renderer
        self.process_launcher = process_launcher
        self.answer_wait_seconds = answer_wait_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.observer = observer
        self.repository = ResolverStateRepository(config.state_root, config.run_id)
        self.leases = WritableRootLeases(config.worktree_root)
        self.worktrees = WorktreeOrchestrator(
            process_launcher, config.workspace, worktree_preparer
        )
        self.mailbox = QuestionMailbox(self.repository.root)
        self.wake = asyncio.Event()
        self.state_lock = asyncio.Lock()
        self.state: ResolveState | None = None

    async def run(self, source: ResolverInput) -> ResolveManifest:
        """Run through final review and stop at the human acceptance boundary."""
        with self.repository.exclusive():
            inventory = (
                await self.plan_inventory(source)
                if isinstance(source, ResolveRequest)
                else source
            )
            return await self.run_exclusive(inventory)

    async def plan_inventory(self, request: ResolveRequest) -> ResolveInventory:
        """Organize raw review evidence into concerns in a read-only turn.

        A rejected partition is fed back to the planner by name rather than
        ending the run: intake is the point where the least work is persisted
        and the most would be lost.
        """
        prompt = (
            "Organize every review note into generalized implementation concerns "
            "without editing. Cluster by underlying issue, not file. Reference "
            "notes through note_indexes using each note's zero-based position in "
            "the evidence below. A note is not a unit of work: split one that "
            "raises several issues across several concerns, and reference it "
            "from each. Every index must appear at least once; none may repeat "
            "within a single concern. Give each concern path-safe id, complete acceptance "
            "criteria, dependencies, material questions, and starting files. Declare "
            "an allowance only when the plan cannot be carried out without the gate "
            "it names, so approving the concern approves what it actually needs. Do "
            "not decide eligibility or integration approval; the resolver asks the "
            "user."
            f"\n\nReview evidence:\n{request.model_dump_json(indent=2)}"
        )
        correction = ""
        complaint: str | None = None
        for _ in range(INVENTORY_PLAN_ATTEMPTS):
            result = await query(
                self.reviewer_factory(self.config.workspace),
                turn_request(TurnInput(text=prompt + correction), ConcernInventory),
            )
            referenced = [
                index
                for planned in result.output.concerns
                for index in planned.note_indexes
            ]
            complaint = coverage_complaint(referenced, len(request.notes))
            if complaint is None:
                break
            correction = (
                f"\n\nA previous attempt left review evidence unaccounted for — "
                f"{complaint}. Every index from 0 to {len(request.notes) - 1} must "
                "be referenced by at least one concern."
            )
        else:
            raise ResolverInvariantError(
                "inventory planner left review notes unaccounted for across "
                f"{INVENTORY_PLAN_ATTEMPTS} attempts — {complaint}"
            )
        concerns = [
            Concern(
                notes=[
                    ReviewNote.model_validate(
                        request.notes[index].model_dump(exclude={"context"})
                    )
                    for index in planned.note_indexes
                ],
                eligible=True,
                integration_approved=True,
                **planned.model_dump(exclude={"note_indexes"}),
            )
            for planned in result.output.concerns
        ]
        return ResolveInventory(source=request.source, concerns=concerns)

    async def run_exclusive(self, inventory: ResolveInventory) -> ResolveManifest:
        """Execute a new run while the repository owns its process lease."""
        if self.repository.exists():
            raise ResolverInvariantError(
                f"resolver run {self.config.run_id!r} already exists; resume it explicitly"
            )
        state = ResolveState(
            run_id=self.config.run_id,
            config_digest=resolver_config_digest(self.config),
            phase=ResolvePhase.INVENTORY,
            source=inventory.source,
            spec=self.spec,
            concerns=inventory.concerns,
            progress=[
                ConcernProgress(concern_id=concern.id) for concern in inventory.concerns
            ],
        )
        self.persist(state)
        try:
            return await self.advance(state)
        except ResolverAwaitingAnswers:
            raise
        except Exception as error:
            self.persist_failure(error)
            raise

    async def resume(self) -> ResolveManifest:
        """Resume a persisted run without redoing completed concern outcomes."""
        with self.repository.exclusive():
            return await self.resume_exclusive()

    async def resume_exclusive(self) -> ResolveManifest:
        """Resume while holding the run's inter-process lease."""
        if not self.repository.exists():
            raise ResolverInvariantError(
                f"resolver run {self.config.run_id!r} does not exist"
            )
        state = self.repository.load()
        self.state = state
        if (
            state.run_id != self.config.run_id
            or state.spec != self.spec
            or state.config_digest != resolver_config_digest(self.config)
        ):
            raise ResolverInvariantError(
                "persisted resolver identity or specification does not match"
            )
        if state.phase == ResolvePhase.ABORTED:
            raise ResolverInvariantError(
                f"resolver run {state.run_id!r} was aborted: {state.abort_reason}"
            )
        if state.phase == ResolvePhase.COMPLETE:
            self.state = state
            return self.manifest(state)
        if state.phase == ResolvePhase.ACCEPTANCE:
            self.state = state
            async with self.promoting():
                return self.manifest(await self.settle_acceptance())
        if state.phase == ResolvePhase.FAILED:
            if state.resume_from is None:
                raise ResolverInvariantError(
                    "failed resolver state has no resume phase"
                )
            state = state.model_copy(
                update={"phase": state.resume_from, "resume_from": None}
            )
            self.persist(state)
        self.restore_leases(state)
        state = self.require_state()
        try:
            return await self.advance(state)
        except ResolverAwaitingAnswers:
            raise
        except Exception as error:
            self.persist_failure(error)
            raise

    async def advance(self, state: ResolveState) -> ResolveManifest:
        """Advance an initial or restored state through the acceptance boundary.

        A stale park marker would abort the first wait of a resumed run, so
        it is the one mailbox record a resume clears.
        """
        async with self.promoting():
            return await self.advance_exclusive(state)

    @asynccontextmanager
    async def promoting(self) -> AsyncGenerator[None]:
        """Keep every door's offers promoted for the lifetime of one operation.

        Waiting reads ``answers/``, and only a promoter writes there, so any
        wait that runs without this is a wait no door can satisfy.
        """
        self.mailbox.clear_park()
        stop = asyncio.Event()
        promoter = asyncio.create_task(self.promote_until(stop))
        try:
            yield
        finally:
            stop.set()
            await promoter

    async def advance_exclusive(self, state: ResolveState) -> ResolveManifest:
        """Advance while a promoter is folding every door's answers in."""
        if state.questions is None:
            initial_questions = QuestionBatch(
                run_id=state.run_id,
                questions=[
                    question
                    for concern in state.concerns
                    for question in concern.questions
                ]
                + [
                    approval_question(concern)
                    for concern in state.concerns
                    if concern.eligible and concern.integration_approved
                ],
            )
            self.queue_questions(initial_questions.questions, "planning")
            state = state.model_copy(
                update={
                    "phase": ResolvePhase.QUESTIONS,
                    "questions": initial_questions,
                }
            )
            state = self.progress_state(
                state,
                [
                    concern.id
                    for concern in state.concerns
                    if concern.questions
                    or (concern.eligible and concern.integration_approved)
                ],
                ConcernStatus.WAITING_FOR_ANSWERS,
            )
            self.persist(state)
        questions = state.questions
        if questions is None:
            raise ResolverInvariantError("question phase has no persisted batch")
        await self.await_questions(questions.questions)
        state = self.require_state()

        answers = state.answers
        if answers is None:
            raise ResolverInvariantError("eligibility requires persisted answers")
        decisions = approval_decisions(state.concerns, answers)
        decision_ids = decisions.directly_approved
        approved_ids = decisions.eligible
        graph = ConcernGraph(state.concerns)
        approved = [concern for concern in state.concerns if concern.id in approved_ids]
        if not state.eligibility:
            eligibility = [
                ConcernEligibility(
                    concern_id=concern.id,
                    eligible=concern.id in approved_ids,
                    integration_approved=concern.id in decision_ids,
                    reason=(
                        "ready"
                        if concern.id in approved_ids
                        else (
                            "an ancestor is deferred or not approved"
                            if concern.id in decision_ids
                            else "deferred or not approved"
                        )
                    ),
                )
                for concern in state.concerns
            ]
            state = state.model_copy(
                update={
                    "phase": ResolvePhase.ELIGIBILITY,
                    "eligibility": eligibility,
                }
            )
            state = self.progress_state(
                state,
                [item.concern_id for item in eligibility if item.eligible],
                ConcernStatus.ELIGIBLE,
            )
            state = self.progress_state(
                state,
                [item.concern_id for item in eligibility if not item.eligible],
                ConcernStatus.INELIGIBLE,
                "deferred, unapproved, or blocked by an ancestor",
            )
            self.persist(state)

        if state.phase in {
            ResolvePhase.INVENTORY,
            ResolvePhase.QUESTIONS,
            ResolvePhase.ELIGIBILITY,
        }:
            state = state.model_copy(update={"phase": ResolvePhase.DAG})
            self.persist(state)

        lease_by_concern = {
            lease.concern_id: lease
            for lease in state.leases
            if lease.concern_id != "integration"
        }
        if not lease_by_concern:
            for concern in approved:
                branch = f"resolve/{self.config.run_id}/{concern.id}"
                lease_by_concern[concern.id] = self.leases.acquire(concern.id, branch)
            state = state.model_copy(
                update={
                    "phase": ResolvePhase.LEASES,
                    "leases": list(lease_by_concern.values()),
                }
            )
            state = self.progress_state(
                state,
                [concern.id for concern in approved],
                ConcernStatus.LEASED,
            )
            self.persist(state)
        if state.phase in {ResolvePhase.DAG, ResolvePhase.LEASES}:
            state = state.model_copy(update={"phase": ResolvePhase.WORKERS})
            self.persist(state)

        commits = {
            outcome.concern_id: outcome.commit
            for outcome in state.outcomes
            if outcome.verified and outcome.commit is not None
        }
        outcomes = list(state.outcomes)
        completed_ids = {outcome.concern_id for outcome in outcomes}
        builder = DependencyBaseBuilder(state.source)
        if state.integration is None:
            for batch in graph.topological_batches():
                selected = [
                    item
                    for item in batch
                    if item.id in approved_ids and item.id not in completed_ids
                ]
                runnable = [
                    concern
                    for concern in selected
                    if all(parent in commits for parent in concern.dependencies)
                ]
                for blocked in selected:
                    if blocked in runnable:
                        continue
                    outcomes.append(
                        ConcernOutcome(
                            concern_id=blocked.id,
                            branch=lease_by_concern[blocked.id].branch,
                            failure="a dependency did not produce a verified commit",
                        )
                    )
                    completed_ids.add(blocked.id)
                results = await asyncio.gather(
                    *[
                        self.execute_concern(
                            concern,
                            lease_by_concern[concern.id],
                            commits,
                            builder,
                        )
                        for concern in runnable
                    ],
                    return_exceptions=True,
                )
                executions = [
                    result for result in results if isinstance(result, ConcernExecution)
                ]
                failures = [
                    result for result in results if isinstance(result, BaseException)
                ]
                for execution in executions:
                    outcomes.append(execution.outcome)
                    if (
                        execution.outcome.verified
                        and execution.outcome.commit is not None
                    ):
                        commits[execution.outcome.concern_id] = execution.outcome.commit
                    completed_ids.add(execution.outcome.concern_id)
                state = self.require_state()
                bases = list(state.bases)
                state = state.model_copy(
                    update={
                        "phase": ResolvePhase.WORKERS,
                        "bases": bases,
                        "outcomes": outcomes,
                    }
                )
                state = self.progress_state(
                    state,
                    [blocked.id for blocked in selected if blocked not in runnable],
                    ConcernStatus.FAILED,
                    "a dependency did not produce a verified commit",
                )
                self.persist(state)
                self.repository.write_agent_round(state)
                if failures:
                    errors = [
                        failure
                        for failure in failures
                        if isinstance(failure, Exception)
                    ]
                    if len(errors) != len(failures):
                        raise ResolverInvariantError(
                            "parallel concern execution was cancelled"
                        )
                    parked = [
                        error
                        for error in errors
                        if isinstance(error, ResolverAwaitingAnswers)
                    ]
                    if parked and len(parked) == len(errors):
                        raise merge_parked(parked)
                    raise ExceptionGroup("parallel concern failures", errors)

            state = self.require_state()
            state = state.model_copy(update={"phase": ResolvePhase.DEPENDENCY_BASES})
            self.persist(state)
            state = state.model_copy(update={"phase": ResolvePhase.REVIEW})
            self.persist(state)
            state = await self.integrate(state, outcomes)
        elif state.final_review is None:
            state = await self.integrate(state, outcomes)
        if state.phase is ResolvePhase.ACCEPTANCE and state.accepted is None:
            state = await self.settle_acceptance()
        return self.manifest(state)

    def restore_leases(self, state: ResolveState) -> None:
        """Validate persisted authority and reset incomplete attempts for retry."""
        self.leases.leases = {
            lease.concern_id: lease for lease in state.leases if lease.active
        }
        outcomes = {outcome.concern_id: outcome for outcome in state.outcomes}
        bases = {base.concern_id: base for base in state.bases}
        concerns = {concern.id: concern for concern in state.concerns}
        commits = {
            outcome.concern_id: outcome.commit
            for outcome in state.outcomes
            if outcome.verified and outcome.commit is not None
        }
        for lease in self.leases.leases.values():
            if lease.concern_id == "integration":
                if (
                    state.integration is not None
                    and state.integration.commit is not None
                ):
                    recorded = True
                    expected = state.integration.commit
                else:
                    # Joins already committed are progress, not a failed
                    # attempt. `reset` exists to discard an uncommitted attempt,
                    # and resetting to the worktree's own HEAD does exactly
                    # that: a half-finished merge and its index go, every
                    # completed join stays. Naming the source commit here
                    # discarded all of them on every resume, so a run that
                    # parked mid-integration replayed every join and re-derived
                    # the same questions under fresh ids.
                    recorded = False
                    expected = (
                        self.worktrees.head(lease)
                        if lease.root.exists()
                        else state.source.commit
                    )
                self.restore_worktree(lease, expected, recorded)
                continue
            outcome = (
                outcomes[lease.concern_id] if lease.concern_id in outcomes else None
            )
            base = bases[lease.concern_id] if lease.concern_id in bases else None
            if base is not None:
                expected = base.commit
            else:
                concern = concerns[lease.concern_id]
                parent_commits = [
                    commits[parent]
                    for parent in concern.dependencies
                    if parent in commits
                ]
                expected = parent_commits[0] if parent_commits else state.source.commit
            if outcome is not None:
                self.restore_worktree(lease, outcome.commit or expected, True)
                continue
            if not lease.root.exists() and not self.worktrees.branch_exists(lease):
                self.restore_concern_progress(lease.concern_id)
                continue
            self.restore_worktree(lease, expected, False)
            self.restore_concern_progress(lease.concern_id)

    def restore_worktree(
        self, lease: WritableRootLease, expected: str, terminal: bool
    ) -> None:
        """Restore one persisted branch and validate or reset its exact commit."""
        if not lease.root.exists():
            if self.worktrees.branch_exists(lease):
                self.worktrees.restore(lease)
            else:
                self.worktrees.create(lease, expected)
        self.worktrees.branch(lease)
        if terminal:
            if self.worktrees.head(lease) != expected:
                raise ResolverInvariantError(
                    f"persisted commit changed for {lease.concern_id}"
                )
            return
        # A merge left open is not an abandoned attempt: it is the join a turn
        # was resolving when the run parked to ask about it, and the resolution
        # lives in the working tree the reset would wipe. Preparing the same
        # join is idempotent, so leaving this alone is what lets an answered
        # question resume the work it interrupted rather than recreate the
        # conflict it was asked about.
        if self.worktrees.merging(lease) is not None:
            return
        self.worktrees.reset(lease, expected)

    def restore_concern_progress(self, concern_id: str) -> None:
        """Return one interrupted concern to its leased retry boundary."""
        state = self.require_state()
        current = next(
            item.status for item in state.progress if item.concern_id == concern_id
        )
        if current == ConcernStatus.LEASED:
            return
        if current != ConcernStatus.ELIGIBLE:
            state = self.progress_state(
                state, [concern_id], ConcernStatus.ELIGIBLE, "retry after interruption"
            )
            self.persist(state)
        state = self.progress_state(
            state, [concern_id], ConcernStatus.LEASED, "retry lease restored"
        )
        self.persist(state)

    def persist_failure(self, error: Exception) -> None:
        """Persist both the failure and the exact phase from which to resume."""
        state = self.require_state()
        resume_from = (
            state.resume_from if state.phase == ResolvePhase.FAILED else state.phase
        )
        self.persist(
            state.model_copy(
                update={
                    "phase": ResolvePhase.FAILED,
                    "resume_from": resume_from,
                    "failures": [*state.failures, *failure_messages(error)],
                }
            )
        )

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
            await self.transition_concern(
                concern.id,
                ConcernStatus.WAITING_FOR_ANSWERS,
                "parked on material questions",
            )
            raise
        except Exception as error:
            await self.transition_concern(concern.id, ConcernStatus.FAILED, str(error))
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
            joined = await self.join_commits(
                lease,
                parent_commits,
                f"dependency base for {concern.id}",
                f"resolve: join dependencies for {concern.title}",
            )
            base = builder.build(concern, commits, joined_commit=joined)
            await self.record_dependency_base(base)
        else:
            base = builder.build(concern, commits)
            await self.record_dependency_base(base)
            if not lease.root.exists():
                self.worktrees.create(lease, base.commit)

        cleared = self.worktrees.clear_notes(lease, concern, base.commit)
        answers = self.answers_for(concern.id)
        assignment = WorkAssignment(
            run_id=self.config.run_id,
            concern=concern,
            lease=lease,
            dependency_base=base,
            rendered_skill_invocation=self.invocation_renderer.render(
                self.spec.worker_skill
            ),
            answers=answers,
        )
        rounds: list[AgentRound] = []  # lup: ignore[empty-collection]
        current_base = cleared.commit
        feedback = ""
        maximum_round = self.config.max_revision_rounds + 1
        for round_number in range(1, maximum_round + 1):
            await self.transition_concern(concern.id, ConcernStatus.RUNNING)
            worker = await self.worker_turn(assignment, feedback)
            outstanding = await self.unanswered_for(concern.id)
            if outstanding:
                raise ResolverAwaitingAnswers(outstanding, [])
            await self.transition_concern(concern.id, ConcernStatus.VALIDATING)
            diff = self.worktrees.validate_and_commit(
                concern, worker, lease, current_base, self.leases
            )
            if not diff.valid or diff.commit is None:
                review = ReviewReport(
                    concern_id=concern.id,
                    accepted=False,
                    generalized=False,
                    reason=diff.reason,
                )
            else:
                await self.transition_concern(concern.id, ConcernStatus.REVIEWING)
                review = await self.review_turn(
                    concern, worker, diff.commit, lease.root
                )
                expected_criteria = {criterion.id for criterion in concern.criteria}
                if (
                    review.accepted
                    and set(  # lup: ignore[set-shape] — identity comparison
                        review.criteria_met
                    )
                    != expected_criteria
                ):
                    review = review.model_copy(
                        update={
                            "accepted": False,
                            "reason": "review omitted persisted acceptance criteria",
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
            if diff.commit is not None:
                current_base = diff.commit
            if review.accepted and diff.commit is not None:
                await self.transition_concern(concern.id, ConcernStatus.VERIFIED)
                return ConcernExecution(
                    base=base,
                    outcome=ConcernOutcome(
                        concern_id=concern.id,
                        branch=lease.branch,
                        commit=diff.commit,
                        verified=True,
                        rounds=rounds,
                        notes_cleared=cleared.clearance.cleared,
                        notes_missing=cleared.clearance.missing,
                    ),
                )
            await self.transition_concern(
                concern.id, ConcernStatus.REVISING, review.reason
            )
            feedback = review.reason + "\n" + "\n".join(review.residual)
        await self.transition_concern(
            concern.id, ConcernStatus.FAILED, "revision limit exhausted"
        )
        return ConcernExecution(
            base=base,
            outcome=ConcernOutcome(
                concern_id=concern.id,
                branch=lease.branch,
                commit=rounds[-1].diff.commit if rounds else None,
                verified=False,
                rounds=rounds,
                failure="revision limit exhausted",
                notes_cleared=cleared.clearance.cleared,
                notes_missing=cleared.clearance.missing,
            ),
        )

    async def worker_turn(
        self, assignment: WorkAssignment, feedback: str
    ) -> WorkerReport:
        prompt = (
            "Execute the portable worker skill below. You may edit only the assigned "
            "writable root. Do not create branches or commits; the orchestrator owns "
            "that authority. Resolve every acceptance criterion. Your concern's "
            "review-note markers are already gone from this worktree — the "
            "orchestrator removed them before you started, so the spec is the whole "
            "of the feedback. Do not re-introduce a marker, and do not leave an "
            "explanatory comment where one stood. Every `# lup:` marker still "
            "present belongs to another concern or is parked work behind a wake "
            "condition: leave it in place. If resolving your concern means deleting "
            "or moving code that carries one, do so and name it in your summary.\n\n"
            f"{ASK_PREAMBLE}\n\n"
            f"{assignment.rendered_skill_invocation}\n\n"
            f"Assignment:\n{assignment.model_dump_json(indent=2)}"
        )
        if feedback:
            prompt += f"\n\nPersisted review feedback:\n{feedback}"
        result = await query(
            self.worker_factory(
                WorkerContext(
                    root=assignment.lease.root,
                    concern_id=assignment.concern.id,
                    allowances=assignment.concern.allowances,
                )
            ),
            turn_request(TurnInput(text=prompt), WorkerReport),
        )
        if result.output.concern_id != assignment.concern.id:
            raise ResolverInvariantError("worker returned a foreign concern id")
        return result.output

    async def join_commits(
        self,
        lease: WritableRootLease,
        commits: list[str],
        purpose: str,
        title: str,
    ) -> str:
        """Join parents one at a time so every conflict reaches semantic review."""
        if len(commits) < 2:
            raise ValueError("a semantic join requires at least two commits")
        if not lease.root.exists():
            self.worktrees.create(lease, commits[0])
        current = self.worktrees.head(lease)
        for parent in commits[1:]:
            # The loop carries no resumption point, so a resumed join re-enters
            # at the first parent. One already contained in HEAD has nothing to
            # merge, and a merge turn spent on it is not free: the session
            # cannot tell "already joined" from "something upstream is wrong",
            # so it reasonably asks rather than reporting success, and every
            # such round costs a question and a resume. Skip what is already in.
            if self.worktrees.already_joined(lease, parent):
                continue
            self.worktrees.prepare_join(lease, [current, parent])
            merge = await self.merge_turn(
                lease,
                [current, parent],
                self.invocation_renderer.render(self.spec.merge_skill),
                purpose,
            )
            if not merge.completed or merge.unresolved_paths:
                raise ResolverInvariantError(
                    f"semantic join failed for {lease.concern_id}: {merge.summary}"
                )
            current = self.worktrees.commit_join(lease, title)
        return current

    async def review_turn(
        self, concern: Concern, worker: WorkerReport, commit: str, worktree: Path
    ) -> ReviewReport:
        invocation = self.invocation_renderer.render(self.spec.review_skill)
        prompt = (
            "Independently review the committed concern against every persisted "
            "acceptance criterion.\n\n"
            f"{invocation}\n\nConcern:\n{concern.model_dump_json(indent=2)}\n\n"
            f"Worker report:\n{worker.model_dump_json(indent=2)}\n\n"
            f"Commit: {commit}"
        )
        result = await query(
            self.reviewer_factory(worktree),
            turn_request(TurnInput(text=prompt), ReviewReport),
        )
        if result.output.concern_id != concern.id:
            raise ResolverInvariantError("reviewer returned a foreign concern id")
        return result.output

    async def merge_turn(
        self,
        lease: WritableRootLease,
        commits: list[str],
        invocation: str,
        purpose: str,
    ) -> MergeReport:
        prompt = (
            "Resolve the prepared semantic merge in the assigned worktree. Stage "
            "every resolution with `git add` — settling the index is your work "
            "and the merge cannot complete without it. Do not commit and do not "
            "change branches; the orchestrator owns commit authority, which "
            "covers committing only.\n\n"
            f"{invocation}\n\nPurpose: {purpose}\nWorktree: {lease.root}\n"
            f"Parent commits:\n" + "\n".join(commits)
        )
        result = await query(
            self.worker_factory(
                WorkerContext(root=lease.root, concern_id=lease.concern_id)
            ),
            turn_request(TurnInput(text=prompt), MergeReport),
        )
        return result.output

    async def unanswered_for(self, concern_id: str) -> list[MaterialQuestion]:
        """Questions this concern asked that no door has answered yet.

        A worker asks through its tools and waits there, so reaching this
        point with anything outstanding means the tool returned ``parked``
        and the worker submitted rather than guessing. Reading the mailbox
        is what turns that into the run's existing park.
        """
        await self.apply_mailbox()
        answered = self.mailbox.answered_ids()
        return [
            item.question
            for item in self.mailbox.questions()
            if item.question.concern_id == concern_id
            and item.question.id not in answered
        ]

    def queue_questions(self, questions: list[MaterialQuestion], asked_by: str) -> None:
        """Publish questions so any door can answer them."""
        for question in questions:
            self.mailbox.queue(
                PendingQuestion(
                    run_id=self.config.run_id,
                    question=question,
                    asked_by=asked_by,
                    asked_at=utc_now(),
                )
            )

    def promote_offers(self) -> list[str]:
        """Promote what the doors offered, and report what could not count.

        This is the only writer of recorded answers. A design question's
        choices are the planner's suggestions, so an answer in the human's own
        words is recorded as given; only the reserved integration gates close
        their domain, and an offer outside one is a correctable problem rather
        than a fatal one — a door is a form, not a trusted caller.
        """
        questions = {
            item.question.id: item.question for item in self.mailbox.questions()
        }
        answered = self.mailbox.answered_ids()
        fresh = [
            offer
            for offer in sorted(self.mailbox.offers(), key=lambda item: item.offered_at)
            if offer.question_id in questions and offer.question_id not in answered
        ]
        valid = [
            offer
            for offer in fresh
            if not questions[offer.question_id].closed_choices
            or offer.value in questions[offer.question_id].choices
        ]
        for offer in valid:
            self.mailbox.record(
                RecordedAnswer(
                    run_id=self.config.run_id,
                    answer=QuestionAnswer(
                        question_id=offer.question_id, value=offer.value
                    ),
                    door=offer.door,
                    answered_at=utc_now(),
                )
            )
        return [
            f"{offer.question_id} was answered {offer.value!r}, but that gate "
            "accepts only: " + ", ".join(questions[offer.question_id].choices)
            for offer in fresh
            if offer not in valid
        ]

    async def apply_mailbox(self) -> list[str]:
        """Promote the doors' offers and fold the mailbox into persisted state."""
        problems = self.promote_offers()
        async with self.state_lock:
            state = self.require_state()
            questions = QuestionBatch(
                run_id=state.run_id,
                questions=[item.question for item in self.mailbox.questions()],
            )
            answers = AnswerBatch(
                run_id=state.run_id,
                answers=[record.answer for record in self.mailbox.answers()],
            )
            if state.questions != questions or state.answers != answers:
                self.persist(
                    state.model_copy(
                        update={"questions": questions, "answers": answers}
                    )
                )
        self.wake.set()
        return problems

    async def promote_until(self, stop: asyncio.Event) -> None:
        """Keep promoting for the lifetime of one advance."""
        while not stop.is_set():
            await self.apply_mailbox()
            try:
                async with asyncio.timeout(self.poll_interval_seconds):
                    await stop.wait()
            except TimeoutError:
                continue
        await self.apply_mailbox()

    async def await_questions(self, questions: list[MaterialQuestion]) -> AnswerBatch:
        """Wait for every named question, or park the run on what is missing."""
        if not questions:
            return AnswerBatch(run_id=self.config.run_id, answers=[])
        await self.apply_mailbox()
        result = await wait_for_answers(
            self.mailbox,
            [question.id for question in questions],
            wait_seconds=self.answer_wait_seconds,
            poll_interval_seconds=self.poll_interval_seconds,
            wake=self.wake,
        )
        problems = await self.apply_mailbox()
        if result.unanswered:
            raise ResolverAwaitingAnswers(
                [
                    question
                    for question in questions
                    if question.id in result.unanswered
                ],
                problems,
            )
        return AnswerBatch(
            run_id=self.config.run_id,
            answers=[record.answer for record in result.answered],
        )

    def answers_for(self, concern_id: str) -> list[QuestionAnswer]:
        state = self.require_state()
        question_ids = {
            question.id
            for question in (state.questions.questions if state.questions else [])
            if question.concern_id == concern_id
        }
        return [
            answer
            for answer in (state.answers.answers if state.answers else [])
            if answer.question_id in question_ids
        ]

    async def integrate(
        self, state: ResolveState, outcomes: list[ConcernOutcome]
    ) -> ResolveState:
        if state.integration is None:
            verified = [outcome for outcome in outcomes if outcome.verified]
            integration_lease = next(
                (lease for lease in state.leases if lease.concern_id == "integration"),
                None,
            )
            if integration_lease is None:
                integration_lease = self.leases.acquire(
                    "integration", self.config.integration_branch
                )
                leases = [*state.leases, integration_lease]
            else:
                leases = state.leases
            state = state.model_copy(
                update={"phase": ResolvePhase.INTEGRATION, "leases": leases}
            )
            state = self.progress_state(
                state,
                [outcome.concern_id for outcome in verified],
                ConcernStatus.INTEGRATING,
            )
            self.persist(state)
            if not integration_lease.root.exists():
                self.worktrees.create(integration_lease, state.source.commit)
            commits = [
                outcome.commit for outcome in verified if outcome.commit is not None
            ]
            if commits:
                parents = [state.source.commit, *commits]
                integration_commit = await self.join_commits(
                    integration_lease,
                    parents,
                    "final review-master integration",
                    "resolve: integrate approved concerns",
                )
            else:
                integration_commit = self.worktrees.head(integration_lease)
            integrated_ids = {outcome.concern_id for outcome in verified}
            integration = IntegrationRecord(
                branch=integration_lease.branch,
                worktree=integration_lease.root,
                concerns=sorted(integrated_ids),
                commit=integration_commit,
                completed=False,
            )
            state = state.model_copy(
                update={
                    "integration": integration,
                }
            )
            self.persist(state)
        else:
            integration = state.integration
            try:
                integration_lease = next(
                    lease for lease in state.leases if lease.concern_id == "integration"
                )
            except StopIteration as error:
                raise ResolverInvariantError(
                    "persisted integration has no writable-root lease"
                ) from error

        if not integration.completed:
            verification: list[VerificationRecord] = []  # lup: ignore[empty-collection]
            for command in self.config.verification_commands:
                status = self.process_launcher.launch(
                    LaunchRequest(
                        arguments=command.arguments,
                        cwd=integration_lease.root,
                    )
                )
                verification.append(
                    VerificationRecord(
                        name=command.name,
                        arguments=command.arguments,
                        passed=status.code == 0,
                        exit_code=status.code,
                    )
                )
            state = state.model_copy(
                update={
                    "phase": ResolvePhase.VERIFICATION,
                    "verification": verification,
                }
            )
            self.persist(state)
            failed = [record.name for record in verification if not record.passed]
            if failed:
                raise ResolverInvariantError(
                    "integration verification failed: " + ", ".join(failed)
                )
            integrated_ids = {identifier: True for identifier in integration.concerns}
            integration = integration.model_copy(update={"completed": True})
            integrated_outcomes = [
                outcome.model_copy(
                    update={"integrated": outcome.concern_id in integrated_ids}
                )
                for outcome in state.outcomes
            ]
            state = state.model_copy(
                update={
                    "outcomes": integrated_outcomes,
                    "integration": integration,
                }
            )
            state = self.progress_state(
                state,
                integration.concerns,
                ConcernStatus.INTEGRATED,
            )
            self.persist(state)
        else:
            verification = state.verification

        if any(not record.passed for record in verification):
            raise ResolverInvariantError("persisted integration verification failed")

        review_prompt = (
            "Perform an independent final review of the dedicated review branch. "
            "The user's source branch must remain untouched.\n\n"
            f"{self.invocation_renderer.render(self.spec.review_skill)}\n\n"
            f"Integration:\n{integration.model_dump_json(indent=2)}\n\n"
            f"Verification:\n"
            + "\n".join(record.model_dump_json() for record in verification)
        )
        reviewed = await query(
            self.reviewer_factory(integration.worktree),
            turn_request(TurnInput(text=review_prompt), FinalReview),
        )
        state = state.model_copy(
            update={
                "phase": ResolvePhase.ACCEPTANCE,
                "final_review": reviewed.output,
            }
        )
        self.persist(state)
        return state

    async def settle_acceptance(self) -> ResolveState:
        """Offer the review decision through the mailbox and apply any answer.

        Acceptance is a reserved question, so the page, a CLI door, and
        ``--accept``/``--reject`` are one form rather than three separate
        paths into cleanup. A run whose decision has not arrived returns
        unchanged, exactly as it did before there was a door to answer
        through — the decision is a boundary, not a failure.
        """
        question = acceptance_question()
        self.queue_questions([question], ACCEPTANCE_CONCERN_ID)
        await self.apply_mailbox()
        result = await wait_for_answers(
            self.mailbox,
            [question.id],
            wait_seconds=self.answer_wait_seconds,
            poll_interval_seconds=self.poll_interval_seconds,
            wake=self.wake,
        )
        await self.apply_mailbox()
        if result.unanswered:
            return self.require_state()
        self.record_human_acceptance_exclusive(
            result.answered[0].answer.value == ACCEPT
        )
        return self.require_state()

    def abort(self, reason: str) -> ResolveManifest:
        """End a run from any phase, freeing its leases but keeping its evidence.

        Cleanup was reachable only at acceptance, so a run abandoned while its
        concerns held leases stranded one worktree and one branch each with no
        way back. Aborting frees those the same way acceptance does and retains
        the integration lease, because the review branch may hold real work.
        Concern statuses are left as they stood: what each concern reached is
        the evidence an abort exists to preserve.
        """
        with self.repository.exclusive():
            state = self.repository.load()
            self.state = state
            if state.phase in {ResolvePhase.ABORTED, ResolvePhase.COMPLETE}:
                raise ResolverInvariantError(f"run is already {state.phase}")
            cleanup = [
                CleanupRecord(
                    path=lease.root,
                    branch=lease.branch,
                    action="retained",
                    reason=f"review branch retained after abort: {reason}",
                )
                if lease.concern_id == ACCEPTANCE_CONCERN_ID
                else self.abort_lease(lease)
                for lease in state.leases
            ]
            aborted = state.model_copy(
                update={
                    "phase": ResolvePhase.ABORTED,
                    "abort_reason": reason,
                    "resume_from": None,
                    "cleanup": [*state.cleanup, *cleanup],
                    "leases": [
                        lease.model_copy(update={"active": False})
                        for lease in state.leases
                    ],
                }
            )
            self.persist(aborted)
            return self.manifest(aborted)

    def abort_lease(self, lease: WritableRootLease) -> CleanupRecord:
        """Free one concern lease, reporting a dirty tree instead of forcing it."""
        removed = self.worktrees.remove(lease)
        return CleanupRecord(
            path=lease.root,
            branch=lease.branch,
            action="removed" if removed else "retained",
            reason=(
                "concern worktree freed by abort"
                if removed
                else "worktree holds uncommitted work; remove manually"
            ),
        )

    def record_human_acceptance(self, accepted: bool) -> ResolveManifest:
        """Record cleanup/retention after the human decides on the review branch."""
        with self.repository.exclusive():
            return self.record_human_acceptance_exclusive(accepted)

    def record_human_acceptance_exclusive(self, accepted: bool) -> ResolveManifest:
        """Complete a run while holding its inter-process authority lease."""
        state = self.repository.load()
        self.state = state
        if state.phase != ResolvePhase.ACCEPTANCE:
            raise ResolverInvariantError("run is not awaiting human acceptance")
        cleanup: list[CleanupRecord] = []  # lup: ignore[empty-collection]
        progress = state
        for lease in state.leases:
            if lease.concern_id == "integration":
                cleanup.append(
                    CleanupRecord(
                        path=lease.root,
                        branch=lease.branch,
                        action="retained",
                        reason=(
                            "review branch accepted for manual integration"
                            if accepted
                            else "review branch retained for revision or inspection"
                        ),
                    )
                )
                continue
            removed = self.worktrees.remove(lease)
            progress = self.progress_state(
                progress,
                [lease.concern_id],
                ConcernStatus.CLEANED if removed else ConcernStatus.RETAINED,
            )
            cleanup.append(
                CleanupRecord(
                    path=lease.root,
                    branch=lease.branch,
                    action="removed" if removed else "retained",
                    reason=(
                        "concern worktree cleaned after review"
                        if removed
                        else "automatic cleanup failed; remove manually"
                    ),
                )
            )
        completed = progress.model_copy(
            update={
                "phase": ResolvePhase.CLEANUP,
                "accepted": accepted,
                "cleanup": cleanup,
                "leases": [
                    lease.model_copy(update={"active": False}) for lease in state.leases
                ],
            }
        )
        self.persist(completed)
        completed = completed.model_copy(update={"phase": ResolvePhase.COMPLETE})
        self.persist(completed)
        return self.manifest(completed)

    def persist(self, state: ResolveState) -> None:
        """Persist while keeping the phase a monotonic high-water mark.

        Resumed runs re-enter completed stages whose persisted evidence makes
        them no-ops; the re-entered stage may not move the recorded phase
        backward. Failure recording and explicit failed-state resumption are
        the only non-forward moves and stay owned by ``save()``.
        """
        current = self.state
        if (
            current is not None
            and ResolvePhase.FAILED not in {current.phase, state.phase}
            and PHASE_ORDER[state.phase] < PHASE_ORDER[current.phase]
        ):
            state = state.model_copy(update={"phase": current.phase})
        self.state = state
        self.repository.save(state)
        self.emit_transitions(current, state)

    def emit_transitions(
        self, previous: ResolveState | None, state: ResolveState
    ) -> None:
        """Report only durably saved phase and concern changes to the observer."""
        if self.observer is None:
            return
        if previous is None or previous.phase != state.phase:
            self.observer.phase_changed(state.phase)
        before = (
            {item.concern_id: item for item in previous.progress}
            if previous is not None
            else {}
        )
        for item in state.progress:
            prior = before[item.concern_id] if item.concern_id in before else None
            if prior != item:
                self.observer.concern_changed(item)

    def progress_state(
        self,
        state: ResolveState,
        concern_ids: list[str],
        status: ConcernStatus,
        reason: str = "",
    ) -> ResolveState:
        """Return one state with the selected concern transitions applied."""
        selected = dict.fromkeys(concern_ids)
        return state.model_copy(
            update={
                "progress": [
                    item.model_copy(update={"status": status, "reason": reason})
                    if item.concern_id in selected
                    else item
                    for item in state.progress
                ]
            }
        )

    async def transition_concern(
        self, concern_id: str, status: ConcernStatus, reason: str = ""
    ) -> None:
        """Persist one concern transition without losing parallel sibling updates."""
        async with self.state_lock:
            state = self.require_state()
            self.persist(self.progress_state(state, [concern_id], status, reason))

    async def record_dependency_base(self, base: DependencyBase) -> None:
        """Persist one immutable dependency base before worker execution."""
        async with self.state_lock:
            state = self.require_state()
            existing = next(
                (
                    candidate
                    for candidate in state.bases
                    if candidate.concern_id == base.concern_id
                ),
                None,
            )
            if existing is not None and existing != base:
                raise ResolverInvariantError(
                    f"dependency base changed for {base.concern_id}"
                )
            if existing is None:
                self.persist(state.model_copy(update={"bases": [*state.bases, base]}))

    def require_state(self) -> ResolveState:
        if self.state is None:
            raise ResolverInvariantError("resolver state is not initialized")
        return self.state

    def manifest(self, state: ResolveState) -> ResolveManifest:
        return ResolveManifest(
            run_id=state.run_id,
            source=state.source,
            review_branch=(
                state.integration.branch
                if state.integration is not None
                else self.config.integration_branch
            ),
            outcomes=state.outcomes,
            verification=state.verification,
            final_review=state.final_review,
            accepted=state.accepted,
            cleanup=state.cleanup,
        )
