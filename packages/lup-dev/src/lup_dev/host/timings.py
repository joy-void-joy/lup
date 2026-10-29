"""What a page measures of itself in the operator's own browser, kept on the host for agents to read.

`docs/host.md`, *A page's timings*; `docs/dashboard.md`, *Its timings*. A page
the operator uses, lup's dashboard first, runs a script (`page/src/timings.ts`)
that measures how long each key takes to reach the screen, from the browser's
Event Timing API, grouped by kinds of key the page names; its long animation
frames, where the browser has them; and the page's size at the time, in
measures the page names. Timings and sizes only, never what's typed or shown.
No room can stand in for the operator's browser, their machine and what they
have open: this is what an agent compares before and after a change, by the
page's build.

**A report** (`Report`) is one page session's, a page loaded: its browser, its
device's kind, its build, what the browser couldn't measure, and the windows
measured since the last report it sent, each numbered within the session and
sent once more where its answer didn't come. A window holds, for each kind of
key, how many keys took how long, in whole milliseconds (`Latencies`), so
percentiles merge exactly across windows and sessions; Event Timing gives a
key's duration in 8 ms steps.

**Kept 14 days** (`TimingsStore`), in lup's state, a line per window, a file per
page and per day the host received it, the days past the last 14 removed as a
report comes; reading takes each window's last copy. The page's request writes
(`KeepTimings`), the operator's dashboard sending it through its API; reading
(`ShowTimings`) is every room's, of every repository, since a page's timings are
no repository's and hold nothing of one: `lup-dev dashboard timings` reads
them in a room as on the host (`docs/host.md`, *Reading from a room*).
"""

import asyncio
import math
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, override

from filelock import FileLock
from pydantic import AfterValidator, Field, ValidationError

from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.host.protocol import HostError, Reply, Request
from lup_dev.host.service import Handler, Reading, Route

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


def measure(name: str, longest: int = 32) -> str:
    r"""Return `name` if it can name a kind of key or a measure of a page's size: letters, digits, spaces, `-` and `_`, starting and ending with neither space, at most `longest` long.

    >>> measure("drawers open")
    'drawers open'
    >>> measure("lines\n")
    Traceback (most recent call last):
    ...
    ValueError: a kind of key or a measure of a page's size is letters, digits, spaces, `-` and `_`, at most 32 long, starting and ending with no space: not 'lines\n'
    """
    allowed = all(each.isalnum() or each in " -_" for each in name)
    if not name or not allowed or name != name.strip() or len(name) > longest:
        message = (
            "a kind of key or a measure of a page's size is letters, digits, spaces, "
            f"`-` and `_`, at most {longest} long, starting and ending with no space: "
            f"not {name!r}"
        )
        raise ValueError(message)
    return name


def token(text: str, longest: int = 64) -> str:
    """Return `text` if it can name a page or a page session as the host keeps them, a page by its directory: letters, digits, `-` and `_`, at most `longest` long.

    >>> token("dashboard")
    'dashboard'
    >>> token("..")
    Traceback (most recent call last):
    ...
    ValueError: a page and a page session are named by letters, digits, `-` and `_`, at most 64 long: not '..'
    """
    allowed = all(each.isascii() and (each.isalnum() or each in "-_") for each in text)
    if not text or not allowed or len(text) > longest:
        message = (
            "a page and a page session are named by letters, digits, `-` and `_`, "
            f"at most {longest} long: not {text!r}"
        )
        raise ValueError(message)
    return text


type Measure = Annotated[str, AfterValidator(measure)]
"""A kind of key, or a measure of a page's size, as the page names it:
`typing`, `lines`, `drawers open`."""

type Token = Annotated[str, AfterValidator(token)]
"""A page, as `dashboard`, or a page session, by the id the page gave it."""

type Milliseconds = Annotated[int, Field(ge=0, le=3_600_000)]

type Count = Annotated[int, Field(ge=0, le=100_000_000)]

type Histogram = Annotated[dict[Milliseconds, Count], Field(max_length=4096)]
"""How many took how long, by the whole milliseconds each took."""

