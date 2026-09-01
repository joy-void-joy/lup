"""The product contract's own scenarios, run against the composed policy.

Every row of the overhaul's acceptance matrix that this layer can answer,
spelled once here so the contract is a suite rather than a table somebody
compares by eye. Rows about provider delivery, host transport, and crash
recovery live with the components that own them; what is here is what the
semantic policy decides.

The profile matters and is stated per case rather than assumed. Most of the
matrix describes the default *contained* profile, where odd local work is
settled inside; the uncontained rows are the ones that read differently, and
running both is how a change to one is stopped from silently moving the other.
"""

from pathlib import Path

import pytest

from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.edit import decide_edit
from lup.policy.kernel.rows import PathRoleRow, ShellRuleRow
from lup.policy.kernel.semantics import UnjudgedAmbient
from lup.policy.kernel.shell import decide_shell
from lup.policy.shell_rules import erase_shell_rules
from lup.policy.vocabulary import default_vocabulary, gh_rule, git_rule

PRODUCTION = [PathRoleRow(root="src", role="production")]


def rows() -> list[ShellRuleRow]:
    """The library's offered table, which is what the contract describes."""
    return erase_shell_rules(default_vocabulary())


def contained(command: str, recovered: bool = False) -> KernelDecision:
    """One command under the default contained profile."""
    return decide_shell(
        command,
        rows(),
        sandboxed=True,
        contained=True,
        escapable=False,
        recovered=recovered,
    )


def exposed(command: str, unjudged_ambient: UnjudgedAmbient = "ask") -> KernelDecision:
    """The same command with no containment beneath it."""
    return decide_shell(command, rows(), unjudged_ambient=unjudged_ambient)


@pytest.mark.parametrize(
    ("command", "effect"),
    [
        # Suspicious local inspection is contained, not reviewed. The
        # operation observes the contained environment, and a host path that
        # is not there fails inside with a diagnostic naming the escalation
        # that would reach it.
        ("cat /etc/passwd", "allow"),
        ("ls /proc", "allow"),
        ("find / -name '*.key'", "allow"),
        # Ordinary Git collaboration, unguarded at a classified destination.
        ("git push origin HEAD", "allow"),
        ("git push origin refs/heads/feature", "allow"),
        ("git tag v1.2.3", "allow"),
        # What removes or replaces history keeps its question in both
        # spellings — as a flag, and as refspec grammar.
        ("git push --force origin main", "ask"),
        ("git push +main:main", "ask"),
        ("git push origin :refs/heads/main", "ask"),
        ("git push --delete origin feat", "ask"),
        ("git push --mirror origin", "ask"),
        # Compensable GitHub collaboration.
        ("gh pr create --fill", "allow"),
        ("gh pr edit 12 --title x", "allow"),
        ("gh pr comment 12 --body x", "allow"),
        ("gh pr close 12", "allow"),
        ("gh pr reopen 12", "allow"),
        ("gh pr review 12 --comment --body x", "allow"),
        ("gh issue create --title x", "allow"),
        ("gh issue comment 3 --body x", "allow"),
        ("gh issue close 3", "allow"),
        ("gh issue reopen 3", "allow"),
        # Execution, attestation, publication, repository security, and the
        # deletion nested inside an otherwise allowed operation.
        ("gh pr merge 12", "ask"),
        ("gh pr review 12 --approve", "ask"),
        ("gh pr review 12 --request-changes --body x", "ask"),
        ("gh pr close 12 --delete-branch", "ask"),
        ("gh api -X POST repos/o/r/issues", "ask"),
        ("gh release create v1", "ask"),
        ("gh secret set TOKEN", "ask"),
        ("gh repo edit --visibility public", "ask"),
        ("gh workflow run deploy.yml", "ask"),
        # Deliberately unreadable execution stays refused: a person shown the
        # readable half would be approving the other half unseen.
        ('eval "$COMMAND"', "deny"),
        ("source setup.sh", "deny"),
    ],
)
def test_the_matrix_rows_a_contained_session_answers(command: str, effect: str) -> None:
    """Each row of the contract that the shell policy settles on its own."""
    assert contained(command).effect == effect, command


def test_a_legible_unlisted_operation_is_settled_inside(tmp_path: Path) -> None:
    """The practical default for odd local work.

    Contained, everything it can affect is confined, so it runs there rather
    than costing a question — and it is Lup's permission rather than a
    handoff, so the placement holds however permissive the session's mode is.
    """
    settled = contained("frobnicate --weird")

    assert (settled.effect, settled.sandbox) == ("allow", "inside")


def test_an_unlisted_ambient_operation_follows_the_declared_policy() -> None:
    """Uncontained, the profile answers: visible by default, or handed over."""
    assert exposed("frobnicate --weird").effect == "ask"
    assert exposed("frobnicate --weird", unjudged_ambient="defer").effect == "defer"


