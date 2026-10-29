"""What a page measured of itself, as the host keeps it: each window a line, a file per page and per day, the days past the last 14 removed, a window sent twice read once, every room reading it, and how `lup-dev dashboard timings` says it."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from lup_dev.host.protocol import HostError
from lup_dev.host.timings import (
    Browser,
    Frames,
    KeepTimings,
    Latencies,
    Report,
    ShowTimings,
    Summary,
    Timings,
    TimingsKept,
    TimingsStore,
    Window,
    routes,
)

if TYPE_CHECKING:
    from conftest import FakeClock

FIREFOX = Browser(
    name="Firefox", version="144", system="Linux", device="desktop", cores=16
)
PHONE = Browser(name="Chrome", version="151", system="Android", device="phone", cores=8)
START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def raw(sequence: int, **fields: object) -> dict[str, object]:
    """Window `sequence` of a session as the page sends it, five minutes each from `START`."""
    start = START + timedelta(minutes=5 * (sequence - 1))
    end = start + timedelta(minutes=5)
    return {"sequence": sequence, "start": start, "end": end} | fields


def window(sequence: int, **fields: object) -> Window:
    """Window `sequence` of a session, five minutes each from `START`."""
    return Window.model_validate(raw(sequence, **fields))


def report(of: str, *windows: Window, **fields: object) -> Report:
    """A report of the dashboard's session `of`, in Firefox unless said."""
    return Report.model_validate(
        {
            "page": "dashboard",
            "session": of,
            "build": "b1",
            "browser": FIREFOX,
            "windows": list(windows),
        }
        | fields
    )


