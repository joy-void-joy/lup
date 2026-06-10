"""with_retry behavior: retries, exhaustion, and selectivity."""

import pytest

from lup.retry import with_retry


async def test_retries_then_succeeds() -> None:
    calls = {"n": 0}

    @with_retry(
        max_attempts=3, min_wait=0.01, max_wait=0.02, extra_exceptions=(ValueError,)
    )
    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return "ok"

    assert await flaky() == "ok"
    assert calls["n"] == 3


async def test_reraises_after_exhausting_attempts() -> None:
    calls = {"n": 0}

    @with_retry(
        max_attempts=2, min_wait=0.01, max_wait=0.02, extra_exceptions=(ValueError,)
    )
    async def always_fails() -> str:
        calls["n"] += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError, match="permanent"):
        await always_fails()
    assert calls["n"] == 2


async def test_unlisted_exceptions_are_not_retried() -> None:
    calls = {"n": 0}

    @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02)
    async def hard_failure() -> str:
        calls["n"] += 1
        raise KeyError("not retryable")

    with pytest.raises(KeyError):
        await hard_failure()
    assert calls["n"] == 1