type EntryType = Literal["event", "long-animation-frame"]
"""An entry type of the browser's performance timeline the script reads: Event
Timing's (`event`), each key's; and the long animation frames'."""

PAINTED = "key down to the next paint"


class Latencies(Model):
    """How long one kind of key took, each in whole milliseconds, by how many keys took it."""

    painted: Histogram = {}
    """From the key going down to the next paint after the page handled it:
    Event Timing's `duration`, in 8 ms steps."""
    waited: Histogram = {}
    """From the key going down to the page's first handler of it starting, the
    main thread busy meanwhile: `processingStart` less `startTime`."""
    handled: Histogram = {}
    """The page's handlers of it: `processingEnd` less `processingStart`."""
    under: Count = 0
    """The keys under the browser's floor, of which Event Timing says nothing
    (16 ms): seen going down, their entry never coming while a later key's
    did, or within a minute."""

    def keys(self) -> int:
        """Return how many keys it counts, those under the floor among them.

        >>> Latencies(painted={16: 2, 40: 1}, under=3).keys()
        6
        """
        return self.under + sum(self.painted.values())

    def ranked(self, share: float) -> int | None:
        """Return how long the key at `share` of them, by their nearest rank, took to paint; none where it's one under the floor.

        >>> latencies = Latencies(painted={16: 2, 40: 1}, under=3)
        >>> latencies.ranked(0.5), latencies.ranked(0.75), latencies.ranked(1)
        (None, 16, 40)
        """
        return ranked(self.painted, self.under, share)

    @classmethod
    def merged(cls, each: Iterable[Latencies]) -> Latencies:
        """Return `each` counted as one.

        >>> Latencies.merged([Latencies(painted={16: 1}, under=1), Latencies(painted={16: 2, 24: 1})])
        Latencies(painted={16: 3, 24: 1}, waited={}, handled={}, under=1)
        """
        listed = list(each)
        return cls(
            painted=added(each.painted for each in listed),
            waited=added(each.waited for each in listed),
            handled=added(each.handled for each in listed),
            under=sum(each.under for each in listed),
        )


def added(histograms: Iterable[Mapping[int, int]]) -> dict[int, int]:
    """Return `histograms` counted as one, in order of how long."""
    total = Counter[int]()
    for each in histograms:
        total.update(each)
    return dict(sorted(total.items()))


def ranked(histogram: Mapping[int, int], under: int, share: float) -> int | None:
    """Return the value at `share` of what `histogram` and `under` more below its least count, by nearest rank; none where it's one of `under`, or there's nothing.

    >>> ranked({8: 1, 16: 1}, 0, 0.5), ranked({}, 0, 0.5), ranked({}, 2, 0.5)
    (8, None, None)
    """
    total = under + sum(histogram.values())
    rank = max(1, math.ceil(share * total))
    if total == 0 or rank <= under:
        return None
    seen = under
    for value, count in sorted(histogram.items()):
        seen += count
        if seen >= rank:
            return value
    return None


class Frames(Model):
    """A page's long animation frames, those over 50 ms the browser reports, each in whole milliseconds."""

    count: Count = 0
    total: Milliseconds = 0
    blocking: Milliseconds = 0
    """How long of them blocked input: each frame's longest tasks past 50 ms
    (`blockingDuration`)."""
    longest: Milliseconds = 0
    ran: Annotated[
        dict[Annotated[str, Field(min_length=1, max_length=128)], Milliseconds],
        Field(max_length=32),
    ] = {}
    """How long the scripts in them ran, by what began each: its invoker's type,
    and its event or the API that called it (`event-listener onmessage`,
    `user-callback Window.requestAnimationFrame`), never an element of the
    page's."""

    @classmethod
    def merged(cls, each: Iterable[Frames]) -> Frames:
        """Return `each` counted as one.

        >>> Frames.merged([Frames(count=1, total=60, longest=60, ran={"a": 50}), Frames(count=1, total=90, longest=90, ran={"a": 10})])
        Frames(count=2, total=150, blocking=0, longest=90, ran={'a': 60})
        """
        listed = list(each)
        ran = Counter[str]()
        for frames in listed:
            ran.update(frames.ran)
        return cls(
            count=sum(each.count for each in listed),
            total=sum(each.total for each in listed),
            blocking=sum(each.blocking for each in listed),
            longest=max((each.longest for each in listed), default=0),
            ran=dict(ran.most_common()),
        )


