"""Routing a model id to the provider that serves it.

The convenience over the two named constructors, for a caller who has a model
and does not also want to know which vendor owns which prefix. What it may not
do is guess: opening a session against the wrong vendor fails downstream in
that vendor's vocabulary, which is a worse error arriving later.
"""

import subprocess
import sys
from collections.abc import Mapping

import pytest

from lup.client import (
    PROVIDER_PREFIXES,
    Client,
    Provider,
    create_client,
    provider_for,
)


def test_each_vendors_prefixes_reach_its_own_provider() -> None:
    assert provider_for("claude-opus-5") == "claude"
    assert provider_for("gpt-5.5") == "codex"
    assert provider_for("o3-mini") == "codex"


def test_a_longer_prefix_wins_over_one_that_contains_it() -> None:
    """First match by length, so a narrower entry can sit beside a broader one.

    Iteration order over a table is not a rule anybody should have to know, and
    an adopter adding `gpt-5.5-local` beside `gpt-` means the narrower one.
    """
    prefixes: Mapping[str, Provider] = {"gpt-": "codex", "gpt-5.5-local": "claude"}

    assert provider_for("gpt-5.5-local-preview", prefixes) == "claude"
    assert provider_for("gpt-4o", prefixes) == "codex"


def test_a_model_nothing_claims_names_what_it_knows() -> None:
    """Raised rather than guessed, and the message carries the way forward."""
    with pytest.raises(LookupError) as raised:
        create_client("llama-3")

    assert "llama-3" in str(raised.value)
    assert "provider=" in str(raised.value)
    assert "claude-" in str(raised.value)


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
            "print('lup.adapters.codex.runtime' in sys.modules, "
            "'claude_agent_sdk' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert reported == "False False"


def test_the_shipped_table_covers_both_constructors() -> None:
    """A prefix table naming one vendor would route everything to it silently."""
    assert set(PROVIDER_PREFIXES.values()) == {"claude", "codex"}
