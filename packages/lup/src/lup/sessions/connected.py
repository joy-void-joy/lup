"""The first program a held session's room runs: it connects to its launcher's socket, puts the connection on its standard input and output, and runs the rest in its own place.

    python3 -I connected.py /run/lup/session.sock <the room's own start> <the CLI> …

Written into the launch's directory and run on the room's Python, so it uses
the standard library alone. A held session's input and output are then a
socket, which a process in the room can't open again through `/proc/<pid>/fd/0`
as it can a pipe ("No such device or address"): no other process of the room
can write the session's turns, which reach it as the operator's words
(`docs/field-notes.md`, *A session held with no terminal*). It runs before
anything else of the room's starts, so its connection is the one its launcher
accepts.
"""

import os
import socket
import sys


def main() -> None:
    """Connect to the socket the first argument names, put it on standard input and output, and run the program the rest name in this one's place."""
    place, program, *arguments = sys.argv[1:]
    held = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    held.connect(place)
    for each in [0, 1]:
        os.dup2(held.fileno(), each)
    held.close()
    # lup: ignore("os-shell", why="the program runs in this one's place, so the session's input and output are the socket, and the room's init holds it as it would without this; it runs on the room's Python, with no lup to run it")
    os.execvp(program, [program, *arguments])


if __name__ == "__main__":
    main()