class Window(Model):
    """What a page session measured over a stretch of it: up to 5 minutes, or until its tab was hidden."""

    sequence: Annotated[int, Field(ge=1)]
    """Its number within the session, from 1: one sent twice is kept once."""
    start: datetime
    end: datetime
    """As the browser's clock says each."""
    size: Annotated[dict[Measure, Count], Field(max_length=16)] = {}
    """The page's size, each of its measures the largest seen in the window, as
    the page names them: `lines`, `items`, `drawers open`."""
    keys: Annotated[dict[Measure, Latencies], Field(max_length=16)] = {}
    """How long each kind of key took, by the kind the page named it."""
    unmatched: Count = 0
    """Event Timing's entries of a key going down that matched no key the
    script saw go down: where many come, the browser stamps the two apart."""
    frames: Frames | None = None
    """Its long animation frames; none where the browser has none to report."""


class Browser(Model):
    """The browser a page session ran in, as the page reads it: never its whole user agent string."""

    name: Annotated[str, Field(min_length=1, max_length=32)]
    """`Firefox`, `Chrome`, `Safari`, `Edge`; `other` for the rest."""
    version: Annotated[str, Field(max_length=16)] = ""
    """Its major version."""
    system: Annotated[str, Field(max_length=32)] = ""
    """`Linux`, `Android`, `iOS`, `macOS`, `Windows`; `other` for the rest."""
    device: Literal["desktop", "tablet", "phone"]
    """By its pointer and its screen: a coarse pointer on a small screen is a
    phone's."""
    cores: Annotated[int, Field(ge=1, le=1024)] | None = None
    """How many logical processors the browser says the machine has."""

    def said(self) -> str:
        """Say it in a few words.

        >>> Browser(name="Firefox", version="144", system="Linux", device="desktop", cores=16).said()
        'Firefox 144 on Linux, a desktop, 16 cores'
        """
        named = " ".join(each for each in [self.name, self.version] if each)
        on = f" on {self.system}" if self.system else ""
        cores = "" if self.cores is None else f", {self.cores} cores"
        return f"{named}{on}, a {self.device}{cores}"


class Session(Model):
    """What a page session says of itself in each report: the page, the session, its build and its browser, and what the browser couldn't measure."""

    page: Token
    """The page, as `dashboard`; a site's, under #292, its own."""
    session: Token
    """The page session's id, a page loaded: random, made by the page."""
    build: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    """The page's build, as its server names it: the dashboard's, a digest of its
    `index.html` (`About.build`); none where the page didn't know it yet."""
    browser: Browser
    unmeasured: Annotated[list[EntryType], Field(max_length=2)] = []
    """The entry types this browser doesn't report: keys, where it has no
    Event Timing; long animation frames, where it has none."""


class Report(Session):
    """What a page session sends: itself, and the windows it measured since its last report was answered."""

    windows: Annotated[list[Window], Field(min_length=1, max_length=12)]

    def measured(self, at: datetime) -> list[Measured]:
        """Return its windows as the host keeps them, received at `at`, each with the session's own."""
        session = {name: getattr(self, name) for name in Session.model_fields}
        return [Measured(**session, received=at, window=each) for each in self.windows]


class Measured(Session):
    """One window of a page session's, as the host keeps it: when it came, the session's own, and the window."""

    received: datetime
    """As the host's clock says it: what the 14 days are counted from."""
    window: Window


class KeepTimings(Request, reads=False):
    """Keep what a page session measured of itself: the page sends it every 5 minutes, and as its tab is hidden or closed."""

    kind: Literal["page-timings-keep"] = "page-timings-keep"
    report: Report


