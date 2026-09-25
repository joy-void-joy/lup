"""Reasoning effort, asked for portably and rendered by each runtime.

The failure this guards against is silent: both adapters already carried an
``effort`` field and both already passed it to their provider, but a
:class:`~lup.providers.selection.SessionRequest` had no word for it, so an
application that set one watched it reach nothing and got whatever the
runtime's own configuration file happened to say. Nothing raised, and the
value a session actually ran at was only discoverable by reading the provider
call. Each rung is pinned here because a collapse of one rung into another is
exactly the substitution that would otherwise go unnoticed.
"""

from pathlib import Path
from typing import get_args

import pytest

from lup.providers.claude.models import ClaudeEffort
from lup.providers.claude.selection import CLAUDE_EFFORT, claude_config
from lup.providers.codex.models import CodexEffort
from lup.providers.codex.selection import CODEX_EFFORT, codex_config
from lup.providers.selection import SessionEffort, SessionRequest

EVERY_DEGREE: list[SessionEffort] = list(get_args(SessionEffort.__value__))


def test_a_request_naming_no_effort_leaves_both_runtimes_unset() -> None:
    """Absence has to stay absent, or every session gains an opinion."""
    request = SessionRequest(cwd=Path("."))

    assert claude_config(request).effort is None
    assert codex_config(request).effort is None


@pytest.mark.parametrize("degree", EVERY_DEGREE)
def test_every_degree_reaches_both_runtimes_under_its_own_name(
    degree: SessionEffort,
) -> None:
    """Both catalogs list every portable rung, so neither may reinterpret one."""
    request = SessionRequest(cwd=Path("."), effort=degree)

    assert claude_config(request).effort == degree
    assert codex_config(request).effort == degree
    assert CLAUDE_EFFORT[degree] == degree
    assert CODEX_EFFORT[degree] == degree


def test_the_portable_ladder_is_the_rungs_both_catalogs_share() -> None:
    """A rung only one runtime lists would be narrowed on the other in silence."""
    shared = set(get_args(ClaudeEffort.__value__)) & set(
        get_args(CodexEffort.__value__)
    )
    assert set(EVERY_DEGREE) == shared


def test_neither_map_leaves_a_degree_unanswered() -> None:
    """A degree added to the portable ladder is a degree both must render."""
    assert sorted(CLAUDE_EFFORT) == sorted(EVERY_DEGREE)
    assert sorted(CODEX_EFFORT) == sorted(EVERY_DEGREE)


def test_nothing_below_low_is_offered() -> None:
    """``none`` and ``minimal`` left Codex's catalog; neither may linger here."""
    assert "none" not in EVERY_DEGREE
    assert "minimal" not in EVERY_DEGREE


def test_ultra_is_the_top_of_the_portable_ladder() -> None:
    """Asking for the ceiling has to land on a ceiling, not near one."""
    request = SessionRequest(cwd=Path("."), effort="ultra")

    assert EVERY_DEGREE[-1] == "ultra"
    assert claude_config(request).effort == "ultra"
    assert codex_config(request).effort == "ultra"
