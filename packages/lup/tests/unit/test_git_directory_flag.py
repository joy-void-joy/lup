"""What `git -C` costs, and what it should not.

The guard exists because the verb behind the flag is answered by a row
reasoning about *this* worktree: `git -C /elsewhere commit` reads as
reversible on the strength of a reflog that is somewhere else. That is a
statement about mutation, and it was enforced before the subcommand word had
been read at all -- so `git -C . log` was a question about a redirect to
nowhere in front of a verb that reads, and the guidance telling tests to bind
git with `git -C <tmp>` collided with a policy that asked every time.

Two conditions, and the second is easy to lose: the verb has to *observe*,
and the directory has to be one this checkout covers. A read of another tree
is the placement question `reads_path` asks at its `outside` scope, and the
row cannot ask it -- a row declares one scope for every path its verb might
touch, and this one says `project`.
"""

from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.rows import PathRoleRow, ShellRuleRow
from lup.policy.kernel.shell import decide_shell
from lup.policy.shell_rules import erase_shell_rules
from lup.policy.vocabulary import default_vocabulary

SCRATCH = [PathRoleRow(root="tmp", role="scratch")]


def rows() -> list[ShellRuleRow]:
    """The library's offered table, which is what the contract describes."""
    return erase_shell_rules(default_vocabulary())


def verdict(command: str) -> KernelDecision:
    return decide_shell(command, rows(), path_roles=SCRATCH)


def test_a_redirect_in_front_of_a_read_costs_nothing() -> None:
    """The reported friction, in the three spellings it arrived in."""
    for command in (
        "git -C . log",
        "git -C packages/lup log",
        "git -C packages/lup status",
        "git -C packages/lup diff",
    ):
        assert verdict(command).effect == "allow", command


def test_a_redirect_in_front_of_a_mutation_still_asks() -> None:
    """What the guard was written for, and what a first fix let through.

    Asking the verb's *verdict* rather than whether it observes allowed
    `git -C elsewhere commit`: a commit is allowed for being reversible, and
    the whole premise of the guard is that its reversibility belongs to the
    tree it runs in.
    """
    for command in (
        "git -C packages/lup commit -m x",
        "git -C packages/lup push",
        "git -C packages/lup reset --hard",
    ):
        settled = verdict(command)
        assert settled.effect == "ask", command
        assert "-C" in settled.reason, command


def test_a_read_of_a_tree_outside_the_checkout_keeps_its_question() -> None:
    """The scope the row cannot state, asked where the row would have allowed."""
    assert verdict("git -C /etc/somerepo log").effect == "ask"


def test_the_redirect_is_still_named_in_the_way_through() -> None:
    """`cd there && git commit` is two allowed segments, and the reason says so."""
    assert "cd into that tree" in verdict("git -C ../other commit -m x").reason
