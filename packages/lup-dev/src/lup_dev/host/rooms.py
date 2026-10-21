"""A launch's room sockets beside its hook: lup's tools on `mcp.sock`, the room's requests on `request.sock`.

`docs/host.md`, *How a room reaches it*. Each launch the host
service serves has two more sockets in its socket directory, which its room
mounts at `/run/lup`:
- `mcp.sock` serves lup's tools to the launch's session, one MCP session per
  connection, through the library's `serve`. The tools are the modules'
  (`RoomTools`), composed for the launch (`LaunchTools`): each call goes to the
  module serving its tool, with the launch and the conversation calling. Who's
  calling is the `caller` the hook stamped into the call's arguments, the one
  field of them the server reads, taken out before the tool sees them. A call
  with none, whose hook didn't run, is taken as the launch's main conversation's,
  and the service says so; one naming a conversation no hook named isn't run.
- `request.sock` takes one JSON request per connection, told apart by its
  `kind`, and gives one JSON reply, as the control socket does, from the room's
  programs rather than the agent's tools. Its routes are the modules'
  `RoomHandler`s, each answering with the launch the request came from, which the
  service knows by the socket; apart from the control socket's `Handler`s, so a
  room never reaches a control kind that writes. Those that only read are
  routed there too, each answered for the launch's repository alone
  (`Reading`, `host/service.py`).

Both open and close with the launch, and are served again after a restart, as
`hook.sock` is (`host/service.py`).
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, override

from pydantic import JsonValue, ValidationError

from lup.tools.serving import Answer, Toolset
from lup.types import JsonObject, Model
from lup_dev.host.courier import Conversation, Conversations
from lup_dev.host.protocol import Register, Reply, Request

if TYPE_CHECKING:
    from lup.tools.tool import ToolSpec

SERVER = "lup"
"""The name lup's tool server goes by in a launched session, which each runtime
names its tools after."""


def summaries(tools: list[ToolSpec]) -> list[str]:
    """Return a line for each tool, its name and its summary, as a session is told lup's tools: in its guidance, and a subagent at its first hook.

    >>> from lup.tools.speaking import note
    >>> summaries([note.spec()])
    ['- `note`: Attach a remark to your answer, and carry on.']
    """
    return [f"- `{tool.name}`: {tool.summary}" for tool in tools]


class RoomTools(ABC):
    """A module's tools in a launched session: what it serves, and each call to them."""

    @abstractmethod
    def specs(self) -> list[ToolSpec]:
        """Return what the session is told about each tool this serves."""

    @abstractmethod
    async def call(
        self,
        name: str,
        arguments: JsonValue,
        launch: Register,
        caller: Conversation,
        call: str | None,
    ) -> Answer:
        """Run a call to the tool `name` for `caller`, a conversation of `launch`, and return what the model reads.

        The arguments are the model's, as it sent them: the tool validates them.
        `call` is the runtime's id for the call, where its hook stamped it.
        """


class RoomHandler[R: Request](ABC):
    """Answers one kind of request from a room's programs, with the launch it came from."""

    @abstractmethod
    def request(self) -> type[R]:
        """Return the model of the requests this answers: its `kind` routes them here."""

    @abstractmethod
    async def answer(self, request: R, launch: Register) -> Reply:
        """Answer one request from `launch`'s room, on the service's event loop, off it where it blocks.

        A `HostError` refuses the request with its message.
        """


class RoomRoute(Model, arbitrary_types_allowed=True):
    """A room's handler as the service dispatches to it: its kind, and its answer to the JSON from a launch."""

    kind: str
    answer: Callable[[str, Register], Awaitable[Reply]]

    @classmethod
    def to[R: Request](cls, handler: RoomHandler[R]) -> RoomRoute:
        """Route the requests of `handler`'s kind to it, each read as its model."""
        model = handler.request()

        async def answered(raw: str, launch: Register) -> Reply:
            return await handler.answer(model.model_validate_json(raw), launch)

        return cls(kind=model.named(), answer=answered)


class Stamped(Model, extra="allow"):
    """A call's arguments as the server reads them: the `caller` and `call` its hook stamped, and the rest, the tool's."""

    caller: str | None = None
    """lup's id for the conversation calling; none where no hook stamped it."""
    call: str | None = None
    """The runtime's id for the call, as its record keeps it: what an item the
    call makes is anchored to."""

    def given(self) -> JsonObject:
        """Return the arguments the tool reads: all but what the hook stamped."""
        return dict(self.model_extra or {})


def stamp(arguments: JsonObject, caller: str, call: str) -> JsonObject:
    """Return a call's arguments carrying `caller` and `call`, as a hook rewrites a call to lup's tools for the server to read.

    The model's own `caller` or `call`, where it wrote one, gives way to lup's.

    >>> stamp({"text": "hi", "caller": "mine"}, "c1", "t1")
    {'text': 'hi', 'caller': 'c1', 'call': 't1'}
    """
    return {**arguments, **Stamped(caller=caller, call=call).model_dump()}


class LaunchTools(Model, Toolset, arbitrary_types_allowed=True):
    """The modules' tools as one launch's session is served them: each call to the module serving its tool."""

    launch: Register
    tools: list[RoomTools]
    conversations: Conversations
    """The launch's conversations, as its hooks named them."""
    say: Callable[[str], None]

    @override
    def specs(self) -> list[ToolSpec]:
        return [spec for tools in self.tools for spec in tools.specs()]

    @override
    async def call(self, name: str, arguments: JsonValue) -> Answer:
        """Route the call to the module serving `name`, with the launch and the conversation its `caller` names.

        A call with no `caller` is taken as the launch's main conversation's, and
        said; one whose `caller` no hook of the launch minted isn't run.
        """
        serving = [
            tools
            for tools in self.tools
            if any(spec.name == name for spec in tools.specs())
        ]
        if not serving:
            return Answer(text=f"lup serves no tool named `{name}`", error=True)
        [owner] = serving
        match arguments:
            case dict():
                try:
                    stamped = Stamped.model_validate(arguments)
                except ValidationError as unread:
                    return Answer(
                        text=f"this call's `caller` isn't one lup's hook stamps: {unread}",
                        error=True,
                    )
                given: JsonValue = stamped.given()
            case _:
                stamped, given = Stamped(), arguments
        stamp = stamped.caller
        if stamp is not None:
            caller = self.conversations.calling(stamp)
            if caller is None:
                return Answer(
                    text=(
                        f"lup doesn't know the conversation `{stamp}` this call names, "
                        "so it wasn't run; calling it again names yours"
                    ),
                    error=True,
                )
            return await owner.call(name, given, self.launch, caller, stamped.call)
        main = self.conversations.main()
        if main is None:
            return Answer(
                text=(
                    "lup can't tell who's calling: no hook of this session has reached "
                    "it, so this call wasn't run"
                ),
                error=True,
            )
        self.say(
            f"{self.launch.launch}: a call to `{name}` carried no `caller`, so it's "
            f"taken as the main conversation's, {main.id}"
        )
        return await owner.call(name, given, self.launch, main, stamped.call)
