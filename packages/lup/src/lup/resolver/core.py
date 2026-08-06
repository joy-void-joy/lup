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
from lup.resolver.actors import ActorSessions
from lup.resolver.dag import ConcernGraph
from lup.resolver.journal import (
    ActorRef,
    AnswerSettledEvent,
    ConcernProgressedEvent,
    JoinAuditEvent,
    JoinCompletedEvent,
    Journal,
    PhaseChangedEvent,
    QuestionAskedEvent,
    RunFailedEvent,
)
from lup.channels.models import utc_now
from lup.resolver.mailbox import (
    ANSWER_POLL_SECONDS,
    PendingQuestion,
    QuestionMailbox,
    RecordedAnswer,
    wait_for_answers,
)
from lup.resolver.models import (
    INTEGRATION_CONCERN_ID,
    AdmissionRequest,
    AgentRound,
    AnswerBatch,
    CleanupRecord,
    Concern,
    ConcernAdmission,
    ConcernEligibility,
    ConcernInventory,
    ConcernOrigin,
    ConcernProgress,
    ConcernAllowance,
    ConcernStatus,
    DropCandidate,
    ConcernExecution,
    ConcernOutcome,
    DependencyBase,
    IntegrationRecord,
    JoinProgress,
    MaterialQuestion,
    MergeReport,
    QuestionAnswer,
    QuestionBatch,
    ResolveInventory,
    ResolveManifest,
    ResolvePhase,
    ResolveRequest,
    ResolverSource,
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
from lup.runtime.factory import SessionFactory
from lup.runtime.models import TurnInput, turn_request
from lup.runtime.wrappers import CorrectionConfig, decorated_session_factory


class ResolverInvariantError(RuntimeError):
    """A native result or persisted transition violated resolver semantics."""


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


APPROVE = "approve"
DEFER = "defer"

ASK_PREAMBLE = (
    "When a decision is not yours to make, ask through the resolver's question "
    "tools — queue_questions, await_answers, ask_questions — rather than "
    "guessing or ending your turn to report it. " + WAIT_CONTRACT
)


def merge_problems(
    merge: MergeReport, conflicted: list[Path], owed: list[DropCandidate]
) -> list[str]:
    """Every obligation this merge report left unmet.

    Two obligations rather than two prohibitions. Every candidate the
    detector raised must be dispositioned — containment, never equality,
    because a legitimate resolution rewrites hunks and requiring the exact
    candidate set back would reject the right answer. And every edit outside
    the conflict set must be declared, because that is where a silent
    override lives: the merger is handed an already-correct tree with
    unrestricted write access, and the canonical joint failure is fixed in a
    file that never conflicted.
    """
    dispositioned = {
        (disposition.parent, disposition.path.as_posix())
        for disposition in merge.dispositions
    }
    undispositioned = sorted(
        f"{candidate.path.as_posix()} from {candidate.parent[:12]}"
        for candidate in owed
        if (candidate.parent, candidate.path.as_posix()) not in dispositioned
    )
    unreasoned = sorted(
        disposition.path.as_posix()
        for disposition in merge.dispositions
        if not disposition.rationale.strip()
    )
    declared = {edit.path.as_posix() for edit in merge.out_of_conflict_edits}
    conflicting = {path.as_posix() for path in conflicted}
    undeclared = sorted(
        disposition.path.as_posix()
        for disposition in merge.dispositions
        if disposition.fate in {"rewritten", "superseded", "dropped"}
        and disposition.path.as_posix() not in conflicting
        and disposition.path.as_posix() not in declared
    )
    return [
        *(
            [f"content lost with nothing said about it: {', '.join(undispositioned)}"]
            if undispositioned
            else []
        ),
        *(
            [f"dispositioned without a rationale: {', '.join(unreasoned)}"]
            if unreasoned
            else []
        ),
        *(
            [f"changed outside the conflict set undeclared: {', '.join(undeclared)}"]
            if undeclared
            else []
        ),
    ]


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


class ApprovalDecisions(BaseModel):
    """Persisted direct choices and their dependency-safe eligible subset."""

    model_config = ConfigDict(frozen=True)

    directly_approved: list[str]
    eligible: list[str]


class EvidenceCitation(BaseModel):
    """One concern's evidence, named in the fields the concern carries."""

    model_config = ConfigDict(frozen=True)

    notes: list[ReviewNote]
    evidence: str


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
    """Name the evidence a plan ignored and the evidence it invented.

    A note is not a unit of work: one can raise several concerns and several
    can raise one, so concerns reference evidence rather than partitioning
    it. What still cannot happen is evidence no concern claims, because it
    goes unresolved with nothing to show for it.
    """
    faults = [
        ("no concern references", [i for i in range(total) if i not in referenced]),
        ("outside the evidence", [i for i in referenced if i not in range(total)]),
    ]
    named = [f"{label}: {sorted(indexes)}" for label, indexes in faults if indexes]
    return "; ".join(named) if named else None


def planned_evidence(request: ResolveRequest, indexes: list[int]) -> EvidenceCitation:
    """Split one plan's positional references back into what it cites.

    Positions below the note count name notes; the rest continue into the
    statements, so a planner references either kind the same way and the
    materialized concern still carries each in the form it came in.
    """
    return EvidenceCitation(
        notes=[
            ReviewNote.model_validate(
                request.notes[index].model_dump(exclude={"context"})
            )
            for index in indexes
            if index < len(request.notes)
        ],
        evidence="\n".join(
            request.statements[index - len(request.notes)]
            for index in indexes
            if index >= len(request.notes)
        ),
    )


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
        self.journal = Journal(self.repository.root)
        self.actors = ActorSessions(self.repository.root, self.journal, self.mailbox)
        self.ledger: list[LedgerEntry] = []
        self.wake = asyncio.Event()
        self.state_lock = asyncio.Lock()
        self.state: ResolveState | None = None

    async def run(self, source: ResolverSource) -> ResolveManifest:
        """Run through final review and stop at the human acceptance boundary."""
        with self.repository.exclusive():
            inventory = await source.inventory(self.plan_inventory)
            return await self.run_exclusive(inventory)

    async def plan_inventory(
        self,
        request: ResolveRequest,
        origin: ConcernOrigin = ConcernOrigin.INVENTORY,
        taken: list[str] | None = None,
    ) -> ResolveInventory:
        """Organize raw review evidence into concerns in a read-only turn.

        A rejected partition is fed back to the planner by name rather than
        ending the run: intake is the point where the least work is persisted
        and the most would be lost. ``taken`` names the ids a live run has
        already recorded, so evidence planned into a run that is already
        moving cannot collide with the concerns it joins.
        """
        reserved = (
            "\nThese ids already name a concern in this run and may not be "
            "reused; depend on one by id instead: " + ", ".join(taken)
            if taken
            else ""
        )
        prompt = (
            "Organize every piece of review evidence into generalized "
            "implementation concerns without editing. Cluster by underlying "
            "issue, not file. Reference evidence through evidence_indexes using "
            "its zero-based position in the evidence below — notes first, then "
            "statements. A note is not a unit of work: split one that "
            "raises several issues across several concerns, and reference it "
            "from each. Every index must appear at least once; none may repeat "
            "within a single concern. Give each concern path-safe id, complete acceptance "
            "criteria, dependencies, material questions, and starting files. Every "
            "concern's criteria must scope analysis and action together — never "
            "plan one concern to audit and a second to act on what it found. That "
            "splits one piece of work across two leases that cannot see each "
            "other, and the auditing half finds real violations it is forbidden "
            "to fix. Declare "
            "an allowance only when the plan cannot be carried out without the gate "
            "it names, so approving the concern approves what it actually needs. Do "
            "not decide eligibility or integration approval; the resolver asks the "
            f"user.{reserved}"
            f"\n\nReview evidence:\n{request.model_dump_json(indent=2)}"
        )
        planner = self.actors.session(
            ActorRef(kind="planner", id=self.config.run_id),
            self.reviewer_factory(self.config.workspace),
        )
        # A retry is a second turn on the planner's own session, so the
        # correction is the whole input: it already holds the evidence and the
        # partition it just proposed, and restating both would invite it to
        # re-derive from scratch what it should be revising.
        attempt = prompt
        complaint: str | None = None
        for _ in range(INVENTORY_PLAN_ATTEMPTS):
            result = await planner.turn(
                turn_request(TurnInput(text=attempt), ConcernInventory)
            )
            referenced = [
                index
                for planned in result.output.concerns
                for index in planned.evidence_indexes
            ]
            complaint = coverage_complaint(referenced, request.evidence_count())
            if complaint is None:
                break
            attempt = (
                f"That partition left review evidence unaccounted for — "
                f"{complaint}. Every index from 0 to "
                f"{request.evidence_count() - 1} must be referenced by at least "
                "one concern. Revise and resubmit."
            )
        else:
            raise ResolverInvariantError(
                "inventory planner left review evidence unaccounted for across "
                f"{INVENTORY_PLAN_ATTEMPTS} attempts — {complaint}"
            )
        concerns = [
            Concern(
                **planned_evidence(request, planned.evidence_indexes).model_dump(),
                origin=origin,
                eligible=True,
                integration_approved=True,
                **planned.model_dump(exclude={"evidence_indexes"}),
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

        Every actor's session is released here too. A park is an exit like
        any other: the session ids are persisted on the way out, so resuming
        reattaches to the conversations rather than starting new ones.
        """
        self.mailbox.clear_park()
        stop = asyncio.Event()
        promoter = asyncio.create_task(self.promote_until(stop))
        try:
            yield
        finally:
            stop.set()
            await promoter
            await self.actors.close()

    async def advance_exclusive(self, state: ResolveState) -> ResolveManifest:
        """Advance while a promoter is folding every door's answers in.

        Each stage asks what the current concern set still needs rather than
        whether the stage has run before, so a concern admitted after the run
        started reaches the same gates as one from intake instead of skipping
        the stages its siblings already passed.
        """
        asked = {
            question.id
            for question in (state.questions.questions if state.questions else [])
        }
        unasked = [
            question
            for question in self.pending_questions(state.concerns)
            if question.id not in asked
        ]
        if state.questions is None or unasked:
            self.queue_questions(unasked, "planning")
            state = state.model_copy(
                update={
                    "phase": ResolvePhase.QUESTIONS,
                    "questions": QuestionBatch(
                        run_id=state.run_id,
                        questions=[
                            *(state.questions.questions if state.questions else []),
                            *unasked,
                        ],
                    ),
                }
            )
            state = self.progress_state(
                state,
                [question.concern_id for question in unasked],
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
        settled = {item.concern_id for item in state.eligibility}
        undecided = [concern for concern in state.concerns if concern.id not in settled]
        if undecided:
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
                for concern in undecided
            ]
            state = state.model_copy(
                update={
                    "phase": ResolvePhase.ELIGIBILITY,
                    "eligibility": [*state.eligibility, *eligibility],
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
        unleased = [
            concern for concern in approved if concern.id not in lease_by_concern
        ]
        if unleased:
            fresh = [
                self.leases.acquire(concern.id, self.concern_branch(concern.id))
                for concern in unleased
            ]
            lease_by_concern.update({lease.concern_id: lease for lease in fresh})
            state = state.model_copy(
                update={
                    "phase": ResolvePhase.LEASES,
                    "leases": [*state.leases, *fresh],
                }
            )
            state = self.progress_state(
                state,
                [concern.id for concern in unleased],
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
                failures = [
                    result for result in results if isinstance(result, BaseException)
                ]
                executions = [
                    result
                    for result in results
                    if not isinstance(result, BaseException)
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
        elif state.integration is None or not state.integration.completed:
            # A resumed run re-enters integration until the record says it
            # finished. `completed` is written once verification passes, which
            # is the last mechanical fact the run produces — the judgement on
            # top of it belongs to whoever opens the journal afterwards.
            state = await self.integrate(state, outcomes)
        self.land_nested(state)
        return self.manifest(self.release(state))

    def restore_leases(self, state: ResolveState) -> None:
        """Validate persisted authority and reset incomplete attempts for retry."""
        self.leases.adopt(state.leases)
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
                # Three states, and each names the commit it expects rather
                # than accepting whatever HEAD happens to hold. A finished
                # integration expects its record; a partway one expects the
                # last join it recorded, so the joins already built survive
                # and only the interrupted merge and its index are discarded;
                # one that never started expects the source commit.
                if (
                    state.integration is not None
                    and state.integration.commit is not None
                ):
                    recorded = True
                    expected = state.integration.commit
                elif state.join_progress is not None:
                    recorded = True
                    expected = state.join_progress.commit
                else:
                    recorded = False
                    expected = state.source.commit
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
        # A park is a pause, not an abandonment. What sits in the working tree
        # is the turn a question interrupted — the join being resolved, or the
        # edits a worker made before it found the decision it could not take —
        # and the actor's session is reattached still holding it. Discarding it
        # priced every question at a wasted turn, and the rerun re-derived that
        # question under an id no recorded answer matched, so the same decision
        # was put to the human as many as four times in one run.

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
        for message in failure_messages(error):
            self.journal.record(RunFailedEvent(reason=message))
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
        base = await self.record_note_clearance(base, cleared.commit)
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
            worker = await self.worker_turn(assignment, feedback, round_number)
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
                # Verification ran exactly once in a run, over the fully
                # integrated tree, so a concern could reach VERIFIED with a
                # red suite and the breakage surfaced after every join with
                # nothing to attribute it to.
                broke = [
                    record.name
                    for record in self.verify(lease.root)
                    if not record.passed
                ]
                review = (
                    ReviewReport(
                        concern_id=concern.id,
                        accepted=False,
                        generalized=False,
                        reason="verification failed: " + ", ".join(broke),
                    )
                    if broke
                    else await self.review_turn(
                        concern, worker, diff.commit, lease.root, round_number
                    )
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
            "present belongs to another concern or is parked work behind a wake "
            "condition: leave it in place. If resolving your concern means deleting "
            "or moving code that carries one, do so and name it in your summary.\n\n"
            f"{ASK_PREAMBLE}\n\n"
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
        result = await self.actors.session(
            ActorRef(kind="worker", id=assignment.concern.id, round=round_number),
            self.worker_factory(
                WorkerContext(
                    root=assignment.lease.root,
                    concern_id=assignment.concern.id,
                    allowances=assignment.concern.allowances,
                )
            ),
        ).turn(turn_request(TurnInput(text=prompt), WorkerReport))
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
        """Join parents one at a time, spending a turn only where one is owed.

        Every join is pairwise because git cannot merge N branches at once
        when it matters — octopus refuses on conflict — so the boundary that
        moves is the session rather than the sequence. One merger sees every
        parent, and by parent six it has genuinely seen one through five.
        """
        if len(commits) < 2:
            raise ValueError("a semantic join requires at least two commits")
        if not lease.root.exists():
            self.worktrees.create(lease, commits[0])
        base = self.worktrees.head(lease)
        current = base
        joined: list[str] = []  # lup: ignore[empty-collection] — audit input
        for parent in self.join_order(lease, base, commits[1:]):
            # The loop carries no resumption point, so a resumed join re-enters
            # at the first parent. One already contained in HEAD has nothing to
            # merge, and a merge turn spent on it is not free: the session
            # cannot tell "already joined" from "something upstream is wrong",
            # so it reasonably asks rather than reporting success, and every
            # such round costs a question and a resume. Skip what is already in.
            if self.worktrees.already_joined(lease, parent):
                joined.append(parent)
                continue
            before = current
            conflicted = self.worktrees.prepare_join(lease, [before, parent])
            if conflicted:
                await self.adjudicate(lease, parent, purpose, [])
            current = self.worktrees.commit_join(lease, title)
            # What this parent added since it forked, and whether the join
            # still holds it. Asking against the fork point rather than the
            # previous head is what keeps a dependency's own content out of
            # the obligation list.
            fork = self.worktrees.merge_base(lease, before, parent)
            owed = self.worktrees.drop_candidates(lease, fork, parent, current)
            if owed:
                await self.adjudicate(lease, parent, purpose, owed)
                current = self.worktrees.commit_join(lease, title)
            joined.append(parent)
            # Verifying after every join is what makes a red result name a
            # join. Running it once over the finished tree gave the same
            # failure with twelve candidates and no way to tell which one
            # introduced it.
            failed = [
                record.name for record in self.verify(lease.root) if not record.passed
            ]
            if failed:
                await self.adjudicate(
                    lease,
                    parent,
                    f"{purpose} — joining {parent[:12]} broke: {', '.join(failed)}",
                    [],
                )
                current = self.worktrees.commit_join(lease, title)
            self.journal.record(
                JoinCompletedEvent(
                    parent=parent,
                    commit=current,
                    conflicted=conflicted,
                    broke=failed,
                )
            )
            await self.recheck_standing(lease, base, joined[:-1], parent)
            self.record_join_progress(joined, current)
        await self.audit_join(lease, base, joined, current, purpose)
        return current

    def record_join_progress(self, joined: list[str], commit: str) -> None:
        """Say where the join sequence got to, as each parent lands.

        Written after the parent is committed, so what it names is a tree
        that exists. A resume restores to this commit instead of the run's
        source, which is what stops it discarding joins it already built.
        """
        state = self.state
        if state is None:
            return
        self.persist(
            state.model_copy(
                update={
                    "join_progress": JoinProgress(joined=list(joined), commit=commit)
                }
            )
        )

    async def recheck_standing(
        self,
        lease: WritableRootLease,
        base: str,
        standing: list[str],
        parent: str,
    ) -> None:
        """Ask whether this join stopped an already-joined concern holding.

        A regression is precisely an earlier parent's criterion that no longer
        holds. Checking that only after the last join reports it with every
        parent a candidate and the merger long past the context; asking it
        here names the join that caused it while the tree is still small
        enough to read.

        Only concerns this join could have touched are re-examined. A join
        that changes no file an earlier concern changed cannot have broken its
        criteria in a way the per-join verification above would not already
        have caught, and re-reading every concern after every join would cost
        a reviewer turn per pair.
        """
        state = self.state
        if state is None or not standing:
            return
        changed = {
            path.as_posix()
            for path in self.worktrees.changed_between(lease, base, parent)
        }
        owners = {
            outcome.commit: outcome.concern_id
            for outcome in state.outcomes
            if outcome.commit is not None
        }
        for earlier in standing:
            if earlier not in owners:
                continue
            overlap = changed & {
                path.as_posix()
                for path in self.worktrees.changed_between(lease, base, earlier)
            }
            if not overlap:
                continue
            concern = next(
                (item for item in state.concerns if item.id == owners[earlier]), None
            )
            if concern is None:
                continue
            await self.recheck_concern(
                concern,
                lease.root,
                situation=(
                    "A later concern has just been joined into the tree your "
                    "concern is already in, and the two changed the same "
                    "files. Re-check your concern's acceptance criteria "
                    "against this tree. A criterion you passed before may no "
                    "longer hold; say so plainly if it does not.\n\n"
                    "Files both touched:\n"
                    + "\n".join(f"- {path}" for path in sorted(overlap))
                    + f"\n\nJoined commit: {parent[:12]}\nWorktree: {lease.root}"
                ),
                occasion=f"join-{parent[:12]}",
                lost_because=f"once {parent[:12]} was joined into the same tree",
            )

    def join_order(
        self, lease: WritableRootLease, base: str, parents: list[str]
    ) -> list[str]:
        """Order the joins so related work meets while the session is on it.

        Completion order is the order concerns happened to finish, which
        scatters related work across the sequence and puts a merger's own
        precedent behind five unrelated joins. Parents that overlap no file
        with anything already placed go first — those are the ones git
        settles alone — and the rest follow in dependency order, so each
        contested join lands next to the work it contests.
        """
        touched = {
            parent: {
                path.as_posix()
                for path in self.worktrees.changed_between(lease, base, parent)
            }
            for parent in parents
        }
        ranked = sorted(
            parents,
            key=lambda parent: (
                sum(
                    1
                    for other in parents
                    if other != parent and touched[parent] & touched[other]
                ),
                self.dependency_depth(parent),
                parent,
            ),
        )
        return ranked

    async def recheck_criteria(
        self, state: ResolveState, integration: IntegrationRecord
    ) -> None:
        """Re-run each concern's reviewer against the tree its siblings built.

        ``review_turn`` runs against a concern's own worktree before
        integration, so nothing re-checked a criterion that stopped holding
        once a sibling landed. This is the only instrument aimed at "concern
        three's criterion two no longer holds now that concern seven merged"
        — the final audit is about content that went missing, which is a
        different failure.

        A failed criterion opens a question rather than failing the run,
        because later work can legitimately supersede an earlier criterion
        and only a human can say whether this did.
        """
        integrated = {identifier: True for identifier in integration.concerns}
        for concern in state.concerns:
            if concern.id not in integrated:
                continue
            await self.recheck_concern(
                concern,
                integration.worktree,
                situation=(
                    "Every concern in this run is now integrated into one "
                    "tree. Re-check your concern's acceptance criteria "
                    "against that tree rather than the worktree you "
                    "reviewed. A criterion you passed before may no "
                    "longer hold now that a sibling has landed; say so "
                    "plainly if it does not.\n\n"
                    f"Integrated concerns: {', '.join(integration.concerns)}\n"
                    f"Worktree: {integration.worktree}"
                ),
                occasion="integrated",
                lost_because="once every sibling is integrated",
            )

    async def recheck_concern(
        self,
        concern: Concern,
        worktree: Path,
        *,
        situation: str,
        occasion: str,
        lost_because: str,
    ) -> None:
        """Ask one concern's reviewer whether its criteria still hold here.

        A failed criterion opens a question rather than failing the run,
        because later work can legitimately supersede an earlier criterion
        and only a human can say whether this did. The question is keyed by
        occasion so the same concern examined after two different joins asks
        twice rather than colliding on one id — the second failure is its own
        fact, and it names a different join.
        """
        reviewer = self.actors.session(
            ActorRef(kind="reviewer", id=concern.id),
            self.reviewer_factory(worktree),
        )
        result = await reviewer.turn(
            turn_request(TurnInput(text=situation), ReviewReport)
        )
        met = {identifier: True for identifier in result.output.criteria_met}
        lost = [
            criterion.id for criterion in concern.criteria if criterion.id not in met
        ]
        if not lost:
            return
        self.queue_questions(
            [
                MaterialQuestion(
                    id=f"{concern.id}-superseded-{occasion}",
                    concern_id=concern.id,
                    prompt=(
                        f"{concern.id} no longer meets {', '.join(lost)} "
                        f"{lost_because}. The reviewer says: "
                        f"{result.output.reason}. Was this criterion "
                        "superseded by later work, or is this a regression?"
                    ),
                    choices=["superseded", "regression"],
                    closed_choices=True,
                )
            ],
            concern.id,
        )

    def verify(self, root: Path) -> list[VerificationRecord]:
        """Run the whole verification set against one tree.

        The full set every time, never a fast subset. Per-join verification
        is the only mechanical detector of a clean merge that is jointly
        wrong — one branch changes a signature, another adds a caller, and
        the type error exists in neither parent alone — and a subset chosen
        for speed is exactly the one that misses it.
        """
        records: list[VerificationRecord] = []  # lup: ignore[empty-collection]
        for command in self.config.verification_commands:
            status = self.process_launcher.launch(
                LaunchRequest(arguments=command.arguments, cwd=root)
            )
            records.append(
                VerificationRecord(
                    name=command.name,
                    arguments=command.arguments,
                    passed=status.code == 0,
                    exit_code=status.code,
                )
            )
        return records

    async def adjudicate(
        self,
        lease: WritableRootLease,
        parent: str,
        purpose: str,
        owed: list[DropCandidate],
    ) -> None:
        """Put one join to the merger and hold its report to what it declared."""
        conflicted = self.worktrees.conflicted_paths(lease)
        merge = await self.merge_turn(lease, parent, purpose, conflicted, owed)
        # An incompletion is the merger's considered answer and spending
        # another turn on it only re-derives it. An accounting gap is
        # different: the tree may be right and the declaration short, which
        # is precisely what a second turn can settle.
        if not merge.completed or merge.unresolved_paths:
            raise ResolverInvariantError(
                f"semantic join failed for {lease.concern_id}: "
                + (merge.blocked or merge.summary)
            )
        problems = merge_problems(merge, conflicted, owed)
        if problems:
            merge = await self.merge_turn(
                lease, parent, purpose, conflicted, owed, problems
            )
            problems = merge_problems(merge, conflicted, owed)
        if problems:
            raise ResolverInvariantError(
                f"semantic join for {lease.concern_id} was not accounted for: "
                + "; ".join(problems)
            )
        self.ledger.append(
            LedgerEntry(parent=parent, summary=merge.summary, merge=merge)
        )

    async def audit_join(
        self,
        lease: WritableRootLease,
        base: str,
        joined: list[str],
        result: str,
        purpose: str,
    ) -> None:
        """Re-check every parent against the finished tree, not just the last.

        A hunk lost at join three and never noticed is invisible to the
        per-join check, which only ever looked at one parent against one
        result. Running the same detector over every parent once the tree is
        final is what catches it.
        """
        owed = [
            candidate
            for parent in joined
            for candidate in self.worktrees.drop_candidates(
                lease, self.worktrees.merge_base(lease, base, parent), parent, result
            )
        ]
        if not owed:
            return
        self.journal.record(
            JoinAuditEvent(parents=joined, outstanding=len(owed), commit=result)
        )
        await self.adjudicate(lease, joined[-1], f"{purpose} — final audit", owed)
        self.worktrees.commit_join(lease, "resolve: settle the final join audit")

    def dependency_depth(self, commit: str) -> int:
        """How deep in the concern graph the concern that produced this sits."""
        state = self.state
        if state is None:
            return 0
        owner = next(
            (
                outcome.concern_id
                for outcome in state.outcomes
                if outcome.commit == commit
            ),
            None,
        )
        if owner is None:
            return 0
        return len(ConcernGraph(state.concerns).ancestors(owner))

    async def review_turn(
        self,
        concern: Concern,
        worker: WorkerReport,
        commit: str,
        worktree: Path,
        round_number: int,
    ) -> ReviewReport:
        invocation = self.invocation_renderer.render(self.spec.review_skill)
        prompt = (
            "Independently review the committed concern against every persisted "
            "acceptance criterion.\n\n"
            f"{invocation}\n\nConcern:\n{concern.model_dump_json(indent=2)}\n\n"
            f"Worker report:\n{worker.model_dump_json(indent=2)}\n\n"
            f"Commit: {commit}"
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
                f"Commit: {commit}"
            )
        result = await self.actors.session(
            ActorRef(kind="reviewer", id=concern.id, round=round_number),
            self.reviewer_factory(worktree),
        ).turn(turn_request(TurnInput(text=prompt), ReviewReport))
        if result.output.concern_id != concern.id:
            raise ResolverInvariantError("reviewer returned a foreign concern id")
        return result.output

    async def merge_retry(
        self, lease: WritableRootLease, problems: list[str]
    ) -> MergeReport:
        """Name what the last report left unmet, on the session that wrote it."""
        result = await self.actors.session(
            ActorRef(kind="merger", id=lease.concern_id),
            self.worker_factory(
                WorkerContext(
                    root=lease.root,
                    concern_id=lease.concern_id,
                    allowances=self.merge_allowances(),
                )
            ),
        ).turn(
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

    def merge_context(self, parent: str) -> str:
        """What the concern behind this parent was for, and what it decided.

        A merger that knows only the diff can tell what changed but not what
        was deliberate. What it gets is the concern's own specification, the
        criteria it had to meet, the answers a human gave it, and the merge
        notes its worker left for whoever would join it — the last being the
        one thing only that worker could know.
        """
        state = self.state
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
        state = self.state
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

    async def admit_concern(self, concern: Concern) -> None:
        """Take a concern discovered mid-run into the run that discovered it.

        The worked example this exists for: an audit concern whose criteria
        forbade it from moving code, with a second concern depending on it to
        act — two concerns that should have been one, discovered only once
        both were leased. Without admission the choice was to drop the
        finding or restart the run and lose every answer already given.
        """
        async with self.state_lock:
            state = self.require_state()
            if any(item.id == concern.id for item in state.concerns):
                raise ResolverInvariantError(
                    f"concern {concern.id!r} is already in this run"
                )
            self.persist(
                state.model_copy(
                    update={
                        "concerns": [*state.concerns, concern],
                        "progress": [
                            *state.progress,
                            ConcernProgress(
                                concern_id=concern.id,
                                status=ConcernStatus.DISCOVERED,
                                reason=(
                                    f"admitted mid-run, superseding {concern.supersedes}"
                                    if concern.supersedes
                                    else "admitted mid-run"
                                ),
                            ),
                        ],
                    }
                )
            )

    def merge_allowances(self) -> list[ConcernAllowance]:
        """Every gate the joined concerns were approved to pass.

        A join can newly require a suppression that neither parent needed: a
        rule one branch adds first meets a constant another branch adds only
        once the two are together. Nobody could have declared that at plan
        time, and a merge session carrying no allowance at all had no route
        to it except failing.
        """
        state = self.state
        if state is None:
            return []
        return list(
            dict.fromkeys(
                allowance
                for concern in state.concerns
                for allowance in concern.allowances
            )
        )

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
        result = await self.actors.session(
            ActorRef(kind="merger", id=lease.concern_id),
            self.worker_factory(
                WorkerContext(
                    root=lease.root,
                    concern_id=lease.concern_id,
                    allowances=self.merge_allowances(),
                )
            ),
        ).turn(turn_request(TurnInput(text=prompt), MergeReport))
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
            self.journal.record(
                QuestionAskedEvent(question=question, asked_by=asked_by)
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
            answer = QuestionAnswer(question_id=offer.question_id, value=offer.value)
            self.mailbox.record(
                RecordedAnswer(
                    run_id=self.config.run_id,
                    answer=answer,
                    door=offer.door,
                    answered_at=utc_now(),
                )
            )
            self.journal.record(AnswerSettledEvent(answer=answer, door=offer.door))
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
                    "integration", self.integration_lease_branch()
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
            # Re-read rather than updating the copy this scope has held since
            # before the joins: `join_commits` persisted progress under it,
            # and building from the stale local would drop what it recorded.
            # The record supersedes that progress, so it is cleared with the
            # same write that establishes it.
            state = self.require_state().model_copy(
                update={
                    "integration": integration,
                    "join_progress": None,
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
            verification = self.verify(integration_lease.root)
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
            await self.recheck_criteria(state, integration)
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

        return state

    async def admit(self, request: AdmissionRequest) -> ConcernAdmission:
        """Plan evidence found mid-run into the run that found it.

        Restarting was the only way to widen a concern set, and it re-derived
        the inventory from scratch — discarding every material answer already
        collected at exactly the moment a run holds the most of them. Only the
        new evidence is planned here; the run keeps its id, its answers, and
        its completed work, so nothing already decided is decided again.

        Admission stops at integration, because past it the review branch is
        assembled and a concern joining would have to reopen it. Everything
        earlier is fair game: the admitted concern enters at ``discovered``
        and walks the same question, approval, eligibility, and lease path as
        one from intake.

        Nothing is written until the widened set holds: a writable root the
        run already handed out refuses the admission, and so does a graph
        that would not be a unique-id, present-dependency, acyclic one.
        """
        with self.repository.exclusive():
            state = self.repository.load()
            self.state = state
            if state.phase in {ResolvePhase.ABORTED, ResolvePhase.COMPLETE}:
                raise ResolverInvariantError(f"run is already {state.phase}")
            reached = (
                state.resume_from or state.phase
                if state.phase is ResolvePhase.FAILED
                else state.phase
            )
            if PHASE_ORDER[reached] >= PHASE_ORDER[ResolvePhase.INTEGRATION]:
                raise ResolverInvariantError(
                    f"run has reached {reached}; a concern may only join a run "
                    "before its review branch is assembled"
                )
            planned = await self.plan_inventory(
                ResolveRequest(
                    source=state.source,
                    notes=request.notes,
                    statements=request.statements,
                ),
                origin=ConcernOrigin.ADMITTED,
                taken=[concern.id for concern in state.concerns],
            )
            self.leases.adopt(state.leases)
            for concern in planned.concerns:
                self.leases.plan(concern.id, self.concern_branch(concern.id))
            concerns = [*state.concerns, *planned.concerns]
            ConcernGraph(concerns)
            widened = state.model_copy(
                update={
                    "concerns": concerns,
                    "progress": [
                        *state.progress,
                        *[
                            ConcernProgress(concern_id=concern.id)
                            for concern in planned.concerns
                        ],
                    ],
                }
            )
            self.persist(widened)
            return ConcernAdmission(
                run_id=state.run_id,
                phase=self.require_state().phase,
                concerns=planned.concerns,
                questions=self.pending_questions(planned.concerns),
            )

    def concern_branch(self, concern_id: str) -> str:
        return f"resolve/{self.config.run_id}/{concern_id}"

    def pending_questions(self, concerns: list[Concern]) -> list[MaterialQuestion]:
        """Every gate these concerns must pass before any work begins."""
        return [question for concern in concerns for question in concern.questions] + [
            approval_question(concern)
            for concern in concerns
            if concern.eligible and concern.integration_approved
        ]

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
                if lease.concern_id == INTEGRATION_CONCERN_ID
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

    def nested(self) -> bool:
        """Whether this run integrates onto a branch already checked out."""
        return (
            self.worktrees.current_branch(self.config.workspace)
            == self.config.integration_branch
        )

    def integration_lease_branch(self) -> str:
        """The branch the integration worktree owns.

        A nested run cannot take the review branch directly, because git will
        not add a second worktree for a branch that is already checked out.
        It builds on a ref of its own and the standing worktree
        fast-forwards to it at the end, which moves ref, index and working
        tree in one step.
        """
        if self.nested():
            return f"{self.config.integration_branch}-wip-{self.config.run_id}"
        return self.config.integration_branch

    def land_nested(self, state: ResolveState) -> None:
        """Advance the launching worktree's review branch to what this run built."""
        if not self.nested() or state.integration is None:
            return
        built = state.integration.commit
        if built is None or self.worktrees.fast_forward(self.config.workspace, built):
            return
        self.journal.record(
            RunFailedEvent(
                reason=(
                    f"{self.config.integration_branch} could not fast-forward to "
                    f"{built[:12]}; it moved while this run was building on it. "
                    "Merge it by hand."
                )
            )
        )

    def concern_failed(self, state: ResolveState, concern_id: str) -> bool:
        return any(
            item.concern_id == concern_id and item.status == ConcernStatus.FAILED
            for item in state.progress
        )

    def release(self, state: ResolveState) -> ResolveState:
        """Free the concern leases and hand the review branch over.

        There was a human gate here, and it decided nothing. Accept and
        reject both retained the integration lease, both removed every
        concern lease, and differed only in a sentence recorded against the
        cleanup — so the run stopped, spent a question, and used the answer
        to choose wording. Per-concern control is the live stop-and-retarget
        channel while the run moves, and the acceptance of the result is
        whatever the human does with the branch afterwards.
        """
        cleanup: list[CleanupRecord] = []  # lup: ignore[empty-collection]
        progress = state
        for lease in state.leases:
            if lease.concern_id == "integration":
                cleanup.append(
                    CleanupRecord(
                        path=lease.root,
                        branch=lease.branch,
                        action="retained",
                        reason="review branch retained for the human to land",
                    )
                )
                continue
            removed = self.worktrees.remove(lease)
            # A concern that failed keeps saying so. Cleaning its worktree is
            # housekeeping, and relabelling it CLEANED would erase the one
            # thing the run is evidence of.
            if not self.concern_failed(progress, lease.concern_id):
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
                "cleanup": cleanup,
                "leases": [
                    lease.model_copy(update={"active": False}) for lease in state.leases
                ],
            }
        )
        self.persist(completed)
        completed = completed.model_copy(update={"phase": ResolvePhase.COMPLETE})
        self.persist(completed)
        return completed

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
        """Report only durably saved phase and concern changes.

        The journal takes the same transitions the observer does, so a page
        following the record sees state moves interleaved with the turns
        that caused them rather than having to correlate two sources.
        """
        if previous is None or previous.phase != state.phase:
            self.journal.record(PhaseChangedEvent(phase=state.phase))
            if self.observer is not None:
                self.observer.phase_changed(state.phase)
        before = (
            {item.concern_id: item for item in previous.progress}
            if previous is not None
            else {}
        )
        for item in state.progress:
            prior = before[item.concern_id] if item.concern_id in before else None
            if prior == item:
                continue
            self.journal.record(ConcernProgressedEvent(progress=item))
            if self.observer is not None:
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

    async def record_note_clearance(
        self, base: DependencyBase, commit: str
    ) -> DependencyBase:
        """Move this concern's recorded base onto the commit that cleared its notes.

        The orchestrator strips a concern's notes as a commit of its own, so
        the tree its worker starts from is that commit and not the one the
        base was built at. Leaving the record behind bricked every resume of a
        concern that failed: with no verified commit to restore, the expected
        commit fell back to the base while HEAD sat at the clearance, and the
        invariant the resolver itself had violated raised with no CLI
        operation able to repair it.

        Recorded rather than tolerated. An invariant that accepts whatever
        HEAD says is not one, and the fact it needs was always available at
        the moment the commit was made.
        """
        if commit == base.commit:
            return base
        moved = base.model_copy(update={"commit": commit})
        async with self.state_lock:
            state = self.require_state()
            self.persist(
                state.model_copy(
                    update={
                        "bases": [
                            moved if item.concern_id == base.concern_id else item
                            for item in state.bases
                        ]
                    }
                )
            )
        return moved

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
            cleanup=state.cleanup,
        )
