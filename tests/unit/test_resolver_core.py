"""Deterministic resolver DAG, lease, state, and commit-authority tests."""

from collections import Counter
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest
from pydantic import BaseModel

from lup.harness.contracts import SkillInvocationRenderer
from lup.harness.models import ResolveSpec, SkillInvocation
from lup.harness.process import (
    ExitStatus,
    LaunchRequest,
    LocalProcessLauncher,
    ProcessLauncher,
)
from lup.resolver.dag import ConcernGraph, ConcernGraphError
from lup.resolver.mailbox import (
    AnswerDoor,
    AnswerOffer,
    PendingQuestion,
    QuestionMailbox,
)
from lup.resolver.contracts import (
    ResolverAwaitingAnswers,
    ResolverObserver,
    WorktreePreparer,
)
from lup.resolver.core import (
    APPROVE,
    DEFER,
    ResolverCore,
    ResolverInvariantError,
    approval_decisions,
    approval_question,
)
from lup.resolver.models import (
    AdmissionRequest,
    AnswerBatch,
    AcceptanceCriterion,
    Concern,
    ConcernInventory,
    ConcernOrigin,
    ConcernOutcome,
    ConcernProgress,
    ConcernStatus,
    DependencyBase,
    IntegrationRecord,
    InventoryNote,
    MaterialQuestion,
    MergeReport,
    QuestionAnswer,
    ResolveInventory,
    ResolveRequest,
    ResolverConfig,
    ResolvePhase,
    ResolveState,
    ReviewNote,
    ReviewReport,
    SourceSnapshot,
    VerificationCommand,
    WorkerReport,
    WritableRootLease,
)
from lup.resolver.orchestrator import (
    DependencyBaseBuilder,
    LeaseViolationError,
    WorktreeOrchestrator,
    WritableRootLeases,
)
from lup.resolver.state import (
    ResolverStateRepository,
    StateCorruptionError,
    StateTransitionError,
)
from lup.runtime.contracts import Session, Turn
from lup.runtime.factory import SessionFactory
from lup.runtime.composition import is_output_model
from lup.runtime.models import (
    SessionHandle,
    SessionId,
    TurnHandle,
    TurnIdentifiers,
    TurnId,
    TurnRequest,
    TurnResult,
)
from lup.types import JsonObject, Usage


def concern(
    identifier: str,
    dependencies: list[str] | None = None,
    *,
    approved: bool = True,
) -> Concern:
    return Concern(
        id=identifier,
        title=identifier.title(),
        spec=f"Resolve {identifier}",
        criteria=[AcceptanceCriterion(id=f"{identifier}-done", description="done")],
        dependencies=dependencies or [],
        integration_approved=approved,
    )


