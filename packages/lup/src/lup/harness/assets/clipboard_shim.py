#!/usr/bin/env python3
# lup: ignore[os-environ, dict-get, os-path, library-default]
# The shebang is load-bearing: the image links six clipboard names at this
# file and the kernel runs whichever one a caller spells, so `chmod +x`
# without it produces a program that execs to nothing.
# A standalone program copied into the container, which has neither this
# library nor its pydantic settings: it reads its endpoint from the
# environment because that is the only channel it has, reads its replies with
# `.get` because the schema it answers lives across a socket, and takes its
# own name with `os.path` rather than importing pathlib for one basename.
# The tables below are the flag spellings of the tools this stands in for,
# fixed by those tools rather than by anything an adopter would choose.
"""Every clipboard name inside the container, answered by the operator's own.

The image links this program in as `xclip`, `xsel`, `wl-copy`, `wl-paste`,
`pbcopy` and `pbpaste`, so anything that shells out for a clipboard finds it
under the name it already asks for. What it does is forward the question to
the broker running in the launcher, outside the boundary, which reaches
whatever clipboard that machine actually has.

One program for all six names because they differ only in which flags mean
"read": a copy per name would be six chances to disagree about one protocol.
Dispatch is on the name it was invoked as, plus the flags each tool spells.

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


def ask(request):
    """Put one question to the broker and return its reply, or exit."""
    endpoint = os.environ.get("LUP_CLIPBOARD_SOCKET", "")
    if not endpoint:
        sys.stderr.write("no clipboard bridge in this session\n")
        sys.exit(1)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
            channel.connect(endpoint)
            channel.sendall((json.dumps(request) + "\n").encode("utf-8"))
            received = b""
            while not received.endswith(b"\n"):
                block = channel.recv(65536)
                if not block:
                    break
                received += block
    except OSError as error:
        sys.stderr.write("clipboard bridge unreachable: %s\n" % error)
        sys.exit(1)
    reply = json.loads(received.decode("utf-8"))
    if not reply.get("ok", False):
        sys.stderr.write(reply.get("error", "clipboard unavailable") + "\n")
        sys.exit(1)
    return reply


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


def main():
    """Answer as whichever clipboard tool this program was invoked as."""
    name = os.path.basename(sys.argv[0])
    argv = sys.argv[1:]
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
