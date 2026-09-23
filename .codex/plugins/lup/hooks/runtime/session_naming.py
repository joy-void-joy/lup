"""Codex's half of session naming, run as a bare script.

Shipped verbatim into the plugin's ``hooks/runtime/`` beside the coordination
package it imports, and registered under ``UserPromptSubmit``. It holds only
what Codex spells for itself: the CLI a name is asked through, and the
app-server request that names a thread. When to ask, what a name may be and
how one is settled on the roster are :mod:`coordination.naming`'s.

Codex takes no name from a hook's answer. The output schema it documents for
this event (https://learn.chatgpt.com/docs/hooks) admits added context, a
block and the common fields, and closes the object to anything else. A thread
is named through its app-server instead, which a process of its own can reach
after the hook has returned — so nothing waits on the model here: the hook
records that an ask started, hands the prompt to a copy of this file in a
session of its own, and lets the prompt go on.

Measured on Codex 0.155.1:

- A separate, short-lived ``codex app-server`` answered ``thread/name/set``
  for a thread a live TUI had loaded with ``{}``, and the name landed in the
  home's ``session_index.jsonl``. It outlived the TUI's later turns and its
  exit, and ``codex exec resume <name>`` reopened the thread by it. The live
  TUI's status line went on showing the title it already had.
- Codex names a thread itself from its first prompt, and that is what the
  session's own status line shows.
- ``codex exec --ephemeral --skip-git-repo-check --ignore-user-config -C
  <scratch>`` with ``--output-schema`` answered a naming ask in 3.7 seconds
  with JSON meeting the schema, and ``-o`` wrote it to a file. With its shell
  on, it met a prompt asking it to explain something by exploring the
  scratch directory until the deadline passed, so the ask is opened with the
  arguments the generator compiles from the adapter's own list of facilities
  to switch off — every tool, every hook, every write — and the prompt
  arrives quoted, as the thing to name. Killing the npm wrapper at that
  deadline left the binary running, which is why an ask runs in a session of
  its own that is killed whole.
- The hook's ``session_id`` is the thread's id, which the arrival binder
  records as the thread ``codex queue`` takes.

Every failure is silence: the prompt goes on, and the session keeps its name.
"""

import json
import os
import signal

# lup: ignore[subprocess] — `sh` is third-party and this half is shipped into a
# bare script that has no virtual environment to resolve it from
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import TypedDict

# The hook is launched as a bare script, promised no cwd, PYTHONPATH, or
# interpreter environment, and this file sits in the `runtime/` directory
# that holds the coordination package. Naming it as a search path is what
# lets the imports below resolve.
sys.path.insert(0, str(Path(__file__).parent))
from coordination.naming import (
    Arrival,
    Naming,
    answer_schema,
    answered,
    asking,
    compiled_for,
    concluded,
    due,
    looked,
    owning,
    pending,
    ran,
    recalled,
    request_for,
    settled,
    stopped,
)


class ClientInfo(TypedDict):
    name: str
    version: str


class Initialize(TypedDict):
    clientInfo: ClientInfo


class SetName(TypedDict):
    threadId: str
    name: str


class Empty(TypedDict):
    pass


class Request(TypedDict):
    """One app-server request, as its protocol spells it on a stdio line."""

    method: str
    id: int
    params: Initialize | SetName


class Notification(TypedDict):
    method: str
    params: Empty


class Reply(TypedDict, total=False):
    """One line the app-server writes, as far as waiting on a request reads it."""

    id: int
    result: Empty


def asked(prompt: str, naming: Naming) -> str:
    """The name Codex gives the work *prompt* describes, blank for none.

    Asked from a scratch directory, so the project configuration beside the
    session is not the one read, and whole on stdin: a prompt too long for
    the naming model is an ask that fails, not one to cut. The compiled
    arguments are what keep the ask to answering — no tool, no hook, nothing
    written — and the configuration naming this project's plugin is not read.
    """
    with tempfile.TemporaryDirectory(prefix="lup-naming-") as scratch:
        schema = Path(scratch) / "schema.json"
        reply = Path(scratch) / "answer.json"
        try:
            schema.write_text(answer_schema(), encoding="utf-8")
        except OSError:
            return ""
        printed = ran(
            [
                "codex",
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "--ignore-user-config",
                "-C",
                scratch,
                "-m",
                naming["model"],
                "-c",
                f"model_reasoning_effort={json.dumps(naming['effort'])}",
                "-c",
                f"developer_instructions={json.dumps(naming['instruction'])}",
                *naming["arguments"],
                "--output-schema",
                str(schema),
                "-o",
                str(reply),
                "-",
            ],
            request_for(prompt),
            naming["deadline_seconds"],
            cwd=scratch,
        )
        try:
            return (
                answered(reply.read_text("utf-8"), naming["longest"])
                if printed is not None
                else ""
            )
        except OSError:
            return ""


