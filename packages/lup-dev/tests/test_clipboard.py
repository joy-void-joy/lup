"""The operator's clipboard in a room: the room's `wl-paste` and `wl-copy` through the host's handlers, and the host's desktop programs, each stood in."""

import asyncio
import base64
import io
import json
import os
import socket
import stat
import sys
import threading
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup_dev.clipboard import shim
from lup_dev.clipboard.desktop import Clipboard, Desktop
from lup_dev.clipboard.protocol import routes
from lup_dev.host.protocol import HostError, Limits, Refused, Register, Request
from lup_dev.launch.room import RoomClipboard, programs
from lup_dev.layout import LaunchLayout
from lup_dev.settings import LupDevSettings

if TYPE_CHECKING:
    from collections.abc import Generator


class Held(Clipboard):
    """A clipboard holding what it's given, by type, recording each write; or refusing every read, saying `refusing`."""

    def __init__(self, held: dict[str, bytes], refusing: str | None = None) -> None:
        self.held = held
        self.refusing = refusing
        self.written: list[tuple[str, bool]] = []

    @override
    async def types(self, *, primary: bool) -> list[str]:
        return list(self.held)

    @override
    async def read(self, type_: str | None, *, primary: bool) -> bytes:
        if self.refusing is not None:
            raise HostError(self.refusing)
        return self.held[type_ or "text/plain"]

    @override
    async def write(self, text: str, *, primary: bool) -> None:
        self.written.append((text, primary))


LAUNCH = Register(
    launch="one",
    runtime="first",
    worktree=Path("/w"),
    repository=Path("/w/.git"),
    judge=Path("/judge"),
    container="lup-one",
    limits=Limits(actions=[], protected=[]),
    github=None,
)


@contextmanager
def served(clipboard: Clipboard, path: Path) -> Generator[None]:
    """Answer the clipboard's requests on `path` with its handlers, as the host's request socket does, until the generator ends."""
    answering = {route.kind: route for route in routes(clipboard)}
    listening = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listening.bind(str(path))
    listening.listen()
    stop = threading.Event()

    def answered(raw: str) -> str:
        kind = Request.model_validate_json(raw).kind
        try:
            reply = asyncio.run(answering[kind].answer(raw, LAUNCH))
        except HostError as refused:
            reply = Refused(error=str(refused))
        return reply.model_dump_json()

    def run() -> None:
        while not stop.is_set():
            connection, _ = listening.accept()
            with connection:
                raw = b""
                while chunk := connection.recv(65536):
                    raw += chunk
                if raw:
                    connection.sendall(answered(raw.decode()).encode())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as waking:
            waking.connect(str(path))
        thread.join(timeout=60)
        listening.close()


@pytest.fixture
def requests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # A socket's path is limited in length, so its directory is short.
    return tmp_path_factory.mktemp("clip") / "request.sock"


PNG = b"\x89PNG\r\n\x1a\nimage"


