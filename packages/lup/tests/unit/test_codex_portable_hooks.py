"""Portable hooks preserve their declared coverage and approval posture."""

from pathlib import Path

import pytest

from lup.policy.hooks import LupHookInput, LupHookMatcher, LupHookOutput, LupHooksConfig
from lup.providers.codex.hooks import APPROVAL_METHODS
from lup.providers.codex.selection import codex_config
from lup.providers.selection import SessionRequest
from lup.sessions.errors import UnsupportedCapability


async def observe(_event: LupHookInput) -> LupHookOutput:
    return LupHookOutput()


def test_lifecycle_observers_do_not_request_native_approvals(tmp_path: Path) -> None:
    observer = LupHookMatcher(hook=observe)
    hooks = LupHooksConfig(post_tool_use=[observer], stop=[observer])
    config = codex_config(SessionRequest(cwd=tmp_path, hooks=hooks))
    assert config.hooks is hooks
    assert config.approval_policy == "never"


@pytest.mark.parametrize("matcher", [None, "", "*"])
def test_inbox_delivery_does_not_authorize_tools(
    tmp_path: Path, matcher: str | None
) -> None:
    hooks = LupHooksConfig(
        pre_tool_use=[LupHookMatcher(matcher=matcher, hook=observe, tag="inbox")]
    )
    config = codex_config(SessionRequest(cwd=tmp_path, hooks=hooks))
    assert config.hooks is hooks
    assert config.approval_policy == "never"


@pytest.mark.parametrize("matcher", [*APPROVAL_METHODS, "|".join(APPROVAL_METHODS)])
def test_exact_native_scope_enables_approval_callbacks(
    tmp_path: Path, matcher: str
) -> None:
    hooks = LupHooksConfig(pre_tool_use=[LupHookMatcher(matcher=matcher, hook=observe)])
    config = codex_config(SessionRequest(cwd=tmp_path, hooks=hooks))
    assert config.hooks is hooks
    assert config.approval_policy == "on-request"


@pytest.mark.parametrize(
    "matcher", [None, "*", "Bash", "item/.*", f"prefix{APPROVAL_METHODS[0]}"]
)
def test_universal_or_ambiguous_pre_tool_coverage_is_rejected(
    tmp_path: Path, matcher: str | None
) -> None:
    hooks = LupHooksConfig(pre_tool_use=[LupHookMatcher(matcher=matcher, hook=observe)])
    with pytest.raises(UnsupportedCapability, match="explicit native approval scope"):
        codex_config(SessionRequest(cwd=tmp_path, hooks=hooks))
