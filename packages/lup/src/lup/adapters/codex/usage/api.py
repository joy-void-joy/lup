"""What the Codex app-server reports about an account's metered usage.

Two requests answer the whole display: one for the rate-limit windows the
plan meters, one for the daily token buckets behind them. Both are read over
the app-server rather than from the endpoint underneath it, so the rotating
credential stays with the runtime that owns and refreshes it, and a login
this process never reads cannot be a login it leaks.
"""

from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from lup.adapters.codex.app_server import AppServerError, CodexAppServer
from lup.types import EnvVars, JsonValue

FROZEN = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

RATE_LIMITS_METHOD = "account/rateLimits/read"
TOKEN_USAGE_METHOD = "account/tokenUsage/read"


class RateLimitWindow(BaseModel):
    """One metered window: how much is spent, how long it runs, when it clears."""

    model_config = FROZEN

    used_percent: float = Field(default=0, alias="usedPercent")
    resets_at: int | None = Field(default=None, alias="resetsAt")
    window_duration_mins: int | None = Field(default=None, alias="windowDurationMins")

    def clears_at(self) -> datetime | None:
        """When this window clears, as a moment rather than a Unix second."""
        if self.resets_at is None:
            return None
        return datetime.fromtimestamp(self.resets_at, tz=timezone.utc)


class CreditsSnapshot(BaseModel):
    """Whether the account holds credits past its plan, and how many."""

    model_config = FROZEN

    has_credits: bool = Field(default=False, alias="hasCredits")
    unlimited: bool = False
    balance: float | None = None


class RateLimitSnapshot(BaseModel):
    """Every window one plan meters, as one reading of them."""

    model_config = FROZEN

    plan_type: str | None = Field(default=None, alias="planType")
    primary: RateLimitWindow | None = None
    secondary: RateLimitWindow | None = None
    credits: CreditsSnapshot | None = None


class AccountRateLimits(BaseModel):
    """The rate-limit reading, whose single-bucket view is the one rendered."""

    model_config = FROZEN

    rate_limits: RateLimitSnapshot = Field(
        default_factory=RateLimitSnapshot, alias="rateLimits"
    )


class TokenUsageDay(BaseModel):
    """One day's tokens, under the date the account's own billing day starts."""

    model_config = FROZEN

    start_date: str = Field(default="", alias="startDate")
    tokens: int = 0

    def starts_on(self) -> date | None:
        """Which day this counts, or none where it does not name one.

        A bucket whose date is absent or in a shape this cannot read is worth
        less than the whole reading it would otherwise take down: the windows
        are what the display is for, and a day it cannot place is one day
        missing from a breakdown rather than a panel that fails to draw.
        """
        try:
            return date.fromisoformat(self.start_date)
        except ValueError:
            return None


class AccountTokenUsage(BaseModel):
    """The daily buckets behind the windows, where the account reports any."""

    model_config = FROZEN

    daily_usage_buckets: list[TokenUsageDay] | None = Field(
        default=None, alias="dailyUsageBuckets"
    )


class AccountUsage(BaseModel):
    """One complete reading of an account: its windows, and its daily buckets."""

    model_config = ConfigDict(frozen=True)

    limits: AccountRateLimits
    tokens: AccountTokenUsage


class CodexAccountClient:
    """One short-lived app-server connection, opened to ask about an account.

    A display is not a session: it starts the same binary a session would,
    asks its two questions, and stops. Holding the connection open would keep
    a runtime process alive for a panel that refreshes every ten minutes.
    """

    def __init__(self, executable: Path, environment: EnvVars) -> None:
        self.executable = executable
        self.environment = environment

    async def read(self) -> AccountUsage:
        """Ask for the windows and the daily buckets over one connection."""
        server = CodexAppServer(self.executable, environment=dict(self.environment))
        await server.start()
        try:
            limits = await server.request(RATE_LIMITS_METHOD, {})
            tokens = await self.token_usage(server)
        finally:
            await server.close()
        return AccountUsage(
            limits=AccountRateLimits.model_validate(limits), tokens=tokens
        )

    async def token_usage(self, server: CodexAppServer) -> AccountTokenUsage:
        """Read the daily buckets, and none where this build has no such call.

        The windows are what the display is for and the buckets are detail an
        older app-server may not answer at all, so an unknown method leaves
        the daily section empty rather than failing the whole reading.
        """
        try:
            payload: JsonValue = await server.request(TOKEN_USAGE_METHOD, {})
        except AppServerError:
            return AccountTokenUsage()
        return AccountTokenUsage.model_validate(payload)
