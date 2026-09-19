"""One file, named two ways, answering once.

Every declared role is anchored at the repository top, and every reading in the
kernel is lexical, so a role reaches a path only through a repository-relative
spelling. An absolute spelling of the same file matched no declaration and fell
through to "outside the checkout" -- which is the spelling a session that cannot
move between worktrees is told to use.

The root is a fact about the machine, so it arrives from the host per call and
is never declared. Empty is the honest answer where a caller has none, and these
pin that it leaves every reading exactly as it was rather than guessing a root.
"""

from lup.policy.kernel.roles import path_role, repository_relative
from lup.policy.kernel.rows import PathRoleRow
from lup.policy.kernel.words import write_scope

ROLES = [PathRoleRow(root="tmp", role="scratch")]
CHECKOUT = "/home/user/project.git/tree/dev"


def test_a_path_inside_the_checkout_is_read_back_to_its_declared_spelling() -> None:
    """The rewrite itself: absolute in, repository-relative out."""
    assert repository_relative(f"{CHECKOUT}/tmp/run.log", CHECKOUT) == "tmp/run.log"
    assert repository_relative(f"{CHECKOUT}/src/module.py", CHECKOUT) == "src/module.py"


def test_a_path_outside_the_checkout_is_left_alone() -> None:
    """Another checkout is genuinely elsewhere, and stays spelled that way."""
    other = "/home/user/project.git/tree/feature/tmp/run.log"
    assert repository_relative(other, CHECKOUT) == other
    assert repository_relative("/etc/hosts", CHECKOUT) == "/etc/hosts"


def test_a_relative_path_is_already_in_the_vocabulary() -> None:
    """Nothing to do, and nothing done."""
    assert repository_relative("tmp/run.log", CHECKOUT) == "tmp/run.log"


def test_without_a_root_nothing_is_rewritten() -> None:
    """The conservative answer, rather than a rewrite against a guessed root."""
    assert (
        repository_relative(f"{CHECKOUT}/tmp/run.log", "") == f"{CHECKOUT}/tmp/run.log"
    )


def test_a_word_carrying_an_expansion_is_not_a_path_yet() -> None:
    """What it names at run time is not what stands here, as elsewhere."""
    assert repository_relative("$HOME/tmp/run.log", CHECKOUT) == "$HOME/tmp/run.log"


def test_climbing_out_and_back_in_cannot_claim_a_role() -> None:
    """``..`` is normalized before the prefix is taken, not after."""
    escaped = f"{CHECKOUT}/../feature/tmp/run.log"
    assert repository_relative(escaped, CHECKOUT) == escaped


def test_one_file_named_two_ways_earns_one_role() -> None:
    """The defect, at the reading it broke."""
    assert path_role("tmp/run.log", ROLES) == "scratch"
    assert path_role(
        repository_relative(f"{CHECKOUT}/tmp/run.log", CHECKOUT), ROLES
    ) == ("scratch")


def test_one_file_named_two_ways_earns_one_scope() -> None:
    """And at the verdict that rests on it."""
    assert write_scope("tmp/run.log", ROLES, CHECKOUT) == "scratch"
    assert write_scope(f"{CHECKOUT}/tmp/run.log", ROLES, CHECKOUT) == "scratch"
    assert write_scope(f"{CHECKOUT}/src/module.py", ROLES, CHECKOUT) == "production"


def test_the_repository_directory_is_still_the_repository() -> None:
    """Normalization reaches paths inside the checkout and nothing above it."""
    assert write_scope("/home/user/project.git/config", ROLES, CHECKOUT) == "protected"


def test_another_checkout_is_still_outside() -> None:
    """A sibling worktree is somewhere this checkout cannot answer for."""
    other = "/home/user/project.git/tree/feature/src/module.py"
    assert write_scope(other, ROLES, CHECKOUT) == "outside"


def test_without_a_root_the_old_reading_stands() -> None:
    """A composition that forgets the root is conservative, never permissive."""
    assert write_scope(f"{CHECKOUT}/tmp/run.log", ROLES) == "outside"