class TimingsKept(Reply):
    """The windows of a report kept, by how many."""

    kind: Literal["page-timings-kept"] = "page-timings-kept"
    windows: int


class ShowTimings(Request, reads=True):
    """Read what a page measured of itself, as kept: every room's, whatever its repository, since it's no repository's."""

    kind: Literal["page-timings"] = "page-timings"
    page: Token = "dashboard"
    since: datetime | None = None
    """Only the windows received from this time on; none for every one kept."""


class Timings(Reply):
    """Each window kept of the page asked for, its last copy, in the order each was received."""

    kind: Literal["page-timings-shown"] = "page-timings-shown"
    page: str
    measured: list[Measured] = []
    days: int
    """How many days the host keeps them."""


class TimingsStore(Model):
    """What pages measured of themselves, in lup's state on the host (`HostLayout.timings`): a directory per page, a file per day each window was received, a line each.

    Each report's windows are appended in one write under the page's lock; a
    day's file past the last `days` is removed as a report comes.
    """

    home: Path
    days: int = 14

    def keep(self, report: Report, at: datetime) -> list[Measured]:
        """Keep `report`'s windows, received at `at`, removing the days past the last `days`; return them as kept."""
        measured = report.measured(at)
        page = self.home / report.page
        page.mkdir(parents=True, exist_ok=True)
        lines = "".join(f"{each.model_dump_json()}\n" for each in measured)
        day = page / f"{at.astimezone(UTC).date().isoformat()}.jsonl"
        with self.locked(report.page):
            with day.open("a") as kept:
                kept.write(lines)
            for each in self.held(report.page):
                if each.day < self.oldest(at):
                    each.path.unlink()
        return measured

    def read(
        self, page: str, at: datetime, since: datetime | None = None
    ) -> list[Measured]:
        """Read page `page`'s windows kept, received in the last `days` before `at` and from `since` on, each one's last copy, in the order each was first received.

        Raise `HostError` naming a line that doesn't read.
        """
        oldest = datetime.combine(self.oldest(at), datetime.min.time(), UTC)
        start = oldest if since is None else max(since, oldest)
        latest = {
            Copied(session=each.session, sequence=each.window.sequence): each
            for day in self.held(page)
            if day.day >= start.astimezone(UTC).date()
            for each in day.measured()
            if each.received >= start
        }
        return list(latest.values())

    def held(self, page: str) -> list[Day]:
        """List page `page`'s days kept, oldest first: each file named by its day, any other left out."""
        directory = self.home / page
        if not directory.is_dir():
            return []
        days = [
            Day(path=each, day=day)
            for each in directory.glob("*.jsonl")
            if (day := dated(each.stem)) is not None
        ]
        return sorted(days, key=lambda each: each.day)

    def oldest(self, at: datetime) -> date:
        """Return the first day kept at `at`: the last `days` of them, today's among them."""
        return (at.astimezone(UTC) - timedelta(days=self.days - 1)).date()

    def locked(self, page: str) -> FileLock:
        """Return the lock page `page`'s days are written and removed under."""
        return FileLock(self.home / f"{page}.lock")


class Day(Model):
    """One day's file of a page's timings."""

    path: Path
    day: date

    def measured(self) -> list[Measured]:
        """Read each window kept in it, a line each.

        Raise `HostError` naming a line that doesn't read.
        """

        def read(number: int, line: str) -> Measured:
            try:
                return Measured.model_validate_json(line)
            except ValidationError as unread:
                message = f"line {number} of {self.path} doesn't read: {unread}"
                raise HostError(message) from unread

        lines = self.path.read_text().splitlines()
        return [read(number, line) for number, line in enumerate(lines, 1) if line]


class Copied(Model):
    """Which window of which session a line keeps: one sent twice is kept twice, and read once."""

    session: str
    sequence: int


def dated(name: str) -> date | None:
    """Return the day `name` says, as an ISO 8601 date; none where it says none.

    >>> dated("2026-10-30"), dated("notes")
    (datetime.date(2026, 10, 30), None)
    """
    try:
        return date.fromisoformat(name)
    except ValueError:
        return None


