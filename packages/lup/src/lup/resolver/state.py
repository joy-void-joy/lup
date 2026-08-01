"""Atomic schema-versioned resolver state persistence."""

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from lup.resolver.models import (
    AgentRound,
    AnswerBatch,
    BasesDocument,
    ConcernProgress,
    ConcernStatus,
    ConcernsDocument,
    LeasesDocument,
    QuestionBatch,
    ReviewReport,
    ResolveState,
    ResolvePhase,
    WorkerReport,
)

PHASE_ORDER: dict[ResolvePhase, int] = {
    phase: index for index, phase in enumerate(ResolvePhase)
}
# lup: ignore[library-default] — the successor of each phase in this library's own closed enum
PHASE_TRANSITIONS: dict[ResolvePhase, ResolvePhase] = {
    ResolvePhase.INVENTORY: ResolvePhase.QUESTIONS,
    ResolvePhase.QUESTIONS: ResolvePhase.ELIGIBILITY,
    ResolvePhase.ELIGIBILITY: ResolvePhase.DAG,
    ResolvePhase.DAG: ResolvePhase.LEASES,
    ResolvePhase.LEASES: ResolvePhase.WORKERS,
    ResolvePhase.WORKERS: ResolvePhase.DEPENDENCY_BASES,
    ResolvePhase.DEPENDENCY_BASES: ResolvePhase.REVIEW,
    ResolvePhase.REVIEW: ResolvePhase.INTEGRATION,
    ResolvePhase.INTEGRATION: ResolvePhase.VERIFICATION,
    ResolvePhase.VERIFICATION: ResolvePhase.ACCEPTANCE,
    ResolvePhase.ACCEPTANCE: ResolvePhase.CLEANUP,
    ResolvePhase.CLEANUP: ResolvePhase.COMPLETE,
}
# lup: ignore[library-default] — the legal successors of each status in this library's own closed enum
CONCERN_TRANSITIONS: dict[ConcernStatus, list[ConcernStatus]] = {
    ConcernStatus.DISCOVERED: [
        ConcernStatus.WAITING_FOR_ANSWERS,
        ConcernStatus.ELIGIBLE,
        ConcernStatus.INELIGIBLE,
        ConcernStatus.FAILED,
    ],
    ConcernStatus.WAITING_FOR_ANSWERS: [
        ConcernStatus.ELIGIBLE,
        ConcernStatus.INELIGIBLE,
        ConcernStatus.RUNNING,
        ConcernStatus.FAILED,
    ],
    ConcernStatus.ELIGIBLE: [ConcernStatus.LEASED, ConcernStatus.FAILED],
    ConcernStatus.INELIGIBLE: [],
    ConcernStatus.LEASED: [
        ConcernStatus.RUNNING,
        ConcernStatus.ELIGIBLE,
        ConcernStatus.FAILED,
    ],
    ConcernStatus.RUNNING: [
        ConcernStatus.VALIDATING,
        ConcernStatus.WAITING_FOR_ANSWERS,
        ConcernStatus.ELIGIBLE,
        ConcernStatus.FAILED,
    ],
    ConcernStatus.VALIDATING: [
        ConcernStatus.REVIEWING,
        ConcernStatus.REVISING,
        ConcernStatus.ELIGIBLE,
        ConcernStatus.FAILED,
    ],
    ConcernStatus.REVIEWING: [
        ConcernStatus.REVISING,
        ConcernStatus.VERIFIED,
        ConcernStatus.ELIGIBLE,
        ConcernStatus.FAILED,
    ],
    ConcernStatus.REVISING: [
        ConcernStatus.RUNNING,
        ConcernStatus.ELIGIBLE,
        ConcernStatus.FAILED,
    ],
    ConcernStatus.VERIFIED: [
        ConcernStatus.ELIGIBLE,
        ConcernStatus.INTEGRATING,
        ConcernStatus.RETAINED,
        ConcernStatus.FAILED,
    ],
    ConcernStatus.INTEGRATING: [ConcernStatus.INTEGRATED, ConcernStatus.FAILED],
    ConcernStatus.INTEGRATED: [
        ConcernStatus.CLEANED,
        ConcernStatus.RETAINED,
        ConcernStatus.FAILED,
    ],
    ConcernStatus.CLEANED: [],
    ConcernStatus.RETAINED: [],
    ConcernStatus.FAILED: [
        ConcernStatus.ELIGIBLE,
        ConcernStatus.CLEANED,
        ConcernStatus.RETAINED,
    ],
}
type PersistedResolverModel = (
    ResolveState
    | AgentRound
    | ConcernsDocument
    | QuestionBatch
    | AnswerBatch
    | LeasesDocument
    | BasesDocument
    | WorkerReport
    | ReviewReport
)


class StateTransitionError(RuntimeError):
    """A persisted run cannot make the requested state transition."""


