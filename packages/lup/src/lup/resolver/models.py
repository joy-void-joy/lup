"""Immutable, schema-versioned semantic resolver records."""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lup.harness.models import ResolveSpec

FROZEN = ConfigDict(frozen=True)


class ResolvePhase(StrEnum):
    """Persisted resolver phase names in their only valid forward order."""

    INVENTORY = "inventory"
    QUESTIONS = "questions"
    ELIGIBILITY = "eligibility"
    DAG = "dag"
    LEASES = "leases"
    WORKERS = "workers"
    DEPENDENCY_BASES = "dependency_bases"
    REVIEW = "review"
    INTEGRATION = "integration"
    VERIFICATION = "verification"
    ACCEPTANCE = "acceptance"
    CLEANUP = "cleanup"
    COMPLETE = "complete"
    FAILED = "failed"


class ConcernStatus(StrEnum):
    """Persisted lifecycle of one independently scheduled concern."""

    DISCOVERED = "discovered"
    WAITING_FOR_ANSWERS = "waiting_for_answers"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    LEASED = "leased"
    RUNNING = "running"
    VALIDATING = "validating"
    REVIEWING = "reviewing"
    REVISING = "revising"
    VERIFIED = "verified"
    INTEGRATING = "integrating"
    INTEGRATED = "integrated"
    CLEANED = "cleaned"
    RETAINED = "retained"
    FAILED = "failed"


class SourceSnapshot(BaseModel):
    model_config = FROZEN

    branch: str
    commit: str


class ReviewNote(BaseModel):
    model_config = FROZEN

    file: Path
    line: int = Field(ge=1)
    text: str


class InventoryNote(ReviewNote):
    """One review note together with the source context used for planning."""

    context: str


class AcceptanceCriterion(BaseModel):
    model_config = FROZEN

    id: str
    description: str


class MaterialQuestion(BaseModel):
    model_config = FROZEN

    id: str
    concern_id: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
    recommendation: str | None = None

    @model_validator(mode="after")
    def recommendation_is_a_choice(self) -> "MaterialQuestion":
        if (
            self.recommendation is not None
            and self.choices
            and self.recommendation not in self.choices
        ):
            raise ValueError(
                f"question {self.id!r} recommendation is not one of its choices"
            )
        return self


class QuestionBatch(BaseModel):
    model_config = FROZEN

    run_id: str
    questions: list[MaterialQuestion]

    @model_validator(mode="after")
    def unique_questions(self) -> "QuestionBatch":
        identifiers = [question.id for question in self.questions]
        if len(identifiers) != len(dict.fromkeys(identifiers)):
            raise ValueError("question ids must be unique")
        return self


class QuestionAnswer(BaseModel):
    model_config = FROZEN

    question_id: str
    value: str


class AnswerBatch(BaseModel):
    model_config = FROZEN

    run_id: str
    answers: list[QuestionAnswer]

    @model_validator(mode="after")
    def unique_answers(self) -> "AnswerBatch":
        identifiers = [answer.question_id for answer in self.answers]
        if len(identifiers) != len(dict.fromkeys(identifiers)):
            raise ValueError("answer question ids must be unique")
        return self


