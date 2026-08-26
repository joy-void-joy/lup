"""Routing a model id to the provider that serves it.

The convenience over the two named constructors, for a caller who has a model
and does not also want to know which vendor owns which prefix. What it may not
do is guess: opening a session against the wrong vendor fails downstream in
that vendor's vocabulary, which is a worse error arriving later.
"""

import subprocess
import sys

import pytest

from lup import create_client
from lup.providers.routing import (
    PROVIDER_ROUTES,
    PrefixModelMatcher,
    ProviderRoute,
    provider_for,
)
from lup.sessions.client import Client


def test_each_vendors_prefixes_reach_its_own_provider() -> None:
    assert provider_for("claude-opus-5") == "claude"
    assert provider_for("gpt-5.5") == "codex"
    assert provider_for("o3-mini") == "codex"


def test_the_route_declared_first_wins() -> None:
    """Declaration order, which is the rule `ModelRouter` reads its own routes by.

    A narrower entry earns its answer by being written above a broader one. The
    table this replaced was a mapping sorted by prefix length, which put the
    rule somewhere no reader of the declaration could see it; a list puts the
    ordering on the page, where an adopter writing `gpt-5.5-local` above `gpt-`
    can tell what they have said.
    """
    routes = [
        ProviderRoute(provider="claude", matcher=PrefixModelMatcher("gpt-5.5-local")),
        ProviderRoute(provider="codex", matcher=PrefixModelMatcher("gpt-")),
    ]

    assert provider_for("gpt-5.5-local-preview", routes) == "claude"
    assert provider_for("gpt-4o", routes) == "codex"


def test_a_broader_route_written_first_shadows_the_narrower_one() -> None:
    """The other half of declaration order, stated so nobody has to discover it."""
    shadowed = [
        ProviderRoute(provider="codex", matcher=PrefixModelMatcher("gpt-")),
        ProviderRoute(provider="claude", matcher=PrefixModelMatcher("gpt-5.5-local")),
    ]

    assert provider_for("gpt-5.5-local-preview", shadowed) == "codex"


def test_a_model_nothing_claims_names_what_it_knows() -> None:
    """Raised rather than guessed, and the message carries the way forward."""
    with pytest.raises(LookupError) as raised:
        create_client("llama-3")

    assert "llama-3" in str(raised.value)
    assert "provider=" in str(raised.value)
    assert "claude" in str(raised.value)


def test_naming_the_provider_skips_the_table_entirely() -> None:
    """The escape hatch for an id no prefix claims, and for a proxied endpoint.

    A local gateway serving Claude under its own model name is the ordinary
    case: the id says nothing about the vendor, and the caller does.
    """
    client = create_client(
        "some-internal-name",
        provider="claude",
        base_url="http://localhost:4000",
    )

    assert isinstance(client, Client)


def test_routing_builds_a_client_for_either_vendor() -> None:
    assert isinstance(create_client("claude-opus-5"), Client)
    assert isinstance(create_client("gpt-5.5"), Client)


def test_routing_to_one_vendor_leaves_the_other_adapter_unloaded() -> None:
    """Per-call imports, for the reason the package root defers its own.

    An adapter reaches its provider's whole tool ecosystem, so a caller who
    routed to one should not pay for the other. Asked in its own interpreter
    because `sys.modules` in this one carries whatever every earlier test
    imported, which would make the assertion about the test run.
    """
    reported = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from lup import create_client; "
            "create_client('claude-opus-5'); "
            "print('lup.providers.codex.runtime' in sys.modules, "
            "'claude_agent_sdk' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert reported == "False False"


def test_the_shipped_routes_cover_both_constructors() -> None:
    """Routes naming one vendor would send everything to it silently."""
    assert {route.provider for route in PROVIDER_ROUTES} == {"claude", "codex"}
