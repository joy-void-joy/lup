"""Which branches a running resolver is still holding.

A lease is indistinguishable from abandoned work by every signal a branch
survey reads — commits the integration branch lacks, no pull request driving
them — so a sweep offers to land it individually or drop it, and both answers
destroy something. The run directory is the only thing that can tell them
apart, and these pin that it is asked and believed.
"""

from pathlib import Path

from lup.devtools.dev.branches import PRStatus, disposition_for
from lup.harness.models import ResolveSpec, SkillInvocation
from lup.resolver.models import (
    AcceptanceCriterion,
    Concern,
    ConcernProgress,
    ConcernStatus,
    ResolvePhase,
    ResolveState,
    SourceSnapshot,
    WritableRootLease,
)
from lup.resolver.state import ResolverStateRepository, live_lease_branches


def run_state(
    run_id: str, phase: ResolvePhase, leases: list[WritableRootLease]
) -> ResolveState:
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
        run_id=run_id,
        phase=phase,
        source=SourceSnapshot(branch="dev", commit="a" * 40),
        spec=ResolveSpec(
            id="resolve",
            worker_identity="resolver-worker",
            worker_skill=SkillInvocation(plugin="lup", skill="worker"),
            review_skill=SkillInvocation(plugin="lup", skill="review"),
            merge_skill=SkillInvocation(plugin="lup", skill="merge"),
        ),
        concerns=concerns,
        progress=[
            ConcernProgress(
                concern_id=concern.id, status=ConcernStatus.WAITING_FOR_ANSWERS
            )
            for concern in concerns
        ],
        leases=leases,
    )


def lease(concern_id: str, root: Path, active: bool = True) -> WritableRootLease:
    return WritableRootLease(
        concern_id=concern_id,
        root=root / concern_id,
        branch=f"resolve/run-1/{concern_id}",
        active=active,
    )


def test_a_parked_run_still_holds_its_leases(tmp_path: Path) -> None:
    state_root = tmp_path / ".lup" / "resolve"
    ResolverStateRepository(state_root, "run-1").save(
        run_state("run-1", ResolvePhase.WORKERS, [lease("alpha", tmp_path / "leases")])
    )

    held = live_lease_branches(state_root)

    assert list(held) == ["resolve/run-1/alpha"]
    assert held["resolve/run-1/alpha"].run_id == "run-1"
    assert (
        held["resolve/run-1/alpha"].reason()
        == "lease of run run-1 (waiting_for_answers)"
    )


def test_a_finished_run_still_reports_what_it_left_behind(tmp_path: Path) -> None:
    """Completion releases the lease without disposing of the branch.

    Cleanup deactivates every lease whether or not it managed to delete the
    branch it named, so a survivor reads as loose work carrying the whole
    batch's commits. A sweep meeting it that way offers to land a batch that
    may already have gone in under another branch's pull request.
    """
    state_root = tmp_path / ".lup" / "resolve"
    ResolverStateRepository(state_root, "run-1").save(
        run_state(
            "run-1",
            ResolvePhase.COMPLETE,
            [lease("alpha", tmp_path / "leases", active=False)],
        )
    )

    held = live_lease_branches(state_root)

    assert list(held) == ["resolve/run-1/alpha"]
    assert held["resolve/run-1/alpha"].alive is False
    assert "resolve status --run-id run-1" in held["resolve/run-1/alpha"].reason()


def test_a_released_lease_is_not_held(tmp_path: Path) -> None:
    state_root = tmp_path / ".lup" / "resolve"
    ResolverStateRepository(state_root, "run-1").save(
        run_state(
            "run-1",
            ResolvePhase.WORKERS,
            [lease("alpha", tmp_path / "leases", active=False)],
        )
    )

    assert live_lease_branches(state_root) == {}


def test_no_resolver_directory_holds_nothing(tmp_path: Path) -> None:
    assert live_lease_branches(tmp_path / "nowhere") == {}


