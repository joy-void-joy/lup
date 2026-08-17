"""Answering a fetch from disk, and refusing to when what is held is too old."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel

from lup.workspace.fetch_cache import (
    CacheEntry,
    FetchCache,
    Fetched,
    cached_fetch,
    configure,
    resolve_state,
    state,
)


@pytest.fixture(autouse=True)
def clean_state(tmp_path: Path) -> Iterator[None]:
    state.cache = FetchCache(directory=tmp_path / "fetch")
    yield
    state.cache = None


class Counter(BaseModel):
    """How many times a producer was actually asked to go and fetch."""

    calls: int = 0

    def once(self, payload: bytes = b"body") -> Fetched:
        """Record a fetch and answer with the payload it would have returned."""
        self.calls += 1
        return Fetched(payload=payload, content_type="text/html")


def cache(
    *,
    ttl: timedelta | None = None,
    stale_on_error: bool | None = None,
) -> FetchCache:
    """The configured cache, after applying the overrides this test wants."""
    configure(ttl=ttl, stale_on_error=stale_on_error)
    return resolve_state()


class TestReadThrough:
    async def test_a_miss_fetches_and_a_second_ask_does_not(self) -> None:
        counter = Counter()

        async def produce() -> Fetched:
            return counter.once()

        first = await cached_fetch("page", "https://example.com/a", produce)
        second = await cached_fetch("page", "https://example.com/a", produce)

        assert counter.calls == 1
        assert first.payload() == b"body"
        assert second.payload() == b"body"
        assert not second.stale

    async def test_two_urls_do_not_answer_for_each_other(self) -> None:
        counter = Counter()

        async def produce() -> Fetched:
            return counter.once()

        await cached_fetch("page", "https://example.com/a", produce)
        await cached_fetch("page", "https://example.com/b", produce)

        assert counter.calls == 2

    async def test_one_url_in_two_namespaces_is_two_entries(self) -> None:
        counter = Counter()

        async def produce() -> Fetched:
            return counter.once()

        await cached_fetch("page", "https://example.com/a", produce)
        await cached_fetch("pdf", "https://example.com/a", produce)

        assert counter.calls == 2

    async def test_bytes_survive_the_round_trip_unchanged(self) -> None:
        payload = bytes(range(256))

        async def produce() -> Fetched:
            return Fetched(payload=payload, content_type="application/pdf")

        held = await cached_fetch("pdf", "https://example.com/paper.pdf", produce)

        assert held.payload() == payload
        assert held.entry.content_type == "application/pdf"

    async def test_refresh_fetches_even_when_something_current_is_held(self) -> None:
        counter = Counter()

        async def produce() -> Fetched:
            return counter.once()

        await cached_fetch("page", "https://example.com/a", produce)
        await cached_fetch("page", "https://example.com/a", produce, refresh=True)

        assert counter.calls == 2


class TestLifetime:
    async def test_a_payload_past_its_lifetime_is_fetched_again(self) -> None:
        cache(ttl=timedelta(seconds=0))
        counter = Counter()

        async def produce() -> Fetched:
            return counter.once()

        await cached_fetch("page", "https://example.com/a", produce)
        await cached_fetch("page", "https://example.com/a", produce)

        assert counter.calls == 2

    def test_an_entry_reports_its_own_expiry_against_a_lifetime(self) -> None:
        entry = CacheEntry(
            key="https://example.com/a",
            namespace="page",
            fetched_at=datetime.now(UTC) - timedelta(days=3),
        )

        assert entry.expired(timedelta(days=1))
        assert not entry.expired(timedelta(days=7))


class TestFailure:
    async def test_a_failure_with_nothing_held_is_raised(self) -> None:
        async def produce() -> Fetched:
            raise RuntimeError("host unreachable")

        with pytest.raises(RuntimeError):
            await cached_fetch("page", "https://example.com/a", produce)

    async def test_a_failure_is_never_itself_cached(self) -> None:
        counter = Counter()

        async def failing() -> Fetched:
            raise RuntimeError("host unreachable")

        async def working() -> Fetched:
            return counter.once()

        with pytest.raises(RuntimeError):
            await cached_fetch("page", "https://example.com/a", failing)
        held = await cached_fetch("page", "https://example.com/a", working)

        assert counter.calls == 1
        assert held.payload() == b"body"

    async def test_a_failed_refetch_falls_back_to_what_is_held(self) -> None:
        cache(ttl=timedelta(seconds=0))

        async def working() -> Fetched:
            return Fetched(payload=b"the real thing")

        async def failing() -> Fetched:
            raise RuntimeError("host unreachable")

        await cached_fetch("page", "https://example.com/a", working)
        held = await cached_fetch("page", "https://example.com/a", failing)

        assert held.payload() == b"the real thing"
        assert held.stale

    async def test_a_failed_refetch_raises_when_the_fallback_is_declined(self) -> None:
        cache(ttl=timedelta(seconds=0), stale_on_error=False)

        async def working() -> Fetched:
            return Fetched(payload=b"the real thing")

        async def failing() -> Fetched:
            raise RuntimeError("host unreachable")

        await cached_fetch("page", "https://example.com/a", working)

        with pytest.raises(RuntimeError):
            await cached_fetch("page", "https://example.com/a", failing)


class TestDamagedEntries:
    async def test_an_unreadable_record_is_a_miss_rather_than_a_failure(self) -> None:
        store = cache()
        counter = Counter()

        async def produce() -> Fetched:
            return counter.once()

        await cached_fetch("page", "https://example.com/a", produce)
        located = store.located("page", "https://example.com/a")
        located.record.write_text("{ truncated", encoding="utf-8")

        held = await cached_fetch("page", "https://example.com/a", produce)

        assert counter.calls == 2
        assert held.payload() == b"body"

    async def test_a_record_without_its_payload_is_a_miss(self) -> None:
        store = cache()
        counter = Counter()

        async def produce() -> Fetched:
            return counter.once()

        await cached_fetch("page", "https://example.com/a", produce)
        store.located("page", "https://example.com/a").payload.unlink()

        await cached_fetch("page", "https://example.com/a", produce)

        assert counter.calls == 2


class TestReportingAndClearing:
    async def test_entries_describe_what_is_held(self) -> None:
        store = cache()

        async def produce() -> Fetched:
            return Fetched(payload=b"body", content_type="text/html")

        await cached_fetch("page", "https://example.com/a", produce)
        await cached_fetch("pdf", "https://example.com/paper.pdf", produce)

        assert {entry.namespace for entry in store.entries()} == {"page", "pdf"}

    async def test_clearing_a_namespace_leaves_the_others_standing(self) -> None:
        store = cache()

        async def produce() -> Fetched:
            return Fetched(payload=b"body")

        await cached_fetch("page", "https://example.com/a", produce)
        await cached_fetch("pdf", "https://example.com/paper.pdf", produce)

        assert store.clear("page") == 1
        assert [entry.namespace for entry in store.entries()] == ["pdf"]

    async def test_clearing_everything_empties_the_directory(self) -> None:
        store = cache()

        async def produce() -> Fetched:
            return Fetched(payload=b"body")

        await cached_fetch("page", "https://example.com/a", produce)
        await cached_fetch("pdf", "https://example.com/paper.pdf", produce)

        assert store.clear() == 2
        assert store.entries() == []

    def test_a_cache_that_was_never_written_reports_nothing(self) -> None:
        assert cache().entries() == []