def seed_offer(core: ResolverCore, question_id: str, value: str) -> None:
    """Answer through the same door a `--answer` flag uses.

    Offers may precede their questions, so a whole run's decisions can be
    supplied before it starts — which is what replaces a test broker.
    """
    core.mailbox.offer(
        AnswerOffer(
            run_id=core.config.run_id,
            question_id=question_id,
            value=value,
            door=AnswerDoor.FLAG,
            offered_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )


def seed_approvals(core: ResolverCore, concerns: list[Concern]) -> None:
    for item in concerns:
        seed_offer(core, approval_question(item).id, APPROVE)


def worker_asks(mailbox: QuestionMailbox, run_id: str, asked: MaterialQuestion) -> None:
    """Queue a question exactly as a worker's ``queue_questions`` tool does.

    The fake worker cannot call an MCP tool, so it writes the record the
    tool would write. Everything downstream — promotion, folding, and the
    park — then runs against the real mailbox rather than a stub.
    """
    mailbox.queue(
        PendingQuestion(
            run_id=run_id,
            question=asked,
            asked_by=asked.concern_id,
            asked_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )


def dynamic_question(concern_id: str) -> MaterialQuestion:
    return MaterialQuestion(
        id=f"{concern_id}-dynamic",
        concern_id=concern_id,
        prompt="Choose the durable implementation",
        choices=["durable"],
        recommendation="durable",
    )


def resolve_spec() -> ResolveSpec:
    return ResolveSpec(
        id="resolve",
        worker_identity="resolver-worker",
        worker_skill=SkillInvocation(plugin="lup", skill="worker"),
        review_skill=SkillInvocation(plugin="lup", skill="review"),
        merge_skill=SkillInvocation(plugin="lup", skill="merge"),
    )


def test_dag_batches_roots_single_parent_and_multi_parent() -> None:
    graph = ConcernGraph(
        [
            concern("a"),
            concern("b"),
            concern("c", ["a"]),
            concern("d", ["a", "b"]),
            concern("e", ["c", "d"]),
        ]
    )

    assert [[item.id for item in batch] for batch in graph.topological_batches()] == [
        ["a", "b"],
        ["c", "d"],
        ["e"],
    ]
    assert [item.id for item in graph.ancestors("e")] == ["a", "b", "c", "d"]


def test_dag_rejects_missing_nodes_and_cycles_and_filters_unapproved_ancestry() -> None:
    with pytest.raises(ConcernGraphError, match="missing nodes"):
        ConcernGraph([concern("child", ["missing"])])
    with pytest.raises(ConcernGraphError, match="contains a cycle"):
        ConcernGraph([concern("a", ["b"]), concern("b", ["a"])])

    graph = ConcernGraph(
        [concern("parent", approved=False), concern("child", ["parent"])]
    )
    assert graph.approved() == []


def test_a_question_id_must_name_one_mailbox_file() -> None:
    with pytest.raises(ValueError, match="not a path-safe name"):
        MaterialQuestion(id="nested/id", concern_id="a", prompt="Decide?")


def test_a_missing_approval_answer_is_a_named_invariant() -> None:
    """Answers arrive per question now, so absence must read as itself."""
    with pytest.raises(ResolverInvariantError, match="no persisted approval answer"):
        approval_decisions([concern("a")], AnswerBatch(run_id="run-1", answers=[]))


def test_persisted_approval_answers_filter_deferred_ancestry() -> None:
    concerns = [concern("parent"), concern("child", ["parent"])]
    answers = AnswerBatch(
        run_id="approval-decisions",
        answers=[
            QuestionAnswer(
                question_id=approval_question(concerns[0]).id,
                value=DEFER,
            ),
            QuestionAnswer(
                question_id=approval_question(concerns[1]).id,
                value=APPROVE,
            ),
        ],
    )

    decisions = approval_decisions(concerns, answers)

    assert decisions.directly_approved == ["child"]
    assert decisions.eligible == []


def test_leases_are_unique_and_bounded(tmp_path: Path) -> None:
    leases = WritableRootLeases(tmp_path / "agents")
    first = leases.acquire("a", "resolve/a")
    second = leases.acquire("b", "resolve/b")

    assert first.root != second.root
    leases.assert_path("a", first.root / "src" / "module.py")
    with pytest.raises(LeaseViolationError, match="outside"):
        leases.assert_path("a", second.root / "module.py")
    with pytest.raises(LeaseViolationError, match="already has"):
        leases.acquire("a", "resolve/a-2")


def test_dependency_bases_cover_root_single_and_semantic_join() -> None:
    source = SourceSnapshot(branch="feature", commit="source-sha")
    builder = DependencyBaseBuilder(source)
    root = builder.build(concern("root"), {})
    single = builder.build(concern("single", ["root"]), {"root": "root-sha"})

    assert root.commit == "source-sha"
    assert single.commit == "root-sha"
    with pytest.raises(ValueError, match="semantic multi-parent join"):
        builder.build(
            concern("join", ["left", "right"]),
            {"left": "left-sha", "right": "right-sha"},
        )
    joined = builder.build(
        concern("join", ["left", "right"]),
        {"left": "left-sha", "right": "right-sha"},
        joined_commit="join-sha",
    )
    assert joined == DependencyBase(
        concern_id="join",
        parent_concerns=["left", "right"],
        parent_commits=["left-sha", "right-sha"],
        commit="join-sha",
        semantic_join=True,
    )


def test_state_repository_writes_atomic_typed_projection_tree(tmp_path: Path) -> None:
    state = ResolveState(
        config_digest="config-sha",
        run_id="run-1",
        phase=ResolvePhase.INVENTORY,
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        spec=resolve_spec(),
        concerns=[concern("a")],
        progress=[ConcernProgress(concern_id="a")],
    )
    repository = ResolverStateRepository(tmp_path, "run-1")
    repository.save(state)

    assert repository.load() == state
    assert sorted(path.name for path in repository.root.iterdir()) == [
        "agents",
        "answers.json",
        "bases.json",
        "concerns.json",
        "integration",
        "leases.json",
        "questions.json",
        "reviews",
        "state.json",
    ]
    assert not list(repository.root.glob("*.tmp"))

    with pytest.raises(StateTransitionError, match="cannot move"):
        repository.save(state.model_copy(update={"phase": ResolvePhase.DAG}))
    questions = state.model_copy(update={"phase": ResolvePhase.QUESTIONS})
    repository.save(questions)
    with pytest.raises(StateTransitionError, match="cannot move"):
        repository.save(state)


def test_undecodable_persisted_state_raises_a_typed_recovery_error(
    tmp_path: Path,
) -> None:
    state = ResolveState(
        config_digest="config-sha",
        run_id="run-1",
        phase=ResolvePhase.INVENTORY,
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        spec=resolve_spec(),
        concerns=[concern("a")],
        progress=[ConcernProgress(concern_id="a")],
    )
    repository = ResolverStateRepository(tmp_path, "run-1")
    repository.save(state)
    path = repository.root / "state.json"
    complete = path.read_text(encoding="utf-8")

    path.write_text(complete[: len(complete) // 2], encoding="utf-8")
    with pytest.raises(StateCorruptionError, match="restore the file"):
        repository.load()

    path.write_text('{"run_id": "run-1"}', encoding="utf-8")
    with pytest.raises(StateCorruptionError, match="remove the run directory"):
        repository.load()

    path.unlink()
    with pytest.raises(FileNotFoundError, match="does not exist"):
        repository.load()


class RecordingLauncher(ProcessLauncher):
    def __init__(self) -> None:
        self.requests: list[LaunchRequest] = []
        self.rev_parse_calls = 0

    def launch(self, request: LaunchRequest) -> ExitStatus:
        self.requests.append(request)
        stdout = ""
        if request.arguments[1:3] == ["rev-parse", "HEAD"]:
            self.rev_parse_calls += 1
            stdout = "base-sha\n" if self.rev_parse_calls == 1 else "created-sha\n"
        elif request.arguments[1:3] == ["diff", "--name-only"]:
            stdout = "src/module.py\n"
        elif request.arguments[1:3] == ["branch", "--show-current"]:
            stdout = "resolve/a\n"
        return ExitStatus(code=0, stdout=stdout)


class FailingVerificationLauncher(ProcessLauncher):
    def launch(self, request: LaunchRequest) -> ExitStatus:
        return ExitStatus(code=1, stderr=f"failed: {request.arguments}")


class SuccessfulLauncher(ProcessLauncher):
    def launch(self, request: LaunchRequest) -> ExitStatus:
        return ExitStatus(code=0)


class MissingBranchLauncher(ProcessLauncher):
    def launch(self, request: LaunchRequest) -> ExitStatus:
        return ExitStatus(code=1)


def unused_session_factory() -> SessionFactory:
    def refuse(
        resume: SessionId | None = None,
    ) -> AbstractAsyncContextManager[SessionHandle]:
        raise AssertionError(f"session factory should not be opened: {resume}")

    return SessionFactory(refuse)


class UnusedInvocationRenderer(SkillInvocationRenderer):
    def render(self, invocation: SkillInvocation) -> str:
        raise AssertionError(f"invocation should not be rendered: {invocation}")


class StaticResultTurn[T: BaseModel | None](Turn[T]):
    def __init__(self, result: TurnResult[T]) -> None:
        self.value = result

    async def result(self) -> TurnResult[T]:
        return self.value


type ResolverResponse = Callable[[Path, str], JsonObject]


class ResolverTestSession(Session):
    def __init__(self, root: Path, response: ResolverResponse) -> None:
        self.root = root
        self.response = response
        self.sequence = 0

    async def start[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnHandle[T]:
        output_type = request.output_type
        if not is_output_model(output_type):
            raise AssertionError("resolver turns must request typed output")
        self.sequence += 1
        output = output_type.model_validate(
            self.response(self.root, output_type.__name__)
        )
        result = TurnResult[T].model_validate(
            {
                "output": output,
                "messages": [],
                "blocks": [],
                "usage": Usage(),
                "duration": timedelta(),
                "identifiers": TurnIdentifiers(
                    session=SessionId(value=f"resolver-{self.root.name}"),
                    turn=TurnId(value=f"turn-{self.sequence}"),
                ),
            }
        )
        return TurnHandle[T](turn=StaticResultTurn(result))


def resolver_test_factory(root: Path, response: ResolverResponse) -> SessionFactory:
    @asynccontextmanager
    async def open_session(
        _resume: SessionId | None = None,
    ) -> AsyncGenerator[SessionHandle]:
        yield SessionHandle(session=ResolverTestSession(root, response))

    return SessionFactory(open_session)


class LiteralInvocationRenderer(SkillInvocationRenderer):
    def render(self, invocation: SkillInvocation) -> str:
        return f"{invocation.plugin}:{invocation.skill}"


def two_note_request() -> ResolveRequest:
    """Evidence wide enough that a plan can quietly leave one note behind."""
    return ResolveRequest(
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        notes=[
            InventoryNote(
                file=Path("src/module.py"),
                line=7,
                text="close the union",
                context="def render(self):  # lup: close the union",
            ),
            InventoryNote(
                file=Path("docs/guide.md"),
                line=1,
                text="this guide repeats itself",
                context="# Guide  <!-- lup: this guide repeats itself -->",
            ),
        ],
    )


def planning_core(tmp_path: Path, response: ResolverResponse) -> ResolverCore:
    """A core wired for planning turns only."""
    return ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=tmp_path,
            worktree_root=tmp_path / "worktrees",
            run_id="coverage",
            integration_branch="resolve/coverage/review",
            verification_commands=[
                VerificationCommand(name="verify", arguments=["git", "diff"])
            ],
        ),
        resolve_spec(),
        lambda context: resolver_test_factory(context.root, response),
        lambda root: resolver_test_factory(root, response),
        LiteralInvocationRenderer(),
        RecordingLauncher(),
    )


def concern_referencing(indexes: list[int]) -> JsonObject:
    return {
        "id": f"concern-{'-'.join(str(index) for index in indexes)}",
        "title": "A concern",
        "spec": "Do the thing",
        "criteria": [{"id": "done", "description": "It is done"}],
        "evidence_indexes": [index for index in indexes],
    }


def plan_of(*concerns: JsonObject) -> JsonObject:
    return {"concerns": [concern for concern in concerns]}


@pytest.mark.asyncio
async def test_a_note_no_concern_claims_names_itself_and_stops_the_run(
    tmp_path: Path,
) -> None:
    """Coverage is the surviving invariant: an ignored note goes unresolved."""
    core = planning_core(tmp_path, lambda *_: plan_of(concern_referencing([0])))

    with pytest.raises(ResolverInvariantError, match=r"no concern references: \[1\]"):
        await core.plan_inventory(two_note_request())


@pytest.mark.asyncio
async def test_a_plan_that_ignored_a_note_is_corrected_rather_than_discarded(
    tmp_path: Path,
) -> None:
    """The complaint names the gap, so the next attempt can close it."""
    replies = iter(
        [
            plan_of(concern_referencing([0])),
            plan_of(concern_referencing([0]), concern_referencing([1])),
        ]
    )
    core = planning_core(tmp_path, lambda *_: next(replies))

    inventory = await core.plan_inventory(two_note_request())

    assert [note.line for concern in inventory.concerns for note in concern.notes] == [
        7,
        1,
    ]


@pytest.mark.asyncio
async def test_one_note_raising_two_issues_reaches_both_concerns(
    tmp_path: Path,
) -> None:
    """A note is not a unit of work — several concerns may answer one note."""
    request = ResolveRequest(
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        notes=[
            InventoryNote(
                file=Path("src/module.py"),
                line=7,
                text="close the union, and write the principle into guidance",
                context="def render(self):  # lup: close the union",
            )
        ],
    )

    def reviewer_response(_root: Path, output_name: str) -> JsonObject:
        assert output_name == ConcernInventory.__name__
        return {
            "concerns": [
                {
                    "id": "close-the-union",
                    "title": "Close the union",
                    "spec": "Let each variant answer for itself",
                    "criteria": [{"id": "closed", "description": "No dispatch"}],
                    "evidence_indexes": [0],
                },
                {
                    "id": "write-the-principle",
                    "title": "Write the principle into guidance",
                    "spec": "State the convention where conventions live",
                    "criteria": [{"id": "stated", "description": "Guidance says it"}],
                    "evidence_indexes": [0],
                },
            ]
        }

    core = ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=tmp_path,
            worktree_root=tmp_path / "worktrees",
            run_id="shared",
            integration_branch="resolve/shared/review",
            verification_commands=[
                VerificationCommand(name="verify", arguments=["git", "diff"])
            ],
        ),
        resolve_spec(),
        lambda context: resolver_test_factory(context.root, reviewer_response),
        lambda root: resolver_test_factory(root, reviewer_response),
        LiteralInvocationRenderer(),
        RecordingLauncher(),
    )

    inventory = await core.plan_inventory(request)

    shared = ReviewNote(
        file=Path("src/module.py"),
        line=7,
        text="close the union, and write the principle into guidance",
    )
    assert [concern.notes for concern in inventory.concerns] == [[shared], [shared]]


@pytest.mark.asyncio
async def test_inventory_planner_clusters_every_contextual_note_once(
    tmp_path: Path,
) -> None:
    request = ResolveRequest(
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        notes=[
            InventoryNote(
                file=Path("src/module.py"),
                line=7,
                text="use the domain type",
                context="value: int  # lup: use the domain type",
            )
        ],
    )

    def reviewer_response(_root: Path, output_name: str) -> JsonObject:
        assert output_name == ConcernInventory.__name__
        return {
            "concerns": [
                {
                    "id": "domain-type",
                    "title": "Use the domain type",
                    "spec": "Represent the domain concept explicitly",
                    "criteria": [
                        {"id": "typed", "description": "Domain type is explicit"}
                    ],
                    "evidence_indexes": [0],
                }
            ]
        }

    core = ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=tmp_path,
            worktree_root=tmp_path / "worktrees",
            run_id="inventory",
            integration_branch="resolve/inventory/review",
            verification_commands=[
                VerificationCommand(name="verify", arguments=["git", "diff"])
            ],
        ),
        resolve_spec(),
        lambda context: resolver_test_factory(context.root, reviewer_response),
        lambda root: resolver_test_factory(root, reviewer_response),
        LiteralInvocationRenderer(),
        RecordingLauncher(),
    )

    inventory = await core.plan_inventory(request)

    assert inventory.source == request.source
    assert [item.id for item in inventory.concerns] == ["domain-type"]
    assert inventory.concerns[0].eligible
    assert inventory.concerns[0].integration_approved
    # Notes are materialized from the request by position — context stripped,
    # content authoritative, never echoed by the planner.
    assert inventory.concerns[0].notes == [
        ReviewNote(file=Path("src/module.py"), line=7, text="use the domain type")
    ]


