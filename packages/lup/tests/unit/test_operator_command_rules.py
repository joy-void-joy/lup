"""Declared access for deeply nested command paths survives policy compilation."""

import pytest

from lup.policy.kernel.commands import decide_command_rows
from lup.policy.kernel.effects import declare
from lup.policy.shell_rules import (
    ShellCommandRule,
    ShellOperationRule,
    ShellSubcommandRule,
    erase_shell_rules,
)


@pytest.mark.parametrize("action,expected", [("show", "allow"), ("answer", "deny")])
def test_nested_operator_access_uses_declarations(action: str, expected: str) -> None:
    rows = erase_shell_rules(
        [
            ShellCommandRule(
                name="example-admin",
                effects=[declare("changes_nothing")],
                subcommands=[
                    ShellSubcommandRule(
                        name="review",
                        operations=[
                            ShellOperationRule(name="pending"),
                            ShellOperationRule(
                                name="answer",
                                parents=["pending"],
                                operator_only=True,
                                reason="Operator credentials are required",
                                recovery="Use the operator console",
                            ),
                        ],
                    )
                ],
            ),
        ]
    )
    decision = decide_command_rows(["example-admin", "review", "pending", action], rows)
    assert decision.effect == expected
    if action == "answer":
        assert decision.hard
        assert decision.rule == "shell:example-admin.review.pending.answer"
        assert decision.recovery == "Use the operator console"
