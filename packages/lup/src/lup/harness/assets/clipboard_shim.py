#!/usr/bin/env python3
# lup: ignore[os-environ, dict-get, os-path, library-default]
# The shebang is load-bearing: the image links every name under the bridge's
# `shims` at this file and the kernel runs whichever one a caller spells, so
# `chmod +x` without it produces a program that execs to nothing.
# A standalone program copied into the container, which has neither this
# library nor its pydantic settings: it reads its endpoint from the
# environment because that is the only channel it has, reads its replies with
# `.get` because the schema it answers lives across a socket, and takes its
# own name with `os.path` rather than importing pathlib for one basename.
# The tables below are the flag spellings of the tools this stands in for,
# fixed by those tools rather than by anything an adopter would choose.
"""Every clipboard name inside the container, answered by the operator's own.

The image links this program in as `xclip`, `xsel`, `wl-copy`, `wl-paste`,
`pbcopy`, `pbpaste` and `tmux`, so anything that shells out for a clipboard
finds it under the name it already asks for. What it does is forward the
question to the broker running in the launcher, outside the boundary, which
reaches whatever clipboard that machine actually has.

One program for all of them because they differ only in which flags mean
"read": a copy per name would be as many chances to disagree about one
protocol. Dispatch is on the name it was invoked as, plus the flags each
tool spells.

`tmux` is the one name that is not a clipboard program, and it is here
because the handoff carries `TMUX` while the socket it points at stays on the
host. A session told it is inside a multiplexer and then given no `tmux` to
run is being told two contradictory things, and a runtime that reaches for
the buffer verbs -- which is how a terminal's own copy is spelled when a
multiplexer owns the screen -- finds nothing. Only those verbs are answered.
Every other subcommand exits non-zero naming the boundary, because a session
cannot reach the operator's server and a shim that pretended otherwise would
answer questions about panes and clients with silence that reads as fact.

Exits non-zero when no broker is listening, which is what "this machine has
no clipboard" already looked like to every caller.
"""

import base64
import json
import os
import socket
import sys

READERS = ("wl-paste", "pbpaste")
WRITERS = ("wl-copy", "pbcopy", "clip")
TYPE_FLAGS = ("-t", "--type")
TMUX_BUFFER_VERBS = ("load-buffer", "set-buffer")
TMUX_VALUE_FLAGS = ("-b", "-t", "-n")


class UnsupportedClipboardType(ValueError):
    """A normal native format probe outside the broker's declared types."""


def exchange(request, timeout=5, limit=32 * 1024 * 1024):
    """One bounded broker exchange, shared by command and native clients."""
    endpoint = os.environ.get("LUP_CLIPBOARD_SOCKET", "")
    if not endpoint:
        raise OSError("no clipboard bridge in this session")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.settimeout(timeout)
        channel.connect(endpoint)
        channel.sendall((json.dumps(request) + "\n").encode("utf-8"))
        # JSON may encode one text byte as six characters (a Unicode escape).
        # The broker owns the payload limit; this bounds its wire envelope too.
        with channel.makefile("rb") as reader:
            received = reader.readline(limit * 6 + 65536)
        if not received.endswith(b"\n"):
            raise ValueError("clipboard bridge reply incomplete or oversized")
    reply = json.loads(received.decode("utf-8"))
    if not isinstance(reply, dict):
        raise ValueError("clipboard bridge reply is not an object")
    if reply.get("ok") is not True:
        if reply.get("code") == "unsupported_type":
            raise UnsupportedClipboardType(reply.get("error", "unsupported type"))
        raise ValueError(reply.get("error", "clipboard unavailable"))
    return reply


def ask(request):
    """Put one question to the broker and return its reply, or exit."""
    try:
        return exchange(request)
    except (OSError, ValueError) as error:
        sys.stderr.write("clipboard bridge: %s\n" % error)
        sys.exit(1)


def wanted_type(argv):
    """The media type these arguments ask for, empty when they ask for none."""
    for flag in TYPE_FLAGS:
        if flag in argv:
            position = argv.index(flag) + 1
            if position < len(argv):
                return argv[position]
    return ""


def writing(name, argv):
    """Whether this invocation means to put something on the clipboard.

    A tool that only ever writes says so by its name; the ones that do both
    read only when asked to, which is what `-o` and `--output` mean to every
    caller that spells them.
    """
    if name in WRITERS:
        return True
    if name in READERS:
        return False
    return "-o" not in argv and "--output" not in argv


def tmux_operand(argv):
    """The one operand a buffer verb carries, past the flags around it.

    Read positionally rather than matched, because what the operand *means*
    is the verb's business: `set-buffer` carries the text itself and
    `load-buffer` carries where to read it from. `-b`, `-t` and `-n` take a
    value that is not it; `-w` and its like take none.
    """

    def operands():
        expecting = False
        for word in argv:
            if expecting:
                expecting = False
            elif word in TMUX_VALUE_FLAGS:
                expecting = True
            elif word == "-" or not word.startswith("-"):
                yield word

    return next(operands(), "")


def tmux_text(verb, operand):
    """What a buffer verb is putting on the clipboard.

    `-` is stdin, and so is a verb given no operand at all, which is what a
    caller piping into `load-buffer` spells either way.
    """
    if verb == "set-buffer":
        return operand
    if operand in ("", "-"):
        return sys.stdin.read()
    with open(operand, encoding="utf-8") as handle:
        return handle.read()


def tmux(
    argv,
    unreachable=(
        "tmux: this session reaches the operator's clipboard but not their "
        "server; tmux runs on the host.\n"
    ),
):
    """Answer the buffer verbs, and name the boundary for everything else.

    What the refusal *says* is a judgement rather than tmux's own vocabulary,
    so it arrives as a default a caller can replace -- unlike the verbs and
    flags above, which are spelled by tmux and not by anyone here.
    """
    verb = argv[0] if argv else ""
    if verb not in TMUX_BUFFER_VERBS:
        sys.stderr.write(unreachable)
        sys.exit(1)
    ask({"op": "set", "text": tmux_text(verb, tmux_operand(argv[1:]))})


def main():
    """Answer as whichever clipboard tool this program was invoked as."""
    name = os.path.basename(sys.argv[0])
    argv = sys.argv[1:]
    if name == "tmux":
        tmux(argv)
        return
    if writing(name, argv):
        ask({"op": "set", "text": sys.stdin.read()})
        return
    asked = wanted_type(argv)
    if "--list-types" in argv or asked == "TARGETS":
        for offered in ask({"op": "types"})["types"]:
            sys.stdout.write(offered + "\n")
    elif asked:
        reply = ask({"op": "typed", "media_type": asked})
        sys.stdout.buffer.write(base64.b64decode(reply["data"]))
    else:
        sys.stdout.write(ask({"op": "text"})["text"])


if __name__ == "__main__":
    main()
