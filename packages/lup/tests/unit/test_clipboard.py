"""Which clipboard backend answers, and what each one can honestly be asked.

Nothing here talks to a real clipboard: the point of the module is the
declaration, and a test that needed a display server would be skipped on
exactly the machines whose absence of one this is about. What is pinned is
the shape -- the ordering that keeps XWayland from answering for the wrong
clipboard, and the refusal to ask a text-only backend for an image.
"""

from lup.devtools.clipboard import (
    CLIPBOARD_TOOLS,
    ClipboardTool,
    clipboard_image,
    clipboard_probes,
    clipboard_text,
    copy_to_clipboard,
)
from lup.harness.toolchain import clipboard_requirement


def test_wayland_is_tried_before_x11() -> None:
    """The trap this ordering exists for, and the one a reorder would restore.

    A Wayland session commonly also has `xclip`, answering through XWayland
    against a clipboard the user is not copying into. Trying X11 first finds a
    tool that works and gives wrong answers, which is worse than finding none.
    """
    names = [tool.writer for tool in CLIPBOARD_TOOLS]
    assert names.index("wl-copy") < names.index("xclip")


def test_the_backend_that_can_enumerate_is_tried_before_the_one_that_cannot() -> None:
    """An image paste needs types, and only some backends know about them."""
    names = [tool.writer for tool in CLIPBOARD_TOOLS]
    assert names.index("xclip") < names.index("xsel")


def test_only_the_backends_that_can_enumerate_say_they_can() -> None:
    """`xsel` and `pbpaste` print characters and know nothing about types."""
    enumerating = {tool.writer for tool in CLIPBOARD_TOOLS if tool.enumerates()}
    assert enumerating == {"wl-copy", "xclip"}


def test_a_text_only_backend_refuses_a_typed_read_rather_than_guessing() -> None:
    """Asking `pbpaste` for a PNG returns its text, which is not a PNG.

    Bytes that are not an image, saved with a `.png` suffix, is a paste that
    looks like it worked until something tries to open the file.
    """
    text_only = ClipboardTool(writer="pbcopy", reader="pbpaste")
    assert text_only.typed("image/png") == b""
    assert text_only.types() == []


def test_a_backend_with_no_reader_answers_nothing_rather_than_failing() -> None:
    """Absence is a valid answer here: CI and containers have no clipboard."""
    write_only = ClipboardTool(writer="clip")
    assert write_only.text() is None


def test_every_backend_reads_through_its_own_binary() -> None:
    """Half of them use a different program for each direction.

    A roster that let the writer and the reader be chosen separately could
    pick `wl-copy` on a machine that has it beside `pbpaste` on one that does
    not, and the pairing is the whole reason this is one declaration.
    """
    assert {(tool.writer, tool.reader) for tool in CLIPBOARD_TOOLS} >= {
        ("wl-copy", "wl-paste"),
        ("pbcopy", "pbpaste"),
    }


def test_nothing_answers_when_no_backend_is_installed() -> None:
    """The whole roster missing is an ordinary machine, not an error."""
    absent = (ClipboardTool(writer="lup-no-such-writer", reader="lup-no-such-reader"),)
    assert copy_to_clipboard("x", absent) is False
    assert clipboard_text(absent) is None
    assert clipboard_image(("image/png",), absent) is None


def test_the_manifest_exercises_the_same_backends_the_code_reaches_for() -> None:
    """The drift this derivation closes, which had already happened.

    The requirement listed four backends including Wayland while the code
    that reached for a clipboard tried four that did not -- so a Wayland
    machine was told it had a clipboard and then silently failed to use it.
    """
    probed = set(clipboard_requirement().exercise.programs())
    assert probed == {tool.reader for tool in CLIPBOARD_TOOLS if tool.reader}


def test_every_probe_reads_the_clipboard_rather_than_writing_it() -> None:
    """A probe that wrote would destroy what the operator had put there.

    Every launch, to establish something they were not asking about.
    """
    written = {tool.writer for tool in CLIPBOARD_TOOLS} - {
        tool.reader for tool in CLIPBOARD_TOOLS
    }
    assert not [probe for probe in clipboard_probes() if probe[0] in written]


def test_no_probe_settles_for_asking_a_program_its_version() -> None:
    """`wl-copy --version` succeeds with no compositor and `xclip -version` with
    no DISPLAY, which is exactly the machine where pasting does nothing."""
    assert not [
        probe
        for probe in clipboard_probes()
        if any("version" in word for word in probe)
    ]
