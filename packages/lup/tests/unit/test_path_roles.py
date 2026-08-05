"""Path-role resolution: what a repository path is for, decided lexically."""

from lup.policy.kernel.roles import path_role
from lup.policy.kernel.rows import PathRoleRow

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
