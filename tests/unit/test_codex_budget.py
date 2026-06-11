"""Budget enforcement on the Codex runtime.

The Codex SDK reports token counts, never cost, so the adapter enforces
``max_budget_usd`` through its own accounting: per-turn usage accumulates
in the conversation, a caller-supplied estimator turns it into USD, and
the turn after the budget is crossed is refused. These tests pin that
contract without any LLM call.
"""

from typing import TYPE_CHECKING, cast

import pytest
from openai_codex.generated.v2_all import ThreadTokenUsage, TokenUsageBreakdown

from lup.adapters.codex import CodexAdapter, CodexConversation, per_mtok_usage_cost
from lup.adapters.common import BudgetExceededError
from lup.types import Usage

if TYPE_CHECKING:
    from openai_codex import AsyncThread


def usage_for_turn(
    input_tokens: int, output_tokens: int, cached: int = 0
) -> ThreadTokenUsage:
    breakdown = TokenUsageBreakdown(
        cached_input_tokens=cached,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=0,
        total_tokens=input_tokens + output_tokens,
    )
    return ThreadTokenUsage(last=breakdown, total=breakdown, model_context_window=None)


class FakeTurnResult:
    """Minimal TurnResult stand-in: no items, scripted usage."""

    def __init__(self, usage: ThreadTokenUsage) -> None:
        self.items: list[object] = []
        self.final_response: str | None = None
        self.usage = usage


class FakeThread:
    """AsyncThread stand-in returning scripted per-turn usage."""

    def __init__(self, usages: list[ThreadTokenUsage]) -> None:
        self.id = "thread-fake"
        self.usages = usages
        self.prompts: list[str] = []

    async def run(
        self,
        prompt: str,
        *,
        effort: object = None,
        output_schema: object = None,
    ) -> FakeTurnResult:
        self.prompts.append(prompt)
        return FakeTurnResult(self.usages[len(self.prompts) - 1])


def conversation(
    usages: list[ThreadTokenUsage],
    *,
    max_budget_usd: float | None = None,
    usd_per_input_mtok: float | None = 1.0,
) -> CodexConversation:
    usage_cost = (
        per_mtok_usage_cost(input_usd=usd_per_input_mtok, output_usd=0.0)
        if usd_per_input_mtok is not None
        else None
    )
    return CodexConversation(
        cast("AsyncThread", FakeThread(usages)),
        max_budget_usd=max_budget_usd,
        usage_cost=usage_cost,
    )


class TestPerMtokUsageCost:
    def test_input_and_output_rates(self) -> None:
        cost = per_mtok_usage_cost(input_usd=2.0, output_usd=10.0)
        usage = Usage(input_tokens=1_000_000, output_tokens=500_000)
        assert cost(usage) == pytest.approx(2.0 + 5.0)

    def test_cached_subset_billed_at_cached_rate(self) -> None:
        cost = per_mtok_usage_cost(input_usd=2.0, output_usd=0.0, cached_input_usd=0.5)
        usage = Usage(input_tokens=1_000_000, cache_read_input_tokens=400_000)
        assert cost(usage) == pytest.approx(600_000 * 2.0 / 1e6 + 400_000 * 0.5 / 1e6)

    def test_cached_rate_defaults_to_input_rate(self) -> None:
        cost = per_mtok_usage_cost(input_usd=2.0, output_usd=0.0)
        usage = Usage(input_tokens=1_000_000, cache_read_input_tokens=400_000)
        assert cost(usage) == pytest.approx(2.0)


class TestConversationAccounting:
    async def test_cost_accumulates_across_turns_and_stamps_result(self) -> None:
        conv = conversation(
            [usage_for_turn(1_000_000, 0), usage_for_turn(1_000_000, 0)]
        )

        first = await conv.send("turn one")
        assert first.result is not None
        assert first.result.total_cost_usd == pytest.approx(1.0)

        second = await conv.send("turn two")
        assert second.result is not None
        assert second.result.total_cost_usd == pytest.approx(2.0)
        assert conv.turns_usage.input_tokens == 2_000_000

    async def test_without_estimator_cost_stays_unknown(self) -> None:
        conv = conversation([usage_for_turn(1_000_000, 0)], usd_per_input_mtok=None)

        response = await conv.send("turn one")
        assert response.result is not None
        assert response.result.total_cost_usd is None
        assert conv.cost_usd is None

    async def test_budget_refuses_turn_after_crossing(self) -> None:
        conv = conversation(
            [usage_for_turn(1_000_000, 0)] * 3,
            max_budget_usd=1.5,
        )

        await conv.send("cost 1.0 — under budget")
        await conv.send("cost 2.0 — crosses budget mid-flight")

        with pytest.raises(BudgetExceededError, match="budget"):
            await conv.send("refused")
        assert len(cast(FakeThread, cast(object, conv.thread)).prompts) == 2


class TestAdapterValidation:
    def test_budget_without_estimator_raises(self) -> None:
        with pytest.raises(ValueError, match="usage_cost"):
            CodexAdapter(
                model="gpt-5.5",
                system_prompt="",
                max_budget_usd=1.0,
            )


class TestTemplateBudgetOptions:
    def test_budget_without_rates_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from lup_template.agent.config import settings
        from lup_template.agent.core import codex_budget_options

        monkeypatch.setattr(settings, "max_budget_usd", 2.0)
        monkeypatch.setattr(settings, "codex_usd_per_mtok_input", None)
        monkeypatch.setattr(settings, "codex_usd_per_mtok_output", None)

        with pytest.raises(ValueError, match="CODEX_USD_PER_MTOK"):
            codex_budget_options()

    def test_rates_enable_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from lup_template.agent.config import settings
        from lup_template.agent.core import codex_budget_options

        monkeypatch.setattr(settings, "max_budget_usd", 2.0)
        monkeypatch.setattr(settings, "codex_usd_per_mtok_input", 1.25)
        monkeypatch.setattr(settings, "codex_usd_per_mtok_output", 10.0)
        monkeypatch.setattr(settings, "codex_usd_per_mtok_cached_input", None)

        max_budget_usd, usage_cost = codex_budget_options()
        assert max_budget_usd == 2.0
        assert usage_cost is not None
        assert usage_cost(Usage(input_tokens=1_000_000)) == pytest.approx(1.25)
