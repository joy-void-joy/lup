"""Persistent conversation browser and profile lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from lup.adapters.codex.login import CODEX_LOGIN
from lup.devtools.conversation import app as conversation_app
from lup.devtools.conversation import browser
from lup.devtools.harness.composition import local_profile_directory


@pytest.mark.asyncio
async def test_login_finishes_when_the_browser_window_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = AsyncMock()
    context = AsyncMock()
    context.pages = [page]

    @asynccontextmanager
    async def opened(_directory: Path, *, headless: bool) -> AsyncIterator[AsyncMock]:
        assert not headless
        yield context

    monkeypatch.setattr(browser, "browser_context", opened)

    await browser.login(
        tmp_path / "chatgpt-web",
        "https://chatgpt.com/c/conversation-1",
        "ChatGPT",
    )

    page.goto.assert_awaited_once_with(
        "https://chatgpt.com/c/conversation-1",
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    page.wait_for_event.assert_awaited_once_with("close", timeout=0)


def test_a_named_codex_profile_keeps_chatgpt_web_state_beside_its_home(
    tmp_path: Path,
) -> None:
    profiles = local_profile_directory(tmp_path, CODEX_LOGIN)
    profile = profiles.add("work")

    directory = profiles.state_dir("work", "chatgpt-web")

    assert profile.config_dir == tmp_path / ".lup" / "profiles" / "work" / "codex-home"
    assert directory == tmp_path / ".lup" / "profiles" / "work" / "chatgpt-web"


def test_the_active_profile_supplies_browser_state_when_none_is_named(
    tmp_path: Path,
) -> None:
    profiles = local_profile_directory(tmp_path, CODEX_LOGIN)
    profiles.add("work")

    assert profiles.state_dir(None, "chatgpt-web") == (
        tmp_path / ".lup" / "profiles" / "work" / "chatgpt-web"
    )


def test_chatgpt_command_reuses_the_active_codex_profile_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profiles = local_profile_directory(tmp_path, CODEX_LOGIN)
    profiles.add("work")
    opened: list[Path] = []

    async def download(_url: str, _root: Path, directory: Path, output: Path) -> Path:
        opened.append(directory)
        destination = output / "chatgpt" / "conversation-1"
        destination.mkdir(parents=True)
        return destination

    monkeypatch.setattr(conversation_app, "project_root", lambda: tmp_path)
    monkeypatch.setattr(conversation_app, "authenticated_chatgpt", download)
    monkeypatch.setattr(
        conversation_app,
        "checkpoint_delivery",
        lambda _root, _destination, *, provider: None,
    )

    result = CliRunner().invoke(
        conversation_app.create_conversation_app(profiles),
        ["chatgpt", "https://chatgpt.com/c/conversation-1"],
    )

    assert result.exit_code == 0
    assert opened == [tmp_path / ".lup" / "profiles" / "work" / "chatgpt-web"]