class JoinLauncher(ProcessLauncher):
    """Answer the join probes, reporting one unmerged path with chosen markers."""

    def __init__(self, marker_check_code: int) -> None:
        self.marker_check_code = marker_check_code

    def launch(self, request: LaunchRequest) -> ExitStatus:
        match request.arguments[1:3]:
            case ["diff", "--check"]:
                return ExitStatus(code=self.marker_check_code, stdout="leftover marker")
            case ["diff", "--name-only"]:
                return ExitStatus(code=0, stdout="src/module.py\n")
            case ["status", "--porcelain"]:
                return ExitStatus(code=0, stdout="UU src/module.py\n")
            case ["rev-parse", "HEAD"]:
                return ExitStatus(code=0, stdout="joined-sha\n")
            case _:
                return ExitStatus(code=0)


class AncestryLauncher(ProcessLauncher):
    """Answer merge-base ancestry with a fixed verdict, recording every call."""

    def __init__(self, is_ancestor: bool) -> None:
        self.is_ancestor = is_ancestor
        self.arguments: list[list[str]] = []

    def launch(self, request: LaunchRequest) -> ExitStatus:
        self.arguments.append(request.arguments)
        if request.arguments[1:3] == ["merge-base", "--is-ancestor"]:
            return ExitStatus(code=0 if self.is_ancestor else 1)
        return ExitStatus(code=0)


class MergingLauncher(ProcessLauncher):
    """Report an open merge against a chosen parent, recording every call."""

    def __init__(self, merge_head: str) -> None:
        self.merge_head = merge_head
        self.arguments: list[list[str]] = []

    def launch(self, request: LaunchRequest) -> ExitStatus:
        self.arguments.append(request.arguments)
        if request.arguments[1:3] == ["rev-parse", "-q"]:
            if not self.merge_head:
                return ExitStatus(code=1)
            return ExitStatus(code=0, stdout=f"{self.merge_head}\n")
        return ExitStatus(code=0)


def test_preparing_the_same_join_twice_leaves_the_open_merge_alone(
    tmp_path: Path,
) -> None:
    launcher = MergingLauncher("parent-sha")
    orchestrator = WorktreeOrchestrator(launcher, tmp_path)
    lease = WritableRootLeases(tmp_path / "agents").acquire("integration", "resolve/i")

    orchestrator.prepare_join(lease, ["head-sha", "parent-sha"])

    assert ["git", "merge", "--no-commit", "--no-ff", "parent-sha"] not in (
        launcher.arguments
    )


def test_preparing_a_different_join_still_opens_the_merge(tmp_path: Path) -> None:
    launcher = MergingLauncher("")
    orchestrator = WorktreeOrchestrator(launcher, tmp_path)
    lease = WritableRootLeases(tmp_path / "agents").acquire("integration", "resolve/i")

    orchestrator.prepare_join(lease, ["head-sha", "parent-sha"])

    assert [
        "git",
        "merge",
        "--no-commit",
        "--no-ff",
        "parent-sha",
    ] in launcher.arguments


def test_already_joined_reports_containment_from_merge_base(tmp_path: Path) -> None:
    lease = WritableRootLeases(tmp_path / "agents").acquire("integration", "resolve/i")

    contained = AncestryLauncher(is_ancestor=True)
    assert WorktreeOrchestrator(contained, tmp_path).already_joined(lease, "sha")
    assert contained.arguments == [
        ["git", "merge-base", "--is-ancestor", "sha", "HEAD"]
    ]

    absent = AncestryLauncher(is_ancestor=False)
    assert not WorktreeOrchestrator(absent, tmp_path).already_joined(lease, "sha")


def test_join_accepts_a_resolved_path_the_merger_left_unstaged(
    tmp_path: Path,
) -> None:
    orchestrator = WorktreeOrchestrator(JoinLauncher(marker_check_code=0), tmp_path)
    lease = WritableRootLeases(tmp_path / "agents").acquire("integration", "resolve/i")

    assert orchestrator.commit_join(lease, "resolve: integrate") == "joined-sha"


def test_join_still_refuses_a_path_whose_content_carries_markers(
    tmp_path: Path,
) -> None:
    orchestrator = WorktreeOrchestrator(JoinLauncher(marker_check_code=2), tmp_path)
    lease = WritableRootLeases(tmp_path / "agents").acquire("integration", "resolve/i")

    with pytest.raises(RuntimeError, match="invalid changes"):
        orchestrator.commit_join(lease, "resolve: integrate")


def test_only_orchestrator_creates_commits_and_reads_their_identity(
    tmp_path: Path,
) -> None:
    launcher = RecordingLauncher()
    orchestrator = WorktreeOrchestrator(launcher, tmp_path)
    leases = WritableRootLeases(tmp_path / "agents")
    lease = leases.acquire("a", "resolve/a")
    item = concern("a")

    orchestrator.create(lease, "base-sha")
    diff = orchestrator.validate_and_commit(
        item,
        WorkerReport(
            concern_id="a",
            changed=True,
            summary="updated module",
            files_changed=[Path("src/module.py")],
        ),
        lease,
        "base-sha",
        leases,
    )

    assert diff.valid
    assert diff.commit == "created-sha"
    assert [request.arguments for request in launcher.requests] == [
        ["git", "worktree", "add", "-b", "resolve/a", str(lease.root), "base-sha"],
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "HEAD"],
        ["git", "add", "-N", "."],
        ["git", "diff", "--check", "base-sha"],
        ["git", "diff", "--name-only", "base-sha"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", "resolve: A"],
        ["git", "rev-parse", "HEAD"],
    ]


@pytest.mark.asyncio
async def test_failed_integration_verification_is_not_marked_successful(
    tmp_path: Path,
) -> None:
    run_id = "verification-failure"
    integration_root = tmp_path / "integration"
    integration = IntegrationRecord(
        branch="resolve/review",
        worktree=integration_root,
        concerns=["a"],
        commit="integration-sha",
        completed=False,
    )
    state = ResolveState(
        config_digest="config-sha",
        run_id=run_id,
        phase=ResolvePhase.INTEGRATION,
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        spec=resolve_spec(),
        concerns=[concern("a")],
        progress=[ConcernProgress(concern_id="a", status=ConcernStatus.INTEGRATING)],
        leases=[
            WritableRootLease(
                concern_id="integration",
                root=integration_root,
                branch="resolve/review",
            )
        ],
        outcomes=[
            ConcernOutcome(
                concern_id="a",
                branch="resolve/a",
                commit="a-sha",
                verified=True,
            )
        ],
        integration=integration,
    )
    config = ResolverConfig(
        state_root=tmp_path / "state",
        workspace=tmp_path,
        worktree_root=tmp_path / "worktrees",
        run_id=run_id,
        integration_branch="resolve/review",
        verification_commands=[VerificationCommand(name="tests", arguments=["pytest"])],
    )
    core = ResolverCore(
        config,
        resolve_spec(),
        lambda _cwd: unused_session_factory(),
        lambda _cwd: unused_session_factory(),
        UnusedInvocationRenderer(),
        FailingVerificationLauncher(),
    )
    core.persist(state)

    with pytest.raises(ResolverInvariantError, match="verification failed"):
        await core.integrate(state, state.outcomes)

    persisted = core.repository.load()
    assert persisted.phase == ResolvePhase.VERIFICATION
    assert persisted.integration is not None
    assert not persisted.integration.completed
    assert [record.passed for record in persisted.verification] == [False]
    assert [outcome.integrated for outcome in persisted.outcomes] == [False]


def test_illegal_per_concern_transition_is_rejected(tmp_path: Path) -> None:
    state = ResolveState(
        config_digest="config-sha",
        run_id="illegal-progress",
        phase=ResolvePhase.INVENTORY,
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        spec=resolve_spec(),
        concerns=[concern("a")],
        progress=[ConcernProgress(concern_id="a")],
    )
    repository = ResolverStateRepository(tmp_path, state.run_id)
    repository.save(state)

    with pytest.raises(StateTransitionError, match="cannot move"):
        repository.save(
            state.model_copy(
                update={
                    "progress": [
                        ConcernProgress(concern_id="a", status=ConcernStatus.INTEGRATED)
                    ]
                }
            )
        )


def test_interrupted_concern_returns_to_persisted_lease_boundary(
    tmp_path: Path,
) -> None:
    run_id = "interrupted"
    lease = WritableRootLease(
        concern_id="a",
        root=tmp_path / "worktrees" / "a",
        branch="resolve/interrupted/a",
    )
    state = ResolveState(
        config_digest="config-sha",
        run_id=run_id,
        phase=ResolvePhase.WORKERS,
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        spec=resolve_spec(),
        concerns=[concern("a")],
        progress=[ConcernProgress(concern_id="a", status=ConcernStatus.REVIEWING)],
        leases=[lease],
        bases=[
            DependencyBase(
                concern_id="a",
                parent_concerns=[],
                parent_commits=[],
                commit="source-sha",
            )
        ],
    )
    core = ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=tmp_path,
            worktree_root=tmp_path / "worktrees",
            run_id=run_id,
            integration_branch="resolve/interrupted/review",
            verification_commands=[
                VerificationCommand(name="tests", arguments=["pytest"])
            ],
        ),
        resolve_spec(),
        lambda _cwd: unused_session_factory(),
        lambda _cwd: unused_session_factory(),
        UnusedInvocationRenderer(),
        MissingBranchLauncher(),
    )
    core.persist(state)

    core.restore_leases(state)

    persisted = core.repository.load()
    assert persisted.progress == [
        ConcernProgress(
            concern_id="a",
            status=ConcernStatus.LEASED,
            reason="retry lease restored",
        )
    ]


