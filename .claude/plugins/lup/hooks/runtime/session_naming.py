"""Claude Code's half of session naming, run as a bare script.

Shipped verbatim into the plugin's ``hooks/runtime/`` beside the coordination
package it imports, and registered under ``UserPromptSubmit``. It holds only
what Claude Code spells for itself: the title the payload reports, the CLI a
name is asked through, and the answer that sets the title. When to ask, what a
name may be and how one is settled on the roster are
:mod:`coordination.naming`'s.

Measured on 2.1.280 rather than only read from
https://code.claude.com/docs/en/hooks, which documents ``sessionTitle`` for
this event:

- ``hookSpecificOutput.sessionTitle`` replaces the title a launch set with
  ``--name`` on the prompt bar, and a title set with ``/rename`` too — so an
  answer repeated at every prompt would undo a person's rename, which is why
  the roster's name is carried once per change.
- The payload carries ``session_title``, the title the chrome shows as the
  prompt arrives, including a ``/rename`` made since the last one; the docs
  list the field for ``SessionStart`` alone.
- ``claude --safe-mode -p`` answers with plugins, hooks and MCP servers off,
  so the ask cannot re-enter this hook, and with ``--output-format json`` and
  ``--json-schema`` the name arrives as ``structured_output``. On Sonnet at
  low effort it took 3.6 to 6.3 seconds.

Only this hook's own answer can set the title — an async hook's answer
carries ``additionalContext`` and ``systemMessage`` and nothing else — so the
ask runs while the prompt waits, bounded by the declared deadline.

The same field is how the roster follows the chrome. A reopened conversation
keeps the title it last had — the launcher names a new session and leaves a
resumed one alone — and a ``/rename`` or a rename from another surface
changes the title under this hook; either arrives here as a ``session_title``
the roster does not answer to, and is taken up at the prompt it arrives with.

Every failure is silence: the prompt goes on, and the session keeps its name.
"""

import json
import sys
from pathlib import Path
from typing import TypedDict

# The hook is launched as a bare script, promised no cwd, PYTHONPATH, or
# interpreter environment, and this file sits in the `runtime/` directory
# that holds the coordination package. Naming it as a search path is what
# lets the imports below resolve.
sys.path.insert(0, str(Path(__file__).parent))
from coordination.naming import (
    Answer,
    Arrival,
    Naming,
    adoptable,
    answer_schema,
    asking,
    compiled_for,
    concluded,
    due,
    looked,
    named,
    owning,
    pending,
    ran,
    request_for,
    settled,
)


class Payload(Arrival, total=False):
    """What ``UserPromptSubmit`` hands the hook, with the one field only Claude Code sends."""

    session_title: str


class Result(TypedDict, total=False):
    """The single result ``claude -p --output-format json`` prints."""

    is_error: bool
    structured_output: Answer


class Titled(TypedDict):
    hookEventName: str
    sessionTitle: str


class Answered(TypedDict):
    """The event's answer: the title, and nothing that could refuse the prompt."""

    hookSpecificOutput: Titled


def asked(prompt: str, naming: Naming) -> str:
    """The name Claude gives the work *prompt* describes, blank for none.

    The prompt travels on stdin rather than as an argument, which a long
    pasted one would overrun, and whole: a prompt too long for the naming
    model is an ask that fails, not one to cut.
    """
    printed = ran(
        [
            "claude",
            "--safe-mode",
            "-p",
            "--model",
            naming["model"],
            "--effort",
            naming["effort"],
            "--no-session-persistence",
            *naming["arguments"],
            "--output-format",
            "json",
            "--json-schema",
            answer_schema(),
            "--system-prompt",
            naming["instruction"],
        ],
        request_for(prompt),
        naming["deadline_seconds"],
    )
    try:
        result: Result = json.loads(printed or "")
    except ValueError:
        return ""
    if not isinstance(result, dict) or result.get("is_error", True):
        return ""
    return named(result.get("structured_output"), naming["longest"])


def titled(root: Path, member_id: str, payload: Payload, naming: Naming) -> str:
    """The title this prompt sets, blank where it sets none.

    A title the chrome shows and the roster lacks is taken up first — it is
    the newer choice — and handed back only where the roster had to number it
    past a live session's name, so the two go on agreeing. One the roster
    could not take up is left unrecorded, and taken up at the next prompt.
    """
    member = owning(root, member_id, payload)
    if member is None:
        return ""
    titling = looked(root, member_id, member)
    shown = payload.get("session_title", "")
    if wanted := adoptable(member, titling, shown):
        name = settled(root, member_id, wanted, over_a_rename=True)
        if name:
            concluded(root, member_id, titling, name)
        return "" if name == shown else name
    prompt = payload.get("prompt", "")
    if prompt.strip() and due(member, titling, naming, shown):
        titling = asking(root, member_id, titling)
        wanted = asked(prompt, naming)
        name = settled(root, member_id, wanted) if wanted else ""
        concluded(root, member_id, titling, name)
        return name
    name = pending(member, titling)
    if name:
        concluded(root, member_id, titling, name)
    return name


def main() -> None:
    """Name the session, or say nothing and let the prompt through.

    The store root, the launcher-proven member id (blank where nothing
    launched this session) and the event's name arrive as arguments; the
    compiled declaration is read under this file's name.
    """
    try:
        root, member_id, event = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
        payload: Payload = json.load(sys.stdin)
        naming = compiled_for(Path(__file__))
        title = (
            titled(root, member_id or payload.get("session_id", ""), payload, naming)
            if naming is not None
            else ""
        )
    except Exception:
        return
    if title:
        print(
            json.dumps(
                Answered(
                    hookSpecificOutput=Titled(hookEventName=event, sessionTitle=title)
                )
            )
        )


if __name__ == "__main__":
    main()
