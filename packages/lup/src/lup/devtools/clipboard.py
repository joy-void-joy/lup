"""Reading and writing the system clipboard, whichever one this machine has.

Writing was already here and reading was not, so every caller that needed to
*read* wrote its own -- and each of them reached for ``xclip`` by name, which
answers on X11 and on nothing else. A Wayland session, a macOS laptop and a
headless CI box all get the same silence, and silence from a clipboard reads
exactly like an empty clipboard.

The two directions are one declaration because a machine that can write
through ``wl-copy`` reads through ``wl-paste``, and a roster that knew only
half of each pair would pick a writer on one backend and a reader on another.

**Reading is not one operation but three**, and the backends disagree about
which they can do. Every one can hand back text. Only some can say what types
the clipboard is currently offering, and only those same ones can be asked for
a particular type -- which is what an image paste needs, since "give me the
clipboard as PNG" is meaningless to a tool that only knows how to print
characters. ``xsel``, ``pbpaste`` and Windows' clipboard cannot enumerate at
all, so they are declared as text-only rather than tried and silently failing
at something they were never able to do.

Absence is a valid answer throughout. No display server is an ordinary state
for CI, for a remote shell, and for a container -- so nothing here raises, and
a caller that gets ``None`` has learned something true about the machine
rather than suffered an error.
"""

import io
from collections.abc import Iterator

import sh
from pydantic import BaseModel, Field


class ClipboardImage(BaseModel, frozen=True):
    """One image taken off the clipboard, with the type it was offered as.

    The type travels with the bytes because the caller's next act is almost
    always to write them somewhere with a suffix, and a PNG saved as ``.bin``
    is a file nothing will open.
    """

    media_type: str
    data: bytes


class ClipboardTool(BaseModel, frozen=True):
    """One backend, spelled in its own words for every direction it supports.

    A model rather than a pair of lookup tables because the fields are only
    correct together: ``wl-copy`` writes and ``wl-paste`` reads, and a roster
    that let those be chosen independently could pick a writer this machine
    has beside a reader it does not.
    """

    writer: str = Field(description="The program that puts text on the clipboard")
    write_arguments: list[str] = Field(
        default=[], description="What the writer takes before reading stdin"
    )
    reader: str = Field(
        default="",
        description=(
            "The program that reads the clipboard back, empty where this "
            "backend has none. Separate from the writer because half the "
            "backends use a different binary for each direction"
        ),
    )
    text_arguments: list[str] = Field(
        default=[], description="What the reader takes to print the clipboard as text"
    )
    list_arguments: list[str] = Field(
        default=[],
        description=(
            "What the reader takes to list the types on offer. Empty where "
            "the backend cannot enumerate, which is a real limit rather than "
            "a gap: `xsel` and `pbpaste` print characters and know nothing "
            "about types at all"
        ),
    )
    typed_arguments: list[str] = Field(
        default=[],
        description=(
            "What the reader takes before the media type it should hand "
            "back, the type appended as the last word. Empty alongside an "
            "empty `list_arguments`, since asking for a type is only useful "
            "where the types can be discovered first"
        ),
    )

    def enumerates(self) -> bool:
        """Whether this backend can be asked what the clipboard is offering."""
        return bool(self.list_arguments and self.typed_arguments)

    def write(self, text: str) -> bool:
        """Put text on the clipboard, reporting whether this backend could."""
        try:
            sh.Command(self.writer)(*self.write_arguments, _in=text)
        except (sh.ErrorReturnCode, sh.CommandNotFound):
            return False
        return True

    def text(self) -> str | None:
        """The clipboard as text, or nothing when this backend cannot say.

        An empty clipboard and an absent backend both come back as ``None``,
        deliberately: a caller has the same thing to do about either, and
        distinguishing them would mean claiming the clipboard is empty on a
        machine where nothing was ever asked.
        """
        if not self.reader:
            return None
        try:
            held = str(sh.Command(self.reader)(*self.text_arguments))
        except (sh.ErrorReturnCode, sh.CommandNotFound):
            return None
        return held or None

    def types(self) -> list[str]:
        """Every media type the clipboard is currently offering, as this tool sees.

        Empty where the backend cannot enumerate, which reads correctly at
        every call site: nothing on offer and nothing askable both mean there
        is no typed read to attempt.
        """
        if not self.enumerates():
            return []
        try:
            listed = str(sh.Command(self.reader)(*self.list_arguments))
        except (sh.ErrorReturnCode, sh.CommandNotFound):
            return []
        return [line.strip() for line in listed.splitlines() if line.strip()]

    def typed(self, media_type: str) -> bytes:
        """The clipboard as one specific type, empty when it cannot be had.

        Bytes rather than text because the types worth asking for by name are
        the ones text cannot carry, and decoding an image as UTF-8 is how a
        working paste turns into a mangled one.
        """
        if not self.enumerates():
            return b""
        # Captured into a byte buffer rather than through `sh`'s text
        # handling, which decodes: this is the one read whose payload is not
        # characters, and a lossy decode is invisible until an image will not
        # open.
        buffer = io.BytesIO()
        try:
            sh.Command(self.reader)(*self.typed_arguments, media_type, _out=buffer)
        except (sh.ErrorReturnCode, sh.CommandNotFound):
            return b""
        return buffer.getvalue()


