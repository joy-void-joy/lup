"""What a run already downloaded, kept for the run that follows it.

A pipeline that ingests the same conversation, paper, and reference pages every
time it runs pays for them every time it runs — the same multi-megabyte PDF,
the same snapshot, fetched again because nothing on disk answered for them.
Writing the result somewhere is not enough on its own: a directory scoped to
one run cannot be consulted by the next, and a store keyed by anything other
than the request cannot say whether what it holds is the thing being asked for.

This is the store a fetcher consults first. It is keyed by the request, it
lives outside any one run's directory, and it is old enough to refuse. What it
holds is the *raw* payload rather than anything extracted from it, so changing
how a page is parsed re-parses what is already on disk instead of downloading
it again.

Failures are never cached. A run that could not reach a host has learned
nothing about the host, and a cached error would outlive the outage that
produced it. Serving a stale payload when a refetch fails is the opposite
trade and the useful one: that payload was real once, and the record says it
is stale so a caller can say so too.
"""

import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from lup.workspace.content_safety import slugify_label
from lup.workspace.paths import fetch_cache_path

logger = logging.getLogger(__name__)


class Fetched(BaseModel, frozen=True):
    """What a producer hands back once it has actually gone and got the thing."""

    payload: bytes = Field(description="The bytes the fetch returned, unparsed")
    content_type: str = Field(
        default="",
        description="What the server called them, empty where it said nothing",
    )


class CacheEntry(BaseModel, frozen=True):
    """The record written beside a cached payload, saying what it is."""

    key: str = Field(description="The request identity this payload answers for")
    namespace: str = Field(description="Which kind of fetch produced it")
    content_type: str = Field(default="", description="As the server declared it")
    fetched_at: datetime = Field(description="When the fetch that produced it returned")

    def age(self) -> timedelta:
        """How long ago this payload was fetched."""
        return datetime.now(UTC) - self.fetched_at

    def expired(self, ttl: timedelta) -> bool:
        """Whether this payload has stopped answering for its request."""
        return self.age() > ttl


class EntryPaths(BaseModel, frozen=True):
    """Where one cached request's two files sit."""

    payload: Path = Field(description="The bytes as they arrived")
    record: Path = Field(description="The JSON record describing them")


class CachedFetch(BaseModel, frozen=True):
    """A payload the cache answered with, and whether it is known to be current."""

    entry: CacheEntry
    path: Path = Field(description="Where the payload sits on disk")
    stale: bool = Field(
        default=False,
        description="True when no successful fetch stands behind this payload — "
        "it is past its lifetime, or it was served because a refetch failed",
    )

    def payload(self) -> bytes:
        """The cached bytes."""
        return self.path.read_bytes()

    def text(self, encoding: str = "utf-8") -> str:
        """The cached bytes as text, replacing anything that will not decode."""
        return self.path.read_text(encoding=encoding, errors="replace")


