"""Behavior tests for Settings env parsing (agent/config.py)."""

from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict

from lup_template.agent.config import Settings


class EnvOnlySettings(Settings):
    """Settings variant that ignores .env files — process env vars only."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def test_extra_dirs_parses_path_style_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_EXTRA_DIRS", "/data/reference:/home/u/transcripts")
    assert EnvOnlySettings().extra_dirs == [
        Path("/data/reference"),
        Path("/home/u/transcripts"),
    ]


def test_extra_dirs_defaults_empty_and_skips_blank_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_EXTRA_DIRS", raising=False)
    assert EnvOnlySettings().extra_dirs == []

    monkeypatch.setenv("AGENT_EXTRA_DIRS", "/only:")
    assert EnvOnlySettings().extra_dirs == [Path("/only")]
