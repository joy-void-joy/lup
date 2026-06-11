"""Path resolution, lazy root detection, and access-control helpers."""

from collections.abc import Iterator
from pathlib import Path

import pytest

import lup.paths as paths
from lup.paths import extract_glob_dir, path_is_under


@pytest.fixture
def restore_path_globals() -> Iterator[None]:
    """Snapshot and restore the lazily-populated path globals."""
    saved = {name: paths.__dict__.get(name) for name in paths.PATH_GLOBALS}
    had = {name: name in paths.__dict__ for name in paths.PATH_GLOBALS}
    yield
    for name in paths.PATH_GLOBALS:
        if had[name]:
            paths.__dict__[name] = saved[name]
        else:
            paths.__dict__.pop(name, None)


def test_root_detection_is_deferred(
    restore_path_globals: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing touches the globals until an accessor is called.

    The whole point of lazy init: importing lup must not run root detection,
    so the package imports even when installed outside a [tool.lup] tree.
    """
    for name in paths.PATH_GLOBALS:
        paths.__dict__.pop(name, None)

    calls = {"n": 0}
    real_root = paths.find_project_root()

    def counting_root() -> Path:
        calls["n"] += 1
        return real_root

    monkeypatch.setattr(paths, "find_project_root", counting_root)

    # Accessing nothing keeps detection at zero.
    assert calls["n"] == 0
    # First accessor triggers exactly one detection; the result is memoized.
    assert paths.agent_version()
    assert paths.project_root() == real_root
    assert calls["n"] == 1


def test_configure_version_only_keeps_root(restore_path_globals: None) -> None:
    """A version-only override must not be clobbered by later detection."""
    for name in paths.PATH_GLOBALS:
        paths.__dict__.pop(name, None)
    paths.configure(version="9.9.9")
    # The version override survives, and base paths still resolve.
    assert paths.agent_version() == "9.9.9"
    assert paths.sessions_dir().name == "sessions"
    assert paths.sessions_dir().parent.name == "9.9.9"


def test_path_is_under_rejects_outside(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    assert path_is_under(allowed / "child.json", [allowed])
    assert path_is_under(allowed / "deep" / "child.json", [allowed])
    assert not path_is_under(tmp_path / "sibling.json", [allowed])


def test_path_is_under_blocks_traversal(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    escape = allowed / ".." / "secret.json"
    assert not path_is_under(escape, [allowed])


def test_extract_glob_dir() -> None:
    assert extract_glob_dir("/tmp/foo/**/*.py") == "/tmp/foo"
    assert extract_glob_dir("**/*.py") == ""
    assert extract_glob_dir("/tmp/foo/bar") == "/tmp/foo/bar"
    assert extract_glob_dir("/a/b/*.txt") == "/a/b"
    assert extract_glob_dir("/a/[abc].py") == "/a"
