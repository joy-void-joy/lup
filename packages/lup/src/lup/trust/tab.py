"""The browser tab a launch's review left open, which the command it runs continues in.

``lup-launch`` asks its question in a review inbox it opens in the operator's
browser. Once a ``run`` hands its command over, that command opening a page
of its own -- a local dashboard, a provider's page for a key -- would open a
second tab beside the one the operator is looking at. So the launcher names a
handshake file in the command's environment, the command writes the page
there instead of opening it, and the inbox sends its tab to the page.

Only the first page goes there: the handshake is written once, and anything
the command opens after that opens as it always would, as does everything a
command opens with no review behind it. What it carries is only ever a page
address, an http or https URL, in a file under a directory the launcher made
for its own operator alone.
"""

import webbrowser
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings

# lup: ignore[constant-declaration] — the variable the launcher and every
# command it hands over agree on; neither side may name another
REVIEW_TAB_ENV = "LUP_REVIEW_TAB"
"""Where a command hands the first page it opens, when a review's tab waits for it."""


class ReviewTab(BaseSettings, populate_by_name=True):
    """The handshake this command was handed, where a launch's review left a tab open."""

    handshake: Path | None = Field(default=None, validation_alias=REVIEW_TAB_ENV)


class PageAnnouncement(BaseModel, frozen=True):
    """The page a command opened, as it hands it to the review's tab."""

    url: str

    @field_validator("url")
    @classmethod
    def a_page(cls, value: str) -> str:
        """Refuse anything but a web page's address, which is all a tab is sent to."""
        if urlparse(value).scheme not in ("http", "https"):
            raise ValueError(f"{value!r} is not an http or https address")
        return value


def handed_to_review_tab(url: str, tab: ReviewTab | None = None) -> bool:
    """Hand a page to the tab a launch's review left open, answering whether it went.

    Written beside the handshake and linked into place, so the launcher never
    reads half of it, and only where nothing was handed yet: a second page,
    or a handshake the launcher has already taken away, is the caller's to
    open as it always would.
    """
    handshake = (tab if tab is not None else ReviewTab()).handshake
    if handshake is None:
        return False
    try:
        announced = PageAnnouncement(url=url)
    except ValidationError:
        return False
    staged = handshake.with_name(f"{handshake.name}.{uuid4().hex}")
    try:
        staged.write_text(announced.model_dump_json(), encoding="utf-8")
        handshake.hardlink_to(staged)
    except OSError:
        return False
    finally:
        staged.unlink(missing_ok=True)
    return True


def shown_to_operator(url: str) -> None:
    """Open a page for the operator: in the tab their launch's review left, else a new one.

    The one way a command opens a page, so a command ``lup-launch run`` handed
    over after a review in the browser sends its first page to that review's
    tab, and the operator is not left with two.
    """
    if not handed_to_review_tab(url):
        webbrowser.open(url)


def announced_page(handshake: Path) -> str | None:
    """The page a command handed to the review's tab, once it has handed one."""
    try:
        return PageAnnouncement.model_validate_json(handshake.read_bytes()).url
    except (OSError, ValidationError):
        return None
