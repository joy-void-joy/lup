"""A redirection's question is one a proven capture is allowed to answer.

The rule asked and said nothing about what it was asking *about*: the verdict
carried no purpose and the default `unrecoverable` requirement, so
`recovery_dischargeable` refused it twice over and the snapshot every session
takes could not retire the question. Nor could any boundary, since
`ContainedEffects` rewrites a deferral and this is an ask -- which left a
redirection asking a person behind a container, behind a sandbox, and with the
tree captured, three answers already in hand.

A file redirection is the textbook unrecovered local mutation: it overwrites
one named path and a capture of that path puts it back. Saying so is the whole
change; the rows that refuse a generated tree, a protected path or a
credential all sit *above* this one and keep their questions untouched.
"""

from lup.policy.kernel.decision import recovery_dischargeable
from lup.policy.kernel.rows import PathRuleRow, ShellRuleRow
from lup.policy.kernel.settlement import SettlementFacts, settle
from lup.policy.kernel.shell import decide_shell
from lup.policy.shell_rules import erase_shell_rules
from lup.policy.vocabulary import default_vocabulary

REDIRECTION = "cat > $B"
"""A write whose target no relaxation above the fallback can resolve."""


def rows() -> list[ShellRuleRow]:
    """The library's offered table, which is what the contract describes."""
    return erase_shell_rules(default_vocabulary())


def test_a_redirection_asks_about_a_loss_a_capture_can_put_back() -> None:
    """The question states its own subject, which is what makes it answerable."""
    decision = decide_shell(REDIRECTION, rows())

    assert decision.effect == "ask"
    assert recovery_dischargeable(decision)


def test_a_proven_capture_settles_what_an_absent_one_leaves_standing() -> None:
    """Both halves, because a capture that was never taken must still ask.

    `absent` and `complete` are the two a session actually reaches here, and
    the question is worth a person's attention in exactly one of them.
    """
    decision = decide_shell(REDIRECTION, rows())

    unheld = settle(SettlementFacts(decision, checkpoint="absent"))
    assert unheld.effect == "ask"

    held = settle(SettlementFacts(decision, checkpoint="complete"))
    assert held.effect == "allow"


def test_a_redirection_into_a_protected_path_keeps_its_question() -> None:
    """The rows above the fallback are untouched, which is why this is safe.

    A protected path is not a local loss a capture discharges, and it is
    judged before the fallback ever runs -- so the relaxation cannot reach it
    however complete the capture is.
    """
    owned = [
        PathRuleRow(
            kind="exact",
            value="docs/owned.md",
            reason="human-owned",
            allow_autonomous=False,
        )
    ]
    into_owned = decide_shell("cat > docs/owned.md", rows(), path_rules=owned)

    assert into_owned.effect == "ask"
    assert not recovery_dischargeable(into_owned)
