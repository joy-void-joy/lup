"""Compiling a boundary from a declaration, and measuring it against probes.

The suite for the half `test_execution_boundary.py` deliberately leaves out.
That one pins what the types mean once somebody holds them; this one pins that
a project's own declaration is what fills them, and that a launch's own probes
are what answer them — which is the difference between a boundary and a claim.
"""

from pathlib import Path

from lup.harness.models import HookPathRole, HookSandbox, HookSet
from lup.harness.requirements import (
    Finding,
    LostCapability,
    RefusedLaunch,
    Requirement,
    Run,
)
from lup.policy.boundary import BoundaryCapability, depends_on
from lup.policy.profiles import compile_boundary, measured


def declaration(capabilities: list[BoundaryCapability] = []) -> HookSet:
    """A hook set spelling one of each thing the boundary reads off it."""
    return HookSet(
        id="hooks.probe",
        policy_ids=[],
        boundary_capabilities=capabilities,
        path_roles=[
            HookPathRole(root=Path("build"), role="scratch"),
            HookPathRole(root=Path("tests"), role="test"),
        ],
        sandbox=HookSandbox(
            extra_domains=["api.example.com"],
            credential_paths=["~/.ssh"],
            writable_paths=["~/.cache/uv"],
            excluded_commands=["git *"],
        ),
    )


def answered(capability: str, working: bool, detail: str = "") -> Finding:
    """One roster's answer about one requirement, without running anything."""
    return Finding(
        requirement=Requirement(
            capability=capability,
            purpose="a probe standing in for a real one",
            exercise=Run(command=["true"]),
            absence=LostCapability(capability=capability),
        ),
        working=working,
        detail=detail,
    )


def test_the_boundary_is_read_off_the_declaration_rather_than_restated() -> None:
    """A second list is a list that drifts.

    Every field here already exists in the project's harness declaration, so
    compiling is what keeps a path added to the sandbox grant, or a tree given
    the scratch role, from having to be remembered twice.
    """
    boundary = compile_boundary(declaration(), contained=True)

    assert boundary.disposable_roots == [Path("build")]
    assert Path("~/.cache/uv") in boundary.writable_roots
    assert boundary.credential_paths == [Path("~/.ssh")]
    assert "api.example.com" in boundary.network_destinations


def test_a_profile_is_named_for_what_it_promises() -> None:
    """The name reaches a diagnostic, so it says which profile could not start."""
    assert compile_boundary(declaration(), contained=True).name == "contained"
    assert compile_boundary(declaration(), contained=False).name == "ambient"


def test_the_lease_is_the_writable_half_a_judgement_can_use() -> None:
    """Absolute and mounted at the same path on both sides, which the grants are not.

    The declared sandbox grants answer for an uncontained session and are
    spelled as they were written; the lease is what a write target can
    actually be judged against.
    """
    leased = Path("/repo/tree/feature")

    boundary = compile_boundary(declaration(), contained=True, writable=[leased])

    assert boundary.writable_roots[0] == leased


def test_a_capability_nothing_measures_is_absent_rather_than_omitted() -> None:
    """A guarantee whose mechanism has not been built is absent, and says so.

    Omitting it would say the profile does not depend on it, which is a
    different claim — and the one that quietly permits every operation the
    missing channel was supposed to carry.
    """
    capabilities = [depends_on("host_executor", required=False, reason="no transport")]
    boundary = compile_boundary(declaration(capabilities), contained=True)

    preflight = measured(boundary, capabilities, [])

    assert preflight.launchable()
    assert preflight.blocked() == ["host_executor"]
    assert "no mechanism carries host_executor" in preflight.diagnosis()


def test_a_declared_probe_no_roster_ran_is_a_failed_measurement() -> None:
    """The wiring mistake this layer must not swallow.

    A capability naming a manifest handle nothing declares, or a host-side
    probe expected out of an image-side roster, is a capability that was never
    asked about. Reported as delivered it would be the exact claim-without-a-
    check the whole type exists to refuse, so it is reported as a failure that
    names which handle went unexercised.
    """
    capabilities = [depends_on("question_relay", "question relay")]
    boundary = compile_boundary(declaration(capabilities), contained=True)

    preflight = measured(boundary, capabilities, [answered("something else", True)])

    assert not preflight.delivered("question_relay")
    assert "'question relay'" in preflight.diagnosis()
    assert "never asked about" in preflight.diagnosis()


def test_a_probes_own_words_reach_the_diagnostic() -> None:
    """ "The sandbox is broken" sends somebody to read configuration."""
    capabilities = [depends_on("inside_placement", "inside placement")]
    boundary = compile_boundary(declaration(capabilities), contained=True)

    preflight = measured(
        boundary,
        capabilities,
        [answered("inside placement", False, "the container reported no sentinel")],
    )

    assert not preflight.launchable()
    assert "the container reported no sentinel" in preflight.diagnosis()


def test_a_required_capability_stops_the_launch_and_an_optional_one_does_not() -> None:
    """The two failures are different on purpose, and both are measured here.

    A session that cannot deliver its own boundary is not the session anybody
    asked for. A session missing an optional channel is — it simply cannot do
    the things that channel carries, and refusing those with a typed cause is
    what sends the agent to the channel rather than to argue with a rule.
    """
    capabilities = [
        depends_on(
            "inside_placement", "inside placement", reason="the profile is this"
        ),
        depends_on("checkpoint_store", "checkpoint store", required=False),
    ]
    boundary = compile_boundary(declaration(capabilities), contained=True)

    preflight = measured(
        boundary,
        capabilities,
        [
            answered("inside placement", True, "sentinel observed"),
            answered("checkpoint store", False, "the ref namespace refused a write"),
        ],
    )

    assert preflight.launchable()
    assert preflight.blocked() == ["checkpoint_store"]
    assert preflight.delivered("inside_placement")


def test_every_declared_capability_gets_a_row_including_the_ones_that_failed() -> None:
    """A preflight holding only what worked reads like one where nothing was asked."""
    capabilities = [
        depends_on("inside_placement", "inside placement"),
        depends_on("question_relay", "question relay"),
        depends_on("host_executor", required=False),
    ]
    boundary = compile_boundary(declaration(capabilities), contained=True)

    preflight = measured(
        boundary,
        capabilities,
        [
            answered("inside placement", True),
            answered("question relay", False, "the queue directory refused a write"),
        ],
    )

    assert [entry.capability for entry in preflight.evidence] == [
        "inside_placement",
        "question_relay",
        "host_executor",
    ]


def test_a_requirement_the_refusal_grade_belongs_to_is_the_manifests_not_this() -> None:
    """Two vocabularies for absence, and they answer different questions.

    A manifest entry's ``absence`` decides whether the *roster* stops a launch,
    and a capability's ``required`` decides whether the *profile* does. They
    agree here by declaration rather than by derivation, because a project may
    depend on a capability the library offers as merely degrading — and a
    derivation would quietly overrule it.
    """
    entry = Requirement(
        capability="checkpoint store",
        purpose="proving a loss was captured",
        exercise=Run(command=["true"]),
        absence=RefusedLaunch(because="the store is what recovery rests on"),
    )
    capabilities = [depends_on("checkpoint_store", "checkpoint store", required=False)]
    boundary = compile_boundary(declaration(capabilities), contained=True)

    preflight = measured(
        boundary,
        capabilities,
        [Finding(requirement=entry, working=False, detail="refused")],
    )

    assert preflight.launchable()
    assert preflight.blocked() == ["checkpoint_store"]
