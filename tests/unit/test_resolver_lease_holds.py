"""Which runs still hold the branches they leased, and which have let go.

A lease is indistinguishable from abandoned work by every signal a branch
survey has: commits the integration branch lacks, and no pull request driving
them. So the survey asks the run directory instead, and a run that answers
holds its branch out of the sweep entirely.

The distinction these tests pin is which phases answer. Finishing releases a
lease because the join machinery carried the work out; failing and aborting do
not, and a sweep that treats them as release offers to land or drop branches
whose work nobody has salvaged — the two verbs that each destroy something.
"""

from pathlib import Path

import pytest

from lup.devtools.dev.branches import disposition_for, runs_holding
from lup.harness.models import ResolveSpec, SkillInvocation
from lup.resolver.models import (
    AcceptanceCriterion,
    Concern,
    ConcernProgress,
    ConcernStatus,
    HeldLease,
    ResolvePhase,
    ResolveState,
    SourceSnapshot,
    WritableRootLease,
)
from lup.resolver.state import ResolverStateRepository, live_lease_branches

RUN_ID = "run-1"
BRANCH = "resolve/run-1/alpha"


def run_state(
    phase: ResolvePhase,
    *,
    active: bool = True,
    status: ConcernStatus = ConcernStatus.DISCOVERED,
) -> ResolveState:
    """One run holding one lease, at the phase and standing under test."""
    return ResolveState(
        config_digest="config-sha",
        run_id=RUN_ID,
        phase=phase,
        source=SourceSnapshot(branch="dev", commit="source-sha"),
        spec=ResolveSpec(
            id="resolve",
            worker_identity="resolver-worker",
            worker_skill=SkillInvocation(plugin="lup", skill="worker"),
            review_skill=SkillInvocation(plugin="lup", skill="review"),
            merge_skill=SkillInvocation(plugin="lup", skill="merge"),
        ),
        concerns=[
            Concern(
                id="alpha",
                title="Alpha",
                spec="Resolve alpha",
                criteria=[AcceptanceCriterion(id="alpha-done", description="done")],
            )
        ],
        progress=[ConcernProgress(concern_id="alpha", status=status)],
        leases=[
            WritableRootLease(
                concern_id="alpha",
                root=Path("/tmp/alpha"),
                branch=BRANCH,
                active=active,
            )
        ],
    )


def held(tmp_path: Path, state: ResolveState) -> dict[str, str]:
    """Persist one run and report the reason it gives per branch, if any."""
    ResolverStateRepository(tmp_path, RUN_ID).save(state)
    return {
        branch: lease.reason()
        for branch, lease in live_lease_branches(tmp_path).items()
    }


@pytest.mark.parametrize(
    "phase",
    [ResolvePhase.FAILED, ResolvePhase.ABORTED],
)
def test_a_run_that_died_still_holds_its_branches(
    tmp_path: Path, phase: ResolvePhase
) -> None:
    """Failing is not finishing, and its branches are the least salvaged."""
    assert BRANCH in held(tmp_path, run_state(phase))


def test_completion_releases_the_lease(tmp_path: Path) -> None:
    """The one phase that carried every lease through the join machinery."""
    assert held(tmp_path, run_state(ResolvePhase.COMPLETE)) == {}


def test_a_working_run_holds_its_branches(tmp_path: Path) -> None:
    assert BRANCH in held(tmp_path, run_state(ResolvePhase.WORKERS))


def test_an_inactive_lease_is_never_held(tmp_path: Path) -> None:
    """Released mid-run: the branch is the sweep's business again."""
    assert held(tmp_path, run_state(ResolvePhase.FAILED, active=False)) == {}


def test_a_dead_run_reports_its_phase_not_a_frozen_concern_status(
    tmp_path: Path,
) -> None:
    """The reason a human reads has to say the run needs salvaging.

    A per-concern status frozen at the moment the run died reads as though
    something is still working on it, which is the opposite of true.
    """
    reasons = held(
        tmp_path, run_state(ResolvePhase.FAILED, status=ConcernStatus.REVIEWING)
    )
    assert "failed" in reasons[BRANCH]
    assert "reviewing" not in reasons[BRANCH]


def test_a_working_run_reports_where_its_concern_had_got_to(tmp_path: Path) -> None:
    reasons = held(
        tmp_path, run_state(ResolvePhase.WORKERS, status=ConcernStatus.REVIEWING)
    )
    assert "reviewing" in reasons[BRANCH]


def test_a_dead_run_is_reported_as_not_alive(tmp_path: Path) -> None:
    """What a sweep reads to know nothing will retire these branches."""
    ResolverStateRepository(tmp_path, RUN_ID).save(run_state(ResolvePhase.FAILED))
    assert [hold.alive for hold in runs_holding(live_lease_branches(tmp_path))] == [
        False
    ]


def test_a_working_run_is_reported_as_alive(tmp_path: Path) -> None:
    ResolverStateRepository(tmp_path, RUN_ID).save(run_state(ResolvePhase.WORKERS))
    assert [hold.alive for hold in runs_holding(live_lease_branches(tmp_path))] == [
        True
    ]


def test_holds_group_under_the_run_answerable_for_them() -> None:
    """One entry per run, so a run-shaped sweep cannot present as loose branches."""
    holds = runs_holding(
        {
            "b": HeldLease(branch="b", run_id="two", standing="failed", alive=False),
            "a": HeldLease(branch="a", run_id="one", standing="workers"),
            "c": HeldLease(branch="c", run_id="one", standing="workers"),
        }
    )
    assert [(hold.run_id, hold.branches) for hold in holds] == [
        ("one", ["a", "c"]),
        ("two", ["b"]),
    ]


def test_no_run_holding_anything_is_no_entries() -> None:
    assert runs_holding({}) == []


def test_a_held_branch_surveys_as_keep_rather_than_land(tmp_path: Path) -> None:
    """The whole point: the disposition a sweep would act on.

    Without the hold this branch is textbook LAND — commits the integration
    branch lacks and no PR driving them — and both verbs on offer destroy
    work the run never got to carry out.
    """
    reasons = held(tmp_path, run_state(ResolvePhase.FAILED))
    verdict = disposition_for(
        BRANCH,
        integration="dev",
        current="dev-checkout",
        contained_in=[],
        pr=None,
        unique_commits=7,
        held=reasons[BRANCH],
    )
    assert verdict.status == "KEEP"
    assert RUN_ID in verdict.reason
