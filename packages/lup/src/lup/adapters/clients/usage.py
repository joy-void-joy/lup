"""Usage normalization: native usage payloads into portable ``Usage`` counts.

Usage is diagnostic — a broken normalizer must never fail a run that
already completed, so engines run theirs through
:func:`safe_normalize_usage`, and engines whose raw payload is a plain
mapping use :func:`extract_token_usage` as the normalizer itself.
"""

import logging
from collections.abc import Callable, Mapping

from pydantic import ValidationError

from lup.types import JsonValue, Usage

logger = logging.getLogger(__name__)


def extract_token_usage(raw: Mapping[str, JsonValue] | None) -> Usage | None:
    """Extract portable token counts from a raw vendor usage mapping.

    Reads only the known count fields and ignores vendor extras, so
    payload growth in any SDK can never fail a completed run. Default
    normalizer for adapters whose raw payload is a mapping.
    """
    if not raw:
        return None

    def count(key: str) -> int:
        value = raw.get(key)
        return value if isinstance(value, int) else 0

    return Usage(
        input_tokens=count("input_tokens"),
        output_tokens=count("output_tokens"),
        cache_read_input_tokens=count("cache_read_input_tokens"),
        cache_creation_input_tokens=count("cache_creation_input_tokens"),
    )


def safe_normalize_usage[T](
    normalizer: Callable[[T], Usage | None],
    raw: T | None,
) -> Usage | None:
    """Run a usage normalizer, degrading to None on failure.

    Usage is diagnostic — a broken normalizer must never fail a run that
    already completed. Failures are logged loudly and dropped.
    """
    if raw is None:
        return None
    try:
        return normalizer(raw)
    except (ValidationError, KeyError, TypeError, AttributeError):
        name = getattr(normalizer, "__name__", repr(normalizer))
        logger.exception("Usage normalizer %s failed; dropping usage", name)
        return None