def test_releasing_a_run_cleans_concern_branches_and_keeps_the_review_one(
    tmp_path: Path,
) -> None:
    """Cleanup is unconditional; there is no decision left to spend a park on."""
    run_id = "acceptance"
    concern_lease = WritableRootLease(
        concern_id="a",
        root=tmp_path / "worktrees" / "a",
        branch="resolve/acceptance/a",
    )
    integration_lease = WritableRootLease(
        concern_id="integration",
        root=tmp_path / "worktrees" / "integration",
        branch="resolve/acceptance/review",
    )
    state = ResolveState(
        config_digest="config-sha",
        run_id=run_id,
        phase=ResolvePhase.VERIFICATION,
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        spec=resolve_spec(),
        concerns=[concern("a")],
        progress=[ConcernProgress(concern_id="a", status=ConcernStatus.INTEGRATED)],
        leases=[concern_lease, integration_lease],
        outcomes=[
            ConcernOutcome(
                concern_id="a",
                branch=concern_lease.branch,
                commit="a-sha",
                verified=True,
                integrated=True,
            )
        ],
        integration=IntegrationRecord(
            branch=integration_lease.branch,
            worktree=integration_lease.root,
            concerns=["a"],
            commit="integration-sha",
            completed=True,
        ),
    )
    core = ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=tmp_path,
            worktree_root=tmp_path / "worktrees",
            run_id=run_id,
            integration_branch=integration_lease.branch,
            verification_commands=[
                VerificationCommand(name="tests", arguments=["pytest"])
            ],
        ),
        resolve_spec(),
        lambda _cwd: unused_session_factory(),
        lambda _cwd: unused_session_factory(),
        UnusedInvocationRenderer(),
        SuccessfulLauncher(),
    )
    core.persist(state)

    core.release(state)

    persisted = core.repository.load()
    assert persisted.phase == ResolvePhase.COMPLETE
    assert all(not lease.active for lease in persisted.leases)
    assert persisted.progress[0].status == ConcernStatus.CLEANED
    assert [record.action for record in persisted.cleanup] == ["removed", "retained"]


@pytest.mark.asyncio
async def test_complete_resolver_lifecycle_uses_real_isolated_git_worktrees(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "source"
    workspace.mkdir()
    launcher = LocalProcessLauncher()

    def git(*arguments: str, cwd: Path = workspace) -> str:
        status = launcher.launch(LaunchRequest(arguments=["git", *arguments], cwd=cwd))
        if status.code != 0:
            raise AssertionError(status.stderr)
        return status.stdout.strip()

    git("init", "-b", "source")
    git("config", "user.email", "resolver@example.test")
    git("config", "user.name", "Resolver Test")
    (workspace / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "base")
    source_commit = git("rev-parse", "HEAD")
    source_branch = git("branch", "--show-current")

    worker_calls: Counter[str] = Counter()
    review_calls: Counter[str] = Counter()

    def worker_response(root: Path, output_name: str) -> JsonObject:
        identifier = root.name
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "semantic join reviewed"}
        if output_name != WorkerReport.__name__:
            raise AssertionError(output_name)
        call = worker_calls[identifier] + 1
        worker_calls[identifier] = call
        if identifier == "b" and call == 1:
            worker_asks(
                QuestionMailbox(tmp_path / "state" / run_id),
                run_id,
                dynamic_question("b"),
            )
        relative = Path(f"{identifier}.txt")
        (root / relative).write_text(f"{identifier} round {call}\n", encoding="utf-8")
        return {
            "concern_id": identifier,
            "changed": True,
            "summary": f"implemented {identifier}",
            "files_changed": [relative.as_posix()],
        }

    def reviewer_response(root: Path, output_name: str) -> JsonObject:
        if output_name != ReviewReport.__name__:
            raise AssertionError(output_name)
        identifier = root.name
        call = review_calls[identifier] + 1
        review_calls[identifier] = call
        if identifier == "a" and call == 1:
            return {
                "concern_id": "a",
                "accepted": False,
                "generalized": False,
                "reason": "one revision required",
                "residual": ["revise the implementation"],
            }
        return {
            "concern_id": identifier,
            "accepted": True,
            "generalized": True,
            "reason": "criteria met",
            "criteria_met": [f"{identifier}-done"],
        }

    run_id = "complete-lifecycle"
    core = ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=workspace,
            worktree_root=tmp_path / "resolver-worktrees",
            run_id=run_id,
            integration_branch=f"resolve/{run_id}/review",
            verification_commands=[
                VerificationCommand(
                    name="combined-diff", arguments=["git", "diff", "--check", "HEAD"]
                )
            ],
        ),
        resolve_spec(),
        lambda context: resolver_test_factory(context.root, worker_response),
        lambda root: resolver_test_factory(root, reviewer_response),
        LiteralInvocationRenderer(),
        launcher,
    )
    initial_question = MaterialQuestion(
        id="a-initial",
        concern_id="a",
        prompt="Confirm integration",
        choices=["yes"],
        recommendation="yes",
    )
    inventory = ResolveInventory(
        source=SourceSnapshot(branch=source_branch, commit=source_commit),
        concerns=[
            concern("a").model_copy(update={"questions": [initial_question]}),
            concern("b"),
            concern("c", ["a", "b"]),
        ],
    )

    seed_approvals(core, inventory.concerns)
    seed_offer(core, "a-initial", "yes")
    seed_offer(core, "b-dynamic", "durable")

    manifest = await core.run(inventory)

    assert all(record.passed for record in manifest.verification)
    assert all(outcome.verified for outcome in manifest.outcomes)
    assert {outcome.concern_id for outcome in manifest.outcomes} == {"a", "b", "c"}
    assert worker_calls == {"a": 2, "b": 1, "c": 1}
    assert {item.question.id for item in core.mailbox.questions()} >= {
        "a-initial",
        "b-dynamic",
    }
    assert git("branch", "--show-current") == source_branch
    assert git("rev-parse", "HEAD") == source_commit

    assert [record.action for record in manifest.cleanup] == [
        "removed",
        "removed",
        "removed",
        "retained",
    ]
    assert (tmp_path / "resolver-worktrees" / "integration").exists()
    for identifier in ("a", "b", "c"):
        branch = f"refs/heads/resolve/{run_id}/{identifier}"
        status = launcher.launch(
            LaunchRequest(
                arguments=["git", "show-ref", "--verify", "--quiet", branch],
                cwd=workspace,
            )
        )
        assert status.code != 0


def test_persist_clamps_phase_to_the_recorded_high_water_mark(tmp_path: Path) -> None:
    run_id = "phase-clamp"
    state = ResolveState(
        config_digest="config-sha",
        run_id=run_id,
        phase=ResolvePhase.REVIEW,
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        spec=resolve_spec(),
        concerns=[concern("a")],
        progress=[ConcernProgress(concern_id="a", status=ConcernStatus.VERIFIED)],
        outcomes=[
            ConcernOutcome(
                concern_id="a",
                branch="resolve/a",
                commit="a-sha",
                verified=True,
            )
        ],
    )
    core = ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=tmp_path,
            worktree_root=tmp_path / "worktrees",
            run_id=run_id,
            integration_branch="resolve/review",
            verification_commands=[
                VerificationCommand(name="tests", arguments=["pytest"])
            ],
        ),
        resolve_spec(),
        lambda _cwd: unused_session_factory(),
        lambda _cwd: unused_session_factory(),
        UnusedInvocationRenderer(),
        RecordingLauncher(),
    )
    core.persist(state)

    core.persist(state.model_copy(update={"phase": ResolvePhase.WORKERS}))

    assert core.repository.load().phase == ResolvePhase.REVIEW


@pytest.mark.asyncio
async def test_resume_after_a_kill_past_workers_completes_without_backward_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "source"
    workspace.mkdir()
    launcher = LocalProcessLauncher()

    def git(*arguments: str) -> str:
        status = launcher.launch(
            LaunchRequest(arguments=["git", *arguments], cwd=workspace)
        )
        assert status.code == 0, status.stderr
        return status.stdout.strip()

    git("init", "-b", "source")
    git("config", "user.email", "resolver@example.test")
    git("config", "user.name", "Resolver Test")
    (workspace / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "base")
    source = SourceSnapshot(
        branch=git("branch", "--show-current"), commit=git("rev-parse", "HEAD")
    )

    def worker_response(root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "semantic join reviewed"}
        assert output_name == WorkerReport.__name__
        relative = Path("a.txt")
        (root / relative).write_text("a\n", encoding="utf-8")
        return {
            "concern_id": "a",
            "changed": True,
            "summary": "implemented a",
            "files_changed": [relative.as_posix()],
        }

    def reviewer_response(root: Path, output_name: str) -> JsonObject:
        assert output_name == ReviewReport.__name__
        return {
            "concern_id": "a",
            "accepted": True,
            "generalized": True,
            "reason": "criteria met",
            "criteria_met": ["a-done"],
        }

    def build_core() -> ResolverCore:
        return ResolverCore(
            ResolverConfig(
                state_root=tmp_path / "state",
                workspace=workspace,
                worktree_root=tmp_path / "resolver-worktrees",
                run_id="kill-resume",
                integration_branch="resolve/kill-resume/review",
                verification_commands=[
                    VerificationCommand(
                        name="combined-diff",
                        arguments=["git", "diff", "--check", "HEAD"],
                    )
                ],
            ),
            resolve_spec(),
            lambda context: resolver_test_factory(context.root, worker_response),
            lambda root: resolver_test_factory(root, reviewer_response),
            LiteralInvocationRenderer(),
            launcher,
        )

    killed = build_core()
    monkeypatch.setattr(killed, "persist_failure", lambda error: None)
    acquire = killed.leases.acquire

    def kill_before_integration(concern_id: str, branch: str) -> WritableRootLease:
        if concern_id == "integration":
            raise RuntimeError("killed before the integration lease")
        return acquire(concern_id, branch)

    monkeypatch.setattr(killed.leases, "acquire", kill_before_integration)
    with pytest.raises(RuntimeError, match="killed before"):
        seed_approvals(killed, [concern("a")])
        await killed.run(ResolveInventory(source=source, concerns=[concern("a")]))
    assert killed.repository.load().phase == ResolvePhase.REVIEW

    resumed = build_core()
    manifest = await resumed.resume()

    assert all(record.passed for record in manifest.verification)
    assert [outcome.verified for outcome in manifest.outcomes] == [True]
    assert resumed.repository.load().phase == ResolvePhase.COMPLETE


