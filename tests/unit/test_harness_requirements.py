"""Behavior tests for the declare-and-exercise requirement manifest.

The point of the manifest is that it says something true about the machine it
runs on, so most of these pin the distinctions a presence check cannot make:
installed-but-not-working, one capability spelled several ways, and a
diagnosis that stays quiet about a failure it does not explain.
"""

from lup.harness.requirements import (
    Advisory,
    AnyOf,
    EnvironmentRedirect,
    ExerciseOutcome,
    Finding,
    LostCapability,
    Manifest,
    RefusedLaunch,
    Requirement,
    Run,
    SupplementaryGroup,
    refused,
)

WORKING = Run(command=["echo", "hello"])
"""A command every host this suite runs on has, exercised for real."""


def requirement(name: str, exercise: Run | AnyOf, **rest: object) -> Requirement:
    """One requirement with the fields a test does not care about filled in."""
    return Requirement(
        capability=name,
        purpose=f"whatever {name} is for",
        exercise=exercise,
        absence=LostCapability(capability=f"the {name} capability"),
        **rest,  # pyright: ignore[reportArgumentType]
    )


def test_a_clean_exit_proves_a_requirement() -> None:
    found = requirement("echo", WORKING).check({})
    assert found.working
    assert found.lines() == ["echo: working"]


def test_a_missing_program_is_named_as_missing_rather_than_as_a_failure() -> None:
    """`not on PATH` and `exited 1` send a reader to different places."""
    found = requirement("absent", Run(command=["lup-no-such-program"])).check({})
    assert not found.working
    assert "not on PATH" in found.detail


def test_a_program_that_runs_without_working_is_not_counted_as_working() -> None:
    """The failure a presence check cannot see: installed, and doing nothing.

    `expect` is the whole reason the manifest exercises rather than probes --
    a daemon client that answers while pointed at the wrong endpoint exits
    zero, and every `which` in the world calls that success.
    """
    found = requirement("wrong", Run(command=["echo", "nothing"], expect="banana"))
    checked = found.check({})
    assert not checked.working
    assert "installed without working" in checked.detail


def test_any_of_takes_the_first_spelling_that_works() -> None:
    """A capability several programs provide is held when any one is."""
    exercise = AnyOf(
        alternatives=[Run(command=["lup-no-such-program"]), WORKING],
    )
    assert requirement("clipboard", exercise).check({}).working


def test_any_of_reports_every_spelling_it_tried_when_none_worked() -> None:
    """Naming one absent program would send an operator to install the wrong one."""
    exercise = AnyOf(
        alternatives=[
            Run(command=["lup-no-such-program"]),
            Run(command=["lup-also-absent"]),
        ],
    )
    detail = requirement("clipboard", exercise).check({}).detail
    assert "lup-no-such-program" in detail and "lup-also-absent" in detail


def test_a_lost_capability_does_not_stop_a_launch() -> None:
    """Absence is an ordinary answer: no clipboard is still a usable session."""
    found = requirement("clipboard", Run(command=["lup-no-such-program"])).check({})
    assert not found.refuses()
    assert refused([found]) == []


def test_a_refusing_requirement_stops_a_launch() -> None:
    stopped = Requirement(
        capability="uv",
        purpose="every command here",
        exercise=Run(command=["lup-no-such-program"]),
        absence=RefusedLaunch(because="nothing runs without it"),
    ).check({})
    assert stopped.refuses()
    assert refused([stopped]) == [stopped]


def test_an_environment_redirect_names_the_endpoint_rather_than_the_service() -> None:
    """The diagnosis that replaces an evening: the variable, not the daemon."""
    redirect = EnvironmentRedirect(variable="DOCKER_HOST")
    spoken = redirect.cause(
        {"DOCKER_HOST": "unix:///nowhere/at/all.sock"},
        ExerciseOutcome(proved=False, detail="cannot connect"),
    )
    assert "DOCKER_HOST points at /nowhere/at/all.sock" in spoken
    assert "does not exist" in spoken


def test_an_environment_redirect_is_silent_when_the_target_is_there() -> None:
    redirect = EnvironmentRedirect(variable="DOCKER_HOST")
    outcome = ExerciseOutcome(proved=False, detail="cannot connect")
    assert redirect.cause({"DOCKER_HOST": "unix:///"}, outcome) == ""
    assert redirect.cause({}, outcome) == ""


def test_a_group_diagnosis_stays_quiet_about_a_failure_it_cannot_explain() -> None:
    """The red herring this gate exists for.

    A group difference is nearly always present and nearly never the cause.
    Ungated, this volunteered "this session is not in the docker group" for a
    daemon reached over a socket the user already owned outright -- true about
    the groups, unrelated to the failure, and actively costly: a reader who
    acts on it starts a new session and finds nothing changed.
    """
    group = SupplementaryGroup(group="docker")
    unrelated = ExerciseOutcome(proved=False, detail="docker is not on PATH")
    assert group.cause({"USER": "anybody"}, unrelated) == ""


