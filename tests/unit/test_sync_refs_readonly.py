"""A `refs/` shortcut that cannot move is reported, and the sync goes on.

A contained session holds `refs/` read-only so a session cannot repoint what
confines it. Every materialization re-points `refs/<name>` at the project's
current path, so where the registered path and the standing link differed the
whole sync family aborted on the unlink before it had fetched anything -- and
`sync mark-synced` with it, which is the step that closes an update out. The
link is a convenience and nothing a fetch depends on.
"""

import logging
from pathlib import Path

import pytest

from lup.devtools import sync


def test_a_link_that_cannot_move_is_named_and_the_call_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    refs = tmp_path / "refs"
    refs.mkdir()
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    (refs / "lup").symlink_to(tmp_path / "old")
    monkeypatch.setattr(sync, "refs_dir", lambda: refs)
    refs.chmod(0o555)
    try:
        with caplog.at_level(logging.WARNING):
            sync.ensure_ref_symlink("lup", str(tmp_path / "new"))
    finally:
        refs.chmod(0o755)

    assert (refs / "lup").resolve() == (tmp_path / "old").resolve()
    assert "refs/lup could not be pointed" in caplog.text


def test_a_link_that_can_move_is_moved_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    refs = tmp_path / "refs"
    refs.mkdir()
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    (refs / "lup").symlink_to(tmp_path / "old")
    monkeypatch.setattr(sync, "refs_dir", lambda: refs)

    with caplog.at_level(logging.WARNING):
        sync.ensure_ref_symlink("lup", str(tmp_path / "new"))

    assert (refs / "lup").resolve() == (tmp_path / "new").resolve()
    assert caplog.text == ""