def failure_leg_workspace(tmp_path: Path, launcher: LocalProcessLauncher) -> Path:
    workspace = tmp_path / "source"
    workspace.mkdir()

    def git(*arguments: str) -> None:
        status = launcher.launch(
            LaunchRequest(arguments=["git", *arguments], cwd=workspace)
        )
        if status.code != 0:
            raise AssertionError(status.stderr)

    git("init", "-b", "source")
    git("config", "user.email", "resolver@example.test")
    git("config", "user.name", "Resolver Test")
    (workspace / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "base")
    return workspace


def failure_leg_core(
    tmp_path: Path,
    workspace: Path,
    launcher: LocalProcessLauncher,
    run_id: str,
    worker_response: Callable[[Path, str], JsonObject],
    reviewer_response: Callable[[Path, str], JsonObject],
    max_revision_rounds: int = 2,
) -> ResolverCore:
    return ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=workspace,
            worktree_root=tmp_path / "resolver-worktrees",
            run_id=run_id,
            integration_branch=f"resolve/{run_id}/review",
            verification_commands=[
                VerificationCommand(
                    name="combined-diff", arguments=["git", "diff", "--check", "HEAD"]
                )
            ],
            max_revision_rounds=max_revision_rounds,
        ),
        resolve_spec(),
        lambda context: resolver_test_factory(context.root, worker_response),
        lambda root: resolver_test_factory(root, reviewer_response),
        LiteralInvocationRenderer(),
        launcher,
    )


def snapshot(workspace: Path, launcher: LocalProcessLauncher) -> SourceSnapshot:
    def git(*arguments: str) -> str:
        status = launcher.launch(
            LaunchRequest(arguments=["git", *arguments], cwd=workspace)
        )
        assert status.code == 0, status.stderr
        return status.stdout.strip()

    return SourceSnapshot(
        branch=git("branch", "--show-current"), commit=git("rev-parse", "HEAD")
    )


@pytest.mark.asyncio
async def test_worker_crash_persists_the_failure_and_raises_a_group(
    tmp_path: Path,
) -> None:
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)

    def worker_response(_root: Path, _output_name: str) -> JsonObject:
        raise RuntimeError("worker exploded")

    def reviewer_response(_root: Path, _output_name: str) -> JsonObject:
        raise AssertionError("the reviewer must not run after a worker crash")

    core = failure_leg_core(
        tmp_path,
        workspace,
        launcher,
        "worker-crash",
        worker_response,
        reviewer_response,
    )

    with pytest.raises(ExceptionGroup) as raised:
        seed_approvals(core, [concern("a")])
        await core.run(
            ResolveInventory(
                source=snapshot(workspace, launcher), concerns=[concern("a")]
            )
        )

    assert [str(error) for error in raised.value.exceptions] == ["worker exploded"]
    persisted = core.repository.load()
    progress = {item.concern_id: item for item in persisted.progress}
    assert progress["a"].status == ConcernStatus.FAILED
    assert progress["a"].reason == "worker exploded"
    assert any("worker exploded" in failure for failure in persisted.failures)


@pytest.mark.asyncio
async def test_revision_exhaustion_soft_fails_and_blocks_dependents(
    tmp_path: Path,
) -> None:
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)
    worker_calls: Counter[str] = Counter()

    def worker_response(root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "integration join reviewed"}
        assert output_name == WorkerReport.__name__
        identifier = root.name
        worker_calls[identifier] += 1
        relative = Path(f"{identifier}.txt")
        (root / relative).write_text(
            f"{identifier} round {worker_calls[identifier]}\n", encoding="utf-8"
        )
        return {
            "concern_id": identifier,
            "changed": True,
            "summary": f"implemented {identifier}",
            "files_changed": [relative.as_posix()],
        }

    def reviewer_response(root: Path, output_name: str) -> JsonObject:
        assert output_name == ReviewReport.__name__
        identifier = root.name
        if identifier == "a":
            return {
                "concern_id": "a",
                "accepted": False,
                "generalized": False,
                "reason": "never good enough",
                "residual": ["still wrong"],
            }
        return {
            "concern_id": identifier,
            "accepted": True,
            "generalized": True,
            "reason": "criteria met",
            "criteria_met": [f"{identifier}-done"],
        }

    core = failure_leg_core(
        tmp_path,
        workspace,
        launcher,
        "revision-exhaustion",
        worker_response,
        reviewer_response,
        max_revision_rounds=1,
    )

    seed_approvals(core, [concern("a"), concern("b"), concern("c", ["a"])])
    manifest = await core.run(
        ResolveInventory(
            source=snapshot(workspace, launcher),
            concerns=[concern("a"), concern("b"), concern("c", ["a"])],
        )
    )

    outcomes = {outcome.concern_id: outcome for outcome in manifest.outcomes}
    assert outcomes["a"].verified is False
    assert outcomes["a"].failure == "revision limit exhausted"
    assert outcomes["b"].verified is True
    assert outcomes["c"].verified is False
    assert outcomes["c"].failure == "a dependency did not produce a verified commit"
    assert worker_calls == {"a": 2, "b": 1}
    persisted = core.repository.load()
    progress = {item.concern_id: item for item in persisted.progress}
    assert progress["a"].status == ConcernStatus.FAILED
    assert progress["c"].status == ConcernStatus.FAILED


@pytest.mark.asyncio
async def test_unresolved_semantic_join_fails_the_dependent_concern(
    tmp_path: Path,
) -> None:
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)

    def worker_response(root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {
                "completed": False,
                "summary": "conflicting intents in shared.txt",
                "unresolved_paths": ["shared.txt"],
            }
        assert output_name == WorkerReport.__name__
        identifier = root.name
        (root / "shared.txt").write_text(f"{identifier} version\n", encoding="utf-8")
        return {
            "concern_id": identifier,
            "changed": True,
            "summary": f"implemented {identifier}",
            "files_changed": ["shared.txt"],
        }

    def reviewer_response(root: Path, output_name: str) -> JsonObject:
        assert output_name == ReviewReport.__name__
        identifier = root.name
        return {
            "concern_id": identifier,
            "accepted": True,
            "generalized": True,
            "reason": "criteria met",
            "criteria_met": [f"{identifier}-done"],
        }

    core = failure_leg_core(
        tmp_path,
        workspace,
        launcher,
        "join-conflict",
        worker_response,
        reviewer_response,
    )

    with pytest.raises(ExceptionGroup) as raised:
        seed_approvals(core, [concern("a"), concern("b"), concern("c", ["a", "b"])])
        await core.run(
            ResolveInventory(
                source=snapshot(workspace, launcher),
                concerns=[concern("a"), concern("b"), concern("c", ["a", "b"])],
            )
        )

    assert len(raised.value.exceptions) == 1
    joined_failure = raised.value.exceptions[0]
    assert isinstance(joined_failure, ResolverInvariantError)
    assert "semantic join failed for c" in str(joined_failure)
    persisted = core.repository.load()
    progress = {item.concern_id: item for item in persisted.progress}
    assert progress["a"].status == ConcernStatus.VERIFIED
    assert progress["b"].status == ConcernStatus.VERIFIED
    assert progress["c"].status == ConcernStatus.FAILED
    assert "semantic join failed for c" in (progress["c"].reason or "")


@pytest.mark.asyncio
async def test_aborting_a_parked_run_frees_its_leases_and_refuses_resumption(
    tmp_path: Path,
) -> None:
    """Cleanup used to be reachable only at acceptance, stranding leases."""
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)

    def worker_response(_root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "joined"}
        mailbox = QuestionMailbox(tmp_path / "state" / "abandoned")
        worker_asks(mailbox, "abandoned", dynamic_question("a"))
        return {
            "concern_id": "a",
            "changed": False,
            "summary": "parked awaiting a material choice",
        }

    def build_core() -> ResolverCore:
        return ResolverCore(
            ResolverConfig(
                state_root=tmp_path / "state",
                workspace=workspace,
                worktree_root=tmp_path / "resolver-worktrees",
                run_id="abandoned",
                integration_branch="resolve/abandoned/review",
                verification_commands=[
                    VerificationCommand(name="v", arguments=["git", "diff"])
                ],
            ),
            resolve_spec(),
            lambda context: resolver_test_factory(context.root, worker_response),
            lambda root: resolver_test_factory(root, lambda *_: {}),
            LiteralInvocationRenderer(),
            launcher,
        )

    parked = build_core()
    seed_approvals(parked, [concern("a")])
    with pytest.raises(ResolverAwaitingAnswers):
        await parked.run(
            ResolveInventory(
                source=snapshot(workspace, launcher), concerns=[concern("a")]
            )
        )
    leased = [lease.root for lease in parked.repository.load().leases]
    assert leased and all(root.exists() for root in leased)

    manifest = build_core().abort("superseded by a re-plan")

    assert [record.action for record in manifest.cleanup] == ["removed"]
    assert not any(root.exists() for root in leased)
    persisted = build_core().repository.load()
    assert persisted.phase == ResolvePhase.ABORTED
    assert persisted.abort_reason == "superseded by a re-plan"
    with pytest.raises(ResolverInvariantError, match="was aborted"):
        await build_core().resume()


