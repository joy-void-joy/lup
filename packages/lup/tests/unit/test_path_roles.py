"""Path-role resolution: what a repository path is for, decided lexically."""

from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.edit import decide_edit
from lup.policy.kernel.roles import path_role
from lup.policy.kernel.rows import AcceptanceGuardRow, PathRoleRow

ROLES = [
    PathRoleRow(root="tests", role="test"),
    PathRoleRow(root="tmp", role="scratch"),
]


def test_a_declared_root_and_everything_beneath_it_carries_its_role() -> None:
    assert path_role("tests", ROLES) == "test"
    assert path_role("tests/unit/test_thing.py", ROLES) == "test"
    assert path_role("tmp/briefing.md", ROLES) == "scratch"


def test_an_undeclared_path_is_production() -> None:
    assert path_role("src/module.py", ROLES) == "production"
    assert path_role("packages/lup/src/lup/x.py", ROLES) == "production"
    assert path_role("anything", []) == "production"


def test_a_root_never_matches_a_sibling_that_merely_shares_its_prefix() -> None:
    assert path_role("tests_helpers/x.py", ROLES) == "production"
    assert path_role("tmpfile.py", ROLES) == "production"


def test_traversal_cannot_carry_a_role_out_of_its_root() -> None:
    """`tmp/../src/x.py` is production, so a scratch grant cannot reach it."""
    assert path_role("tmp/../src/x.py", ROLES) == "production"
    assert path_role("tests/../packages/lup/x.py", ROLES) == "production"
    assert path_role("../outside/x.py", ROLES) == "production"
    assert path_role("..", ROLES) == "production"


def test_an_absolute_path_holds_no_repository_role() -> None:
    """Roots are repository-relative, so an absolute path is never one of them."""
    assert path_role("/tmp/x", ROLES) == "production"
    assert path_role("/home/user/tests/x.py", ROLES) == "production"


def test_traversal_that_lands_back_inside_a_root_keeps_its_role() -> None:
    """Normalization decides, so a path is judged by where it actually points."""
    assert path_role("tmp/run/../out.json", ROLES) == "scratch"


def test_the_session_scratchpad_is_scratch_though_no_root_declares_it() -> None:
    """The harness names this root, not the repository.

    It sits outside every worktree, so no repo-relative declaration could
    reach it, and a path there is as disposable as the declared `tmp`.
    """
    assert path_role("/tmp/claude-1000/session/scratchpad/note.md", ROLES) == "scratch"
    assert path_role("$TMPDIR/note.md", ROLES) == "scratch"
    assert path_role("${TMPDIR}/nested/note.md", ROLES) == "scratch"


def test_the_scratchpad_role_survives_no_traversal_out_of_it() -> None:
    assert path_role("/tmp/claude-1000/../../etc/passwd", ROLES) == "production"
    assert path_role("$TMPDIR/../../etc/passwd", ROLES) == "production"
    assert path_role("$TMPDIR/$OTHER/x", ROLES) == "production"


def test_a_scratchpad_lookalike_is_not_the_scratchpad() -> None:
    assert path_role("/tmp/claudex/x", ROLES) == "production"
    assert path_role("/tmp/x", ROLES) == "production"


def authoring(path: str) -> str:
    """The verdict on creating a file that does not exist yet."""
    return decide_edit(
        path,
        None,
        "whatever the agent wrote",
        path_exists=False,
        path_rules=[],
        antipattern_rows=[],
        path_roles=ROLES,
    ).effect


def test_the_edit_gate_consumes_the_role_resolution_produces() -> None:
    """The resolution above is wired to the gate, not merely computed.

    Authoring in the scratchpad costs a reviewer nothing — the file
    reaches no diff — so it carries the same verdict as the declared
    `tmp`, while production still buys its full write with a question.
    """
    assert authoring("/tmp/claude-1000/session/scratchpad/note.md") == "allow"
    assert authoring("tmp/briefing.md") == "allow"
    assert authoring("src/module.py") == "ask"


GUARD = AcceptanceGuardRow(
    ask_reason="weigh the test", autonomous_reason="report instead"
)


def guarded(
    path: str, before: str | None, after: str | None, autonomous: bool = False
) -> KernelDecision:
    """One edit judged with the acceptance guard declared."""
    return decide_edit(
        path,
        before,
        after,
        path_exists=before is not None,
        path_rules=[],
        antipattern_rows=[],
        path_roles=ROLES,
        autonomous=autonomous,
        acceptance_guard=GUARD,
    )


def test_a_declared_guard_asks_before_an_ordinary_session_edits_a_test() -> None:
    """Someone has to be able to fix a test that encodes wrong behaviour.

    The gate is a question rather than a refusal for exactly that case, and
    the reason is what tells the human which of the two they are looking at.
    """
    decision = guarded("tests/unit/test_thing.py", "old body", "new body")
    assert decision.effect == "ask"
    assert decision.reason == "weigh the test"


def test_a_declared_guard_refuses_the_session_implementing_against_the_test() -> None:
    """The one caller for whom these tests are the specification.

    This is the only gate where autonomy costs a caller more rather than
    less, because everywhere else autonomy means the caller reviews its own
    edits, and here the edit is to the thing doing the reviewing.
    """
    decision = guarded("tests/unit/test_thing.py", "old body", "new body", True)
    assert decision.effect == "deny"
    assert decision.reason == "report instead"


def test_the_guard_answers_before_deletion_is_waved_through() -> None:
    """Removing the test outright is the cheapest way to stop it failing.

    Pure deletion allows unconditionally further down, so a guard that ran
    in declaration order would refuse edits to a test while permitting its
    removal — which is the same defect, faster.
    """
    assert guarded("tests/unit/test_thing.py", "old body", None).effect == "ask"
    assert guarded("tests/unit/test_thing.py", "old body", "").effect == "ask"


def test_the_guard_reaches_only_what_a_test_root_declares() -> None:
    """It is scoped by role, so nothing outside a declared test root moves."""
    assert guarded("src/module.py", "old", "new").effect == "allow"
    assert guarded("tmp/scratch.py", "old", "new").effect == "allow"


def test_an_undeclared_guard_leaves_tests_judged_by_the_ordinary_lattice() -> None:
    """Off is the library's answer, so adopting lup changes no verdict."""
    unguarded = decide_edit(
        "tests/unit/test_thing.py",
        "old body",
        "new body",
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        path_roles=ROLES,
    )
    assert unguarded.effect == "allow"
