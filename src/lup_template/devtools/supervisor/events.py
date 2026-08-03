"""Server-sent events, read from the run's own journal.

Nothing publishes into this module. A run records everything it does to
``journal.jsonl``, so a connected page is a reader like any other door — it
follows the file. That is what lets a page follow a run no process in this
program is attached to, and why there is no hub, no queue, and no thread to
hand events across.

The stream carries the record rather than a diff of two projections. A diff
answers "what changed since I last looked", which is enough to keep a status
table current and useless for reading what an actor actually did; the record
answers both, and reconnecting replays from the last sequence number seen
rather than from the beginning.
"""

import asyncio
from collections.abc import AsyncGenerator

from lup.resolver.journal import Journal, JournalEntry

HEARTBEAT_SECONDS = 15.0
RETRY_MILLISECONDS = 3000
WATCH_INTERVAL_SECONDS = 0.5


def frame(entry: JournalEntry) -> str:
    """One SSE frame carrying its sequence number as the event id.

    The id is what a reconnect sends back in ``Last-Event-ID``, so numbering
    frames by journal sequence is what makes a resume exact instead of
    approximate.
    """
    return f"id: {entry.seq}\ndata: {entry.model_dump_json()}\n\n"


async def stream(
    journal: Journal,
    after_seq: int = -1,
    interval: float = WATCH_INTERVAL_SECONDS,
    heartbeat: float = HEARTBEAT_SECONDS,
) -> AsyncGenerator[str, None]:
    """Replay what this reader missed, then follow the journal as it grows.

    The catch-up pass reads the whole file once and the follow reads only
    what is new, so a page open for a long run costs the size of what
    arrives rather than the size of what has accumulated.

    The tick drives both the events and the keep-alive, so no await is ever
    cancelled to deliver a heartbeat — an async generator interrupted that
    way would be closed rather than resumed, and the stream would go silent
    exactly when the run went quiet.
    """
    yield f"retry: {RETRY_MILLISECONDS}\n\n"
    caught_up = journal.tail(0)
    for entry in caught_up.entries:
        if entry.seq > after_seq:
            yield frame(entry)
    offset = caught_up.offset
    silent = 0.0
    while True:
        arrived = journal.tail(offset)
        offset = arrived.offset
        for entry in arrived.entries:
            yield frame(entry)
        silent = 0.0 if arrived.entries else silent + interval
        if silent >= heartbeat:
            yield ": keep-alive\n\n"
            silent = 0.0
        await asyncio.sleep(interval)
