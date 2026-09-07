"""Behavior tests for a directory redirect that stays inside this repository.

The `-C` guard protects a premise rather than a directory: the verb behind it
is answered by a row reasoning about *this* worktree, so `git -C /elsewhere
commit` reads as reversible on the strength of a reflog somewhere else. Inside
one repository that premise holds -- linked worktrees share an object store and
a reflog -- and these pin that the guard steps aside there and nowhere else.
"""

from lup.policy.kernel.commands import redirect_stays_in_this_repository
from lup.policy.kernel.shell import decide_shell
from lup.policy.shell_rules import erase_shell_rules
from lup_template.harness.catalog import declared_hook_set

SHELL_RULES = erase_shell_rules(declared_hook_set().resolved_shell_rules())
HERE = "/repo/tree/mine"
SIBLING = "/repo/tree/other"


def effect_of(command: str, worktrees: list[str]) -> str:
    """One command's verdict under a host that measured these worktrees."""
    return decide_shell(command, SHELL_RULES, repository_worktrees=worktrees).effect


def test_a_sibling_checkout_is_recognized_wherever_it_sits() -> None:
    """Identity, not containment: worktrees live wherever somebody put them.

    The first version of this guard compared path prefixes, which is all a pure
    evaluator can do alone, and so read every absolute spelling as outside.
    """
    assert redirect_stays_in_this_repository(SIBLING, [HERE, SIBLING])


def test_a_path_outside_the_repository_is_not() -> None:
    assert not redirect_stays_in_this_repository("/tmp/elsewhere", [HERE, SIBLING])


def test_a_relative_redirect_keeps_its_question() -> None:
    """Unsettleable here, and an approval is the cheaper way to be wrong."""
    assert not redirect_stays_in_this_repository("../other", [HERE, SIBLING])


def test_an_expanding_value_keeps_its_question() -> None:
    """Nobody can weigh a redirect whose destination is decided at run time."""
    assert not redirect_stays_in_this_repository("$TREE", [HERE, SIBLING])


def test_nothing_measured_leaves_every_redirect_asking() -> None:
    """A host that could not answer relaxes nothing, which is the safe way."""
    assert not redirect_stays_in_this_repository(SIBLING, [])


def test_a_commit_into_a_sibling_of_this_repository_is_allowed() -> None:
    """The reflog the row reasons about is the one that is actually there."""
    assert effect_of(f"git -C {SIBLING} commit -m x", [HERE, SIBLING]) == "allow"


def test_the_same_commit_still_asks_where_nothing_was_measured() -> None:
    assert effect_of(f"git -C {SIBLING} commit -m x", []) == "ask"


def test_a_commit_outside_the_repository_still_asks() -> None:
    assert effect_of("git -C /tmp/elsewhere commit -m x", [HERE, SIBLING]) == "ask"


def test_the_verb_behind_the_redirect_is_still_judged() -> None:
    """Stepping aside hands the question on rather than answering it.

    A merge asks for its own reason -- it puts work on a branch other people
    build on -- and that reason is unchanged by which checkout it runs in. A
    guard that allowed the redirect *and* the verb would have relaxed two
    things while claiming to weigh one.
    """
    assert effect_of(f"git -C {SIBLING} merge topic", [HERE, SIBLING]) == "ask"


def test_a_redirected_read_is_allowed_with_or_without_a_measurement() -> None:
    """Unchanged by this: a verb that only reads has no reflog in it to be
    somebody else's, so the redirect was already stepping aside for one."""
    assert effect_of(f"git -C {SIBLING} log", []) == "allow"
    assert effect_of(f"git -C {SIBLING} log", [HERE, SIBLING]) == "allow"