def thread_named(thread: str, name: str, deadline: float) -> bool:
    """Name *thread* through a short-lived app-server over the session's own home.

    The home is whatever the environment names, which is the session's: a
    hook inherits it from the runtime that spawned it. In a session of its
    own and killed whole at the deadline, which ends every read below with
    the stream it was waiting on — the wrapper and the binary it starts alike.
    """
    try:
        server = subprocess.Popen(
            ["codex", "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
    except OSError:
        return False
    watchdog = threading.Timer(deadline, os.killpg, (server.pid, signal.SIGKILL))
    watchdog.start()
    try:
        return (
            requested(
                server,
                Request(
                    method="initialize",
                    id=1,
                    params=Initialize(clientInfo=ClientInfo(name="lup", version="0")),
                ),
            )
            and notified(server, Notification(method="initialized", params=Empty()))
            and requested(
                server,
                Request(
                    method="thread/name/set",
                    id=2,
                    params=SetName(threadId=thread, name=name),
                ),
            )
        )
    finally:
        watchdog.cancel()
        stopped(server)


def notified(server: subprocess.Popen[str], notification: Notification) -> bool:
    """Send one notification, which nothing answers."""
    if server.stdin is None:
        return False
    server.stdin.write(json.dumps(notification) + "\n")
    server.stdin.flush()
    return True


def requested(server: subprocess.Popen[str], request: Request) -> bool:
    """Send one request and read until its reply, saying whether it succeeded."""
    if server.stdin is None or server.stdout is None:
        return False
    server.stdin.write(json.dumps(request) + "\n")
    server.stdin.flush()
    for line in server.stdout:
        try:
            reply: Reply = json.loads(line)
        except ValueError:
            continue
        if isinstance(reply, dict) and reply.get("id") == request["id"]:
            return "result" in reply
    return False


def named_in_background(root: Path, member_id: str, thread: str, prompt: str) -> None:
    """Ask, settle the roster's name, and give the thread the name settled."""
    naming = compiled_for(Path(__file__))
    titling = recalled(root, member_id)
    if naming is None or titling is None:
        return
    wanted = asked(prompt, naming)
    name = settled(root, member_id, wanted) if wanted else ""
    if name and thread:
        thread_named(thread, name, naming["deadline_seconds"])
    concluded(root, member_id, titling, name)


def detached(arguments: list[str], prompt: str) -> None:
    """Run this file again in a session of its own, handing it *prompt* on stdin.

    Its own session, so nothing that ends the hook's process group ends it,
    and nothing of the hook's output is held open by it: the runtime reads
    the hook as finished the moment the hook exits.
    """
    worker = subprocess.Popen(
        [sys.executable, str(Path(__file__)), *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    if worker.stdin is not None:
        worker.stdin.write(prompt)
        worker.stdin.close()


def hooked(root: Path, member_id: str, payload: Arrival, naming: Naming) -> None:
    """Start what this prompt calls for, and return without waiting on it."""
    member = owning(root, member_id, payload)
    if member is None:
        return
    titling = looked(root, member_id, member)
    thread, prompt = payload.get("session_id", ""), payload.get("prompt", "")
    if prompt.strip() and due(member, titling, naming, None):
        asking(root, member_id, titling)
        detached(["ask", str(root), member_id, thread], prompt)
        return
    name = pending(member, titling)
    if name and thread:
        concluded(root, member_id, titling, name)
        detached(["push", str(root), thread, name], "")


def main() -> None:
    """Answer the event, or run one detached half of it; say nothing either way.

    As the hook, the store root, the launcher-proven member id (blank where
    nothing launched this session) and the event's name arrive as arguments,
    and the compiled declaration is read under this file's name.
    """
    try:
        match sys.argv[1:]:
            case ["ask", root, member_id, thread]:
                named_in_background(Path(root), member_id, thread, sys.stdin.read())
            case ["push", _root, thread, name]:
                naming = compiled_for(Path(__file__))
                if naming is not None:
                    thread_named(thread, name, naming["deadline_seconds"])
            case [root, member_id, _event]:
                payload: Arrival = json.load(sys.stdin)
                naming = compiled_for(Path(__file__))
                if naming is not None:
                    hooked(
                        Path(root),
                        member_id or payload.get("session_id", ""),
                        payload,
                        naming,
                    )
    except Exception:
        return


if __name__ == "__main__":
    main()
