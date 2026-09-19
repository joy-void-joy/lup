"""A project that declined the resolver module declares no resolver spec."""

import pytest

import lup_template.harness.catalog as catalog
import lup_template.harness.content.catalog as content


def test_a_declined_resolver_leaves_the_harness_without_a_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The spec's three invocations name skills the declined module no longer
    declares, so a harness that still carried one would refuse to validate."""
    monkeypatch.setattr(content, "DECLINED", ["resolver"])
    monkeypatch.setattr(catalog, "MODULE_SELECTION", content.selection())

    assert catalog.portable_harness().resolver is None


def test_a_taken_resolver_still_declares_its_spec() -> None:
    spec = catalog.portable_harness().resolver
    assert spec is not None
    assert spec.worker_skill.skill == "implementer"
