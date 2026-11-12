"""Claude Code held with no terminal: its stream-json input and output, which a launcher talks over (`lup.sessions.held`).

The command is the terminal's (`lup.adapters.claude.terminal`), every flag of
lup's kept, with `--output-format stream-json --verbose --input-format
stream-json` after them, the argv the Agent SDK's client gives it, and no `-p`:
Claude Code's headless docs say `--bare` "will become the default for `-p` in a
future release", and a bare session runs no hooks and refuses a subscription
login, so a held session would lose lup's judge and its login at a CLI update.
It's compiled with no channel and no messaging socket (`unpushed`): a channel is
ignored without a terminal, and the messaging socket frames what arrives as
another session's message, so a held session is given its turns on its input
alone.

The wire, one JSON object a line each way:
- **In:** a user turn, `{"type": "user", "message": {"role": "user", "content":
  <text>}, "parent_tool_use_id": null, "session_id": ""}`, which starts a turn of
  an idle session, its text `UserPromptSubmit`'s `prompt` whole, and is read in
  the same turn by a busy one, once its running call ends; an interrupt,
  `{"type": "control_request", "request_id": <id>, "request": {"subtype":
  "interrupt"}}`, answered at once.
- **Out:** `system` `init` at each turn's start, carrying the session's id;
  `result` at each turn's end, `is_error` and `terminal_reason` saying how it
  ended; `control_response` answering a request by its id; the turn's messages
  and each hook's start and response between. A background command's end can
  start a turn nothing was sent for, its own `result` after.

What this rests on (`docs/field-notes.md`, *A session held with no terminal*),
measured on 2.1.319, some with the Agent SDK's client and some on this wire:
- `SessionStart` runs as the process starts, before anything is sent, with the
  id `--session-id` gives it; `--resume <id>` keeps the id and the record, and
  refuses a session that never took a turn ("No conversation found");
- an interrupt ends the turn in 0.1 s, `error_during_execution` with
  `terminal_reason` `aborted_tools`, killing a foreground command; a command in
  the background runs on; during a held hook the hook gets `SIGTERM`;
- the input's end ends an idle process in 0.7 s; one in a turn finishes it first,
  a held hook or a background command or subagent keeping it there, so a
  launcher ending one past its patience stops its container;
- nothing stops a second writer: a terminal resuming the session while this
  process holds it is let in, and the one record branches. lup's launcher holds
  a lock per session for that.
"""

import asyncio
import json
from collections.abc import Callable, Iterator
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Literal, override

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

from lup.errors import LupError
from lup.rooms.engine import Pipes
from lup.sessions.held import HeldSession
from lup.types import JsonObject, Model, MutableModel

if TYPE_CHECKING:
    from lup.sessions.terminal import Terminal, TerminalSettings


class HeldError(LupError):
    """A held session that didn't do what it was asked: an interrupt refused, or not answered."""


def unpushed(settings: TerminalSettings) -> TerminalSettings:
    """Return `settings` with no messaging socket and no tool server pushing: a held session's turns come on its input alone."""
    return settings.model_copy(
        update={
            "messages": None,
            "servers": [
                each.model_copy(update={"pushes": False}) for each in settings.servers
            ],
        }
    )


def held_terminal(terminal: Terminal) -> Terminal:
    """Return `terminal`'s command held over Claude Code's stream-json input and output, with no `-p`."""
    return terminal.model_copy(
        update={
            "command": [
                *terminal.command,
                "--output-format",
                "stream-json",
                "--verbose",
                "--input-format",
                "stream-json",
            ]
        }
    )


class Content(Model):
    """A user turn's message."""

    role: Literal["user"] = "user"
    content: str


class UserTurn(Model):
    """A user turn, written to the session's input."""

    type: Literal["user"] = "user"
    message: Content
    parent_tool_use_id: None = None
    session_id: str = ""


class Interrupting(Model):
    """What an interrupt asks."""

    subtype: Literal["interrupt"] = "interrupt"


class Asking(Model):
    """A request of the launcher's, written to the session's input, answered by its id."""

    type: Literal["control_request"] = "control_request"
    request_id: str
    request: Interrupting


class Kind(Model):
    """What a line Claude Code writes is: its type, and its subtype where it has one."""

    type: str
    subtype: str | None = None


class Started(Model):
    """`system` `init`: a turn starts."""

    session_id: str


class Ended(Model):
    """`result`: a turn ends, and how."""

    subtype: str
    is_error: bool = False
    terminal_reason: str | None = None

    def said(self) -> str:
        """Say how the turn ended, in a line.

        >>> Ended(subtype="error_during_execution", is_error=True, terminal_reason="aborted_tools").said()
        'A turn ended: error_during_execution, aborted_tools, an error.'
        """
        how = [
            self.subtype,
            *([] if self.terminal_reason is None else [self.terminal_reason]),
            *(["an error"] if self.is_error else []),
        ]
        return f"A turn ended: {', '.join(how)}."


