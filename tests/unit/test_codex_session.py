# lup: ignore[bare-object, cast]
# Test fixtures and assertions construct these shapes deliberately.
"""Codex session behavior: thread lifecycle, pricing, and native validation.

The runtime's own session concerns, pinned without any LLM call: the
thread door (start vs resume), the session id, the per-open entry of
session resources, per-MTok pricing, and the priced-budget validation on
the native config. Budget and timeout governance is composed over these
sessions by the create recipe and tested engine-agnostically in
``test_session_governance``.
"""

from collections.abc import Generator
from contextlib import contextmanager
from types import TracebackType
from typing import TYPE_CHECKING, cast

import pytest

from lup.adapters.clients.codex.native import CodexNativeConfig
from lup.adapters.clients.codex.sessions import CodexSession, CodexSessions
from lup.adapters.clients.usage import per_mtok_usage_cost
from lup.types import Usage

if TYPE_CHECKING:
    from openai_codex import ApprovalMode, AsyncCodex, AsyncThread
    from openai_codex import Sandbox as CodexSandbox


class FakeTurnResult:
    """Minimal TurnResult stand-in: no items, no usage."""

    def __init__(self) -> None:
        self.items: list[object] = []
        self.final_response: str | None = None
        self.usage = None


class FakeThread:
    """AsyncThread stand-in recording prompts."""

    def __init__(self) -> None:
        self.id = "thread-fake"
        self.prompts: list[str] = []

    async def run(
        self,
        prompt: str,
        *,
        effort: object = None,
        output_schema: object = None,
    ) -> FakeTurnResult:
        self.prompts.append(prompt)
        return FakeTurnResult()


class FakeCodex:
    """AsyncCodex stand-in recording which thread door was used."""

    def __init__(self, thread: FakeThread) -> None:
        self.thread = thread
        self.started: list[str] = []
        self.resumed: list[str] = []

    async def __aenter__(self) -> "FakeCodex":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

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
    fake = FakeCodex(FakeThread())
    codex = cast("AsyncCodex", cast(object, fake))
    sessions = CodexSessions(CodexNativeConfig(model="gpt-5.5"))

    started = await sessions.open_thread(codex, resume=None)
    assert started is fake.thread
    assert fake.started == ["gpt-5.5"]

    resumed = await sessions.open_thread(codex, resume="thread-9")
    assert resumed is fake.thread
    assert fake.resumed == ["thread-9"]


def test_session_id_is_the_thread_id() -> None:
    conv = CodexSession(cast("AsyncThread", FakeThread()))
    assert conv.id == "thread-fake"


async def test_session_resources_enter_fresh_per_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each open() enters one fresh context per factory, exited on close.

    Factories rather than contexts, because one client opens many
    sessions — a single reused ``@contextmanager`` instance would raise
    on the second open.
    """
    events = list[str]()

    @contextmanager
    def resource() -> Generator[None]:
        events.append("enter")
        yield
        events.append("exit")

    fake = FakeCodex(FakeThread())
    monkeypatch.setattr("openai_codex.AsyncCodex", lambda *, config: fake)
    sessions = CodexSessions(
        CodexNativeConfig(model="gpt-5.5", session_resources=[resource])
    )

    async with sessions.open():
        assert events == ["enter"]
    assert events == ["enter", "exit"]

    async with sessions.open():
        pass
    assert events == ["enter", "exit", "enter", "exit"]


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