@pytest.mark.asyncio
async def test_midrun_question_parks_the_concern_and_resumes_after_answers(
    tmp_path: Path,
) -> None:
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)
    worker_calls: Counter[str] = Counter()

    def worker_response(root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "semantic join reviewed"}
        if output_name != WorkerReport.__name__:
            raise AssertionError(output_name)
        worker_calls["a"] += 1
        mailbox = QuestionMailbox(tmp_path / "state" / "midrun-park")
        worker_asks(mailbox, "midrun-park", dynamic_question("a"))
        if "a-dynamic" not in mailbox.answered_ids():
            return {
                "concern_id": "a",
                "changed": False,
                "summary": "parked awaiting a material choice",
            }
        (root / "a.txt").write_text("durable\n", encoding="utf-8")
        return {
            "concern_id": "a",
            "changed": True,
            "summary": "implemented a",
            "files_changed": ["a.txt"],
        }

    def reviewer_response(_root: Path, output_name: str) -> JsonObject:
        return {
            "concern_id": "a",
            "accepted": True,
            "generalized": True,
            "reason": "criteria met",
            "criteria_met": ["a-done"],
        }

    def build_core() -> ResolverCore:
        return ResolverCore(
            ResolverConfig(
                state_root=tmp_path / "state",
                workspace=workspace,
                worktree_root=tmp_path / "resolver-worktrees",
                run_id="midrun-park",
                integration_branch="resolve/midrun-park/review",
                verification_commands=[
                    VerificationCommand(
                        name="combined-diff",
                        arguments=["git", "diff", "--check", "HEAD"],
                    )
                ],
            ),
            resolve_spec(),
            lambda context: resolver_test_factory(context.root, worker_response),
            lambda root: resolver_test_factory(root, reviewer_response),
            LiteralInvocationRenderer(),
            launcher,
        )

    parked_core = build_core()
    seed_approvals(parked_core, [concern("a")])
    with pytest.raises(ResolverAwaitingAnswers) as raised:
        await parked_core.run(
            ResolveInventory(
                source=snapshot(workspace, launcher), concerns=[concern("a")]
            )
        )

    assert [question.id for question in raised.value.pending] == ["a-dynamic"]
    persisted = parked_core.repository.load()
    progress = {item.concern_id: item for item in persisted.progress}
    assert progress["a"].status == ConcernStatus.WAITING_FOR_ANSWERS
    assert progress["a"].reason == "parked on material questions"
    assert persisted.phase != ResolvePhase.FAILED
    assert persisted.questions is not None
    assert "a-dynamic" in {q.id for q in persisted.questions.questions}

    resumed = build_core()
    seed_offer(resumed, "a-dynamic", "durable")
    manifest = await resumed.resume()

    assert worker_calls["a"] == 2
    assert [outcome.verified for outcome in manifest.outcomes] == [True]
    assert all(record.passed for record in manifest.verification)


@pytest.mark.asyncio
async def test_a_finished_run_releases_itself_without_a_human_gate(
    tmp_path: Path,
) -> None:
    """The gate decided nothing: both answers cleaned the same leases.

    So a run reaches COMPLETE on its own, having freed every concern
    worktree and kept the review branch for whoever lands it.
    """
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)

    def worker_response(root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "semantic join reviewed"}
        (root / "a.txt").write_text("durable\n", encoding="utf-8")
        return {
            "concern_id": "a",
            "changed": True,
            "summary": "implemented a",
            "files_changed": ["a.txt"],
        }

    def reviewer_response(_root: Path, output_name: str) -> JsonObject:
        return {
            "concern_id": "a",
            "accepted": True,
            "generalized": True,
            "reason": "criteria met",
            "criteria_met": ["a-done"],
        }

    def build_core() -> ResolverCore:
        return ResolverCore(
            ResolverConfig(
                state_root=tmp_path / "state",
                workspace=workspace,
                worktree_root=tmp_path / "resolver-worktrees",
                run_id="acceptance-door",
                integration_branch="resolve/acceptance-door/review",
                verification_commands=[
                    VerificationCommand(
                        name="combined-diff",
                        arguments=["git", "diff", "--check", "HEAD"],
                    )
                ],
            ),
            resolve_spec(),
            lambda context: resolver_test_factory(context.root, worker_response),
            lambda root: resolver_test_factory(root, reviewer_response),
            LiteralInvocationRenderer(),
            launcher,
        )

    core = build_core()
    seed_approvals(core, [concern("a")])
    manifest = await core.run(
        ResolveInventory(source=snapshot(workspace, launcher), concerns=[concern("a")])
    )

    assert all(record.passed for record in manifest.verification)
    assert core.repository.load().phase == ResolvePhase.COMPLETE
    assert [record.action for record in manifest.cleanup] == ["removed", "retained"]


@pytest.mark.asyncio
async def test_an_offer_outside_a_closed_gate_never_decides(
    tmp_path: Path,
) -> None:
    """A door is a form, not a trusted caller."""
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)
    core = ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=workspace,
            worktree_root=tmp_path / "resolver-worktrees",
            run_id="bad-acceptance",
            integration_branch="resolve/bad-acceptance/review",
            verification_commands=[VerificationCommand(name="v", arguments=["git"])],
        ),
        resolve_spec(),
        lambda context: resolver_test_factory(context.root, lambda *_: {}),
        lambda root: resolver_test_factory(root, lambda *_: {}),
        LiteralInvocationRenderer(),
        launcher,
    )
    core.queue_questions(
        [
            MaterialQuestion(
                id="a-superseded",
                concern_id="a",
                prompt="superseded or a regression?",
                choices=["superseded", "regression"],
                closed_choices=True,
            )
        ],
        "a",
    )
    seed_offer(core, "a-superseded", "maybe")

    problems = core.promote_offers()

    assert core.mailbox.answers() == []
    assert problems == [
        "a-superseded was answered 'maybe', but that gate "
        "accepts only: superseded, regression"
    ]


@pytest.mark.asyncio
async def test_a_design_question_records_an_answer_in_the_humans_own_words(
    tmp_path: Path,
) -> None:
    """A planner's choices are suggestions, so an answer outside them counts."""
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)
    core = ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=workspace,
            worktree_root=tmp_path / "resolver-worktrees",
            run_id="own-words",
            integration_branch="resolve/own-words/review",
            verification_commands=[VerificationCommand(name="v", arguments=["git"])],
        ),
        resolve_spec(),
        lambda context: resolver_test_factory(context.root, lambda *_: {}),
        lambda root: resolver_test_factory(root, lambda *_: {}),
        LiteralInvocationRenderer(),
        launcher,
    )
    core.queue_questions(
        [
            MaterialQuestion(
                id="shape",
                concern_id="design",
                prompt="Which shape?",
                choices=["a method", "a registry"],
            )
        ],
        "design",
    )
    seed_offer(core, "shape", "neither — close the union at its base")

    problems = core.promote_offers()

    assert problems == []
    assert [record.answer.value for record in core.mailbox.answers()] == [
        "neither — close the union at its base"
    ]


def admitted_plan(*concerns: JsonObject) -> JsonObject:
    """One planner reply admitting concerns against a run's new evidence."""
    return {"concerns": [item for item in concerns]}


def admitted_concern(
    identifier: str,
    dependencies: list[str] | None = None,
    questions: list[JsonObject] | None = None,
) -> JsonObject:
    return {
        "id": identifier,
        "title": identifier.title(),
        "spec": f"Resolve {identifier}",
        "criteria": [{"id": f"{identifier}-done", "description": "done"}],
        "dependencies": [parent for parent in dependencies or []],
        "questions": [question for question in questions or []],
        "evidence_indexes": [0],
    }


def admitting_core(
    tmp_path: Path,
    workspace: Path,
    launcher: LocalProcessLauncher,
    run_id: str,
    worker_response: ResolverResponse,
    reviewer_response: ResolverResponse,
) -> ResolverCore:
    return ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=workspace,
            worktree_root=tmp_path / "resolver-worktrees",
            run_id=run_id,
            integration_branch=f"resolve/{run_id}/review",
            verification_commands=[
                VerificationCommand(
                    name="combined-diff", arguments=["git", "diff", "--check", "HEAD"]
                )
            ],
        ),
        resolve_spec(),
        lambda context: resolver_test_factory(context.root, worker_response),
        lambda root: resolver_test_factory(root, reviewer_response),
        LiteralInvocationRenderer(),
        launcher,
    )


def admitted(identifier: str, evidence: str = "a human said so") -> Concern:
    """One concern as an admission records it: origin and evidence carried."""
    return concern(identifier).model_copy(
        update={"origin": ConcernOrigin.ADMITTED, "evidence": evidence}
    )


def implementing_worker(
    parks: dict[str, str],  # lup: ignore[dict-str-payload] — concern-id index
    state_root: Path,
    run_id: str,
) -> ResolverResponse:
    """A worker that parks each named concern once, then implements it.

    ``parks`` maps a concern id to the question it asks before doing any
    work, which is what puts a run at the boundary a human discovers more
    work from.
    """

    def respond(root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "semantic join reviewed"}
        if output_name != WorkerReport.__name__:
            raise AssertionError(output_name)
        identifier = root.name
        if identifier in parks:
            mailbox = QuestionMailbox(state_root / run_id)
            worker_asks(mailbox, run_id, dynamic_question(identifier))
            if parks[identifier] not in mailbox.answered_ids():
                return {
                    "concern_id": identifier,
                    "changed": False,
                    "summary": "parked awaiting a material choice",
                }
        (root / f"{identifier}.txt").write_text("durable\n", encoding="utf-8")
        return {
            "concern_id": identifier,
            "changed": True,
            "summary": f"implemented {identifier}",
            "files_changed": [f"{identifier}.txt"],
        }

    return respond