class Answer(Model):
    """A control response's answer to one request, by its id."""

    subtype: Literal["success", "error"]
    request_id: str
    error: str | None = None


class Answered(Model):
    """`control_response`: the answer to a request of the launcher's."""

    response: Answer


class Asked(Model):
    """`control_request`: a request Claude Code makes of the launcher."""

    request_id: str
    request: JsonObject


class Refusal(Model):
    """The launcher's answer to a request of Claude Code's it doesn't take."""

    subtype: Literal["error"] = "error"
    request_id: str
    error: str


class Refusing(Model):
    """A control response refusing a request of Claude Code's."""

    type: Literal["control_response"] = "control_response"
    response: Refusal


class ClaudeHeld(MutableModel, HeldSession, arbitrary_types_allowed=True):
    """Claude Code held over its stream-json input and output."""

    pipes: Pipes
    said: Callable[[str], None]
    """Where it says what the session does: each turn's start and end."""
    patience: timedelta = timedelta(seconds=10)
    """How long a request waits for its answer."""
    turning: bool = False
    """Whether a turn runs, as the session last said: from its `init` to its
    `result`."""
    session: str | None = None
    """The session's id, as its last turn's start said."""
    pending: dict[str, asyncio.Future[Answer]] = {}
    numbers: Iterator[int] = Field(default_factory=lambda: count(1))

    @override
    async def send(self, text: str) -> None:
        await self.written(UserTurn(message=Content(content=text)))

    @override
    async def interrupt(self) -> None:
        """End the turn under way, once Claude Code answers the interrupt; raise `HeldError` where it refuses, or doesn't answer within `patience`."""
        number = f"lup-{next(self.numbers)}"
        answer = asyncio.get_running_loop().create_future()
        self.pending[number] = answer
        try:
            await self.written(Asking(request_id=number, request=Interrupting()))
            try:
                answered = await asyncio.wait_for(answer, self.patience.total_seconds())
            except TimeoutError as unanswered:
                message = (
                    f"Claude Code didn't answer the interrupt within {self.patience}"
                )
                raise HeldError(message) from unanswered
        finally:
            del self.pending[number]
        if answered.subtype == "error":
            message = f"Claude Code refused the interrupt: {answered.error}"
            raise HeldError(message)

    @override
    async def served(self) -> None:
        """Read each line Claude Code writes until its output ends; then fail each request still waiting for its answer.

        A line too long to read is read past, and said.
        """
        output = self.pipes.output
        while True:
            try:
                line = await output.readline()
            except ValueError:
                self.said("A line of the session's output was too long to read.")
                continue
            if not line:
                break
            await self.heard(line)
        for each in self.pending.values():
            if not each.done():
                each.set_exception(HeldError("the session ended before answering"))

    async def heard(self, line: bytes) -> None:
        """Take in one line Claude Code wrote: a turn's start or end, an answer, or a request of its own, refused; any other line is the turn's, and passed over.

        A line that doesn't read as what its type says is said and passed
        over, so reading goes on: a reader that stopped would leave the
        session blocked once its output filled.
        """
        try:
            raw = TypeAdapter[JsonValue](JsonValue).validate_json(line)
            await self.taken(Kind.model_validate(raw), raw)
        except ValidationError as unread:
            self.said(
                f"The session wrote a line of {len(line):,} bytes that doesn't read "
                f"as one of its messages: {unread.error_count()} errors."
            )

    async def taken(self, kind: Kind, raw: JsonValue) -> None:
        """Act on one line of Claude Code's, of the kind `kind`, raising `ValidationError` where it isn't what its kind says."""
        match kind:
            case Kind(type="system", subtype="init"):
                self.turning = True
                self.session = Started.model_validate(raw).session_id
                self.said("A turn started.")
            case Kind(type="result"):
                self.turning = False
                self.said(Ended.model_validate(raw).said())
            case Kind(type="control_response"):
                answer = Answered.model_validate(raw).response
                waiting = self.pending.get(answer.request_id)
                if waiting is not None and not waiting.done():
                    waiting.set_result(answer)
            case Kind(type="control_request"):
                asked = Asked.model_validate(raw)
                self.said(
                    f"The session asked the launcher {json.dumps(asked.request)}, "
                    "which it doesn't answer: refused."
                )
                await self.written(
                    Refusing(
                        response=Refusal(
                            request_id=asked.request_id,
                            error="lup's launcher takes no request of the session's",
                        )
                    )
                )
            case _:
                pass

    async def written(self, line: Model) -> None:
        """Put one line on the session's input, whole, and return at once, whether or not the runtime reads it; raise `HeldError` where its input is closed.

        Never waiting for the runtime to read it: any process of the room can
        stop the runtime, which then reads nothing, and a wait for its input to
        drain would hold the launcher's answer to the host with it. What isn't
        read yet waits in the launcher, the runtime reading it as it goes on.
        """
        writer = self.pipes.input
        if writer.is_closing():
            message = "the session's input is closed: its runtime has ended"
            raise HeldError(message)
        writer.write(f"{line.model_dump_json()}\n".encode())
