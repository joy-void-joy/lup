"""Listing what was made over time, sized to be read whole: when it was made, the latest of it, and what an answer left out.

`docs/inbox.md`, *lup's tools*. `judged` lists verdicts and holds, `inbox` the
inbox's items, and `lup-dev inbox` what waits for the operator, each narrowed
alike, here, so they can't drift apart:
- **When:** `since` and `until` (`Span`), each a time, one without a zone read as
  the host's, as the answers say times (`clocked`); or a duration, counted back
  by the host service's clock (`Window`).
- **How many:** the latest, up to a limit the call sets, never splitting a
  moment, so an `until` at the earliest listed reads every one left out
  (`latest`).
- **What's left out:** said on the answer's last line, how many, the `until`
  that reads them, and the limit that lists them all (`unlisted`), so nothing
  is out of reach.
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import Field, TypeAdapter

from lup.types import Model
from lup_dev.inbox.delivery import clocked

if TYPE_CHECKING:
    from collections.abc import Callable


def moment(given: datetime | timedelta | None, now: datetime) -> datetime | None:
    """Return the time `since` or `until` names: a time as given, one without a zone the host's; a duration, counted back from `now`; none where none is given.

    >>> from datetime import UTC
    >>> moment(timedelta(hours=2), datetime(2026, 1, 1, 12, tzinfo=UTC))
    datetime.datetime(2026, 1, 1, 10, 0, tzinfo=datetime.timezone.utc)
    """
    match given:
        case None:
            return None
        case timedelta():
            return now - given
        case datetime():
            return given.astimezone()


def given(text: str | None) -> datetime | timedelta | None:
    """Read a `since` or an `until` as a command line gives it: an ISO 8601 time, or an ISO 8601 duration back from now; none where it gives none.

    Raise `ValueError` where it's neither.

    >>> given("PT2H"), given("2026-10-19T09:30")
    (datetime.timedelta(seconds=7200), datetime.datetime(2026, 10, 19, 9, 30))
    """
    if text is None:
        return None
    return TypeAdapter[datetime | timedelta](datetime | timedelta).validate_strings(
        text
    )


class Window(Model):
    """When what's listed was made: from `since` on, and before `until`; unbounded on a side with none."""

    since: datetime | None = None
    until: datetime | None = None

    def covers(self, time: datetime) -> bool:
        """Say whether `time` falls in the window."""
        return (self.since is None or time >= self.since) and (
            self.until is None or time < self.until
        )

    def said(self) -> str:
        """Say the window after a heading's subject, to the minute as each line says a time; or nothing where it's unbounded."""
        if self.since is not None and self.until is not None:
            return f" between {clocked(self.since)} and {clocked(self.until)}"
        if self.since is not None:
            return f" since {clocked(self.since)}"
        if self.until is not None:
            return f" before {clocked(self.until)}"
        return ""


class Span(Model):
    """When what a call lists was made, as the call gives it: `since` and `until`, each a time or a duration back from now."""

    since: datetime | timedelta | None = Field(
        default=None,
        description=(
            "Only what was made from this time on: an ISO 8601 time, such as "
            "`2026-10-19T09:30` (without a zone, the host's, as the answer says "
            "times), or an ISO 8601 duration back from now, such as `PT2H` or "
            "`P3D`. Left out, from the first."
        ),
    )
    until: datetime | timedelta | None = Field(
        default=None,
        description=(
            "Only what was made before this time, in the same forms as `since`: "
            "an answer that leaves earlier ones out says the `until` that reads "
            "them. Left out, up to now."
        ),
    )

    def window(self, now: datetime) -> Window:
        """Return when what's listed was made, a duration counted back from `now`."""
        return Window(since=moment(self.since, now), until=moment(self.until, now))


def latest[T](items: list[T], when: Callable[[T], datetime], most: int) -> list[T]:
    """Return the latest `most` of `items`, which are oldest first by `when`.

    Fewer where the oldest of them shares its moment with one left out, so an
    `until` at that moment reads every one left out; where they all share it,
    every item of that moment, however many.

    >>> from datetime import UTC
    >>> def day(item: int) -> datetime:
    ...     return datetime(2026, 1, item, tzinfo=UTC)
    >>> latest([1, 2, 3], day, 2), latest([1, 2, 2, 3], day, 2), latest([1, 3, 3, 3], day, 2)
    ([2, 3], [3], [3, 3, 3])
    """
    if len(items) <= most:
        return items
    shown = items[-most:]
    cut = when(shown[0])
    if when(items[-most - 1]) != cut:
        return shown
    after = [item for item in shown if when(item) > cut]
    return after or [item for item in items if when(item) == cut]


def unlisted(
    left: int,
    noun: str,
    before: datetime,
    every: int,
    *,
    state: str = "",
    until: str = "until",
    limit: str = "limit",
) -> list[str]:
    """Say how many of `noun` an answer left out, in `state`, the `until` that reads them, the moment of the earliest listed, and the `limit` that lists all `every` of them, each as the caller names it: a tool's field, or a command's option; nothing where it left none out."""
    if not left:
        return []
    moment = before.astimezone().isoformat()
    return [
        (
            f'Not listed: {many(left, noun)}{state}, which `{until}` "{moment}" '
            f"reads; a `{limit}` of {every} lists them all."
        )
    ]


def many(count: int, noun: str) -> str:
    """Say a count of `noun`, plural but for one.

    >>> many(1, "verdict"), many(2, "earlier verdict")
    ('1 verdict', '2 earlier verdicts')
    """
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
