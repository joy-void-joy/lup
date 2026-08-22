"""The one channel out of the boundary, and what keeps it that narrow.

A sign-in cannot finish inside a container: the browser, the operator and the
second factor are all outside it. So a URL crosses. That is a real capability
handed to a confined process -- it can make the operator's desktop open a
page -- and the tests that matter here are the ones about what it refuses,
because a widened bridge looks exactly like a working one right up until it
does not.
"""

import json
import time
import webbrowser
from pathlib import Path

import pytest
import sh

from lup.harness.browser import BrowserBridge
from lup.harness.image import Image
from lup.harness.requirements import Manifest


@pytest.mark.parametrize(
    "forgery",
    [
        "https://claude.ai.evil.test/steal",
        "https://evil.test/?next=https://claude.ai",
        "https://notclaude.ai/",
        "https://claude.ai@evil.test/",
        "http://claude.ai/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "",
    ],
)
def test_a_url_that_only_looks_like_a_sign_in_is_dropped(forgery: str) -> None:
    """Every cheap version of this comparison admits one of these.

    `startswith` takes the subdomain, `in` takes the query parameter,
    `endswith` takes the suffix, and anything reading the text rather than
    parsing it takes the userinfo -- `https://claude.ai@evil.test/` is a
    request to `evil.test`, and only a parser says so. Plain http is refused
    with them, because a bridge that opens one is a bridge that can be
    steered by whatever answered the name.
    """
    assert BrowserBridge().admitted(forgery) == ""


@pytest.mark.parametrize(
    "address",
    [
        "https://claude.ai/oauth/authorize?code=x",
        "https://claude.com/oauth/authorize",
        "https://platform.claude.com/v1/oauth/token",
    ],
)
def test_the_addresses_a_sign_in_actually_visits_are_opened(address: str) -> None:
    """Refusing these would be a bridge that never carries the one thing it is for."""
    assert BrowserBridge().admitted(address) == address


def test_every_admitted_address_says_what_needed_it() -> None:
    """The accretion problem, which is the whole reason the reason travels.

    An address nobody can say why about is one nobody can ever argue for
    removing, and this list is the width of the only opening in the boundary.
    """
    assert all(item.because for item in BrowserBridge().admits)


def test_the_opener_returns_rather_than_blocking_when_nothing_listens() -> None:
    """A probe and a one-off `run` mount no pipe, and a writer to one blocks.

    Without the guard a sign-in in an unbridged launch would hang on exactly
    the step this exists to unblock -- and the printed URL, which is all the
    fallback flow needs, would never arrive either.
    """
    script = BrowserBridge().script()
    assert script.index("printf") < script.index("-p ")
    assert "|| exit 0" in script


def test_the_generated_opener_is_a_script_the_shell_accepts(tmp_path: Path) -> None:
    """It is shell assembled by an f-string, which nothing else type-checks."""
    written = tmp_path / "lup-open"
    written.write_text(BrowserBridge().script(), encoding="utf-8")
    sh.Command("sh")("-n", str(written))


def test_the_image_bakes_the_opener_and_the_variable_naming_it() -> None:
    """Both halves, or `BROWSER` points at a script the image does not have."""
    bridge, rendered = BrowserBridge(), Image().dockerfile(Manifest())
    assert f"ENV BROWSER={json.dumps(bridge.opener)}" in rendered
    assert f"COPY <<'OPEN' {bridge.opener}" in rendered


def test_a_url_written_inside_reaches_a_browser_outside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bridge end to end, minus the container, which supplies no behaviour.

    Both directions in one test on purpose: that the admitted URL arrives is
    half of it, and that the refused one does not is the half worth having.
    """
    opened: list[str] = []
    monkeypatch.setattr(
        webbrowser, "open", lambda url, *rest, **named: bool(opened.append(url))
    )
    bridge = BrowserBridge()
    directory = bridge.serve()
    assert directory is not None
    pipe = directory / bridge.channel
    for line in ["https://claude.ai/oauth/authorize?x=1", "https://evil.test/x"]:
        pipe.write_text(f"{line}\n", encoding="utf-8")
        time.sleep(0.2)
    assert opened == ["https://claude.ai/oauth/authorize?x=1"]


def test_the_launch_says_the_channel_exists_before_a_browser_opens_by_itself() -> None:
    """An operator whose desktop acts on its own should have been told what can."""
    said = "\n".join(item.text for item in BrowserBridge().notice(True))
    assert "channel" in said


def test_an_unbridged_launch_says_what_to_do_instead() -> None:
    """The documented fallback: open the URL yourself, paste the code back."""
    said = "\n".join(item.text for item in BrowserBridge().notice(False))
    assert "Paste code here" in said


def test_a_bridged_launch_says_the_callback_will_not_come_back() -> None:
    """The half a working bridge makes it easy to leave out.

    Carrying the URL out is the visible success, and it ends on a browser
    error every time: the CLI asked to be redirected to a loopback port that
    is the container's, and the browser resolving it is the operator's. An
    operator not told that reads `Unable to connect` as this bridge failing
    and debugs the pipe, which is working. So the same fallback the unbridged
    launch prints has to be here too, where it is less obviously needed.
    """
    said = "\n".join(item.text for item in BrowserBridge().notice(True))

    assert "Paste code here" in said
    assert "#" in said
