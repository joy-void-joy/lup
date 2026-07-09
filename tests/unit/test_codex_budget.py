"""Budget enforcement on the Codex runtime.

The Codex SDK reports token counts, never cost, so the adapter enforces
``max_budget_usd`` through its own accounting: per-turn usage accumulates
in the conversation, a caller-supplied estimator turns it into USD, and
the turn after the budget is crossed is refused. These tests pin that
contract without any LLM call.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest
from openai_codex.generated.v2_all import ThreadTokenUsage, TokenUsageBreakdown

from lup.adapters.clients.codex.sessions import CodexSession, CodexSessions
from lup.adapters.clients.codex.native import CodexNativeConfig
from lup.adapters.clients.codex.translate import subprocess_sandbox_cleanup
from lup.adapters.clients.codex.usage import per_mtok_usage_cost
from lup.adapters.errors import BudgetExceededError, TurnTimeoutError
from lup.adapters.options import LupAgentOptions
from lup.types import Usage

if TYPE_CHECKING:
    from openai_codex import ApprovalMode, AsyncCodex, AsyncThread
    from openai_codex import Sandbox as CodexSandbox


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


class SlowFakeThread:
    """AsyncThread stand-in whose turn outlives any test timeout."""

    def __init__(self) -> None:
        self.id = "thread-slow"

    async def run(
        self,
        prompt: str,
        *,
        effort: object = None,
        output_schema: object = None,
    ) -> FakeTurnResult:
        await asyncio.sleep(10)
        return FakeTurnResult(usage_for_turn(0, 0))


async def test_turn_timeout_cancels_slow_turn() -> None:
    conv = CodexSession(
        cast("AsyncThread", SlowFakeThread()),
        turn_timeout_seconds=0.05,
    )
    with pytest.raises(TurnTimeoutError, match="wall-clock"):
        await conv.send("hi")


def session(
    usages: list[ThreadTokenUsage],
    *,
    max_budget_usd: float | None = None,
    usd_per_input_mtok: float | None = 1.0,
) -> CodexSession:
    usage_cost = (
        per_mtok_usage_cost(input_usd=usd_per_input_mtok, output_usd=0.0)
        if usd_per_input_mtok is not None
        else None
    )
    return CodexSession(
        cast("AsyncThread", FakeThread(usages)),
        max_budget_usd=max_budget_usd,
        usage_cost=usage_cost,
    )


class FakeCodex:
    """AsyncCodex stand-in recording which thread door was used."""

    def __init__(self, thread: FakeThread) -> None:
        self.thread = thread
        self.started: list[str] = []
        self.resumed: list[str] = []

    async def thread_start(
        self,
        *,
        model: str,
        model_provider: str | None,
        developer_instructions: str,
        sandbox: "CodexSandbox | None",
        approval_mode: "ApprovalMode",
    ) -> FakeThread:
        _ = (model_provider, developer_instructions, sandbox, approval_mode)
        self.started.append(model)
        return self.thread

    async def thread_resume(
        self,
        thread_id: str,
        *,
        model: str,
        model_provider: str | None,
        developer_instructions: str,
        sandbox: "CodexSandbox | None",
        approval_mode: "ApprovalMode",
    ) -> FakeThread:
        _ = (model, model_provider, developer_instructions, sandbox, approval_mode)
        self.resumed.append(thread_id)
        return self.thread


async def test_open_thread_dispatches_start_vs_resume() -> None:
    """session(resume=) restores the saved thread instead of starting one."""
    fake = FakeCodex(FakeThread([]))
    codex = cast("AsyncCodex", cast(object, fake))  # lup: ignore — SDK-boundary fake
    sessions = CodexSessions(CodexNativeConfig(model="gpt-5.5"))

    started = await sessions.open_thread(codex, resume=None)
    assert started is fake.thread
    assert fake.started == ["gpt-5.5"]

    resumed = await sessions.open_thread(codex, resume="thread-9")
    assert resumed is fake.thread
    assert fake.resumed == ["thread-9"]


def test_session_id_is_the_thread_id() -> None:
    assert session([]).id == "thread-fake"


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
        conv = session([usage_for_turn(1_000_000, 0), usage_for_turn(1_000_000, 0)])

        first = await conv.send("turn one")
        assert first.result is not None
        assert first.result.total_cost_usd == pytest.approx(1.0)

        second = await conv.send("turn two")
        assert second.result is not None
        assert second.result.total_cost_usd == pytest.approx(2.0)
        assert conv.turns_usage.input_tokens == 2_000_000

    async def test_without_estimator_cost_stays_unknown(self) -> None:
        conv = session([usage_for_turn(1_000_000, 0)], usd_per_input_mtok=None)

        response = await conv.send("turn one")
        assert response.result is not None
        assert response.result.total_cost_usd is None
        assert conv.cost_usd is None

    async def test_budget_refuses_turn_after_crossing(self) -> None:
        conv = session(
            [usage_for_turn(1_000_000, 0)] * 3,
            max_budget_usd=1.5,
        )

        await conv.send("cost 1.0 — under budget")
        await conv.send("cost 2.0 — crosses budget mid-flight")

        with pytest.raises(BudgetExceededError, match="budget"):
            await conv.send("refused")
        assert len(cast(FakeThread, cast(object, conv.thread)).prompts) == 2


class FakeAsyncCodex:
    """AsyncCodex stand-in: an async context yielding a FakeCodex."""

    def __init__(self, *, config: object) -> None:
        _ = config
        self.client = FakeCodex(FakeThread([]))

    async def __aenter__(self) -> FakeCodex:
        return self.client

    async def __aexit__(self, *exc: object) -> None:
        return None


class TestSandboxCleanup:
    async def test_each_open_enters_a_fresh_cleanup_guard(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One client, two sessions: the guard factory is called per open.

        ``@contextmanager`` guards are single-use — carrying an instance
        instead of the factory made the second open on the same client
        raise ``RuntimeError`` and tore the sandbox down after the first.
        """
        import openai_codex

        entered: list[int] = []

        @contextmanager
        def open_guard() -> Iterator[None]:
            entered.append(1)
            yield

        monkeypatch.setattr(openai_codex, "AsyncCodex", FakeAsyncCodex)
        sessions = CodexSessions(CodexNativeConfig(model="gpt-5.5", cleanup=open_guard))
        async with sessions.open():
            pass
        async with sessions.open():
            pass
        assert len(entered) == 2

    def test_without_session_context_the_factory_is_reusable(self) -> None:
        factory = subprocess_sandbox_cleanup(LupAgentOptions(model="gpt-5.5"))
        with factory():
            pass
        with factory():
            pass


class TestAdapterValidation:
    def test_budget_without_estimator_raises(self) -> None:
        with pytest.raises(ValueError, match="usage_cost"):
            CodexNativeConfig(
                model="gpt-5.5",
                max_budget_usd=1.0,
            )


class TestTemplateBudgetOptions:
    def test_without_rates_no_estimator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No rates means no estimator — the codex engine then refuses budgets."""
        from lup_template.agent.config import settings
        from lup_template.agent.core import build_usage_cost

        monkeypatch.setattr(settings, "codex_usd_per_mtok_input", None)
        monkeypatch.setattr(settings, "codex_usd_per_mtok_output", None)

        assert build_usage_cost() is None

    def test_rates_enable_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from lup_template.agent.config import settings
        from lup_template.agent.core import build_usage_cost

        monkeypatch.setattr(settings, "codex_usd_per_mtok_input", 1.25)
        monkeypatch.setattr(settings, "codex_usd_per_mtok_output", 10.0)
        monkeypatch.setattr(settings, "codex_usd_per_mtok_cached_input", None)

        usage_cost = build_usage_cost()
        assert usage_cost is not None
        assert usage_cost(Usage(input_tokens=1_000_000)) == pytest.approx(1.25)
