"""Codex usage normalization and cost estimation.

The runtime reports token counts, never cost — budget enforcement needs
the caller to supply pricing (:func:`per_mtok_usage_cost`), and each
turn's raw ``ThreadTokenUsage`` normalizes into portable counts through
:func:`codex_usage_to_lup`.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from lup.types import Usage, UsageCost

if TYPE_CHECKING:
    import openai_codex.generated.v2_all as codex_items

type CodexUsageNormalizer = Callable[["codex_items.ThreadTokenUsage"], Usage | None]
"""Transforms the Codex SDK usage object into a (subclass of) Usage."""


def per_mtok_usage_cost(
    *,
    input_usd: float,
    output_usd: float,
    cached_input_usd: float | None = None,
) -> UsageCost:
    """Build a usage→USD estimator from per-million-token rates.

    The Codex runtime reports token counts, never cost — budget
    enforcement needs the caller to supply pricing. Cached input tokens
    are treated as a subset of ``input_tokens`` (OpenAI-style usage
    reporting); when ``cached_input_usd`` is given, that subset is
    billed at the cached rate instead of the input rate.
    """

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


def codex_usage_to_lup(usage: "codex_items.ThreadTokenUsage") -> Usage | None:
    """Default Codex usage normalizer — portable token counts only."""
    total = usage.total
    return Usage(
        input_tokens=total.input_tokens,
        output_tokens=total.output_tokens,
        cache_read_input_tokens=total.cached_input_tokens,
    )
