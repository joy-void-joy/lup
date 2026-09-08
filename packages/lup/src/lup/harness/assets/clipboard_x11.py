#!/usr/bin/env python3
# lup: ignore[argparse, subprocess, os-environ]
# Standalone image helper: the image supplies python-xlib, Xvfb, and xauth,
# not Lup's application dependencies.
"""A private X11 selection connected only to the bounded clipboard broker."""

import argparse
import base64
import importlib
import os
import secrets
import select
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from Xlib import X, Xatom, display, error
from Xlib.protocol import event

if __package__:
    from .clipboard_shim import UnsupportedClipboardType, exchange
else:
    clipboard_shim = importlib.import_module("clipboard_shim")
    exchange = clipboard_shim.exchange
    UnsupportedClipboardType = clipboard_shim.UnsupportedClipboardType


class Outbound:
    """One incremental transfer, retaining every byte until acknowledged."""

    def __init__(self, requestor, property_atom, target, data, deadline):
        self.requestor = requestor
        self.property_atom = property_atom
        self.target = target
        self.data = data
        self.deadline = deadline
        self.offset = 0


class SelectionBridge:
    """Serve broker reads and forward native text copies, without desktop access."""

    def __init__(self, limit=32 * 1024 * 1024, timeout=10, chunk_size=65536):
        if limit < 1 or timeout <= 0 or not 1 <= chunk_size <= 65536:
            raise ValueError("invalid clipboard transfer bounds")
        self.limit = limit
        self.timeout = timeout
        self.chunk_size = chunk_size
        self.connection = display.Display()
        self.connection.set_error_handler(self.protocol_error)
        self.window = self.connection.screen().root.create_window(
            0,
            0,
            1,
            1,
            0,
            X.CopyFromParent,
            X.InputOnly,
            event_mask=X.PropertyChangeMask,
        )
        self.clipboard = self.atom("CLIPBOARD")
        self.targets = self.atom("TARGETS")
        self.incr = self.atom("INCR")
        self.incoming = self.atom("LUP_CLIPBOARD_INCOMING")
        self.outbound = []
        self.reading_owner = 0
        self.reading_target = self.targets
        self.reading_data = bytearray()
        self.reading_incremental = False
        self.reading_deadline = 0.0

    def atom(self, name):
        return self.connection.intern_atom(name)

    def owner(self):
        owner = self.connection.get_selection_owner(self.clipboard)
        return 0 if isinstance(owner, int) else owner.id

    def claim(self):
        self.window.set_selection_owner(self.clipboard, X.CurrentTime)
        self.connection.sync()
        if self.owner() != self.window.id:
            raise OSError("private clipboard selection ownership failed")

    def protocol_error(self, failure, _request):
        # A requesting window can disappear between its request and our answer.
        # Drop its retained payload rather than retrying a vanished client.
        self.outbound = [
            held for held in self.outbound if held.requestor.id != failure.resource_id
        ]
        if not isinstance(failure, error.BadWindow):
            print(
                f"lup: private clipboard X11 error ({type(failure).__name__}).",
                file=sys.stderr,
            )

    def request(self, asked):
        property_atom = asked.property or asked.target
        accepted = X.NONE
        try:
            if asked.selection != self.clipboard:
                raise ValueError("unsupported selection")
            if asked.target == self.targets:
                types = exchange({"op": "types"}, limit=self.limit)["types"]
                asked.requestor.change_property(
                    property_atom,
                    Xatom.ATOM,
                    32,
                    [self.targets, *[self.atom(name) for name in types]],
                )
            else:
                name = self.connection.get_atom_name(asked.target)
                reply = exchange({"op": "typed", "media_type": name}, limit=self.limit)
                data = base64.b64decode(reply["data"], validate=True)
                if len(data) > self.limit:
                    raise ValueError("clipboard payload exceeds limit")
                if len(data) <= self.chunk_size:
                    asked.requestor.change_property(
                        property_atom, asked.target, 8, data
                    )
                else:
                    if (
                        sum(len(held.data) for held in self.outbound) + len(data)
                        > self.limit
                    ):
                        raise ValueError("clipboard transfers exceed memory limit")
                    asked.requestor.change_attributes(event_mask=X.PropertyChangeMask)
                    self.outbound.append(
                        Outbound(
                            asked.requestor,
                            property_atom,
                            asked.target,
                            data,
                            time.monotonic() + self.timeout,
                        )
                    )
                    asked.requestor.change_property(
                        property_atom, self.incr, 32, [len(data)]
                    )
            accepted = property_atom
        except UnsupportedClipboardType:
            # SelectionNotify(property=None) answers an ordinary format probe.
            pass
        except (OSError, ValueError, error.XError) as failure:
            print(
                f"lup: clipboard read refused ({type(failure).__name__}).",
                file=sys.stderr,
            )
        asked.requestor.send_event(
            event.SelectionNotify(
                time=asked.time,
                requestor=asked.requestor,
                selection=asked.selection,
                target=asked.target,
                property=accepted,
            )
        )

    def advance(self, changed):
        for held in tuple(self.outbound):
            if (
                changed.window.id != held.requestor.id
                or changed.atom != held.property_atom
            ):
                continue
            data = held.data[held.offset : held.offset + self.chunk_size]
            held.requestor.change_property(held.property_atom, held.target, 8, data)
            held.offset += len(data)
            held.deadline = time.monotonic() + self.timeout
            if not data:
                self.outbound.remove(held)

    def copy_started(self):
        self.reading_owner = self.owner()
        self.reading_target = self.targets
        self.reading_data = bytearray()
        self.reading_incremental = False
        if not self.reading_owner or self.reading_owner == self.window.id:
            self.copy_finished()
            return
        self.reading_deadline = time.monotonic() + self.timeout
        self.window.convert_selection(
            self.clipboard, self.targets, self.incoming, X.CurrentTime
        )

    def copy_finished(self):
        owner = self.owner()
        if owner not in (0, self.window.id, self.reading_owner):
            # A second copy superseded the owner whose answer we were reading.
            self.copy_started()
            return
        self.reading_owner = 0
        self.reading_data = bytearray()
        self.reading_incremental = False
        self.reading_deadline = 0.0
        self.claim()

    def copy_received(self):
        try:
            received = self.window.get_property(
                self.incoming,
                X.AnyPropertyType,
                0,
                (self.limit + 3) // 4 + 1,
                delete=True,
            )
            if received is None:
                return
            if received.bytes_after:
                raise ValueError("native clipboard copy exceeds limit")
            if received.property_type == self.incr:
                if (
                    self.reading_target == self.targets
                    or received.format != 32
                    or len(received.value) != 1
                    or received.value[0] > self.limit
                ):
                    raise ValueError("invalid incremental clipboard copy")
                self.reading_incremental = True
                return
            if self.reading_target == self.targets:
                if received.format != 32 or received.property_type != Xatom.ATOM:
                    raise ValueError("invalid clipboard targets")
                chosen = next(
                    (
                        self.atom(name)
                        for name in (
                            "UTF8_STRING",
                            "text/plain;charset=utf-8",
                            "text/plain",
                            "STRING",
                        )
                        if self.atom(name) in received.value
                    ),
                    None,
                )
                if chosen is None:
                    raise ValueError("the host bridge accepts native text copies only")
                self.reading_target = chosen
                self.window.convert_selection(
                    self.clipboard, chosen, self.incoming, X.CurrentTime
                )
                return
            if received.format != 8 or received.property_type != self.reading_target:
                raise ValueError("invalid clipboard text")
            self.reading_data.extend(received.value)
            if len(self.reading_data) > self.limit:
                raise ValueError("native clipboard text exceeds limit")
            self.reading_deadline = time.monotonic() + self.timeout
            if self.reading_incremental and len(received.value):
                return
            encoding = "latin-1" if self.reading_target == Xatom.STRING else "utf-8"
            if self.owner() == self.reading_owner:
                exchange(
                    {"op": "set", "text": self.reading_data.decode(encoding)},
                    limit=self.limit,
                )
        except (OSError, ValueError, error.XError) as failure:
            print(
                f"lup: clipboard copy refused ({type(failure).__name__}).",
                file=sys.stderr,
            )
        self.copy_finished()

    def dispatch(self, received):
        match received.type:
            case X.SelectionRequest:
                self.request(received)
            case X.SelectionClear:
                if received.atom == self.clipboard:
                    self.copy_started()
            case X.SelectionNotify:
                if self.reading_owner and received.selection == self.clipboard:
                    if received.property == X.NONE:
                        self.copy_finished()
                    else:
                        self.copy_received()
            case X.PropertyNotify:
                if received.state == X.PropertyDelete:
                    self.advance(received)
                elif (
                    self.reading_owner
                    and self.reading_incremental
                    and received.window.id == self.window.id
                    and received.atom == self.incoming
                ):
                    self.copy_received()

    def run(self):
        for _ in iter(int, 1):
            for _ in range(self.connection.pending_events()):
                self.dispatch(self.connection.next_event())
            self.connection.flush()
            now = time.monotonic()
            self.outbound = [held for held in self.outbound if held.deadline > now]
            if self.reading_owner and self.reading_deadline <= now:
                print("lup: native clipboard copy timed out.", file=sys.stderr)
                self.copy_finished()
                self.connection.flush()
            deadlines = [held.deadline for held in self.outbound]
            if self.reading_owner:
                deadlines.append(self.reading_deadline)
            wait = max(0, min(deadlines) - time.monotonic()) if deadlines else None
            if not self.connection.pending_events():
                select.select([self.connection], [], [], wait)


