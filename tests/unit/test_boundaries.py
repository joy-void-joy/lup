"""Seam-boundary scan behavior: what breaches, what is sanctioned, what escapes.

The scan (:mod:`lup.codescan.boundaries`) is the regression guard that keeps
per-engine adapter imports from creeping outside ``lup.adapters``; the final
test pins the live tree at zero breaches.
"""

from pathlib import Path

from lup.codescan.boundaries import find_boundary_breaches, path_is_sanctioned

from lup_template.devtools.dev.boundaries import scan_boundaries

BREACHING = "from lup.adapters.clients.claude.sessions import ClaudeSessions\n"


def test_per_engine_imports_breach() -> None:
    text = (
        "import lup.adapters.background.codex\n"
        "from lup.adapters.clients.codex.native import CodexNativeConfig\n"
        "from lup.adapters.profiles.claude.store import ProfileStore\n"
        "from lup.adapters.tools.claude import CLAUDE_BUILTIN_TOOLS\n"
    )
    breaches = find_boundary_breaches(text)
    assert [breach.line for breach in breaches] == [1, 2, 3, 4]
    assert breaches[0].module == "lup.adapters.background.codex"


def test_seam_surface_does_not_breach() -> None:
    text = (
        "from lup.adapters.wiring import create_client\n"
        "from lup.adapters.engines.claude import ClaudeEngine\n"
        "from lup.adapters.clients.composed import ComposedClient\n"
        "from lup.adapters.clients.sessions.Session import Session\n"
        "from lup.adapters.tools.names import BASH\n"
    )
    assert not find_boundary_breaches(text)


def test_inline_ignore_excepts_the_line() -> None:
    ignored = BREACHING.rstrip() + "  # lup: ignore[seam-boundary]\n"
    assert not find_boundary_breaches(ignored)

    bare = BREACHING.rstrip() + "  # lup: ignore\n"
    assert not find_boundary_breaches(bare)

    other_rule = BREACHING.rstrip() + "  # lup: ignore[cast]\n"
    assert len(find_boundary_breaches(other_rule)) == 1


def test_file_level_ignore_excepts_the_file() -> None:
    typed = "# lup: ignore[seam-boundary]\n" + BREACHING
    assert not find_boundary_breaches(typed)

    bare = "# lup: ignore\n" + BREACHING
    assert not find_boundary_breaches(bare)

    other_rule = "# lup: ignore[cast]\n" + BREACHING
    assert len(find_boundary_breaches(other_rule)) == 1


def test_sanctioned_paths() -> None:
    assert path_is_sanctioned(
        Path("packages/lup/src/lup/adapters/clients/claude/create.py")
    )
    assert path_is_sanctioned(Path("tests/unit/test_engines.py"))
    assert not path_is_sanctioned(Path("src/lup_template/agent/core.py"))
    assert not path_is_sanctioned(Path("packages/lup/src/lup/subagents.py"))


def test_live_tree_has_zero_breaches() -> None:
    assert scan_boundaries() == []
