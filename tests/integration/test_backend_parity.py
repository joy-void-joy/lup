"""Live parity test: the same task on both SDK backends.

Costs real LLM calls on two providers, so it is gated behind
``LUP_PARITY_TEST=1`` in addition to the integration marker. Both
backends must produce the same session artifacts through the same
finalization mechanism (submit_output → output.json).
"""

import os

import pytest

from lup_template.agent.config import settings
from lup_template.agent.core import run_agent

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("LUP_PARITY_TEST"),
        reason="set LUP_PARITY_TEST=1 to run live two-backend parity (costs money)",
    ),
]

TASK = (
    "Smoke task: reflect via review with skip_reviewer=true, then submit "
    "a one-line output."
)


async def test_both_backends_produce_equivalent_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = {}
    for sdk, model in (("claude", "claude-haiku-4-5-20251001"), ("codex", "gpt-5.5")):
        monkeypatch.setattr(settings, "agent_sdk", sdk)
        monkeypatch.setattr(settings, "model", model)
        results[sdk] = await run_agent(TASK, session_id=f"parity-{sdk}")

    for sdk, result in results.items():
        assert result.output.summary, f"{sdk}: empty output summary"
        assert result.output.summary != "No output produced", f"{sdk}: no submission"
        assert result.tool_metrics is not None, f"{sdk}: missing tool metrics"
        assert result.token_usage is not None, f"{sdk}: missing token usage"
        assert result.agent_version == results["claude"].agent_version