@contextmanager
def private_display(limit=32 * 1024 * 1024, timeout=15):
    """Own an authenticated server and selection bridge for one native session."""
    children = []

    def start_ready(command, environment, diagnostics=None):
        reading, writing = os.pipe()
        try:
            child = subprocess.Popen(
                [*command, str(writing)],
                env=environment,
                pass_fds=(writing,),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=diagnostics,
                start_new_session=True,
            )
            children.append(child)
            os.close(writing)
            writing = None
            deadline = time.monotonic() + timeout
            ready = bytearray()
            for _ in iter(int, 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([reading], [], [], remaining)[0]:
                    raise OSError("private clipboard startup timed out")
                block = os.read(reading, 4096 - len(ready))
                if not block:
                    raise OSError("private clipboard startup ended before readiness")
                ready.extend(block)
                if ready.endswith(b"\n"):
                    break
                if len(ready) >= 4096:
                    raise ValueError("private clipboard readiness line exceeds limit")
            return child
        except (OSError, ValueError):
            if diagnostics is not None:
                diagnostics.seek(0)
                sys.stderr.write(diagnostics.read())
            raise
        finally:
            os.close(reading)
            if writing is not None:
                os.close(writing)

    with (
        tempfile.TemporaryDirectory(prefix="lup-private-display-") as directory,
        (Path(directory) / "Xvfb.log").open("w+") as diagnostics,
    ):
        server = None
        authority = Path(directory) / "Xauthority"
        authority.touch(mode=0o600)
        # Each container owns its socket namespace; a randomized display also
        # permits independent diagnostic instances on a development host.
        name = f":{100 + secrets.randbelow(10000)}"
        environment = dict(os.environ)
        environment.update(DISPLAY=name, XAUTHORITY=str(authority))
        environment.pop("WAYLAND_DISPLAY", None)
        environment.pop("WAYLAND_SOCKET", None)
        try:
            subprocess.run(
                [
                    "xauth",
                    "-f",
                    str(authority),
                    "add",
                    name,
                    "MIT-MAGIC-COOKIE-1",
                    secrets.token_hex(16),
                ],
                check=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            server = start_ready(
                [
                    "Xvfb",
                    name,
                    "-screen",
                    "0",
                    "1x1x24",
                    "-extension",
                    "GLX",
                    "-nolisten",
                    "tcp",
                    "-noreset",
                    "-auth",
                    str(authority),
                    "-displayfd",
                ],
                environment,
                diagnostics,
            )
            start_ready(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--serve",
                    "--limit",
                    str(limit),
                    "--ready-fd",
                ],
                environment,
            )
            yield environment
        finally:
            if server is not None and server.poll() is not None:
                print(
                    f"lup: private X11 server stopped (exit {server.returncode}).",
                    file=sys.stderr,
                )
                diagnostics.seek(0)
                sys.stderr.write(diagnostics.read())
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--ready-fd", type=int)
    parser.add_argument("--limit", type=int, default=32 * 1024 * 1024)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    if arguments.serve and arguments.ready_fd is None:
        parser.error("--serve requires --ready-fd")
    try:
        if arguments.serve:
            bridge = SelectionBridge(limit=arguments.limit)
            try:
                bridge.claim()
                os.write(arguments.ready_fd, b"ready\n")
                os.close(arguments.ready_fd)
                bridge.run()
            finally:
                bridge.connection.close()
            return
        command = arguments.command
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error("a native command is required")
        with private_display(limit=arguments.limit) as environment:
            with subprocess.Popen(command, env=environment) as child:
                # Terminal SIGINT reaches the CLI in this same foreground group.
                # The detached display helpers must survive a cancelled turn.
                previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
                terminating = signal.signal(
                    signal.SIGTERM, lambda value, _frame: child.send_signal(value)
                )
                try:
                    status = child.wait()
                finally:
                    signal.signal(signal.SIGINT, previous)
                    signal.signal(signal.SIGTERM, terminating)
            sys.exit(status if status >= 0 else 128 - status)
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
        error.DisplayError,
    ) as failure:
        print(
            f"lup: private clipboard unavailable ({type(failure).__name__}). "
            "Check Xvfb, xauth and python-xlib in the session image.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
