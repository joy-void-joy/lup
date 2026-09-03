"""What a profile promises, what a launch measured, and how the two differ.

The distinction this pins is the one the whole type exists for: configuration
intent is not capability evidence. A profile asking for containment and a
runtime whose containment failed to start read identically from the
configuration alone, and only a measurement separates them.
"""

from lup.policy.boundary import (
    BoundaryPreflight,
    CapabilityEvidence,
    CapabilityRequirement,
    ExecutionBoundary,
)


def contained_profile() -> ExecutionBoundary:
    """A profile whose containment is the point, with an optional host channel."""
    return ExecutionBoundary(
        name="contained",
        contained=True,
        unjudged_ambient="ask",
        capabilities=[
            CapabilityRequirement(
                capability="inside_placement",
                required=True,
                reason="containment is what this profile is",
            ),
            CapabilityRequirement(
                capability="question_relay",
                required=True,
                reason="every final ask is recorded here",
            ),
            CapabilityRequirement(
                capability="host_executor",
                required=False,
                reason="an approved crossing may be carried by a person instead",
            ),
        ],
    )


def test_a_launch_missing_a_required_capability_does_not_start() -> None:
    """A session that cannot deliver its own boundary is not the one asked for.

    Failing the launch rather than degrading, because every degradation here
    is silent: the placements still say ``inside`` and the operations run
    wherever the session happened to land.
    """
    preflight = BoundaryPreflight(
        boundary=contained_profile(),
        evidence=[
            CapabilityEvidence(capability="question_relay", delivered=True),
            CapabilityEvidence(
                capability="inside_placement",
                delivered=False,
                detail="the contained sentinel was not observed",
            ),
        ],
    )

    assert not preflight.launchable()
    assert [entry.capability for entry in preflight.missing_required()] == [
        "inside_placement"
    ]


def test_the_diagnosis_names_what_was_tried_and_not_only_that_it_failed() -> None:
    """ "The sandbox is broken" sends somebody to read configuration.

    Naming the measurement sends them to the thing that failed, which is the
    difference between a diagnostic and a complaint.
    """
    preflight = BoundaryPreflight(
        boundary=contained_profile(),
        evidence=[
            CapabilityEvidence(
                capability="inside_placement",
                delivered=False,
                detail="the contained sentinel was not observed",
            )
        ],
    )

    diagnosis = preflight.diagnosis()

    assert "cannot start" in diagnosis
    assert "inside_placement" in diagnosis
    assert "sentinel was not observed" in diagnosis


def test_a_missing_optional_capability_blocks_only_what_depends_on_it() -> None:
    """Not a failure of the launch, and not a question for anybody.

    No reviewer approves a channel into existence, so an operation needing
    one is refused with a typed cause — which sends the agent to the missing
    channel instead of to argue with a rule.
    """
    preflight = BoundaryPreflight(
        boundary=contained_profile(),
        evidence=[
            CapabilityEvidence(capability="inside_placement", delivered=True),
            CapabilityEvidence(capability="question_relay", delivered=True),
            CapabilityEvidence(
                capability="host_executor", delivered=False, detail="no socket declared"
            ),
        ],
    )

    assert preflight.launchable()
    assert preflight.blocked() == ["host_executor"]
    assert "dependent operations are refused" in preflight.diagnosis()
    assert preflight.opening() == preflight.blocked_line()


def test_a_boundary_that_delivered_what_it_promised_says_nothing() -> None:
    """The expected case is the uninformative one.

    A capability per line, each reporting that a measurement came out the way
    the profile said it would, is a block saying "as declared" in as many
    lines as there are capabilities -- printed before every session, above
    the one line that is different today.
    """
    delivered = BoundaryPreflight(
        boundary=contained_profile(),
        evidence=[
            CapabilityEvidence(capability="inside_placement", delivered=True),
            CapabilityEvidence(capability="question_relay", delivered=True),
            CapabilityEvidence(capability="host_executor", delivered=True),
        ],
    )

    assert delivered.opening() == ""
    assert "inside_placement" in delivered.diagnosis()


def test_a_launch_that_cannot_start_says_the_whole_measurement() -> None:
    """Then every line of it is evidence for a refusal, and none of it waits.

    The opening block is printed after the last measurement and a refusing
    launch never reaches it, so the one report a reader cannot afford to lose
    is the one that cannot be held.
    """
    refused = BoundaryPreflight(
        boundary=contained_profile(),
        evidence=[
            CapabilityEvidence(
                capability="inside_placement",
                delivered=False,
                detail="the container reported no sentinel",
            ),
        ],
    )

    assert not refused.launchable()
    assert refused.opening() == refused.diagnosis()
    assert "the container reported no sentinel" in refused.opening()


def test_configuration_intent_is_not_capability_evidence() -> None:
    """The two shapes that read identically from the declaration alone.

    A profile that asks for containment says ``contained=True`` whether or
    not anything delivered it. Only the measurement separates the session
    that is contained from the one that merely asked to be.
    """
    profile = contained_profile()
    asked = BoundaryPreflight(boundary=profile, evidence=[])
    measured = BoundaryPreflight(
        boundary=profile,
        evidence=[
            CapabilityEvidence(capability="inside_placement", delivered=True),
            CapabilityEvidence(capability="question_relay", delivered=True),
        ],
    )

    assert profile.contained
    assert not asked.delivered("inside_placement")
    assert measured.delivered("inside_placement")
    assert not asked.launchable()
    assert measured.launchable()


def test_a_profile_declares_what_it_does_with_work_nobody_judged() -> None:
    """Two answers, both declared, neither inherited from a gap.

    ``ask`` keeps unjudged work visible and is the default. ``defer`` is a
    profile deliberately handing the long tail to provider-native judgement,
    which is a posture somebody chose rather than one a parser limit produced.
    """
    assert ExecutionBoundary().unjudged_ambient == "ask"
    assert ExecutionBoundary(unjudged_ambient="defer").unjudged_ambient == "defer"


def test_a_capability_nothing_declares_is_neither_required_nor_blocked() -> None:
    """A profile depends on what it says it depends on, and nothing else.

    The alternative — every capability implicitly required — makes adding one
    to the vocabulary a change that fails every existing profile's launch.
    """
    profile = ExecutionBoundary()

    assert not profile.declares("checkpoint_store")
    assert not profile.requires("checkpoint_store")
    assert BoundaryPreflight(boundary=profile).launchable()