# lup: ignore[library-default] — each backend's own command line, fixed by what
# the tool accepts rather than by anything an adopter would choose differently
CLIPBOARD_TOOLS = (
    ClipboardTool(
        writer="wl-copy",
        reader="wl-paste",
        # `--no-newline` because wl-paste appends one that was never on the
        # clipboard, which turns a copied token into a token plus a newline.
        text_arguments=["--no-newline"],
        list_arguments=["--list-types"],
        typed_arguments=["--type"],
    ),
    ClipboardTool(
        writer="xclip",
        write_arguments=["-selection", "clipboard"],
        reader="xclip",
        text_arguments=["-selection", "clipboard", "-o"],
        list_arguments=["-selection", "clipboard", "-o", "-t", "TARGETS"],
        typed_arguments=["-selection", "clipboard", "-o", "-t"],
    ),
    ClipboardTool(
        writer="xsel",
        write_arguments=["--clipboard", "--input"],
        reader="xsel",
        text_arguments=["--clipboard", "--output"],
    ),
    ClipboardTool(writer="pbcopy", reader="pbpaste"),
    ClipboardTool(
        writer="clip",
        reader="powershell",
        text_arguments=["-NoProfile", "-Command", "Get-Clipboard"],
    ),
)
"""The backends tried in turn, Wayland first.

Order is the whole of the detection, and it is not arbitrary. Wayland leads
because a Wayland session commonly *also* has ``xclip`` installed and answering
through XWayland, where it sees a clipboard that is not the one the user is
copying into -- so trying X11 first finds a tool that works and gives wrong
answers. `xclip` before `xsel` because only the first can enumerate types, and
a machine with both should get the one that can serve an image paste.
"""


def clipboard_probes(
    tools: tuple[ClipboardTool, ...] = CLIPBOARD_TOOLS,
) -> list[list[str]]:
    """One real read per backend, for the manifest to exercise this capability with.

    Reads rather than writes, and that is not a detail: a probe that proved
    the clipboard by *writing* to it would destroy whatever the operator had
    put there, every launch, to establish something they were not asking
    about.

    Reads rather than ``--version``, for the reason the manifest exists at
    all. ``wl-copy --version`` succeeds on a machine with no compositor
    running and ``xclip -version`` succeeds with no ``DISPLAY`` to connect
    to, so a version probe reports a working clipboard on exactly the machines
    where pasting silently does nothing. Asking for the clipboard's contents
    fails there, which is the answer.

    Derived here rather than written out beside the declaration, so the
    spellings the manifest exercises and the spellings this module uses
    cannot come apart -- which they already had: the requirement listed four
    backends including Wayland while the code tried four that did not.
    """
    return [
        [tool.reader, *(tool.list_arguments or tool.text_arguments)]
        for tool in tools
        if tool.reader
    ]


def copy_to_clipboard(
    text: str, tools: tuple[ClipboardTool, ...] = CLIPBOARD_TOOLS
) -> bool:
    """Copy text to the system clipboard, reporting whether anything could.

    ``False`` when no backend answered, so a caller can fall back to printing
    the text for the reader to copy by hand instead of pretending it landed.
    """
    return any(tool.write(text) for tool in tools)


def clipboard_text(tools: tuple[ClipboardTool, ...] = CLIPBOARD_TOOLS) -> str | None:
    """The clipboard's text through the first backend that answers."""
    return next(
        (held for tool in tools for held in [tool.text()] if held is not None), None
    )


def clipboard_image(
    media_types: tuple[str, ...],
    tools: tuple[ClipboardTool, ...] = CLIPBOARD_TOOLS,
) -> ClipboardImage | None:
    """The clipboard as the first of these types anything on offer matches.

    The caller supplies the types rather than this module naming them,
    because which formats are worth having is the caller's question -- an
    agent sending images to a model accepts what that model accepts, and a
    different consumer accepts something else.

    Backends that cannot enumerate contribute nothing here and are skipped
    rather than guessed at: asking ``pbpaste`` for a PNG returns its text
    output, which would arrive as bytes that are not an image and be saved as
    one.
    """

    def offered() -> Iterator[ClipboardImage]:
        for tool in tools:
            on_offer = tool.types()
            for media_type in media_types:
                if media_type not in on_offer:
                    continue
                data = tool.typed(media_type)
                if data:
                    yield ClipboardImage(media_type=media_type, data=data)

    return next(offered(), None)
