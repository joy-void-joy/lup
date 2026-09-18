"""Two runtimes over one image ask the image each shared question once.

Measured on `harness requirements --inside` with the default target: every
container check ran once per runtime and the boundary notice printed twice,
so a reader watched the same list go by again with nothing saying it was the
same question. Only what a runtime declares differently -- its own session
probe -- is worth a second container start.
"""

from lup.harness.requirements import LostCapability, Manifest, Requirement, Run

OPENING = ["podman", "run", "--rm", "lup-agent:abc"]


def requirement(name: str, command: list[str]) -> Requirement:
    return Requirement.model_validate(
        {
            "capability": name,
            "purpose": f"whatever {name} is for",
            "where": "image",
            "exercise": Run(command=command),
            "absence": LostCapability(capability=f"the {name} capability"),
        }
    )


CLAUDE = Manifest(
    requirements=[
        requirement("uv", ["uv", "--version"]),
        requirement("contained agent session", ["claude", "-p", "SESSION_OK"]),
    ]
)
CODEX = Manifest(
    requirements=[
        requirement("uv", ["uv", "--version"]),
        requirement("contained agent session", ["codex", "exec", "SESSION_OK"]),
    ]
)


def test_a_signature_is_the_declared_question_and_not_the_argv_it_runs_behind() -> None:
    """The same check declared twice reads the same; a different probe does not."""
    first = CLAUDE.inside_signatures()
    second = CODEX.inside_signatures()

    assert first[0] == second[0]
    assert first[1] != second[1]


def test_what_the_first_runtime_exercised_is_not_paid_for_again() -> None:
    remaining = CODEX.check_inside({}, OPENING, skipped=CLAUDE.inside_signatures())

    assert [item.requirement.capability for item in remaining] == [
        "contained agent session"
    ]


def test_nothing_skipped_exercises_everything() -> None:
    assert [
        item.requirement.capability for item in CODEX.check_inside({}, OPENING)
    ] == [
        "uv",
        "contained agent session",
    ]
