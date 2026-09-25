"""Which runtime's own catalog lists a model name.

The question a composition asks when all it holds is a model id: a name one
catalog lists is that runtime's, and a name neither lists is nobody's to
guess at.
"""

from lup.providers.routing import catalog_provider


def test_a_catalog_alias_routes_without_a_vendor_prefix() -> None:
    """``opus`` names no vendor in its spelling; the catalog listing it does."""
    assert catalog_provider("opus") == "claude"
    assert catalog_provider("fable") == "claude"
    assert catalog_provider("gpt-6-astra") == "codex"
    assert catalog_provider("llama-3") is None