def test_each_window_is_kept_a_line_and_one_sent_twice_is_read_once(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = TimingsStore(home=tmp_path / "timings")
    typing = Latencies(painted={16: 3, 24: 1}, waited={0: 4}, handled={8: 4}, under=2)
    first = window(1, size={"lines": 15_000}, keys={"typing": typing})
    kept = store.keep(report("a1", first), clock.now())
    assert [(each.session, each.window, each.received) for each in kept] == [
        ("a1", first, clock.now())
    ]
    clock.sleep(300)
    later = clock.now()
    # The second report's answer never came: its window is sent again with the third.
    second = window(2, size={"lines": 16_000})
    store.keep(report("a1", second), clock.now())
    clock.sleep(300)
    again = second.model_copy(update={"size": {"lines": 16_500}})
    store.keep(report("a1", again, window(3)), clock.now())
    day = tmp_path / "timings" / "dashboard" / "2026-10-01.jsonl"
    assert len(day.read_text().splitlines()) == 4
    read = store.read("dashboard", clock.now())
    assert [each.window.sequence for each in read] == [1, 2, 3]
    assert read[1].window.size == {"lines": 16_500}
    assert read[0].browser == FIREFOX
    assert read[0].build == "b1"
    assert store.read("dashboard", clock.now(), since=later) == (read[1:])
    assert store.read("another-page", clock.now()) == []


def test_the_days_past_the_last_14_are_removed_as_a_report_comes(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = TimingsStore(home=tmp_path / "timings")
    store.keep(report("old", window(1)), clock.now())
    (tmp_path / "timings" / "dashboard" / "notes.txt").write_text("not a day's")
    clock.sleep(timedelta(days=13).total_seconds())
    store.keep(report("recent", window(1)), clock.now())
    assert [each.session for each in store.read("dashboard", clock.now())] == [
        "old",
        "recent",
    ]
    clock.sleep(timedelta(days=1).total_seconds())
    # Read past its 14 days, the oldest is left out before a report removes it.
    assert [each.session for each in store.read("dashboard", clock.now())] == ["recent"]
    store.keep(report("new", window(1)), clock.now())
    days = sorted(each.name for each in (tmp_path / "timings" / "dashboard").iterdir())
    assert days == ["2026-10-14.jsonl", "2026-10-15.jsonl", "notes.txt"]


def test_a_line_that_doesnt_read_is_said_with_its_file(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = TimingsStore(home=tmp_path / "timings")
    store.keep(report("a1", window(1)), clock.now())
    day = tmp_path / "timings" / "dashboard" / "2026-10-01.jsonl"
    day.write_text(day.read_text() + '{"page": "dashboard"\n')
    with pytest.raises(HostError, match=r"line 2 of .*2026-10-01\.jsonl doesn't read"):
        store.read("dashboard", clock.now())


@pytest.mark.parametrize(
    "fields",
    [
        {"page": "../state"},
        {"session": "a b"},
        {"windows": []},
        {"windows": [raw(each) for each in range(1, 14)]},
        {"windows": [raw(1, keys={"typing\n": {}})]},
        {"windows": [raw(1, size={f"m{each}": 1 for each in range(17)})]},
        {"windows": [raw(1, keys={"typing": {"painted": {"-8": 1}}})]},
        {"unmeasured": ["paint"]},
    ],
)
def test_a_report_out_of_bounds_is_refused(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        report("a1", window(1), **fields)


def test_keeping_is_the_operators_and_reading_every_rooms(
    tmp_path: Path, clock: FakeClock
) -> None:
    store = TimingsStore(home=tmp_path / "timings")
    keeping, showing = routes(store, clock)
    assert keeping.scoped is None
    assert showing.scoped is not None
    sent = KeepTimings(report=report("a1", window(1), window(2)))
    kept = asyncio.run(keeping.answer(sent.model_dump_json()))
    assert kept == TimingsKept(windows=2)
    asked = ShowTimings().model_dump_json()
    shown = asyncio.run(showing.answer(asked))
    assert isinstance(shown, Timings)
    assert [each.window.sequence for each in shown.measured] == [1, 2]
    # A room of any repository reads them, since they're no repository's.
    from_room = asyncio.run(showing.scoped(asked, Path("/elsewhere/.git")))
    assert from_room == shown


def test_said_by_build_with_each_browser_and_what_it_couldnt_measure() -> None:
    typing = Latencies(painted={16: 30, 24: 10, 48: 5, 120: 1}, under=54)
    motion = Latencies(
        painted={24: 8, 96: 2}, waited={0: 6, 48: 4}, handled={8: 8, 16: 2}
    )
    ran = {
        "event-listener onmessage": 900,
        "user-callback Window.requestAnimationFrame": 200,
    }
    frames = Frames(count=4, total=1_300, blocking=500, longest=700, ran=ran)
    firefox = report(
        "a1",
        window(1, size={"lines": 15_203, "items": 40}, keys={"typing": typing}),
        window(
            2,
            size={"lines": 48_912, "items": 40},
            keys={"motion": motion},
            frames=frames,
            unmatched=2,
        ),
    )
    phone = report(
        "p1",
        window(3, keys={"typing": Latencies(painted={32: 4})}),
        browser=PHONE,
        build="b2",
        unmeasured=["long-animation-frame"],
    )
    at = START + timedelta(hours=1)
    measured = [*firefox.measured(at), *phone.measured(at)]
    timings = Timings(page="dashboard", days=14, measured=measured)
    lines = Summary().said(timings)
    first_at = START.astimezone()
    last_at = (START + timedelta(minutes=15)).astimezone()
    assert lines[0] == (
        "The dashboard's timings, kept 14 days on the host: 2 builds, 2 page "
        f"sessions, {first_at:%Y-%m-%d %H:%M} to {last_at:%Y-%m-%d %H:%M}, by each "
        "browser's clock."
    )
    first, second = "\n".join(lines[2:]).split("\n\n")
    assert first.splitlines()[0].startswith("Build b1, ")
    assert first.splitlines()[0].endswith(
        ", 1 session: Firefox 144 on Linux, a desktop, 16 cores."
    )
    assert first.splitlines()[1:] == [
        "  The page: 15,203 to 48,912 lines, 40 items.",
        "  Each kind of key, from going down to the next paint, in ms:",
        "    kind    keys  p50  p75  p95  p99  max  waited p95  handled p95",
        "    typing   100  <16   16   48   48  120           -            -",
        "    motion    10   24   24   96   96   96          48           16",
        (
            "  Long animation frames: 4, 1.3 s in all, 500 ms of it blocking, the "
            "longest 700 ms; what ran in them: event-listener onmessage 900 ms, "
            "user-callback Window.requestAnimationFrame 200 ms."
        ),
        (
            "  2 of the browser's entries of a key going down matched no key the "
            "page saw go down."
        ),
    ]
    assert second.splitlines()[0].startswith("Build b2, ")
    assert second.splitlines()[0].endswith(
        ", 1 session: Chrome 151 on Android, a phone, 8 cores."
    )
    assert second.splitlines()[-1] == (
        "  Not measured: long animation frames, in Chrome 151 on Android, a phone, "
        "8 cores."
    )


def test_said_by_session_a_line_for_each_window() -> None:
    typing = Latencies(painted={16: 9, 48: 1})
    sent = report(
        "a1",
        window(1, size={"lines": 15_203}, keys={"typing": typing}),
        window(2, size={"lines": 16_000}),
    )
    timings = Timings(page="dashboard", days=14, measured=sent.measured(START))
    lines = Summary().said(timings, by_session=True)
    assert lines[2].startswith("Session a1, build b1, ")
    assert [each.partition(": ")[2] for each in lines[-2:]] == [
        "15,203 lines; typing 10 keys, p50 16, p95 48",
        "16,000 lines",
    ]


def test_said_when_nothing_was_kept() -> None:
    assert Summary().said(Timings(page="dashboard", days=14)) == [
        (
            "The dashboard kept no timings in the last 14 days: the page sends them "
            "as it's used, every 5 minutes and as its tab is hidden, from every "
            "browser it isn't switched off in, in the palette."
        )
    ]
