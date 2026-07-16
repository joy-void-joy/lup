"""Deterministic resolver DAG, lease, state, and commit-authority tests."""

from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from pathlib import Path
import pytest
from pydantic import BaseModel

from lup.harness.contracts import ProcessLauncher, SkillInvocationRenderer
from lup.harness.models import ExitStatus, LaunchRequest, ResolveSpec, SkillInvocation
from lup.harness.process import LocalProcessLauncher
from lup.resolver.dag import ConcernGraph, ConcernGraphError
from lup.resolver.contracts import QuestionBroker
from lup.resolver.core import ResolverCore, ResolverInvariantError
from lup.resolver.models import (
    AnswerBatch,
    AcceptanceCriterion,
    Concern,
    ConcernOutcome,
    ConcernProgress,
    ConcernStatus,
    DependencyBase,
    FinalReview,
    IntegrationRecord,
    MaterialQuestion,
    MergeReport,
    QuestionAnswer,
    ResolveInventory,
    ResolverConfig,
    ResolvePhase,
    ResolveState,
    ReviewReport,
    SourceSnapshot,
    QuestionBatch,
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
from lup.resolver.state import ResolverStateRepository, StateTransitionError
from lup.runtime.contracts import Session, SessionFactory, Turn
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


def resolve_spec() -> ResolveSpec:
    return ResolveSpec(
        id="resolve",
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


def test_leases_are_unique_bounded_and_releasable(tmp_path: Path) -> None:
    leases = WritableRootLeases(tmp_path / "agents")
    first = leases.acquire("a", "resolve/a")
    second = leases.acquire("b", "resolve/b")

    assert first.root != second.root
    leases.assert_path("a", first.root / "src" / "module.py")
    with pytest.raises(LeaseViolationError, match="outside"):
        leases.assert_path("a", second.root / "module.py")
    with pytest.raises(LeaseViolationError, match="already has"):
        leases.acquire("a", "resolve/a-2")

    released = leases.release("a")
    assert not released.active
    with pytest.raises(LeaseViolationError, match="outside"):
        leases.assert_path("a", first.root / "file.py")


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


class UnusedSessionFactory(SessionFactory):
    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        raise AssertionError(f"session factory should not be opened: {resume}")


class UnusedInvocationRenderer(SkillInvocationRenderer):
    def render(self, invocation: SkillInvocation) -> str:
        raise AssertionError(f"invocation should not be rendered: {invocation}")


class UnusedQuestionBroker(QuestionBroker):
    async def ask(self, questions: QuestionBatch) -> AnswerBatch:
        raise AssertionError(f"questions should not be asked: {questions}")


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


class ResolverTestFactory(SessionFactory):
    def __init__(self, root: Path, response: ResolverResponse) -> None:
        self.root = root
        self.response = response

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        return self.open_session()

    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[SessionHandle]:
        yield SessionHandle(session=ResolverTestSession(self.root, self.response))


class RecordingQuestionBroker(QuestionBroker):
    def __init__(self) -> None:
        self.batches: list[QuestionBatch] = []

    async def ask(self, questions: QuestionBatch) -> AnswerBatch:
        self.batches.append(questions)
        return AnswerBatch(
            run_id=questions.run_id,
            answers=[
                QuestionAnswer(
                    question_id=question.id,
                    value=question.recommendation or question.choices[0],
                )
                for question in questions.questions
            ],
        )


class LiteralInvocationRenderer(SkillInvocationRenderer):
    def render(self, invocation: SkillInvocation) -> str:
        return f"{invocation.plugin}:{invocation.skill}"


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
        lambda _cwd: UnusedSessionFactory(),
        lambda _cwd: UnusedSessionFactory(),
        UnusedInvocationRenderer(),
        UnusedQuestionBroker(),
        FailingVerificationLauncher(),
    )
    core.persist(state)

    with pytest.raises(ResolverInvariantError, match="verification failed"):
        await core.integrate(state, state.outcomes)

    persisted = core.repository.load()
    assert persisted.phase == ResolvePhase.VERIFICATION
    assert persisted.final_review is None
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
        lambda _cwd: UnusedSessionFactory(),
        lambda _cwd: UnusedSessionFactory(),
        UnusedInvocationRenderer(),
        UnusedQuestionBroker(),
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


def test_human_decision_is_locked_persisted_and_cleans_ephemeral_branches(
    tmp_path: Path,
) -> None:
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
        phase=ResolvePhase.ACCEPTANCE,
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
        lambda _cwd: UnusedSessionFactory(),
        lambda _cwd: UnusedSessionFactory(),
        UnusedInvocationRenderer(),
        UnusedQuestionBroker(),
        SuccessfulLauncher(),
    )
    core.persist(state)

    manifest = core.record_human_acceptance(True)

    persisted = core.repository.load()
    assert manifest.accepted is True
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
            return {
                "concern_id": identifier,
                "changed": False,
                "summary": "material choice required",
                "questions": [
                    {
                        "id": "b-dynamic",
                        "concern_id": "b",
                        "prompt": "Choose the durable implementation",
                        "choices": ["durable"],
                        "recommendation": "durable",
                    }
                ],
            }
        relative = Path(f"{identifier}.txt")
        (root / relative).write_text(f"{identifier} round {call}\n", encoding="utf-8")
        return {
            "concern_id": identifier,
            "changed": True,
            "summary": f"implemented {identifier}",
            "files_changed": [relative.as_posix()],
        }

    def reviewer_response(root: Path, output_name: str) -> JsonObject:
        if output_name == FinalReview.__name__:
            return {"accepted": True, "reason": "combined branch verified"}
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

    broker = RecordingQuestionBroker()
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
        lambda root: ResolverTestFactory(root, worker_response),
        lambda root: ResolverTestFactory(root, reviewer_response),
        LiteralInvocationRenderer(),
        broker,
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

    manifest = await core.run(inventory)

    assert manifest.accepted is None
    assert manifest.final_review == FinalReview(
        accepted=True, reason="combined branch verified"
    )
    assert all(outcome.verified for outcome in manifest.outcomes)
    assert {outcome.concern_id for outcome in manifest.outcomes} == {"a", "b", "c"}
    assert worker_calls == {"a": 2, "b": 2, "c": 1}
    assert [batch.questions[0].id for batch in broker.batches] == [
        "a-initial",
        "b-dynamic",
    ]
    assert git("branch", "--show-current") == source_branch
    assert git("rev-parse", "HEAD") == source_commit

    completed = core.record_human_acceptance(True)

    assert completed.accepted is True
    assert [record.action for record in completed.cleanup] == [
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
