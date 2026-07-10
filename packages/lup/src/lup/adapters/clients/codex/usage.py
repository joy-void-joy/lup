"""Codex usage normalization.

The runtime reports token counts, never cost — budget enforcement needs
the caller to supply pricing (the shared
:func:`lup.adapters.clients.usage.per_mtok_usage_cost`), and each turn's
raw ``ThreadTokenUsage`` normalizes into portable counts through
:func:`codex_usage_to_lup`.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from lup.types import Usage

if TYPE_CHECKING:
    import openai_codex.generated.v2_all as codex_items

type CodexUsageNormalizer = Callable[["codex_items.ThreadTokenUsage"], Usage | None]
"""Transforms the Codex SDK usage object into a (subclass of) Usage."""


def codex_usage_to_lup(usage: "codex_items.ThreadTokenUsage") -> Usage | None:
    """Default Codex usage normalizer — portable token counts only."""
    total = usage.total
    return Usage(
        input_tokens=total.input_tokens,
        output_tokens=total.output_tokens,
        cache_read_input_tokens=total.cached_input_tokens,
    )
