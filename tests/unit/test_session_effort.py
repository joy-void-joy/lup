"""Reasoning effort, asked for portably and rendered by each runtime.

The failure this guards against is silent: both adapters already carried an
``effort`` field and both already passed it to their provider, but a
:class:`~lup.providers.selection.SessionRequest` had no word for it, so an
application that set one watched it reach nothing and got whatever the
runtime's own configuration file happened to say. Nothing raised, and the
value a session actually ran at was only discoverable by reading the provider
call. Each rung is pinned here because the two ladders differ at both ends,
and a collapse at either one is exactly the substitution that would otherwise
go unnoticed.
"""

from pathlib import Path

import pytest

from lup.providers.claude.selection import CLAUDE_EFFORT, claude_config
from lup.providers.codex.selection import CODEX_EFFORT, codex_config
from lup.providers.selection import SessionEffort, SessionRequest

EVERY_DEGREE: list[SessionEffort] = [
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
]


def test_a_request_naming_no_effort_leaves_both_runtimes_unset() -> None:
    """Absence has to stay absent, or every session gains an opinion."""
    request = SessionRequest(cwd=Path("."))

    assert claude_config(request).effort is None
    assert codex_config(request).effort is None


@pytest.mark.parametrize("degree", EVERY_DEGREE)
def test_every_degree_reaches_both_runtimes(degree: SessionEffort) -> None:
    """A rung that rendered to None would be the silent fall-through itself."""
    request = SessionRequest(cwd=Path("."), effort=degree)

    assert claude_config(request).effort is not None
    assert codex_config(request).effort is not None


def test_the_shared_middle_rungs_render_unchanged() -> None:
    """Both runtimes spell these four themselves, so neither may reinterpret."""
    for degree in ("low", "medium", "high", "xhigh"):
        assert CLAUDE_EFFORT[degree] == degree
        assert CODEX_EFFORT[degree] == degree


def test_each_ladder_collapses_only_at_the_end_it_lacks() -> None:
    """The two documented narrowings, pinned so a third cannot appear quietly."""
    assert CLAUDE_EFFORT["minimal"] == "low"
    assert CODEX_EFFORT["max"] == "xhigh"

    assert CODEX_EFFORT["minimal"] == "minimal"
    assert CLAUDE_EFFORT["max"] == "max"


def test_neither_map_leaves_a_degree_unanswered() -> None:
    """A degree added to the portable ladder is a degree both must render."""
    assert sorted(CLAUDE_EFFORT) == sorted(EVERY_DEGREE)
    assert sorted(CODEX_EFFORT) == sorted(EVERY_DEGREE)


def test_the_portable_ladder_never_offers_a_rung_claude_cannot_reason_at() -> None:
    """Codex's ``none`` is withheld: on Claude it would become ``low`` in silence."""
    assert "none" not in EVERY_DEGREE
    assert "none" not in CLAUDE_EFFORT.values()
    assert "none" not in CODEX_EFFORT.values()


def test_max_effort_is_the_hardest_each_runtime_thinks() -> None:
    """Asking for the ceiling has to land on a ceiling, not near one."""
    request = SessionRequest(cwd=Path("."), effort="max")

    assert claude_config(request).effort == "max"
    assert codex_config(request).effort == "xhigh"
