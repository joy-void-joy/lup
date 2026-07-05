"""Tests for usage normalization at the adapter boundary.

Vendor usage payloads are unstable (SDKs add nested fields and strings
over releases). These tests pin the contract: normalizers extract the
portable counts, custom normalizers can carry vendor extras through
subclassing, and a broken normalizer degrades to None instead of
failing a completed run.
"""

from collections.abc import Mapping

from openai_codex.generated.v2_all import ThreadTokenUsage, TokenUsageBreakdown

from lup.adapters.clients.codex import codex_usage_to_lup
from lup.adapters.clients.common import extract_token_usage, safe_normalize_usage
from lup.types import (
    JsonValue,
    LupResultMessage,
    Usage,
)

# The shape that broke a live run: nested dicts, strings, and lists
# alongside the token counts.
CLAUDE_VENDOR_PAYLOAD: dict[str, JsonValue] = {
    "input_tokens": 12,
    "output_tokens": 941,
    "cache_read_input_tokens": 18200,
    "cache_creation_input_tokens": 310,
    "cache_creation": {
        "ephemeral_1h_input_tokens": 0,
        "ephemeral_5m_input_tokens": 310,
    },
    "service_tier": "standard",
    "inference_geo": "not_available",
    "iterations": [{"input_tokens": 1, "output_tokens": 75, "type": "message"}],
    "speed": "standard",
}


class TestExtractTokenUsage:
    def test_survives_vendor_extras(self) -> None:
        usage = extract_token_usage(CLAUDE_VENDOR_PAYLOAD)
        assert usage == Usage(
            input_tokens=12,
            output_tokens=941,
            cache_read_input_tokens=18200,
            cache_creation_input_tokens=310,
        )

    def test_non_int_counts_are_dropped_not_fatal(self) -> None:
        usage = extract_token_usage({"input_tokens": "12", "output_tokens": 5})
        assert usage is not None
        assert usage.input_tokens == 0
        assert usage.output_tokens == 5

    def test_empty_payload_returns_none(self) -> None:
        assert extract_token_usage(None) is None
        assert extract_token_usage({}) is None


class TestCustomNormalizer:
    def test_subclass_fields_survive_serialization(self) -> None:
        class RichUsage(Usage):
            service_tier: str = ""

        def rich_normalizer(raw: Mapping[str, JsonValue]) -> Usage | None:
            base = extract_token_usage(raw)
            assert base is not None
            tier = raw.get("service_tier")
            return RichUsage(
                **base.model_dump(),
                service_tier=tier if isinstance(tier, str) else "",
            )

        usage = safe_normalize_usage(rich_normalizer, CLAUDE_VENDOR_PAYLOAD)
        result = LupResultMessage(usage=usage)

        dumped = result.model_dump()["usage"]
        assert dumped is not None
        assert dumped["service_tier"] == "standard"
        assert dumped["input_tokens"] == 12

    def test_failing_normalizer_degrades_to_none(self) -> None:
        def broken(raw: Mapping[str, JsonValue]) -> Usage | None:
            raise KeyError("schema changed under us")

        assert safe_normalize_usage(broken, CLAUDE_VENDOR_PAYLOAD) is None


class TestCodexNormalizer:
    def test_maps_cached_tokens_to_cache_read(self) -> None:
        breakdown = TokenUsageBreakdown(
            cached_input_tokens=500,
            input_tokens=42,
            output_tokens=99,
            reasoning_output_tokens=10,
            total_tokens=151,
        )
        raw = ThreadTokenUsage(
            last=breakdown, total=breakdown, model_context_window=None
        )

        usage = codex_usage_to_lup(raw)
        assert usage == Usage(
            input_tokens=42,
            output_tokens=99,
            cache_read_input_tokens=500,
        )