def test_a_run_whose_state_cannot_be_read_does_not_break_the_survey(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / ".lup" / "resolve"
    (state_root / "run-1").mkdir(parents=True)
    (state_root / "run-1" / "state.json").write_text("{ not json", encoding="utf-8")

    assert live_lease_branches(state_root) == {}


def test_a_held_branch_is_kept_rather_than_offered_for_landing() -> None:
    # The whole point: by every other signal this reads as abandoned work.
    verdict = disposition_for(
        "resolve/run-1/alpha",
        integration="dev",
        current="dev",
        contained_in=[],
        pr=None,
        unique_commits=3,
        held="lease of run run-1 (waiting_for_answers)",
    )

    assert verdict.status == "KEEP"
    assert verdict.reason == "lease of run run-1 (waiting_for_answers)"


def test_an_unheld_branch_with_the_same_shape_is_still_landable() -> None:
    verdict = disposition_for(
        "some-feature",
        integration="dev",
        current="dev",
        contained_in=[],
        pr=None,
        unique_commits=3,
    )

    assert verdict.status == "LAND"


def test_only_an_open_request_can_be_closed_a_second_time() -> None:
    """A retirement closes the request it reuses, and two states refuse that.

    Reusing whichever was most recent pushed the branch and then failed at
    the close, leaving the work half-moved: a branch that merged and then
    gained commits has a MERGED request against its head, and GitHub refuses
    that transition outright.
    """
    assert PRStatus(number=1, state="OPEN").reusable()
    assert not PRStatus(number=2, state="MERGED").reusable()
    assert not PRStatus(number=3, state="CLOSED").reusable()


def test_a_branch_sharing_no_history_is_not_offered_for_landing() -> None:
    """Both verbs a sweep offers a LAND branch would replay an unrelated tree.

    Neither counter fails without a merge base, so the figures come back
    plausible rather than absent: an adopter repo's survey read 17390 lines
    of "divergence" for branches whose real relationship to the integration
    branch was none.
    """
    verdict = disposition_for(
        "fold-other-library",
        integration="dev",
        current="dev",
        contained_in=[],
        pr=None,
        unique_commits=1,
        related=False,
    )

    assert verdict.status == "UNRELATED"
    assert verdict.reason == "shares no history with dev"


def test_a_reserved_worktree_at_the_tip_is_not_spent_work() -> None:
    """The workflow says to create a worktree first and commit into it after.

    Between those two moments the branch is the integration tip exactly, and
    containment alone reads that as merged — so a sweep offered to delete
    the workspace the documented workflow had just told the user to make.
    """
    verdict = disposition_for(
        "feat-not-started",
        integration="dev",
        current="dev",
        contained_in=["dev"],
        pr=None,
        unique_commits=0,
        at_tip=True,
        worktree="/tree/feat-not-started",
    )

    assert verdict.status == "KEEP"
    assert verdict.reason == "reserved workspace at the dev tip"


def test_a_merged_branch_still_holding_a_worktree_is_spent() -> None:
    """The ordinary cleanup path, and the case the guard above must not eat.

    A branch that landed is an ancestor of the integration branch without
    standing at its tip, which is the whole discriminator: it diverged, and
    what it diverged by is now in.
    """
    verdict = disposition_for(
        "feat-landed",
        integration="dev",
        current="dev",
        contained_in=["dev"],
        pr=None,
        unique_commits=0,
        at_tip=False,
        worktree="/tree/feat-landed",
    )

    assert verdict.status == "DELETE"
    assert verdict.reason == "merged into dev"


def test_a_stale_pointer_at_the_tip_with_no_worktree_is_still_spent() -> None:
    """Nothing is reserved, so there is nothing the delete would take away."""
    verdict = disposition_for(
        "feat-abandoned",
        integration="dev",
        current="dev",
        contained_in=["dev"],
        pr=None,
        unique_commits=0,
        at_tip=True,
        worktree=None,
    )

    assert verdict.status == "DELETE"