def planning_reviewer(plan: JsonObject) -> ResolverResponse:
    """A reviewer that plans admitted evidence and accepts every concern."""

    def respond(root: Path, output_name: str) -> JsonObject:
        if output_name == ConcernInventory.__name__:
            return plan
        return {
            "concern_id": root.name,
            "accepted": True,
            "generalized": True,
            "reason": "criteria met",
            "criteria_met": [f"{root.name}-done"],
        }

    return respond


@pytest.mark.asyncio
async def test_a_concern_admitted_into_a_parked_run_finishes_beside_the_originals(
    tmp_path: Path,
) -> None:
    """Discovery mid-run cost a restart, which threw away every answer.

    The run keeps its id, its recorded answers, and its completed work; the
    admitted concern still passes the approval and material-question gates
    its siblings passed.
    """
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)

    def build_core() -> ResolverCore:
        return admitting_core(
            tmp_path,
            workspace,
            launcher,
            "admit-parked",
            implementing_worker({"a": "a-dynamic"}, tmp_path / "state", "admit-parked"),
            planning_reviewer(
                admitted_plan(
                    admitted_concern(
                        "b",
                        questions=[
                            {
                                "id": "b-shape",
                                "concern_id": "b",
                                "prompt": "Which shape?",
                                "choices": ["a method"],
                            }
                        ],
                    )
                )
            ),
        )

    parked = build_core()
    seed_approvals(parked, [concern("a")])
    with pytest.raises(ResolverAwaitingAnswers):
        await parked.run(
            ResolveInventory(
                source=snapshot(workspace, launcher), concerns=[concern("a")]
            )
        )
    before = parked.repository.load()

    admission = await build_core().admit(
        AdmissionRequest(statements=["the relay has to investigate before it asks"])
    )

    assert admission.run_id == "admit-parked"
    assert [item.id for item in admission.concerns] == ["b"]
    assert admission.concerns[0].origin is ConcernOrigin.ADMITTED
    assert admission.concerns[0].evidence == (
        "the relay has to investigate before it asks"
    )
    assert [question.id for question in admission.questions] == [
        "b-shape",
        "integration-approval-b",
    ]
    widened = build_core().repository.load()
    assert [item.id for item in widened.concerns] == ["a", "b"]
    assert widened.answers == before.answers
    assert widened.phase == before.phase

    ungated = build_core()
    seed_offer(ungated, "a-dynamic", "durable")
    seed_offer(ungated, "b-shape", "a method")
    with pytest.raises(ResolverAwaitingAnswers) as gated:
        await ungated.resume()
    assert [question.id for question in gated.value.pending] == [
        "integration-approval-b"
    ]

    resumed = build_core()
    seed_offer(resumed, "integration-approval-b", APPROVE)
    manifest = await resumed.resume()

    assert sorted(
        outcome.concern_id for outcome in manifest.outcomes if outcome.verified
    ) == ["a", "b"]
    assert all(record.passed for record in manifest.verification)
    persisted = resumed.repository.load()
    assert persisted.answers is not None
    assert {answer.question_id for answer in persisted.answers.answers} == {
        "integration-approval-a",
        "a-dynamic",
        "b-shape",
        "integration-approval-b",
    }
    assert [item.status for item in persisted.progress if item.concern_id == "b"] == [
        ConcernStatus.CLEANED
    ]


@pytest.mark.asyncio
async def test_an_admitted_concern_bases_on_a_completed_concerns_recorded_commit(
    tmp_path: Path,
) -> None:
    """Work discovered *because* an earlier concern landed may depend on it.

    One admission carries as many concerns as its evidence needs, so `d`
    rides in beside `c` rather than costing a second pass.
    """
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)

    def build_core() -> ResolverCore:
        return admitting_core(
            tmp_path,
            workspace,
            launcher,
            "admit-dependent",
            implementing_worker(
                {"b": "b-dynamic"}, tmp_path / "state", "admit-dependent"
            ),
            planning_reviewer(
                admitted_plan(admitted_concern("c", ["a"]), admitted_concern("d"))
            ),
        )

    parked = build_core()
    seed_approvals(parked, [concern("a"), concern("b")])
    with pytest.raises(ResolverAwaitingAnswers):
        await parked.run(
            ResolveInventory(
                source=snapshot(workspace, launcher),
                concerns=[concern("a"), concern("b")],
            )
        )
    completed = next(
        outcome
        for outcome in parked.repository.load().outcomes
        if outcome.concern_id == "a"
    )
    assert completed.verified and completed.commit is not None

    admission = await build_core().admit(
        AdmissionRequest(statements=["the landed change needs a follow-up"])
    )
    assert [item.id for item in admission.concerns] == ["c", "d"]

    resumed = build_core()
    seed_offer(resumed, "b-dynamic", "durable")
    seed_offer(resumed, "integration-approval-c", APPROVE)
    seed_offer(resumed, "integration-approval-d", APPROVE)
    manifest = await resumed.resume()

    assert sorted(
        outcome.concern_id for outcome in manifest.outcomes if outcome.verified
    ) == ["a", "b", "c", "d"]
    base = next(
        item for item in resumed.repository.load().bases if item.concern_id == "c"
    )
    assert base.parent_concerns == ["a"]
    assert base.parent_commits == [completed.commit]
    assert base.commit == completed.commit


@pytest.mark.asyncio
async def test_admission_refuses_a_reused_lease_a_cycle_and_a_missing_parent(
    tmp_path: Path,
) -> None:
    """Nothing is persisted unless the widened graph and leases both hold."""
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)

    def build_core(plan: JsonObject) -> ResolverCore:
        return admitting_core(
            tmp_path,
            workspace,
            launcher,
            "admit-refused",
            implementing_worker(
                {"a": "a-dynamic"}, tmp_path / "state", "admit-refused"
            ),
            planning_reviewer(plan),
        )

    parked = build_core(admitted_plan(admitted_concern("b")))
    seed_approvals(parked, [concern("a")])
    with pytest.raises(ResolverAwaitingAnswers):
        await parked.run(
            ResolveInventory(
                source=snapshot(workspace, launcher), concerns=[concern("a")]
            )
        )
    evidence = AdmissionRequest(statements=["something else is broken"])

    with pytest.raises(LeaseViolationError, match="already has a lease"):
        await build_core(admitted_plan(admitted_concern("a"))).admit(evidence)
    with pytest.raises(ConcernGraphError, match="contains a cycle"):
        await build_core(
            admitted_plan(admitted_concern("c", ["d"]), admitted_concern("d", ["c"]))
        ).admit(evidence)
    with pytest.raises(ConcernGraphError, match="missing nodes"):
        await build_core(admitted_plan(admitted_concern("e", ["absent"]))).admit(
            evidence
        )

    survivor = build_core(admitted_plan(admitted_concern("b")))
    assert [item.id for item in survivor.repository.load().concerns] == ["a"]


@pytest.mark.asyncio
async def test_admission_is_refused_once_the_review_branch_is_assembled(
    tmp_path: Path,
) -> None:
    """Past integration a joining concern would have to reopen the branch."""
    run_id = "admit-late"
    core = ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=tmp_path,
            worktree_root=tmp_path / "worktrees",
            run_id=run_id,
            integration_branch="resolve/review",
            verification_commands=[
                VerificationCommand(name="tests", arguments=["pytest"])
            ],
        ),
        resolve_spec(),
        lambda _cwd: unused_session_factory(),
        lambda _cwd: unused_session_factory(),
        UnusedInvocationRenderer(),
        LocalProcessLauncher(),
    )
    core.persist(
        ResolveState(
            config_digest="config-sha",
            run_id=run_id,
            phase=ResolvePhase.INTEGRATION,
            source=SourceSnapshot(branch="feature", commit="source-sha"),
            spec=resolve_spec(),
            concerns=[concern("a")],
            progress=[
                ConcernProgress(concern_id="a", status=ConcernStatus.INTEGRATING)
            ],
        )
    )

    with pytest.raises(ResolverInvariantError, match="review branch is assembled"):
        await core.admit(AdmissionRequest(statements=["too late"]))


def test_a_recorded_concern_is_immutable_while_a_later_one_may_join(
    tmp_path: Path,
) -> None:
    """Widening is the only edit the concern set accepts."""
    state = ResolveState(
        config_digest="config-sha",
        run_id="run-1",
        phase=ResolvePhase.INVENTORY,
        source=SourceSnapshot(branch="feature", commit="source-sha"),
        spec=resolve_spec(),
        concerns=[concern("a")],
        progress=[ConcernProgress(concern_id="a")],
    )
    repository = ResolverStateRepository(tmp_path, "run-1")
    repository.save(state)
    joined = admitted("b")

    repository.save(
        state.model_copy(
            update={
                "concerns": [concern("a"), joined],
                "progress": [
                    ConcernProgress(concern_id="a"),
                    ConcernProgress(concern_id="b"),
                ],
            }
        )
    )

    assert [item.id for item in repository.load().concerns] == ["a", "b"]
    with pytest.raises(StateTransitionError, match="recorded resolver concern"):
        repository.save(
            state.model_copy(
                update={
                    "concerns": [joined],
                    "progress": [ConcernProgress(concern_id="b")],
                }
            )
        )
    with pytest.raises(StateTransitionError, match="cover every concern"):
        repository.save(
            state.model_copy(
                update={
                    "concerns": [concern("a"), joined],
                    "progress": [ConcernProgress(concern_id="a")],
                }
            )
        )