class TimingsKeeping(Model, Handler[KeepTimings], arbitrary_types_allowed=True):
    """Answers `KeepTimings`: the report's windows kept at the host's time, off the event loop; a room never reaches it."""

    store: TimingsStore
    clock: Clock

    @override
    def request(self) -> type[KeepTimings]:
        return KeepTimings

    @override
    async def answer(self, request: KeepTimings) -> Reply:
        kept = await asyncio.to_thread(
            self.store.keep, request.report, self.clock.now()
        )
        return TimingsKept(windows=len(kept))


class TimingsShowing(Model, Reading[ShowTimings], arbitrary_types_allowed=True):
    """Answers `ShowTimings`, off the event loop: to a room of any repository as to the operator, since a page's timings are no repository's."""

    store: TimingsStore
    clock: Clock

    @override
    def request(self) -> type[ShowTimings]:
        return ShowTimings

    @override
    async def answer(self, request: ShowTimings) -> Reply:
        measured = await asyncio.to_thread(
            self.store.read, request.page, self.clock.now(), request.since
        )
        return Timings(page=request.page, measured=measured, days=self.store.days)

    @override
    async def scoped(self, request: ShowTimings, repository: Path) -> Reply:
        del repository
        return await self.answer(request)


def routes(store: TimingsStore, clock: Clock) -> list[Route]:
    """Route keeping and reading pages' timings to their handlers, over `store`, at `clock`'s time."""
    return [
        Route.to(TimingsKeeping(store=store, clock=clock)),
        Route.reading(TimingsShowing(store=store, clock=clock)),
    ]


def ms(value: int | None, missing: str = "<16") -> str:
    """Say a duration in milliseconds as a table's cell: `missing` for none, by default one under the browser's floor.

    >>> ms(1204), ms(None), ms(None, "-")
    ('1,204', '<16', '-')
    """
    return missing if value is None else f"{value:,}"


def seconds(value: int) -> str:
    """Say a long duration given in milliseconds: in seconds from one up.

    >>> seconds(41_230), seconds(640)
    ('41.2 s', '640 ms')
    """
    return f"{value / 1000:.1f} s" if value >= 1000 else f"{value} ms"


def minute(at: datetime) -> str:
    """Say a moment to the minute, in the local time zone."""
    return f"{at.astimezone():%Y-%m-%d %H:%M}"


def unmeasured_said(entry: EntryType) -> str:
    """Say what a browser that doesn't report `entry` couldn't measure."""
    match entry:
        case "event":
            return "keys"
        case "long-animation-frame":
            return "long animation frames"


def kinds(windows: list[Measured]) -> dict[str, Latencies]:
    """Return how long each kind of key took over `windows`, in the order each kind first came."""
    named = dict.fromkeys(kind for each in windows for kind in each.window.keys)
    return {
        kind: Latencies.merged(
            each.window.keys[kind] for each in windows if kind in each.window.keys
        )
        for kind in named
    }


def sized(windows: list[Measured]) -> str:
    """Say the page's size over `windows`, each measure from the least of their largest to the most.

    >>> from datetime import UTC
    >>> def at(size: dict[str, int], sequence: int) -> Measured:
    ...     when = datetime(2026, 10, 30, tzinfo=UTC)
    ...     window = Window(sequence=sequence, start=when, end=when, size=size)
    ...     browser = Browser(name="Firefox", device="desktop")
    ...     return Measured(page="dashboard", session="s1", browser=browser,
    ...         received=when, window=window)
    >>> sized([at({"lines": 15203, "items": 40}, 1), at({"lines": 48912, "items": 40}, 2)])
    '15,203 to 48,912 lines, 40 items'
    """

    def spanned(name: str) -> str:
        values = [
            each.window.size[name] for each in windows if name in each.window.size
        ]
        least, most = min(values), max(values)
        span = f"{least:,}" if least == most else f"{least:,} to {most:,}"
        return f"{span} {name}"

    measures = dict.fromkeys(name for each in windows for name in each.window.size)
    return ", ".join(spanned(name) for name in measures)