def test_a_group_diagnosis_speaks_when_the_failure_is_a_refusal() -> None:
    """Gated on the failure looking like one a group would cause, not on nothing."""
    group = SupplementaryGroup(group="lup-no-such-group")
    refusal = ExerciseOutcome(proved=False, detail="permission denied")
    assert "no lup-no-such-group group" in group.cause({"USER": "anybody"}, refusal)


def test_a_manifest_collects_the_packages_an_image_installs_without_repeating_one() -> (
    None
):
    """One roster feeds the preflight and the image, so they cannot disagree."""
    manifest = Manifest(
        requirements=[
            requirement("first", WORKING, where="image", install=["shared", "one"]),
            requirement("second", WORKING, where="both", install=["shared", "two"]),
        ]
    )
    assert manifest.packages() == ["shared", "one", "two"]


def test_a_host_requirement_never_reaches_the_image() -> None:
    """The container runtime is the case: a socket inside is a full host escape."""
    manifest = Manifest(
        requirements=[requirement("runtime", WORKING, where="host", install=["docker"])]
    )
    assert manifest.packages() == []


def test_an_image_requirement_is_not_exercised_on_the_host() -> None:
    """A laptop with no TypeScript toolchain is not a laptop with a problem."""
    manifest = Manifest(
        requirements=[
            requirement("bun", Run(command=["lup-no-such-program"]), where="image")
        ]
    )
    assert manifest.check({}) == []
    assert manifest.on_the_host(advisory=True) == []


def test_an_advisory_is_silent_at_launch_and_spoken_at_setup() -> None:
    """A nicety repeated before every session becomes a line people skip."""
    convenience = Requirement(
        capability="clipboard",
        purpose="pasting the next command",
        exercise=Run(command=["lup-no-such-program"]),
        absence=Advisory(improves="copying a command to the clipboard"),
    )
    manifest = Manifest(requirements=[convenience])
    assert manifest.check({}) == []
    spoken = manifest.check({}, advisory=True)
    assert [item.requirement.capability for item in spoken] == ["clipboard"]
    assert not spoken[0].refuses()


def test_an_empty_manifest_checks_nothing_and_installs_nothing() -> None:
    """A project with a pure-Python toolchain must not be told it is missing anything."""
    assert Manifest().check({}) == []
    assert Manifest().packages() == []


def test_a_failing_finding_says_what_was_lost_and_what_needed_it() -> None:
    """Why it failed and what is now missing are different questions."""
    lines = requirement("clipboard", Run(command=["lup-no-such-program"])).check({})
    rendered = "\n".join(lines.lines())
    assert "the clipboard capability is unavailable" in rendered
    assert "needed for whatever clipboard is for" in rendered


def test_the_declared_manifest_names_only_programs_this_project_invokes() -> None:
    """A manifest that invents a prerequisite refuses machines that were fine.

    Pinned as a count rather than a list so adding a genuine requirement is
    an ordinary edit, while the roster staying small stays deliberate: an
    earlier draft declared ripgrep, which this project never invokes.
    """
    from lup_template.devtools.harness.content.requirements import MANIFEST

    declared = [item.capability for item in MANIFEST.requirements]
    assert "ripgrep" not in declared
    assert all(item.purpose for item in MANIFEST.requirements)
    assert [item for item in MANIFEST.requirements if item.absence.refuses()]


def test_the_declared_manifest_keeps_a_container_runtime_out_of_the_image() -> None:
    """A container holding a runtime socket can mount the whole host into a sibling."""
    from lup_template.devtools.harness.content.requirements import CONTAINER, MANIFEST

    assert CONTAINER.where == "host"
    assert CONTAINER.install == []
    assert not any("docker" in package for package in MANIFEST.packages())


def test_the_declared_manifest_asks_the_host_for_nothing_image_side() -> None:
    """bun and typescript live in the image, so a bare host is never faulted."""
    from lup_template.devtools.harness.content.requirements import MANIFEST

    on_host = [item.capability for item in MANIFEST.on_the_host(advisory=True)]
    assert "bun" not in on_host and "typescript" not in on_host
    assert {"bun", "typescript"} <= set(MANIFEST.packages())


def test_a_finding_carries_the_requirement_that_produced_it() -> None:
    """So a caller reporting one can say what it was for without a lookup."""
    declared = requirement("echo", WORKING)
    assert Finding(requirement=declared, working=True).requirement is declared
