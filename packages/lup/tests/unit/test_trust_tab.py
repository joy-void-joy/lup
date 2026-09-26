"""A command hands its first page to the tab its launch's review left open, and only that one.

The handshake is a file the launcher names: a command writes the page there
rather than opening it, once, and opens every later page itself -- as it
does every page where no review left a tab. Only a web page's address is
ever handed, since the tab is sent wherever it says.
"""

import webbrowser
from pathlib import Path

import pytest

from lup.trust.tab import (
    REVIEW_TAB_ENV,
    ReviewTab,
    announced_page,
    handed_to_review_tab,
    shown_to_operator,
)


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The pages opened in a browser, recorded rather than opened."""
    pages: list[str] = []

    def record(url: str) -> bool:
        pages.append(url)
        return True

    monkeypatch.setattr(webbrowser, "open", record)
    return pages


def test_the_first_page_goes_to_the_tab_and_the_next_opens_as_always(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opened: list[str]
) -> None:
    handshake = tmp_path / "page.json"
    monkeypatch.setenv(REVIEW_TAB_ENV, str(handshake))

    shown_to_operator("http://127.0.0.1:8900/")
    shown_to_operator("https://aistudio.google.com/apikey")

    assert announced_page(handshake) == "http://127.0.0.1:8900/"
    assert opened == ["https://aistudio.google.com/apikey"]
    assert [path.name for path in tmp_path.iterdir()] == ["page.json"]


def test_with_no_review_behind_it_a_command_opens_its_own_page(
    monkeypatch: pytest.MonkeyPatch, opened: list[str]
) -> None:
    monkeypatch.delenv(REVIEW_TAB_ENV, raising=False)

    shown_to_operator("http://127.0.0.1:8900/")

    assert opened == ["http://127.0.0.1:8900/"]


def test_only_a_web_page_is_handed_to_the_tab(tmp_path: Path) -> None:
    handshake = tmp_path / "page.json"

    handed = handed_to_review_tab("javascript:alert(1)", ReviewTab(handshake=handshake))

    assert not handed
    assert announced_page(handshake) is None


def test_a_handshake_the_launcher_took_away_is_a_page_opened_as_always(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opened: list[str]
) -> None:
    monkeypatch.setenv(REVIEW_TAB_ENV, str(tmp_path / "gone" / "page.json"))

    shown_to_operator("http://127.0.0.1:8900/")

    assert opened == ["http://127.0.0.1:8900/"]
