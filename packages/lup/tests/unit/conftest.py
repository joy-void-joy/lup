# Test fixtures and assertions construct these shapes deliberately.
"""Shared fixtures and fakes for unit tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from lup.workspace import paths
from lup.providers.codex.login import CODEX_HOME
from lup.providers.codex.native_tools import CodexNativeTools
import lup.providers.codex.selection as codex_selection
from tests.unit.doubles import FakeAppServer

LUP_PROJECT_VERSION = "1.2.3"


@pytest.fixture(autouse=True)
def bundled_model_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opening a session reads the model catalog from the vendor's own binary.

    No unit test owns a real Codex, so each would shell out to a path its own
    fixture invented. A test about the catalog overrides this with its own.
    """
    monkeypatch.setattr(
        CodexNativeTools,
        "model_catalog",
        lambda self, executable, environment, model: {"models": [{"slug": "known"}]},
    )


@pytest.fixture
def tmp_lup_project(tmp_path: Path) -> Iterator[Path]:
    """A throwaway project root wired into lup.workspace.paths, restored afterwards."""
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.lup]\nagent_version = "{LUP_PROJECT_VERSION}"\n', encoding="utf-8"
    )
    old_root = paths.project_root()
    paths.configure(root=tmp_path)
    yield tmp_path
    paths.configure(root=old_root)


@pytest.fixture
def fake_app_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeAppServer:
    """A scriptable app-server child, rooted in this test's temporary directory."""
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv(CODEX_HOME, str(home))
    monkeypatch.setattr(codex_selection, "project_root", lambda: tmp_path)
    return FakeAppServer(root=tmp_path)
