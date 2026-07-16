"""Portable usage arithmetic and pricing, independent from native adapters."""

from lup.types import Usage, UsageCost


def per_mtok_usage_cost(
    *,
    input_usd: float,
    output_usd: float,
    cached_input_usd: float | None = None,
) -> UsageCost:
    """Build a usage estimator from prices per million tokens."""

    def cost(usage: Usage) -> float:
        cached = usage.cache_read_input_tokens
        uncached = max(usage.input_tokens - cached, 0)
        cached_rate = input_usd if cached_input_usd is None else cached_input_usd
        return (
            uncached * input_usd
            + cached * cached_rate
            + usage.output_tokens * output_usd
        ) / 1_000_000

    return cost