class StateCorruptionError(RuntimeError):
    """A persisted resolver document cannot be decoded as its schema."""


def progress_index(progress: list[ConcernProgress]) -> dict[str, ConcernProgress]:
    """Index a complete progress projection while rejecting duplicate ids."""
    indexed = {item.concern_id: item for item in progress}
    if len(indexed) != len(progress):
        raise StateTransitionError("resolver concern progress ids must be unique")
    return indexed


def validate_progress_transition(
    current: ResolveState, candidate: ResolveState
) -> None:
    """Require one legal persisted lifecycle transition per changed concern.

    An admitted concern widens the projection, so the candidate covers the
    current run's concerns plus whatever joined it. What may never happen is
    a concern leaving the projection: that would drop recorded work.
    """
    before = progress_index(current.progress)
    after = progress_index(candidate.progress)
    concern_ids = {concern.id for concern in candidate.concerns}
    if after.keys() != concern_ids or not before.keys() <= after.keys():
        raise StateTransitionError("resolver progress must cover every concern exactly")
    for identifier, prior in before.items():
        next_item = after[identifier]
        if next_item.status == prior.status:
            continue
        if next_item.status not in CONCERN_TRANSITIONS[prior.status]:
            raise StateTransitionError(
                f"concern {identifier!r} cannot move from {prior.status} "
                f"to {next_item.status}"
            )


class ResolverStateRepository:
    """Persist a complete state and its stable operational projections."""

    def __init__(self, state_root: Path, run_id: str) -> None:
        self.root = state_root / run_id

    def exists(self) -> bool:
        return (self.root / "state.json").exists()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold one process-wide run lease, released automatically after a crash."""
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".run.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise StateTransitionError(
                    f"resolver run {self.root.name!r} is already active"
                ) from error
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def load(self) -> ResolveState:
        path = self.root / "state.json"
        if not path.exists():
            raise FileNotFoundError(f"resolver state does not exist: {path}")
        try:
            return ResolveState.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as error:
            raise StateCorruptionError(
                f"resolver state at {path} cannot be decoded; restore the file "
                "or remove the run directory to start over"
            ) from error

    def save(self, state: ResolveState) -> None:
        if state.run_id != self.root.name:
            raise StateTransitionError(
                f"state run id {state.run_id!r} does not match {self.root.name!r}"
            )
        if self.exists():
            current = self.load()
            if (
                state.source != current.source
                or state.spec != current.spec
                or state.config_digest != current.config_digest
            ):
                raise StateTransitionError(
                    "resolver source and specification are immutable"
                )
            if state.concerns[: len(current.concerns)] != current.concerns:
                raise StateTransitionError(
                    "a recorded resolver concern is immutable; a concern "
                    "discovered later joins the run beside them"
                )
            validate_progress_transition(current, state)
            resumed = (
                current.phase == ResolvePhase.FAILED
                and current.resume_from is not None
                and state.phase == current.resume_from
            )
            terminal = state.phase in {ResolvePhase.FAILED, ResolvePhase.ABORTED}
            next_phase = (
                PHASE_TRANSITIONS[current.phase]
                if current.phase in PHASE_TRANSITIONS
                else None
            )
            if (
                state.phase != current.phase
                and not resumed
                and not terminal
                and state.phase != next_phase
            ):
                raise StateTransitionError(
                    f"resolver phase cannot move from {current.phase} to {state.phase}"
                )
        self.root.mkdir(parents=True, exist_ok=True)
        for directory in ["agents", "reviews", "integration"]:
            (self.root / directory).mkdir(exist_ok=True)
        self.write_model("state.json", state)
        self.write_model("concerns.json", ConcernsDocument(concerns=state.concerns))
        self.write_model(
            "questions.json",
            state.questions or QuestionBatch(run_id=state.run_id, questions=[]),
        )
        self.write_model(
            "answers.json",
            state.answers or AnswerBatch(run_id=state.run_id, answers=[]),
        )
        self.write_model("leases.json", LeasesDocument(leases=state.leases))
        self.write_model("bases.json", BasesDocument(bases=state.bases))

    def write_agent_round(self, state: ResolveState) -> None:
        """Write each complete round independently for inspection and resumption."""
        for outcome in state.outcomes:
            for round_record in outcome.rounds:
                self.write_round(round_record)

    def write_round(self, round_record: AgentRound) -> None:
        """Persist one complete worker/reviewer round before the next transition."""
        identifier = round_record.concern_id
        self.write_model(
            f"agents/{identifier}-round-{round_record.round}.json",
            round_record.worker,
        )
        self.write_model(
            f"reviews/{identifier}-round-{round_record.round}.json",
            round_record.review,
        )

    def write_model(self, relative: str, value: PersistedResolverModel) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            value.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(path)  # lup: ignore[string-replace] — atomic Path rename
