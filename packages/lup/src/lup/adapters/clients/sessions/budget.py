"""The budget verb: cost metering composed over any sessions.

Runtimes that report token counts but no cost (the Codex app-server)
compose this wrapper: a caller-supplied ``usage_cost`` estimator prices
each turn's normalized usage, the running total stamps
``result.total_cost_usd``, and — when ``max_budget_usd`` is set — the
turn after the budget is crossed is refused
(:class:`~lup.adapters.errors.BudgetExceededError`). Enforcement is
between turns: turns are atomic from the caller's side, so the turn that
crosses the budget completes and every turn after it raises.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from lup.adapters.clients.sessions.Session import Session
from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.errors import BudgetExceededError
from lup.telemetry.trace import TraceLogger
from lup.types import LupResponse, Usage, UsageCost


class BudgetedSession(Session):
    """Meters one conversation's cost; refuses turns past the budget."""

    def __init__(
        self,
        inner: Session,
        *,
        usage_cost: UsageCost,
        max_budget_usd: float | None = None,
        cumulative: bool = False,
    ) -> None:
        self.inner = inner
        self.usage_cost = usage_cost
        self.max_budget_usd = max_budget_usd
        self.cumulative = cumulative
        self.turns_usage = Usage()
        self.cost_usd: float | None = None
        self.id = inner.id

    def check_budget(self) -> None:
        """Refuse to start a turn once accumulated cost reached the budget."""
        if self.max_budget_usd is None or self.cost_usd is None:
            return
        if self.cost_usd >= self.max_budget_usd:
            raise BudgetExceededError(
                f"Session cost ${self.cost_usd:.4f} reached the "
                f"${self.max_budget_usd:.2f} budget; refusing to start a turn."
            )

    def record_turn(self, usage: Usage | None) -> None:
        """Fold one turn's usage into the running total and re-price it.

        ``cumulative`` marks engines whose normalized usage is already the
        session's running total (Codex reports thread totals): the
        snapshot replaces the total instead of adding to it.
        """
        if usage is None:
            return
        if self.cumulative:
            self.turns_usage = usage
        else:
            self.turns_usage = Usage(
                input_tokens=self.turns_usage.input_tokens + usage.input_tokens,
                output_tokens=self.turns_usage.output_tokens + usage.output_tokens,
                cache_read_input_tokens=(
                    self.turns_usage.cache_read_input_tokens
                    + usage.cache_read_input_tokens
                ),
                cache_creation_input_tokens=(
                    self.turns_usage.cache_creation_input_tokens
                    + usage.cache_creation_input_tokens
                ),
            )
        self.cost_usd = self.usage_cost(self.turns_usage)

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        self.check_budget()
        response = await self.inner.send(
            prompt, trace_logger=trace_logger, prefix=prefix
        )
        self.id = self.inner.id
        if response.result is not None:
            self.record_turn(response.result.usage)
            if self.cost_usd is not None:
                response.result.total_cost_usd = self.cost_usd
        return response

    async def interrupt(self) -> None:
        await self.inner.interrupt()


class BudgetedSessions(Sessions):
    """Opens the inner engine's sessions with cost metering composed on."""

    def __init__(
        self,
        inner: Sessions,
        *,
        usage_cost: UsageCost,
        max_budget_usd: float | None = None,
        cumulative: bool = False,
    ) -> None:
        self.inner = inner
        self.usage_cost = usage_cost
        self.max_budget_usd = max_budget_usd
        self.cumulative = cumulative

    @asynccontextmanager
    async def open(self, *, resume: str | None = None) -> AsyncGenerator[Session, None]:
        async with self.inner.open(resume=resume) as session:
            yield BudgetedSession(
                session,
                usage_cost=self.usage_cost,
                max_budget_usd=self.max_budget_usd,
                cumulative=self.cumulative,
            )
