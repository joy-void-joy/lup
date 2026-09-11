"""Resilience primitives for calling flaky or rate-limited services.

`throttle` bounds concurrency and enforces a minimum interval between calls
inside one event loop; `budget` counts requests per key across every process
sharing a directory, so a rate an operator is owed is kept by a repository
rather than by each of its sessions; `retry` re-runs a coroutine with
exponential backoff on transient failures.
"""