def spanned(windows: list[Measured]) -> str:
    """Say from when to when `windows` were measured, by the browsers' clocks."""
    first = min(each.window.start for each in windows)
    last = max(each.window.end for each in windows)
    return f"{minute(first)} to {minute(last)}"


def browsers(windows: list[Measured]) -> str:
    """Say the browsers `windows` were measured in, each with how many sessions where it's more than one."""
    sessions = {each.session: each.browser.said() for each in windows}
    counted = Counter(sessions.values())
    return "; ".join(
        said if count == 1 else f"{said} ({count} sessions)"
        for said, count in counted.items()
    )


class Summary(Model):
    """How `lup-dev dashboard timings` says what a page measured of itself: by its build, oldest first, each build's sessions together; or each session apart, a line for each of its windows after."""

    called: str = "The dashboard"
    """The page, as a sentence's subject names it."""
    shares: list[float] = [0.5, 0.75, 0.95, 0.99]
    """The percentiles each table says, by their share of the keys, before the
    most."""
    slowest: float = 0.95
    """The share of keys whose time waiting and in the page's handlers each
    table says."""

    def said(self, timings: Timings, *, by_session: bool = False) -> list[str]:
        """Say `timings`, by build, or with `by_session` by session."""
        measured = sorted(timings.measured, key=lambda each: each.window.start)
        if not measured:
            none = (
                f"{self.called} kept no timings in the last {timings.days} days: the "
                "page sends them as it's used, every 5 minutes and as its tab is "
                "hidden, from every browser it isn't switched off in, in the palette."
            )
            return [none]
        sessions = dict.fromkeys(each.session for each in measured)
        builds = dict.fromkeys(each.build for each in measured)
        heading = (
            f"{self.called}'s timings, kept {timings.days} days on the host: "
            f"{counted(len(builds), 'build')}, "
            f"{counted(len(sessions), 'page session')}, {spanned(measured)}, by "
            "each browser's clock."
        )
        lines = [heading]
        if by_session:
            for session in sessions:
                windows = [each for each in measured if each.session == session]
                first = windows[0]
                heading = (
                    f"Session {session}, build {first.build or 'unknown'}, "
                    f"{spanned(windows)}: {first.browser.said()}."
                )
                lines.extend(["", *self.block(heading, windows, each_window=True)])
            return lines
        for build in builds:
            windows = [each for each in measured if each.build == build]
            count = len(dict.fromkeys(each.session for each in windows))
            heading = (
                f"Build {build or 'unknown'}, {spanned(windows)}, "
                f"{counted(count, 'session')}: {browsers(windows)}."
            )
            lines.extend(["", *self.block(heading, windows)])
        return lines

    def block(
        self, heading: str, windows: list[Measured], *, each_window: bool = False
    ) -> list[str]:
        """Say what `windows` measured, under `heading`: the page's size, how long each kind of key took, the long animation frames, and what each browser couldn't measure; with `each_window`, a line for each window after."""
        size = sized(windows)
        keys = kinds(windows)
        framed = [each.window.frames for each in windows if each.window.frames]
        unmatched = sum(each.window.unmatched for each in windows)
        unmeasured = {
            f"{unmeasured_said(entry)}, in {each.browser.said()}": None
            for each in windows
            for entry in each.unmeasured
        }
        return [
            heading,
            *([f"  The page: {size}."] if size else []),
            *(
                [
                    "  Each kind of key, from going down to the next paint, in ms:",
                    *(f"    {line}" for line in self.table(keys)),
                ]
                if keys
                else ["  No key measured."]
            ),
            *([f"  {self.frames(Frames.merged(framed))}"] if framed else []),
            *([f"  {self.unmatched(unmatched)}"] if unmatched else []),
            *([f"  Not measured: {'; '.join(unmeasured)}."] if unmeasured else []),
            *(f"    {self.windowed(each)}" for each in windows if each_window),
        ]

    def unmatched(self, count: int) -> str:
        """Say how many of the browser's entries of a key matched none the page saw go down."""
        return (
            f"{count:,} of the browser's entries of a key going down matched no key "
            "the page saw go down."
        )

    def table(self, keys: Mapping[str, Latencies]) -> list[str]:
        """Say how long each kind of key took to paint as a table: how many, the percentiles and the most, and how long the slowest waited before the page handled them and in its handlers, of those over the browser's floor, `-` where there were none.

        >>> latencies = Latencies(painted={16: 3, 24: 1}, waited={0: 4}, handled={8: 4}, under=4)
        >>> for line in Summary().table({"typing": latencies}):
        ...     print(line)
        kind    keys  p50  p75  p95  p99  max  waited p95  handled p95
        typing     8  <16   16   24   24   24           0            8
        """
        slowest = f"p{round(self.slowest * 100)}"
        header = [
            "kind",
            "keys",
            *(f"p{round(share * 100)}" for share in self.shares),
            "max",
            f"waited {slowest}",
            f"handled {slowest}",
        ]
        rows = [
            [
                kind,
                f"{latencies.keys():,}",
                *(ms(latencies.ranked(share)) for share in self.shares),
                ms(latencies.ranked(1)),
                ms(ranked(latencies.waited, 0, self.slowest), "-"),
                ms(ranked(latencies.handled, 0, self.slowest), "-"),
            ]
            for kind, latencies in keys.items()
        ]
        widths = [
            len(max(column, key=len)) for column in zip(header, *rows, strict=True)
        ]
        return [
            "  ".join(
                cell.ljust(width) if at == 0 else cell.rjust(width)
                for at, (cell, width) in enumerate(zip(row, widths, strict=True))
            )
            for row in [header, *rows]
        ]

    def frames(self, frames: Frames) -> str:
        """Say the long animation frames counted, and what ran in them, longest first.

        >>> print(Summary().frames(Frames(count=3, total=1500, blocking=400, longest=900, ran={"event-listener onmessage": 1200})))
        Long animation frames: 3, 1.5 s in all, 400 ms of it blocking, the longest 900 ms; what ran in them: event-listener onmessage 1.2 s.
        """
        ran = ", ".join(f"{what} {seconds(took)}" for what, took in frames.ran.items())
        return (
            f"Long animation frames: {frames.count:,}, {seconds(frames.total)} in all, "
            f"{seconds(frames.blocking)} of it blocking, the longest "
            f"{seconds(frames.longest)}{f'; what ran in them: {ran}' if ran else ''}."
        )

    def windowed(self, measured: Measured) -> str:
        """Say one window in a line: when, the page's size, and for each kind of key how many, their median and the slowest.

        >>> from datetime import UTC
        >>> start = datetime(2026, 10, 30, 9, 12, tzinfo=UTC)
        >>> window = Window(sequence=1, start=start, end=start, size={"lines": 15203},
        ...     keys={"typing": Latencies(painted={16: 9, 48: 1})})
        >>> browser = Browser(name="Firefox", device="desktop")
        >>> line = Summary().windowed(Measured(page="dashboard", session="s1",
        ...     browser=browser, received=start, window=window))
        >>> line.partition(": ")[2]
        '15,203 lines; typing 10 keys, p50 16, p95 48'
        """
        window = measured.window
        size = ", ".join(f"{value:,} {name}" for name, value in window.size.items())
        slowest = f"p{round(self.slowest * 100)}"
        keys = [
            f"{kind} {latencies.keys():,} keys, p50 {ms(latencies.ranked(0.5))}, "
            f"{slowest} {ms(latencies.ranked(self.slowest))}"
            for kind, latencies in window.keys.items()
        ]
        span = f"{minute(window.start)} to {window.end.astimezone():%H:%M}"
        return f"{span}: {'; '.join(each for each in [size, *keys] if each)}"


def counted(count: int, what: str) -> str:
    """Say how many of `what` there are.

    >>> counted(1, "build"), counted(3, "page session")
    ('1 build', '3 page sessions')
    """
    return f"{count} {what}" if count == 1 else f"{count} {what}s"
