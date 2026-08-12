"""Bringing a run's base up to the branch it was cut from.

A run pinned to its creation commit cannot see a fix made to unblock it, so
its workers reason about code that has already been replaced and argue,
carefully and wrongly, for reverting decisions the repository has already
taken. These exercise real Git, because what is being claimed is what Git
does with three shapes of moved branch.
"""

from pathlib import Path

from lup.harness.models import ResolveSpec, SkillInvocation
from lup.harness.process import LaunchRequest, LocalProcessLauncher
from lup.resolver.journal import Journal
from lup.resolver.models import (
    AcceptanceCriterion,
    Concern,
    ConcernOutcome,
    ConcernProgress,
    ConcernStatus,
    ResolvePhase,
    ResolveState,
    SourceSnapshot,
    WritableRootLease,
)
from lup.resolver.orchestrator import WorktreeOrchestrator
from lup.resolver.rebase import BaseRefresher
from lup.resolver.run import ResolveRun
from lup.resolver.state import ResolverStateRepository


class Repository:
    """One throwaway repository, and the few operations these tests need."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.launcher = LocalProcessLauncher()
        root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-b", "dev")
        self.git("config", "user.email", "resolver@example.test")
        self.git("config", "user.name", "Resolver Test")

    def git(self, *arguments: str) -> str:
        status = self.launcher.launch(
            LaunchRequest(arguments=["git", *arguments], cwd=self.root)
        )
        if status.code != 0:
            raise AssertionError(f"{arguments}: {status.stderr}")
        return status.stdout.strip()

    def commit(self, name: str, content: str) -> str:
        (self.root / name).write_text(content, encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-m", f"write {name}")
        return self.git("rev-parse", "HEAD")

    def snapshot(self, note: str) -> str:
        """An unattached commit carrying an uncommitted file, as intake makes.

        Exactly the shape no branch holds: a real commit on top of HEAD that
        the branch itself never reaches, which is why a refresh cannot be a
        matter of taking the newer tip.
        """
        head = self.git("rev-parse", "HEAD")
        (self.root / "notes.md").write_text(note, encoding="utf-8")
        self.git("add", "notes.md")
        tree = self.git("write-tree")
        self.git("reset", "HEAD", "--", "notes.md")
        return self.git("commit-tree", tree, "-p", head, "-m", "source snapshot")

    def orchestrator(self) -> WorktreeOrchestrator:
        return WorktreeOrchestrator(self.launcher, self.root)

    def content(self, commit: str, path: str) -> str:
        return self.git("show", f"{commit}:{path}")


def test_a_branch_that_has_not_moved_keeps_the_base_it_had(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "source")
    head = repository.commit("a.py", "one\n")

    refreshed = repository.orchestrator().refreshed_base(
        SourceSnapshot(branch="dev", commit=head)
    )

    assert not refreshed.moved()
    assert refreshed.commit == head


def test_a_branch_that_moved_forward_is_taken_outright(tmp_path: Path) -> None:
    """The reported run exactly: the fix landed while the run was parked."""
    repository = Repository(tmp_path / "source")
    started = repository.commit("a.py", "one\n")
    fixed = repository.commit("a.py", "one, fixed\n")

    refreshed = repository.orchestrator().refreshed_base(
        SourceSnapshot(branch="dev", commit=started)
    )

    assert refreshed.moved()
    assert refreshed.commit == fixed
    assert refreshed.was == started


def test_an_intake_snapshot_is_merged_rather_than_replaced(tmp_path: Path) -> None:
    """A run planned from uncommitted notes must not lose them to a refresh."""
    repository = Repository(tmp_path / "source")
    repository.commit("a.py", "one\n")
    snapshot = repository.snapshot("# lup: fix this\n")
    repository.commit("b.py", "the upstream fix\n")

    refreshed = repository.orchestrator().refreshed_base(
        SourceSnapshot(branch="dev", commit=snapshot)
    )

    assert refreshed.moved()
    assert refreshed.conflicts == []
    assert repository.content(refreshed.commit, "notes.md") == "# lup: fix this"
    assert repository.content(refreshed.commit, "b.py") == "the upstream fix"


def test_a_refresh_that_would_conflict_names_the_paths_and_stays_put(
    tmp_path: Path,
) -> None:
    """What would be lost is reported; the leases beside it keep their base."""
    repository = Repository(tmp_path / "source")
    repository.commit("a.py", "one\n")
    snapshot = repository.snapshot("this run's notes\n")
    (repository.root / "notes.md").write_text("a rival edit\n", encoding="utf-8")
    repository.git("add", "notes.md")
    repository.git("commit", "-m", "upstream writes the same file")

    refreshed = repository.orchestrator().refreshed_base(
        SourceSnapshot(branch="dev", commit=snapshot)
    )

    assert not refreshed.moved()
    assert [path.as_posix() for path in refreshed.conflicts] == ["notes.md"]
    assert "conflicts" in refreshed.reason


def test_a_branch_the_repository_does_not_have_says_so(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "source")
    head = repository.commit("a.py", "one\n")

    refreshed = repository.orchestrator().refreshed_base(
        SourceSnapshot(branch="detached", commit=head)
    )

    assert not refreshed.moved()
    assert "no branch named 'detached'" in refreshed.reason


def test_a_lease_holding_work_is_told_what_a_refresh_would_conflict_on(
    tmp_path: Path,
) -> None:
    """The concerns most likely to conflict edit the files the fix touched."""
    repository = Repository(tmp_path / "source")
    started = repository.commit("a.py", "one\n")
    worktrees = repository.orchestrator()
    lease = WritableRootLease(
        concern_id="alpha", root=tmp_path / "leases" / "alpha", branch="resolve/alpha"
    )
    worktrees.create(lease, started)
    (lease.root / "a.py").write_text("the worker's rewrite\n", encoding="utf-8")
    repository.launcher.launch(
        LaunchRequest(arguments=["git", "commit", "-am", "worker"], cwd=lease.root)
    )
    upstream = repository.commit("a.py", "the upstream fix\n")

    conflicts = worktrees.predicted_merge(lease, upstream)

    assert [path.as_posix() for path in conflicts] == ["a.py"]
    assert not worktrees.merge_into(lease, upstream, "resolve: refresh")


def test_a_lease_that_touched_nothing_contested_merges_the_moved_base(
    tmp_path: Path,
) -> None:
    repository = Repository(tmp_path / "source")
    started = repository.commit("a.py", "one\n")
    worktrees = repository.orchestrator()
    lease = WritableRootLease(
        concern_id="beta", root=tmp_path / "leases" / "beta", branch="resolve/beta"
    )
    worktrees.create(lease, started)
    (lease.root / "b.py").write_text("the worker's own file\n", encoding="utf-8")
    repository.launcher.launch(
        LaunchRequest(arguments=["git", "add", "-A"], cwd=lease.root)
    )
    repository.launcher.launch(
        LaunchRequest(arguments=["git", "commit", "-m", "worker"], cwd=lease.root)
    )
    upstream = repository.commit("c.py", "the upstream fix\n")

    assert worktrees.predicted_merge(lease, upstream) == []
    assert worktrees.merge_into(lease, upstream, "resolve: refresh")
    assert (lease.root / "c.py").read_text(encoding="utf-8") == "the upstream fix\n"
    assert (lease.root / "b.py").exists()


def refresher(repository: Repository, state: ResolveState) -> BaseRefresher:
    """One refresher over a run whose state is held in memory."""
    journal = Journal(repository.root / ".lup")
    run = ResolveRun(
        ResolverStateRepository(repository.root / ".lup", "run-1"), journal
    )
    run.state = state
    return BaseRefresher(run, repository.orchestrator(), journal)


def run_state(source: SourceSnapshot, leases: list[WritableRootLease]) -> ResolveState:
    concerns = [
        Concern(
            id=lease.concern_id,
            title=lease.concern_id,
            spec=f"Resolve {lease.concern_id}",
            criteria=[AcceptanceCriterion(id="c1", description="done")],
        )
        for lease in leases
    ]
    return ResolveState(
        config_digest="digest",
        run_id="run-1",
        phase=ResolvePhase.WORKERS,
        source=source,
        spec=ResolveSpec(
            id="resolve",
            worker_identity="resolver-worker",
            worker_skill=SkillInvocation(plugin="lup", skill="worker"),
            review_skill=SkillInvocation(plugin="lup", skill="review"),
            merge_skill=SkillInvocation(plugin="lup", skill="merge"),
        ),
        concerns=concerns,
        progress=[
            ConcernProgress(concern_id=concern.id, status=ConcernStatus.LEASED)
            for concern in concerns
        ],
        leases=leases,
    )


def test_a_lease_created_after_the_branch_moved_is_cut_from_the_fix(
    tmp_path: Path,
) -> None:
    """The reported run: parked for a fix, resumed, and leased 28 stale trees."""
    repository = Repository(tmp_path / "source")
    started = repository.commit("a.py", "one\n")
    fixed = repository.commit("a.py", "one, fixed\n")
    state = run_state(SourceSnapshot(branch="dev", commit=started), [])

    refreshed = refresher(repository, state).refreshed(state)

    assert refreshed.root_base().commit == fixed
    assert refreshed.source.commit == started


def test_a_refresh_reports_every_live_lease_before_it_touches_one(
    tmp_path: Path,
) -> None:
    repository = Repository(tmp_path / "source")
    started = repository.commit("a.py", "one\n")
    worktrees = repository.orchestrator()
    contested = WritableRootLease(
        concern_id="alpha", root=tmp_path / "leases" / "alpha", branch="resolve/alpha"
    )
    clean = WritableRootLease(
        concern_id="beta", root=tmp_path / "leases" / "beta", branch="resolve/beta"
    )
    for lease, name in ((contested, "a.py"), (clean, "b.py")):
        worktrees.create(lease, started)
        (lease.root / name).write_text("the worker's work\n", encoding="utf-8")
        repository.launcher.launch(
            LaunchRequest(arguments=["git", "add", "-A"], cwd=lease.root)
        )
        repository.launcher.launch(
            LaunchRequest(arguments=["git", "commit", "-m", "worker"], cwd=lease.root)
        )
    repository.commit("a.py", "the upstream fix\n")
    state = run_state(SourceSnapshot(branch="dev", commit=started), [contested, clean])

    report = refresher(repository, state).report(state)

    assert report.base.moved()
    assert not report.applied
    named = {lease.concern_id: lease for lease in report.leases}
    assert [path.as_posix() for path in named["alpha"].conflicts] == ["a.py"]
    assert named["beta"].conflicts == []
    assert not named["beta"].applied
    assert (contested.root / "a.py").read_text(
        encoding="utf-8"
    ) == "the worker's work\n"


def test_applying_a_refresh_merges_only_what_would_not_conflict(
    tmp_path: Path,
) -> None:
    repository = Repository(tmp_path / "source")
    started = repository.commit("a.py", "one\n")
    worktrees = repository.orchestrator()
    contested = WritableRootLease(
        concern_id="alpha", root=tmp_path / "leases" / "alpha", branch="resolve/alpha"
    )
    clean = WritableRootLease(
        concern_id="beta", root=tmp_path / "leases" / "beta", branch="resolve/beta"
    )
    for lease, name in ((contested, "a.py"), (clean, "b.py")):
        worktrees.create(lease, started)
        (lease.root / name).write_text("the worker's work\n", encoding="utf-8")
        repository.launcher.launch(
            LaunchRequest(arguments=["git", "add", "-A"], cwd=lease.root)
        )
        repository.launcher.launch(
            LaunchRequest(arguments=["git", "commit", "-m", "worker"], cwd=lease.root)
        )
    repository.commit("a.py", "the upstream fix\n")
    state = run_state(SourceSnapshot(branch="dev", commit=started), [contested, clean])

    report = refresher(repository, state).report(state, apply=True)

    named = {lease.concern_id: lease for lease in report.leases}
    assert named["beta"].applied
    assert not named["alpha"].applied
    assert (clean.root / "a.py").read_text(encoding="utf-8") == "the upstream fix\n"
    assert (clean.root / "b.py").exists()
    assert (contested.root / "a.py").read_text(
        encoding="utf-8"
    ) == "the worker's work\n"


def test_a_verified_concern_is_left_where_its_recorded_commit_says(
    tmp_path: Path,
) -> None:
    """Moving its branch is how a resume refuses a run over its own commit."""
    repository = Repository(tmp_path / "source")
    started = repository.commit("a.py", "one\n")
    worktrees = repository.orchestrator()
    lease = WritableRootLease(
        concern_id="alpha", root=tmp_path / "leases" / "alpha", branch="resolve/alpha"
    )
    worktrees.create(lease, started)
    repository.commit("b.py", "the upstream fix\n")
    state = run_state(SourceSnapshot(branch="dev", commit=started), [lease])
    verified = state.model_copy(
        update={
            "outcomes": [
                ConcernOutcome(
                    concern_id="alpha",
                    branch=lease.branch,
                    commit=started,
                    head=started,
                    verified=True,
                )
            ]
        }
    )

    report = refresher(repository, verified).report(verified, apply=True)

    assert report.leases == []
    assert not (lease.root / "b.py").exists()
