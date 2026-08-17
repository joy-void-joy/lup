"""Path-role resolution: what a repository path is for, decided lexically."""

from typing import cast

from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.edit import decide_edit
from lup.policy.kernel.roles import path_role
from lup.policy.kernel.rows import AcceptanceGuardRow, PathRoleRow

ROLES = [
    PathRoleRow(root="tests", role="test", kind="subtree"),
    PathRoleRow(root="tmp", role="scratch", kind="subtree"),
]

NESTED = [
    PathRoleRow(root="tests", role="test", kind="subtree"),
    PathRoleRow(root="tmp", role="scratch", kind="contains_part"),
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


def test_a_subtree_root_reaches_only_the_repository_top() -> None:
    """The default, and what a laid-out tree means by naming a directory."""
    assert path_role("packages/lup/tmp/briefing.md", ROLES) == "production"
    assert path_role("src/app/tests/helper.py", ROLES) == "production"


def test_a_part_matched_root_is_that_directory_wherever_it_sits() -> None:
    """A package opens its own scratch directory beside itself.

    What makes one scratch is what it is, not which package happens to hold
    it, so the declaration matches the segment rather than the prefix.
    """
    assert path_role("packages/lup/tmp/briefing.md", NESTED) == "scratch"
    assert path_role("src/lup_template/tmp/notes.md", NESTED) == "scratch"
    assert path_role("tmp/briefing.md", NESTED) == "scratch"
    assert path_role("tmp", NESTED) == "scratch"


def test_a_part_matched_root_matches_a_segment_and_not_a_substring() -> None:
    """`tmpfile` holds the characters; it is not the directory."""
    assert path_role("packages/tmpfile.py", NESTED) == "production"
    assert path_role("packages/mytmp/x.py", NESTED) == "production"
    assert path_role("packages/tmp_old/x.py", NESTED) == "production"


def test_part_matching_widens_no_root_that_did_not_ask_for_it() -> None:
    """The axis is per declaration, so `tests` keeps the reach it declared."""
    assert path_role("src/app/tests/helper.py", NESTED) == "production"


def test_a_table_generated_before_the_axis_existed_reads_as_anchored() -> None:
    """A row is primitive data, and an older branch renders one without `kind`.

    The gate that decides every edit is also the gate whose recovery is
    regenerating the table, so a missing field reads as the behaviour that
    predates it rather than failing the decision.
    """
    older = cast(PathRoleRow, {"root": "tmp", "role": "scratch"})  # lup: ignore[cast]
    assert path_role("tmp/briefing.md", [older]) == "scratch"
    assert path_role("packages/lup/tmp/briefing.md", [older]) == "production"


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


def creating(path: str, content: str) -> str:
    """The verdict on creating a production file with this exact content."""
    return decide_edit(
        path,
        None,
        content,
        path_exists=False,
        path_rules=[],
        antipattern_rows=[],
        path_roles=ROLES,
        python_source=True,
    ).effect


def test_a_package_marker_is_created_without_a_question() -> None:
    """The full write asks so a reviewer can read the file; there is no file.

    A package marker declares a package by existing. Its docstring says which
    one, and the conventions here allow it nothing else, so the question it
    would raise has no answer that depends on the content.
    """
    assert (
        creating("src/app/thing/__init__.py", '"""The thing package."""\n') == "allow"
    )
    assert creating("src/app/thing/__init__.py", "") == "allow"
    assert creating("packages/lup/src/lup/deep/__init__.py", '"""Deep."""') == "allow"


def test_a_marker_carrying_content_is_the_module_it_became() -> None:
    """The allowance is the empty content, not the name.

    An `__init__.py` is also where a package root declares its public API, and
    that is a file somebody has to read — so it buys its creation the way
    every other new module does.
    """
    barrel = '"""Public API."""\n\nfrom lup.thing import Thing\n'
    assert creating("packages/lup/src/lup/__init__.py", barrel) == "ask"
    assert creating("src/app/thing/__init__.py", "VERSION = 1\n") == "ask"


def test_an_ordinary_module_buys_its_creation_however_empty_it_is() -> None:
    """Nothing here widens past the names declared as markers."""
    assert creating("src/app/thing/helper.py", '"""Helper."""\n') == "ask"
    assert creating("src/app/thing/helper.py", "") == "ask"


def test_a_marker_that_does_not_parse_is_not_treated_as_empty() -> None:
    """What it says is exactly what could not be established."""
    assert creating("src/app/thing/__init__.py", '"""Unterminated\n') == "ask"


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
