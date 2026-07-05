"""Barrel drift guard: every name in lup.__all__ must resolve."""

import lup


def test_every_export_resolves() -> None:
    missing = [name for name in lup.__all__ if getattr(lup, name, None) is None]
    assert missing == []


def test_sandbox_resolves_lazily() -> None:
    from lup.sandbox.container import Sandbox

    assert lup.Sandbox is Sandbox


def test_unknown_attribute_raises() -> None:
    try:
        lup.does_not_exist  # noqa: B018
    except AttributeError as e:
        assert "does_not_exist" in str(e)
    else:
        raise AssertionError("expected AttributeError")
