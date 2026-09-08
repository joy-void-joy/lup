"""Native X11 clients reach synthetic clipboard data, never the host clipboard."""

import io
import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from threading import Event

import pytest
import sh
from pydantic import BaseModel, Field
from Xlib import display, error

from lup.devtools.clipboard import ClipboardImage
from lup.harness.assets.clipboard_x11 import private_display
from lup.harness.clipboard import ClipboardBridge
from lup.harness.image import Image
from lup.harness.requirements import Manifest
from lup.types import EnvVars


class ClipboardState(BaseModel, arbitrary_types_allowed=True):
    text: str = "native clipboard text"
    image: bytes = bytes(range(256)) * 16
    copied: Event = Field(default_factory=Event)


class NativeClipboard(BaseModel, arbitrary_types_allowed=True):
    state: ClipboardState
    environment: EnvVars
    executable: str

    def read(self, media_type: str) -> bytes:
        output = io.BytesIO()
        sh.Command(self.executable)(
            "-selection",
            "clipboard",
            "-t",
            media_type,
            "-o",
            _env=self.environment,
            _out=output,
            _timeout=15,
        )
        return output.getvalue()


@pytest.fixture
def native_clipboard(monkeypatch: pytest.MonkeyPatch) -> Iterator[NativeClipboard]:
    executable = shutil.which("xclip")
    if (
        executable is None
        or shutil.which("Xvfb") is None
        or shutil.which("xauth") is None
    ):
        pytest.skip("native clipboard tests require Xvfb, xauth, and xclip")
    state = ClipboardState()

    def image(media_types: tuple[str, ...]) -> ClipboardImage | None:
        if "image/png" in media_types:
            return ClipboardImage(media_type="image/png", data=state.image)
        return None

    def copied(text: str) -> bool:
        state.text = text
        state.copied.set()
        return True

    monkeypatch.setattr("lup.harness.clipboard.clipboard_text", lambda: state.text)
    monkeypatch.setattr("lup.harness.clipboard.clipboard_image", image)
    monkeypatch.setattr("lup.harness.clipboard.copy_to_clipboard", copied)
    bridge = ClipboardBridge(limit=2 * 1024 * 1024)
    directory = bridge.serve()
    if directory is None:
        pytest.skip("this sandbox does not permit the clipboard broker socket")
    monkeypatch.setenv("LUP_CLIPBOARD_SOCKET", str(directory / bridge.channel))
    with private_display(limit=bridge.limit) as environment:
        yield NativeClipboard(
            state=state, environment=environment, executable=executable
        )


def test_native_x11_text_and_image_reads(native_clipboard: NativeClipboard) -> None:
    assert native_clipboard.read("UTF8_STRING").decode() == native_clipboard.state.text
    assert native_clipboard.read("image/png") == native_clipboard.state.image
    assert b"image/png" in native_clipboard.read("TARGETS")


def test_display_readiness_consumes_complete_fragmented_lines(
    native_clipboard: NativeClipboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = os.read
    received = bytearray()

    def fragmented(descriptor: int, size: int) -> bytes:
        block = original(descriptor, min(size, 1))
        received.extend(block)
        return block

    monkeypatch.setattr("lup.harness.assets.clipboard_x11.os.read", fragmented)
    with private_display():
        assert received.count(b"\n") == 2
        assert received.endswith(b"ready\n")


def test_native_paste_observes_host_clipboard_changes(
    native_clipboard: NativeClipboard,
) -> None:
    assert native_clipboard.read("image/png") == native_clipboard.state.image
    native_clipboard.state.image = bytes(reversed(range(256))) * 16
    assert native_clipboard.read("image/png") == native_clipboard.state.image


def test_large_native_image_is_transferred_whole(
    native_clipboard: NativeClipboard,
) -> None:
    native_clipboard.state.image = bytes(range(256)) * 4097
    assert native_clipboard.read("image/png") == native_clipboard.state.image


@pytest.mark.parametrize(
    "text",
    ["copied from a native client 🌍", "large native text 🌍" * 12000],
    ids=["small", "incremental"],
)
def test_native_text_copies_reach_the_broker(
    native_clipboard: NativeClipboard, text: str
) -> None:
    sh.Command(native_clipboard.executable)(
        "-selection",
        "clipboard",
        "-t",
        "UTF8_STRING",
        "-i",
        "-quiet",
        _env=native_clipboard.environment,
        _in=text,
        _timeout=15,
    )
    assert native_clipboard.state.copied.wait(2)
    assert native_clipboard.state.text == text
    assert native_clipboard.read("UTF8_STRING").decode() == text


def test_native_unsupported_type_is_refused(
    native_clipboard: NativeClipboard, capfd: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(sh.ErrorReturnCode):
        native_clipboard.read("application/x-not-carried")
    assert native_clipboard.read("image/png") == native_clipboard.state.image
    assert "clipboard read refused" not in capfd.readouterr().err


def test_native_oversized_image_is_refused(native_clipboard: NativeClipboard) -> None:
    native_clipboard.state.image = b"x" * (2 * 1024 * 1024 + 1)
    with pytest.raises(sh.ErrorReturnCode):
        native_clipboard.read("image/png")


def test_private_display_requires_its_own_authority(
    native_clipboard: NativeClipboard,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = Path(native_clipboard.environment["XAUTHORITY"])
    assert authority.stat().st_mode & 0o777 == 0o600
    empty = tmp_path / "empty-authority"
    empty.write_bytes(b"")
    monkeypatch.setenv("XAUTHORITY", str(empty))
    with pytest.raises(error.DisplayConnectionError):
        display.Display(native_clipboard.environment["DISPLAY"])


def test_command_clients_start_no_display_and_native_clients_get_a_bounded_helper() -> (
    None
):
    bridge = ClipboardBridge(limit=12345)
    assert bridge.wrap(["native-cli", "argument"], "commands") == [
        "native-cli",
        "argument",
    ]
    assert bridge.wrap(["native-cli", "argument"], "x11") == [
        "lup-clipboard-x11",
        "--limit",
        "12345",
        "--",
        "native-cli",
        "argument",
    ]
    image = Image()
    rendered = image.dockerfile(Manifest())
    assert image.clipboard.native_program() in rendered
    assert "COPY <<'CLIP' /usr/local/bin/clipboard_shim.py" in rendered
    assert "python-xlib" in [package.name for package in image.packages(Manifest())]


def test_native_wrapper_preserves_command_exit_status(
    native_clipboard: NativeClipboard,
) -> None:
    program = (
        Path(__file__).parents[2]
        / "packages/lup/src/lup/harness/assets/clipboard_x11.py"
    )
    with pytest.raises(sh.ErrorReturnCode_7):
        sh.Command(sys.executable)(
            program,
            "--",
            "sh",
            "-c",
            "exit 7",
            _env=native_clipboard.environment,
            _timeout=20,
        )