class FetchCache(BaseModel):
    """A directory of fetched payloads, each keyed by the request that got it."""

    directory: Path = Field(description="Where payloads and their records live")
    ttl: timedelta = Field(
        default=timedelta(days=7),
        description="How long a payload answers for its request before it is "
        "fetched again. The caller's judgement: source documents change over "
        "weeks, a price feed is stale in minutes",
    )
    stale_on_error: bool = Field(
        default=True,
        description="Whether a failed refetch falls back to the expired payload "
        "rather than raising. A degraded answer beats none for a document that "
        "was real when it was fetched",
    )
    digest_chars: int = Field(
        default=16,
        description="How much of the key's digest names its files — enough that "
        "a collision is unimaginable, short enough to read in a directory listing",
    )

    def located(self, namespace: str, key: str) -> EntryPaths:
        """Where this request's payload and record belong.

        The digest is what makes the lookup exact; the slug in front of it is
        for whoever opens the directory, and carries no meaning the lookup
        depends on.
        """
        identity = f"{namespace}\x00{key}".encode()
        digest = hashlib.sha256(identity).hexdigest()[: self.digest_chars]
        slug = slugify_label(key)
        name = f"{namespace}-{slug}-{digest}" if slug else f"{namespace}-{digest}"
        return EntryPaths(
            payload=self.directory / f"{name}.payload",
            record=self.directory / f"{name}.json",
        )

    def loaded(self, record: Path) -> CacheEntry | None:
        """The record at this path, or nothing when it cannot be read.

        A cache is an optimisation, so a record left half-written by an
        interrupted run is a miss rather than a failure: it is logged, and the
        refetch that follows overwrites it.
        """
        try:
            return CacheEntry.model_validate_json(record.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            logger.warning(
                "Unreadable cache record %s (%s) — refetching", record.name, exc
            )
            return None

    def remembered(self, namespace: str, key: str) -> CachedFetch | None:
        """What this cache holds for the request, at any age."""
        located = self.located(namespace, key)
        if not located.payload.exists():
            return None
        entry = self.loaded(located.record)
        if entry is None:
            return None
        return CachedFetch(
            entry=entry, path=located.payload, stale=entry.expired(self.ttl)
        )

    def store(self, namespace: str, key: str, fetched: Fetched) -> CachedFetch:
        """Write a payload and its record, and describe what was written."""
        located = self.located(namespace, key)
        self.directory.mkdir(parents=True, exist_ok=True)
        located.payload.write_bytes(fetched.payload)
        entry = CacheEntry(
            key=key,
            namespace=namespace,
            content_type=fetched.content_type,
            fetched_at=datetime.now(UTC),
        )
        located.record.write_text(entry.model_dump_json(indent=2), encoding="utf-8")
        return CachedFetch(entry=entry, path=located.payload)

    async def through(
        self,
        namespace: str,
        key: str,
        produce: Callable[[], Awaitable[Fetched]],
        *,
        refresh: bool = False,
    ) -> CachedFetch:
        """Answer from the cache, and only fetch when it cannot.

        The one call a fetcher makes: *produce* is whatever it was going to do
        anyway — an HTTP GET, a GraphQL POST, an API call — and runs only when
        this cache has nothing current. That is why the cache knows nothing
        about HTTP: the call sites that need it do not agree on a protocol.
        """
        held = self.remembered(namespace, key)
        if held is not None and not held.stale and not refresh:
            logger.debug("Cache hit for %s (%s)", key, namespace)
            return held

        try:
            return self.store(namespace, key, await produce())
        except Exception as exc:
            if held is None or not self.stale_on_error:
                raise
            logger.warning(
                "Fetch failed for %s (%s) — serving the copy cached %s ago",
                key,
                exc,
                held.entry.age(),
            )
            return held.model_copy(update={"stale": True})

    def entries(self) -> list[CacheEntry]:
        """Every readable record this cache holds, for a caller reporting on it."""
        if not self.directory.exists():
            return []
        return [
            entry
            for record in sorted(self.directory.glob("*.json"))
            if (entry := self.loaded(record)) is not None
        ]

    def discard(self, entry: CacheEntry) -> None:
        """Remove one cached payload and its record."""
        located = self.located(entry.namespace, entry.key)
        located.payload.unlink(missing_ok=True)
        located.record.unlink(missing_ok=True)

    def clear(self, namespace: str = "") -> int:
        """Remove what this cache holds, and say how many entries went.

        An empty *namespace* clears everything, which is what a caller with one
        cache and one clear command wants.
        """
        chosen = [
            entry
            for entry in self.entries()
            if not namespace or entry.namespace == namespace
        ]
        for entry in chosen:
            self.discard(entry)
        return len(chosen)


class FetchCacheState(BaseModel):
    """Holder for the resolved cache, mutated in place.

    Accessors and :func:`configure` share this one instance and assign its
    ``cache`` attribute instead of rebinding a module global.
    """

    cache: FetchCache | None = None


state = FetchCacheState()


def resolve_state() -> FetchCache:
    """The configured cache, defaulting its directory on first use."""
    cache = state.cache
    if cache is None:
        cache = FetchCache(directory=fetch_cache_path())
        state.cache = cache
    return cache


def configure(
    *,
    directory: Path | None = None,
    ttl: timedelta | None = None,
    stale_on_error: bool | None = None,
) -> None:
    """Override where fetched payloads are kept and how long they answer for.

    Args:
        directory: Where payloads land. Defaults to ``<root>/.cache/fetch``.
        ttl: How long a payload answers for its request. An application whose
            sources change faster than the default assumes says so here.
        stale_on_error: Whether a failed refetch falls back to what is held.
    """
    current = resolve_state()
    state.cache = FetchCache(
        directory=directory if directory is not None else current.directory,
        ttl=ttl if ttl is not None else current.ttl,
        stale_on_error=(
            stale_on_error if stale_on_error is not None else current.stale_on_error
        ),
        digest_chars=current.digest_chars,
    )


async def cached_fetch(
    namespace: str,
    key: str,
    produce: Callable[[], Awaitable[Fetched]],
    *,
    refresh: bool = False,
) -> CachedFetch:
    """Answer *key* from the configured cache, fetching only when it cannot.

    The entry point a fetcher calls, so that consulting the cache is one line
    at the site that would otherwise go straight to the network::

        cached = await cached_fetch(
            "page", url, lambda: Fetched(payload=..., content_type=...)
        )

    Args:
        namespace: Which kind of fetch this is, so one cache can hold several
            and a caller can clear or report on them separately.
        key: What identifies the request — a URL, or whatever else names it.
        produce: The fetch itself, run only on a miss.
        refresh: Fetch even when something current is held.
    """
    return await resolve_state().through(namespace, key, produce, refresh=refresh)
