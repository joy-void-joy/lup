"""The one channel out of the boundary, and what keeps it that narrow.

A sign-in cannot finish inside a container: the browser, the operator and the
second factor are all outside it. So a URL crosses. That is a real capability
handed to a confined process -- it can make the operator's desktop open a
page -- and the tests that matter here are the ones about what it refuses,
because a widened bridge looks exactly like a working one right up until it
does not.
"""

import json
import shlex
import time
import webbrowser
from pathlib import Path

import pytest
import sh

from lup.harness.browser import BrowserBridge
from lup.harness.egress import SessionEgress
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


def test_the_opener_says_how_the_flow_ends_at_the_moment_it_starts_one() -> None:
    """The launch says this too, and says it where it gets scrolled away.

    An operator reads the launch notices once, minutes before typing
    `/login`, among every other boundary notice. The dead tab arrives later
    and on its own, so the instruction for it belongs in the one output that
    is on screen when it does -- and in an unbridged launch too, where the
    URL is opened by hand and the callback fails exactly the same way.
    """
    bridge = BrowserBridge()

    assert bridge.paste_back in bridge.script()
    assert bridge.script().index("Unable to connect") < bridge.script().index("-p ")


def test_the_instruction_is_held_once_and_rendered_twice() -> None:
    """Two spellings of one instruction drift, and drift is silent here.

    The notice and the opener ask for the same paste-back. Held apart, one
    gets corrected and the other keeps telling an operator something that is
    no longer how the flow works.
    """
    bridge = BrowserBridge()
    said = "\n".join(item.text for item in bridge.notice(True))

    assert bridge.paste_back in said
    assert bridge.paste_back in bridge.script()


def test_an_apostrophe_in_the_instruction_does_not_become_shell(
    tmp_path: Path,
) -> None:
    """It is prose in a shell string, which is a quoting bug waiting to be typed.

    Nobody editing this sentence is thinking about `sh`, so the quoting has
    to survive the edit rather than be re-derived by whoever makes it.
    """
    bridge = BrowserBridge(paste_back="it is the operator's tab; echo pwned")
    written = tmp_path / "lup-open"
    written.write_text(bridge.script(), encoding="utf-8")

    sh.Command("sh")("-n", str(written))


def test_the_instruction_matches_the_posture_the_sign_in_finishes_under() -> None:
    """One flow, two endings, and the wrong one wastes whoever reads it.

    A session holding its own network namespace redirects the browser at a
    port only the container has, so the tab dies and the code is carried back
    by hand. A session sharing the host's namespace redirects it at a port
    that browser can really open, so there is nothing to carry. The launch and
    the opener both read this, and both have to read the same one.
    """
    bridge = BrowserBridge()
    landing = "\n".join(item.text for item in bridge.notice(True, lands=True))

    assert bridge.completes in landing
    assert bridge.paste_back not in landing
    assert shlex.quote(bridge.completes) in bridge.script(lands=True)
    assert shlex.quote(bridge.paste_back) not in bridge.script(lands=True)


def test_the_image_bakes_the_ending_its_own_network_posture_produces() -> None:
    """The opener is baked once and read at every sign-in, so it cannot ask.

    Which is why the two declarations are members of one image: the script is
    rendered while the posture is in hand, so the sentence is settled there
    rather than by a shell script working out at run time something it has no
    way to see.
    """
    shared = Image(egress=SessionEgress(mode="host")).dockerfile(Manifest())
    scoped = Image(egress=SessionEgress(mode="filtered")).dockerfile(Manifest())

    assert shlex.quote(BrowserBridge().completes) in shared
    assert shlex.quote(BrowserBridge().paste_back) in scoped