class ConcernShape(BaseModel):
    """Planning fields shared by a planned concern and its materialization."""

    model_config = FROZEN

    id: str = Field(min_length=1)
    title: str
    spec: str
    files: list[Path] = Field(default_factory=list)
    criteria: list[AcceptanceCriterion] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    questions: list[MaterialQuestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_are_local_and_unique(self) -> "ConcernShape":
        if Path(self.id).name != self.id or self.id in {"integration", "review"}:
            raise ValueError(f"concern id {self.id!r} is reserved or not path-safe")
        if any(question.concern_id != self.id for question in self.questions):
            raise ValueError(f"concern {self.id!r} contains a foreign question")
        for values, label in [
            (self.dependencies, "dependencies"),
            ([criterion.id for criterion in self.criteria], "criteria"),
            ([question.id for question in self.questions], "questions"),
        ]:
            if len(values) != len(dict.fromkeys(values)):
                raise ValueError(f"concern {self.id!r} has duplicate {label}")
        if self.id in self.dependencies:
            raise ValueError(f"concern {self.id!r} cannot depend on itself")
        return self


class Concern(ConcernShape):
    """One generalized concern and its complete dependency/acceptance inputs."""

    notes: list[ReviewNote] = Field(default_factory=list)
    eligible: bool = True
    integration_approved: bool = False


class PlannedConcern(ConcernShape):
    """One planned concern referencing review notes by zero-based position.

    The planner never echoes note content — positional references make copy
    fidelity a mechanical property instead of a model obligation.
    """

    note_indexes: list[int] = Field(min_length=1)


class ConcernEligibility(BaseModel):
    model_config = FROZEN

    concern_id: str
    eligible: bool
    integration_approved: bool
    reason: str = ""


class ConcernProgress(BaseModel):
    """Atomic persisted status for one concern in the resolver DAG."""

    model_config = FROZEN

    concern_id: str
    status: ConcernStatus = ConcernStatus.DISCOVERED
    reason: str = ""


class WritableRootLease(BaseModel):
    model_config = FROZEN

    concern_id: str
    root: Path
    branch: str
    active: bool = True


class DependencyBase(BaseModel):
    model_config = FROZEN

    concern_id: str
    parent_concerns: list[str]
    parent_commits: list[str]
    commit: str
    semantic_join: bool = False


class WorkAssignment(BaseModel):
    model_config = FROZEN

    run_id: str
    concern: Concern
    lease: WritableRootLease
    dependency_base: DependencyBase
    rendered_skill_invocation: str
    answers: list[QuestionAnswer] = Field(default_factory=list)


class WorkerQuestionResolution(BaseModel):
    model_config = FROZEN

    report: "WorkerReport"
    assignment: WorkAssignment


class WorkerReport(BaseModel):
    model_config = FROZEN

    concern_id: str
    changed: bool
    summary: str
    files_changed: list[Path] = Field(default_factory=list)
    swept_beyond_scope: list[Path] = Field(default_factory=list)
    questions: list[MaterialQuestion] = Field(default_factory=list)


class DiffValidation(BaseModel):
    model_config = FROZEN

    concern_id: str
    valid: bool
    commit: str | None = None
    reason: str = ""


class ReviewReport(BaseModel):
    model_config = FROZEN

    concern_id: str
    accepted: bool
    generalized: bool
    reason: str
    residual: list[str] = Field(default_factory=list)
    criteria_met: list[str] = Field(default_factory=list)


class MergeReport(BaseModel):
    model_config = FROZEN

    completed: bool
    summary: str
    unresolved_paths: list[Path] = Field(default_factory=list)


class AgentRound(BaseModel):
    model_config = FROZEN

    concern_id: str
    round: int = Field(ge=1)
    worker: WorkerReport
    diff: DiffValidation
    review: ReviewReport


class ConcernOutcome(BaseModel):
    model_config = FROZEN

    concern_id: str
    branch: str
    commit: str | None = None
    verified: bool = False
    integrated: bool = False
    rounds: list[AgentRound] = Field(default_factory=list)
    failure: str | None = None


class ConcernExecution(BaseModel):
    model_config = FROZEN

    base: DependencyBase
    outcome: ConcernOutcome


class IntegrationRecord(BaseModel):
    model_config = FROZEN

    branch: str
    worktree: Path
    concerns: list[str]
    commit: str | None = None
    completed: bool = False


class VerificationRecord(BaseModel):
    model_config = FROZEN

    name: str
    arguments: list[str]
    passed: bool
    exit_code: int


class FinalReview(BaseModel):
    model_config = FROZEN

    accepted: bool
    reason: str
    residual: list[str] = Field(default_factory=list)


class CleanupRecord(BaseModel):
    model_config = FROZEN

    path: Path
    branch: str
    action: Literal["removed", "retained"]
    reason: str


class ResolveInventory(BaseModel):
    model_config = FROZEN

    source: SourceSnapshot
    concerns: list[Concern]

    @model_validator(mode="after")
    def unique_concerns(self) -> "ResolveInventory":
        identifiers = [concern.id for concern in self.concerns]
        if len(identifiers) != len(dict.fromkeys(identifiers)):
            raise ValueError("concern ids must be unique")
        return self


class ResolveRequest(BaseModel):
    """Unorganized review evidence supplied to the shared inventory phase."""

    model_config = FROZEN

    source: SourceSnapshot
    notes: list[InventoryNote] = Field(min_length=1)


class ConcernInventory(BaseModel):
    """Structured concern plan produced by the read-only inventory turn.

    Concerns reference the request's notes by position; the resolver
    materializes them into :class:`Concern` objects with the authoritative
    note content, so nothing the planner writes can drift from the evidence.
    """

    model_config = FROZEN

    concerns: list[PlannedConcern] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_concerns(self) -> "ConcernInventory":
        identifiers = [concern.id for concern in self.concerns]
        if len(identifiers) != len(dict.fromkeys(identifiers)):
            raise ValueError("planned concern ids must be unique")
        return self


class ResolverConfig(BaseModel):
    model_config = FROZEN

    state_root: Path
    workspace: Path
    worktree_root: Path
    run_id: str
    integration_branch: str
    max_revision_rounds: int = Field(default=2, ge=0)
    max_question_rounds: int = Field(default=2, ge=0)
    verification_commands: list["VerificationCommand"] = Field(default_factory=list)

    @model_validator(mode="after")
    def run_identity_is_path_safe(self) -> "ResolverConfig":
        if not self.run_id or Path(self.run_id).name != self.run_id:
            raise ValueError("resolver run id must be a non-empty path-safe name")
        if not self.verification_commands:
            raise ValueError("resolver integration requires verification commands")
        return self


class VerificationCommand(BaseModel):
    model_config = FROZEN

    name: str
    arguments: list[str]


class ConcernsDocument(BaseModel):
    model_config = FROZEN

    concerns: list[Concern]


class LeasesDocument(BaseModel):
    model_config = FROZEN

    leases: list[WritableRootLease]


class BasesDocument(BaseModel):
    model_config = FROZEN

    bases: list[DependencyBase]


class ResolveState(BaseModel):
    """Complete resumable run state written atomically after every transition."""

    model_config = FROZEN

    schema_version: int = 1
    config_digest: str
    run_id: str
    phase: ResolvePhase
    source: SourceSnapshot
    spec: ResolveSpec
    concerns: list[Concern]
    progress: list[ConcernProgress]
    questions: QuestionBatch | None = None
    answers: AnswerBatch | None = None
    eligibility: list[ConcernEligibility] = Field(default_factory=list)
    leases: list[WritableRootLease] = Field(default_factory=list)
    bases: list[DependencyBase] = Field(default_factory=list)
    outcomes: list[ConcernOutcome] = Field(default_factory=list)
    integration: IntegrationRecord | None = None
    verification: list[VerificationRecord] = Field(default_factory=list)
    final_review: FinalReview | None = None
    accepted: bool | None = None
    cleanup: list[CleanupRecord] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    resume_from: ResolvePhase | None = None

    @model_validator(mode="after")
    def complete_progress_projection(self) -> "ResolveState":
        concern_ids = [concern.id for concern in self.concerns]
        progress_ids = [item.concern_id for item in self.progress]
        if sorted(concern_ids) != sorted(progress_ids):
            raise ValueError("resolver progress must cover every concern exactly")
        return self


class ResolveManifest(BaseModel):
    model_config = FROZEN

    schema_version: int = 1
    run_id: str
    source: SourceSnapshot
    review_branch: str
    outcomes: list[ConcernOutcome]
    verification: list[VerificationRecord]
    final_review: FinalReview | None = None
    accepted: bool | None = None
    cleanup: list[CleanupRecord] = Field(default_factory=list)