def test_a_safe_outer_command_cannot_erase_a_nested_question() -> None:
    """Joined, one line is one act as far as the person deciding is concerned."""
    assert contained("ls && git push --delete origin feat").effect == "ask"


def test_a_marker_with_no_reason_authorizes_nothing() -> None:
    """The whole content of the request is what it says to whoever answers."""
    refused = contained("# lup: escalate[decision]:\nrm -rf /")

    assert (refused.effect, refused.hard) == ("deny", True)


def test_decision_escalation_moves_an_overrideable_refusal() -> None:
    """A rule's judgement is what somebody with more context may overrule.

    Both of these are refusals a person can be argued out of: work nobody
    classified, and a shape this repository refuses on reviewability grounds.
    Inline execution is deliberately in the second group rather than made an
    invariant — there are shapes for which it is the right answer, and a
    refusal nobody can argue with sends the agent to work around it instead.
    """
    unlisted = exposed("# lup: escalate[decision]: I need it\nfrobnicate --weird")
    inline = exposed('# lup: escalate[decision]: I need it\neval "$COMMAND"')

    assert unlisted.effect == "ask"
    assert inline.effect == "ask"
    assert "escalated (I need it)" in inline.reason


def test_a_policy_invariant_produces_the_same_refusal_when_escalated() -> None:
    """What no approval moves, because approval does not change a shape.

    Every verdict the lattice can reach is wrong for a generated tree: an
    allow writes something the next generation overwrites, and a question puts
    a decision to somebody whose only correct answer is "edit the source".
    """
    refused = decide_edit(
        ".claude/plugins/lup/hooks/runtime/policy_data.py",
        "a = 1\n",
        "a = 2\n",
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
    )

    assert (refused.effect, refused.hard) == ("deny", True)


def test_sandbox_escalation_asks_before_the_operation_crosses() -> None:
    """The crossing is reviewed however ordinary the operation reads inside."""
    asked = decide_shell(
        "# lup: escalate[sandbox]: the host holds the key\ncat /etc/passwd",
        rows(),
        sandboxed=True,
        contained=True,
        escapable=True,
    )

    assert (asked.effect, asked.sandbox) == ("ask", "outside")


def test_the_combined_marker_is_the_only_route_past_a_refusal_to_the_host() -> None:
    """Two requests composed by their order, neither knowing about the other."""
    both = decide_shell(
        "# lup: escalate[decision,sandbox]: needed\nfrobnicate --weird",
        rows(),
        sandboxed=True,
        contained=True,
        escapable=True,
    )

    assert (both.effect, both.sandbox) == ("ask", "outside")


def test_a_production_full_write_asks_and_a_supervisor_may_answer() -> None:
    """A quality checkpoint: what is reviewed is how the code reads."""
    decided = decide_edit(
        "src/app/service.py",
        None,
        "value = 1\n",
        path_exists=False,
        path_rules=[],
        antipattern_rows=[],
        path_roles=PRODUCTION,
        operation="create",
    )

    assert (decided.effect, decided.reviewer) == ("ask", "supervisor_allowed")


def test_an_edit_above_the_size_gate_is_indistinguishable_from_no_lup() -> None:
    """The one verdict under which the session behaves as if Lup were absent."""
    decided = decide_edit(
        "src/app/service.py",
        "a = 1\n",
        "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n",
        path_exists=True,
        path_rules=[],
        antipattern_rows=[],
        path_roles=PRODUCTION,
    )

    assert (decided.effect, decided.abstention) == ("defer", "provider_native")


def test_a_recoverable_loss_settles_to_a_permission_and_an_unrecoverable_one_asks() -> (
    None
):
    """The axis that makes the effect a function of the session, and its limit.

    `git reset --hard` destroys working-tree content a capture holds, so a
    session carrying that capture has no permanent loss to ask about.
    `git clean -fdx` destroys exactly what the capture leaves out, which is
    why it is the one neighbour that keeps asking.
    """
    held = decide_shell(
        "git reset --hard", rows(), sandboxed=True, contained=True, recovered=True
    )
    unheld = decide_shell(
        "git clean -fdx", rows(), sandboxed=True, contained=True, recovered=True
    )

    assert held.effect == "allow"
    assert unheld.effect == "ask"


def test_recovery_never_discharges_a_question_it_has_nothing_to_do_with() -> None:
    """A capture answers local loss and nothing travelling beside it."""
    remote = decide_shell(
        "git push --delete origin feat",
        erase_shell_rules([git_rule(), gh_rule()]),
        sandboxed=True,
        contained=True,
        recovered=True,
    )

    assert remote.effect == "ask"
