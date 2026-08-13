"""What one account's usage looks like, whichever runtime metered it.

Every runtime that bills a subscription answers the same two questions — how
much of each metered window is spent and when it clears, and where the tokens
went day by day — and answers them in its own wire shape. This is the shape
the display reads, so a runtime joins by translating its own answer into it
rather than by growing a second display that drifts from the first.
"""

from abc import ABC, abstractmethod
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

FROZEN = ConfigDict(frozen=True)


class PacingWindow(BaseModel):
    """One metered window: how much of it is spent, and when it clears.

    ``window_hours`` is what makes a bar say more than a percentage: knowing
    the window's length places the reader against even pace inside it, which
    is the difference between "62% used" and "62% used, and half way through".
    """

    model_config = FROZEN

    label: str
    utilization_pct: float
    resets_at: datetime
    window_hours: float


class SpendWindow(BaseModel):
    """Metered spend past the plan, in whatever the account is billed in."""

    model_config = FROZEN

    label: str
    used: float
    limit: float
    utilization_pct: float


class ModelTokens(BaseModel):
    """What one model moved, under the id its own runtime reports it by."""

    model_config = FROZEN

    model: str
    tokens: int


class ModelShare(BaseModel):
    """One model's share of the period, named and coloured by its own runtime.

    A model family's display name and colour are the runtime's judgement about
    its own lineup, so the legend arrives assembled rather than as ids the
    display would need a table of its own to recognise.
    """

    model_config = FROZEN

    label: str
    style: str
    tokens: int


class DayUsage(BaseModel):
    """One day's usage, weighted the way the runtime reporting it prices work.

    ``weight`` is what the day cost against the plan and ``total_tokens`` is
    what it moved; the two differ wherever a runtime prices its models
    differently, and a runtime that publishes no prices weighs a day by its
    token count so the same bars still mean something.
    """

    model_config = FROZEN

    day: date
    total_tokens: int
    weight: float
    by_model: list[ModelTokens] = Field(default_factory=list)
    message_count: int = 0


class UsageReport(BaseModel):
    """One account's usage, in the terms every runtime's display renders."""

    model_config = FROZEN

    runtime_name: str
    windows: list[PacingWindow] = Field(default_factory=list)
    spend: SpendWindow | None = None
    daily: list[DayUsage] = Field(default_factory=list)
    legend: list[ModelShare] = Field(default_factory=list)
    fresh_through: date | None = None
    """The last day the daily figures actually cover, where that is knowable.

    A runtime whose daily detail comes from a cache it refreshes on its own
    schedule can be reporting a window that stops short of today. Saying where
    the figures end lets the display mark the shortfall instead of drawing a
    quiet day that was never measured.
    """


class UsageUnavailable(RuntimeError):
    """One account's usage could not be read this time.

    Every runtime fails at its own boundary and in its own exception type,
    while the display can act on exactly one fact: that this attempt produced
    no figures. Readers raise this from whatever they caught, so a watch loop
    keeps its panel and a one-shot call reports the reason it was given.
    """


class UsageReader(ABC):
    """Read one account's usage from the runtime that meters it."""

    @abstractmethod
    def read(self, detail: bool) -> UsageReport:
        """Read the live windows, and the daily detail when it is asked for.

        Raises :class:`UsageUnavailable` when the account cannot be reached.
        """