def test_an_admitted_concern_must_cite_what_raised_it() -> None:
    """A concern from intake is grounded in notes; an admitted one says so."""
    with pytest.raises(ValueError, match="cites no evidence"):
        Concern.model_validate(
            concern("a").model_dump() | {"origin": ConcernOrigin.ADMITTED}
        )


class RecordingObserver(ResolverObserver):
    def __init__(self) -> None:
        self.phases: list[ResolvePhase] = []
        self.transitions: list[ConcernProgress] = []

    def phase_changed(self, phase: ResolvePhase) -> None:
        self.phases.append(phase)

    def concern_changed(self, progress: ConcernProgress) -> None:
        self.transitions.append(progress)


@pytest.mark.asyncio
async def test_observer_receives_every_persisted_transition_in_order(
    tmp_path: Path,
) -> None:
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)

    def worker_response(root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "semantic join reviewed"}
        (root / "a.txt").write_text("done\n", encoding="utf-8")
        return {
            "concern_id": "a",
            "changed": True,
            "summary": "implemented a",
            "files_changed": ["a.txt"],
        }

    def reviewer_response(_root: Path, output_name: str) -> JsonObject:
        return {
            "concern_id": "a",
            "accepted": True,
            "generalized": True,
            "reason": "criteria met",
            "criteria_met": ["a-done"],
        }

    observer = RecordingObserver()
    core = ResolverCore(
        ResolverConfig(
            state_root=tmp_path / "state",
            workspace=workspace,
            worktree_root=tmp_path / "resolver-worktrees",
            run_id="observed",
            integration_branch="resolve/observed/review",
            verification_commands=[
                VerificationCommand(
                    name="combined-diff",
                    arguments=["git", "diff", "--check", "HEAD"],
                )
            ],
        ),
        resolve_spec(),
        lambda context: resolver_test_factory(context.root, worker_response),
        lambda root: resolver_test_factory(root, reviewer_response),
        LiteralInvocationRenderer(),
        launcher,
        observer=observer,
    )

    seed_approvals(core, [concern("a")])
    await core.run(
        ResolveInventory(source=snapshot(workspace, launcher), concerns=[concern("a")])
    )

    assert observer.phases == [
        ResolvePhase.INVENTORY,
        ResolvePhase.QUESTIONS,
        ResolvePhase.ELIGIBILITY,
        ResolvePhase.DAG,
        ResolvePhase.LEASES,
        ResolvePhase.WORKERS,
        ResolvePhase.DEPENDENCY_BASES,
        ResolvePhase.REVIEW,
        ResolvePhase.INTEGRATION,
        ResolvePhase.VERIFICATION,
        ResolvePhase.CLEANUP,
        ResolvePhase.COMPLETE,
    ]
    assert [item.status for item in observer.transitions] == [
        ConcernStatus.DISCOVERED,
        ConcernStatus.WAITING_FOR_ANSWERS,
        ConcernStatus.ELIGIBLE,
        ConcernStatus.LEASED,
        ConcernStatus.RUNNING,
        ConcernStatus.VALIDATING,
        ConcernStatus.REVIEWING,
        ConcernStatus.VERIFIED,
        ConcernStatus.INTEGRATING,
        ConcernStatus.INTEGRATED,
        ConcernStatus.CLEANED,
    ]
    assert {item.concern_id for item in observer.transitions} == {"a"}


def noted_workspace(tmp_path: Path, launcher: LocalProcessLauncher) -> Path:
    """A source tree whose module carries two concerns' notes at once."""
    workspace = failure_leg_workspace(tmp_path, launcher)
    (workspace / "module.py").write_text(
        "# lup: rework the dispatch\nvalue = 1\n# lup: belongs to another concern\n",
        encoding="utf-8",
    )
    for arguments in (["add", "module.py"], ["commit", "-m", "noted"]):
        status = launcher.launch(
            LaunchRequest(arguments=["git", *arguments], cwd=workspace)
        )
        assert status.code == 0, status.stderr
    return workspace


def noted_concern() -> Concern:
    return Concern(
        id="a",
        title="A",
        spec="Resolve a",
        criteria=[AcceptanceCriterion(id="a-done", description="done")],
        notes=[ReviewNote(file=Path("module.py"), line=1, text="rework the dispatch")],
        integration_approved=True,
    )


def accepting_reviewer(_root: Path, output_name: str) -> JsonObject:
    return {
        "concern_id": "a",
        "accepted": True,
        "generalized": True,
        "reason": "criteria met",
        "criteria_met": ["a-done"],
    }


@pytest.mark.asyncio
async def test_a_concerns_notes_are_cleared_before_its_worker_runs(
    tmp_path: Path,
) -> None:
    """The regression this whole change exists for.

    The worker used to be told to remove its own marker, which the edit
    policy asks on unconditionally, so every concern parked. The
    orchestrator now removes it first — and removes only what this concern
    owns, leaving the sibling's note in the same file untouched.
    """
    launcher = LocalProcessLauncher()
    workspace = noted_workspace(tmp_path, launcher)
    seen: list[str] = []

    def worker_response(root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "joined"}
        seen.append((root / "module.py").read_text(encoding="utf-8"))
        (root / "a.txt").write_text("implemented\n", encoding="utf-8")
        return {
            "concern_id": "a",
            "changed": True,
            "summary": "implemented a",
            "files_changed": ["a.txt"],
        }

    core = failure_leg_core(
        tmp_path,
        workspace,
        launcher,
        "note-clearance",
        worker_response,
        accepting_reviewer,
    )
    seed_approvals(core, [noted_concern()])
    manifest = await core.run(
        ResolveInventory(
            source=snapshot(workspace, launcher), concerns=[noted_concern()]
        )
    )

    outcome = next(item for item in manifest.outcomes if item.concern_id == "a")
    assert outcome.verified, outcome.failure
    assert [note.text for note in outcome.notes_cleared] == ["rework the dispatch"]
    assert seen and "rework the dispatch" not in seen[0]
    assert "belongs to another concern" in seen[0]


@pytest.mark.asyncio
async def test_clearance_commits_separately_from_the_workers_change(
    tmp_path: Path,
) -> None:
    """Its own commit is what keeps the diff-equality invariant strict."""
    launcher = LocalProcessLauncher()
    workspace = noted_workspace(tmp_path, launcher)

    def worker_response(root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "joined"}
        (root / "a.txt").write_text("implemented\n", encoding="utf-8")
        return {
            "concern_id": "a",
            "changed": True,
            "summary": "implemented a",
            "files_changed": ["a.txt"],
        }

    core = failure_leg_core(
        tmp_path,
        workspace,
        launcher,
        "note-commit",
        worker_response,
        accepting_reviewer,
    )
    seed_approvals(core, [noted_concern()])
    manifest = await core.run(
        ResolveInventory(
            source=snapshot(workspace, launcher), concerns=[noted_concern()]
        )
    )

    outcome = next(item for item in manifest.outcomes if item.concern_id == "a")
    assert outcome.commit is not None
    subjects = launcher.launch(
        LaunchRequest(
            arguments=["git", "log", "--format=%s", "-3", outcome.commit],
            cwd=workspace,
        )
    )
    assert "resolve: clear review notes for a" in subjects.stdout


@pytest.mark.asyncio
async def test_a_concern_with_no_notes_clears_nothing(tmp_path: Path) -> None:
    """No note, no commit — the worker's base stays the dependency base."""
    launcher = LocalProcessLauncher()
    workspace = noted_workspace(tmp_path, launcher)

    def worker_response(root: Path, output_name: str) -> JsonObject:
        if output_name == MergeReport.__name__:
            return {"completed": True, "summary": "joined"}
        (root / "a.txt").write_text("implemented\n", encoding="utf-8")
        return {
            "concern_id": "a",
            "changed": True,
            "summary": "implemented a",
            "files_changed": ["a.txt"],
        }

    core = failure_leg_core(
        tmp_path, workspace, launcher, "note-free", worker_response, accepting_reviewer
    )
    seed_approvals(core, [concern("a")])
    manifest = await core.run(
        ResolveInventory(source=snapshot(workspace, launcher), concerns=[concern("a")])
    )

    outcome = next(item for item in manifest.outcomes if item.concern_id == "a")
    assert outcome.verified, outcome.failure
    assert outcome.notes_cleared == []


class RecordingPreparer(WorktreePreparer):
    def __init__(self) -> None:
        self.prepared: list[Path] = []

    def prepare(self, root: Path) -> None:
        self.prepared.append(root)


def test_every_created_and_restored_worktree_is_prepared(tmp_path: Path) -> None:
    launcher = LocalProcessLauncher()
    workspace = failure_leg_workspace(tmp_path, launcher)
    source = snapshot(workspace, launcher)
    preparer = RecordingPreparer()
    orchestrator = WorktreeOrchestrator(launcher, workspace, preparer)
    leases = WritableRootLeases(tmp_path / "resolver-worktrees")
    lease = leases.acquire("a", "resolve/prepared/a")

    orchestrator.create(lease, source.commit)
    assert preparer.prepared == [lease.root]

    orchestrator.remove(lease)
    orchestrator.create(lease, source.commit)
    launcher.launch(
        LaunchRequest(
            arguments=["git", "worktree", "remove", "--force", str(lease.root)],
            cwd=workspace,
        )
    )
    orchestrator.restore(lease)
    assert preparer.prepared == [lease.root, lease.root, lease.root]
