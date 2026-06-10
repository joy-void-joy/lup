"""Session storage round-trip through the versioned notes layout."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel

from lup.history import iter_session_dirs, load_sessions_json, save_session
from lup.paths import configure, project_root

ORIGINAL_ROOT = project_root()


class DemoResult(BaseModel):
    session_id: str
    value: int


@pytest.fixture
def isolated_root(tmp_path: Path) -> Iterator[Path]:
    configure(root=tmp_path, version="1.2.3")
    yield tmp_path
    configure(root=ORIGINAL_ROOT)


class TestSessionRoundTrip:
    def test_save_then_load_through_versioned_layout(self, isolated_root: Path) -> None:
        saved_path = save_session(
            DemoResult(session_id="s1", value=42), session_id="s1"
        )

        assert saved_path.is_relative_to(
            isolated_root / "notes" / "traces" / "1.2.3" / "sessions" / "s1"
        )
        loaded = load_sessions_json("s1")
        assert len(loaded) == 1
        assert loaded[0]["value"] == 42

    def test_iter_session_dirs_filters_by_session(self, isolated_root: Path) -> None:
        save_session(DemoResult(session_id="a", value=1), session_id="a")
        save_session(DemoResult(session_id="b", value=2), session_id="b")

        dirs = list(iter_session_dirs(session_id="a"))
        assert [d.name for d in dirs] == ["a"]

        all_dirs = {d.name for d in iter_session_dirs()}
        assert all_dirs == {"a", "b"}

    def test_load_missing_session_returns_empty(self, isolated_root: Path) -> None:
        assert load_sessions_json("ghost") == []
