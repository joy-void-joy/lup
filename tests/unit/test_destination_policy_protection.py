"""A session cannot accept replacement policy or silently rewrite launch authority."""

from pathlib import Path

import pytest

from lup.harness.enforcement import declared_path_rules
from lup.policy.models import EditBatch, EditChange, ShellCommand
from lup.policy.rules import EditPolicy, ShellPolicy
from lup_template.harness.catalog import declared_hook_set


@pytest.mark.parametrize(
    "prefix", ["", "env -u LUP_BOUNDARY_NONCE ", "LUP_BOUNDARY_NONCE= ", "command "]
)
def test_operator_refresh_cannot_be_called_by_a_requesting_session(prefix: str) -> None:
    hooks = declared_hook_set()
    policy = ShellPolicy(
        hooks.resolved_shell_rules(),
        runner_targets=list(hooks.runner_targets),
        sandbox_active=True,
    )
    decision = policy.decide(
        ShellCommand(
            command=prefix
            + "uv run lup-devtools harness policy-refresh --nonce example --repository /example"
        )
    )

    assert decision.effect == "deny"
    assert decision.hard
    assert "operator" in decision.recovery.lower()


@pytest.mark.parametrize(
    "path",
    [
        ".lup/preflight/session.json",
        ".lup/policy-snapshots/digest/runtime/policy_data.py",
    ],
)
def test_launch_authority_writes_remain_protected(path: str) -> None:
    policy = EditPolicy(declared_path_rules(declared_hook_set()))

    decision = policy.decide(
        EditBatch(
            changes=[
                EditChange(path=Path(path), before="value = 1\n", after="value = 2\n")
            ]
        )
    )

    assert decision.effect == "ask"
    assert "protected" in decision.rule


@pytest.mark.parametrize(
    "command",
    ["sudo pacman -S --noconfirm figlet", "sudo -n true", "cd /tmp && sudo ls"],
)
def test_a_normal_session_is_asked_before_it_uses_sudo(command: str) -> None:
    """The container may grant sudo; in a gated session the policy still asks first."""
    hooks = declared_hook_set()
    policy = ShellPolicy(
        hooks.resolved_shell_rules(),
        runner_targets=list(hooks.runner_targets),
        sandbox_active=True,
    )

    decision = policy.decide(ShellCommand(command=command))

    assert decision.effect == "ask"
    assert "privilege escalation" in decision.reason
