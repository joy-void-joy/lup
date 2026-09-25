"""A model never travels without the reasoning effort that goes with it.

The home a Codex session opens against is seeded from the operator's own
configuration, so it holds the model *they* chose and the effort they chose for
it. Naming only the model therefore did not select a model: it selected half of
somebody else's pair, and the API was the first thing to notice — a 400 before
the turn did anything, naming neither the home nor the caller.

Measured rather than imagined: this repository's scoped home carries
`model_reasoning_effort = "max"`, and every arm of the Codex approval probe
died with `'max' is not supported with the 'gpt-5.5' model`.
"""

from pathlib import Path

from lup.providers.codex import Codex

CWD = Path("/repo")


def test_naming_neither_sends_the_default_effort_over_the_homes_model() -> None:
    """An inherited model has no catalog row, so its default is ``xhigh``."""
    assert Codex(cwd=CWD).model_selection() == {"effort": "xhigh"}


def test_a_named_model_never_travels_without_an_effort() -> None:
    """The defect itself.

    Before this, only the model went and the home's effort rode beside it —
    a pair nobody chose and neither side could be blamed for.
    """
    selected = Codex(cwd=CWD, model="gpt-5.5").model_selection()

    assert selected == {"model": "gpt-5.5", "effort": "xhigh"}


def test_the_callers_own_effort_wins_over_the_default() -> None:
    """A caller who knows what their model should spend is never second-guessed."""
    selected = Codex(cwd=CWD, model="gpt-5.5", effort="high").model_selection()

    assert selected == {"model": "gpt-5.5", "effort": "high"}


def test_a_forwarded_none_still_pairs_the_default() -> None:
    """A caller passing an unset setting through gets the default, not no effort."""
    selected = Codex(cwd=CWD, model="gpt-5.5", effort=None).model_selection()

    assert selected == {"model": "gpt-5.5", "effort": "xhigh"}


def test_an_effort_alone_still_travels_alone() -> None:
    """Asking for effort over the home's own model is a coherent thing to want.

    Only the reverse direction was broken: an effort names no model, so nothing
    about it can disagree with one.
    """
    selected = Codex(cwd=CWD, effort="low").model_selection()

    assert selected == {"effort": "low"}


def test_the_pair_that_broke_the_probe_can_no_longer_be_assembled() -> None:
    """The regression, stated as the thing that actually happened.

    The home said `max`, the caller said `gpt-5.5`, and the API refused the two
    together. Whatever a home now holds, a named model carries an effort the
    caller or this default chose, so the home's cannot reach the wire beside a
    model it never saw.
    """
    selected = Codex(cwd=CWD, model="gpt-5.5").model_selection()

    assert "effort" in selected
    assert selected["effort"] != "max"