def test_wl_paste_lists_types_and_prints_what_the_clipboard_holds(
    requests: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    clipboard = Held({"image/png": PNG, "text/plain": b"hello"})
    printed: list[bytes] = []
    with served(clipboard, requests):
        for arguments in [["--list-types"], ["--type", "image/png"], [], ["-n"]]:
            shim.pasted(arguments, requests)
            printed.append(capsysbinary.readouterr().out)
    assert printed == [b"image/png\ntext/plain\n", PNG, b"hello\n", b"hello"]


def test_wl_copy_puts_its_arguments_or_its_input_on_the_clipboard(
    requests: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clipboard = Held({})
    with served(clipboard, requests):
        shim.copied(["two", "words"], requests)
        monkeypatch.setattr(sys, "stdin", io.StringIO("from input\n"))
        shim.copied(["--primary"], requests)
        monkeypatch.setattr(sys, "stdin", io.StringIO("trimmed\n"))
        shim.copied(["-n"], requests)
    assert clipboard.written == [
        ("two words", False),
        ("from input\n", True),
        ("trimmed", False),
    ]


def test_a_refusal_ends_the_program_saying_why(requests: Path) -> None:
    clipboard = Held({}, refusing="`wl-paste --no-newline` failed: Nothing is copied")
    with served(clipboard, requests), pytest.raises(SystemExit) as ended:
        shim.pasted([], requests)
    assert str(ended.value) == "lup: `wl-paste --no-newline` failed: Nothing is copied"


def test_no_host_is_said(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as ended:
        shim.pasted([], tmp_path / "gone.sock")
    assert str(ended.value).startswith("lup: lup's host service doesn't answer on ")


STAND_IN = """#!/bin/sh
printf '%s\\n' "$(basename "$0") $*" >> "{log}"
case "$*" in
  *--list-types*|*TARGETS*) printf 'image/png\\ntext/plain\\n' ;;
  *fail*) echo "Nothing is copied" >&2; exit 1 ;;
  *slow*) sleep 30 ;;
  *) cat > /dev/null 2>&1 <&0; printf '{data}' ;;
esac
"""


@pytest.fixture
def programs_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stand-in `wl-paste`, `wl-copy` and `xclip` first on the `PATH`, each logging how it was run and its input; return the log."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "ran.log"
    for name in ["wl-paste", "wl-copy", "xclip"]:
        program = bin_ / name
        program.write_text(STAND_IN.format(log=log, data="held"))
        program.chmod(program.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    return log


def test_the_desktop_reads_and_writes_through_waylands_programs(
    programs_on_path: Path,
) -> None:
    desktop = Desktop(session="wayland")

    async def used() -> tuple[list[str], bytes, bytes]:
        types = await desktop.types(primary=False)
        image = await desktop.read("image/png", primary=False)
        text = await desktop.read(None, primary=True)
        await desktop.write("copied", primary=True)
        return types, image, text

    types, image, text = asyncio.run(used())
    assert types == ["image/png", "text/plain"]
    assert image == text == b"held"
    assert programs_on_path.read_text().splitlines() == [
        "wl-paste --list-types",
        "wl-paste --no-newline --type image/png",
        "wl-paste --no-newline --primary",
        "wl-copy --primary",
    ]


def test_the_desktop_reads_and_writes_through_xclip_under_x(
    programs_on_path: Path,
) -> None:
    desktop = Desktop.of(LupDevSettings(wayland_display=None, display=":0"))

    async def used() -> list[str]:
        types = await desktop.types(primary=False)
        await desktop.read("image/png", primary=False)
        await desktop.write("copied", primary=False)
        return types

    assert asyncio.run(used()) == ["image/png", "text/plain"]
    assert programs_on_path.read_text().splitlines() == [
        "xclip -selection clipboard -t TARGETS -o",
        "xclip -selection clipboard -t image/png -o",
        "xclip -selection clipboard",
    ]


def test_the_desktop_says_what_it_cant_do(programs_on_path: Path) -> None:
    async def refused(desktop: Desktop, type_: str) -> str:
        with pytest.raises(HostError) as failure:
            await desktop.read(type_, primary=False)
        return str(failure.value)

    away = Desktop.of(LupDevSettings(wayland_display=None, display=None))
    small = Desktop(session="wayland", limit=3)
    hurried = Desktop(session="wayland", timeout=timedelta(0))
    wayland = Desktop(session="wayland")
    said = [
        asyncio.run(refused(away, "text/plain")),
        asyncio.run(refused(small, "image/png")),
        asyncio.run(refused(wayland, "fail")),
        asyncio.run(refused(hurried, "slow")),
    ]
    assert said[0].startswith("the host service reaches no clipboard: it runs outside")
    assert said[1] == "the clipboard holds more than 3 bytes, which a room isn't given"
    assert said[2] == "`wl-paste --no-newline --type fail` failed: Nothing is copied"
    assert said[3] == "`wl-paste --no-newline --type slow` didn't answer within 0:00:00"


def test_a_room_gets_both_programs_executable_and_a_display_named(
    tmp_path: Path,
) -> None:
    launch = LaunchLayout(directory=tmp_path / "launch")
    clipboard = RoomClipboard(launch=launch)
    clipboard.write()
    written = programs(launch)
    for each in [launch.pasting, launch.copying]:
        assert each.read_text() == written[each]
        assert each.stat().st_mode & 0o777 == 0o755
    assert clipboard.env == {"WAYLAND_DISPLAY": "lup"}


def test_the_reply_carries_bytes_whole() -> None:
    data = bytes(range(256))
    reply = json.loads(
        asyncio.run(
            routes(Held({"image/png": data}))[1].answer(
                '{"kind": "clipboard-read", "type": "image/png"}', LAUNCH
            )
        ).model_dump_json()
    )
    assert base64.b64decode(reply["data"]) == data
