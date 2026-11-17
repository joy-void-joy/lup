"""The dashboard's server: the page, and one socket carrying every view it watches.

The page opens the socket and says the token it was handed in its address's
fragment, which no request carries; the server then tells it the document's root
view and the project's kinds (`Opened`), and answers each view the page watches
(`Watch`), as the operator reads it, with its blocks or why it can't (`Answered`,
`Refused`), and again once what it shows changes. One socket for every watch, since
a browser keeps few connections to a host; a frame the server can't read is
refused alone, never closing the socket (`README.md` in `lup/shell/`, *The server*).

Until the program on the host runs services (#3), it's started as the core's
command, `dashboard`; #3 then runs the same application as the dashboard's
service, from a commit the operator approved, since it holds their approvals.
"""

import asyncio
import hmac
import json
import logging
import secrets
from typing import TYPE_CHECKING, Annotated, Literal, override

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, TypeAdapter, ValidationError
from pydantic.json_schema import GenerateJsonSchema

from lup.core import Core
from lup.doors.door import Accepted
from lup.doors.parties import Operator
from lup.environment.declaration import Resolved
from lup.environment.shell.layout import ShellLayout
from lup.environment.shell.looks import Looks, viewed
from lup.shell.blocks import BlockError, Blocks, Viewing
from lup.types import Model

if TYPE_CHECKING:
    from pydantic_core.core_schema import (
        ComputedField,
        CoreSchema,
        DataclassField,
        ModelField,
        TypedDictField,
    )

log = logging.getLogger(__name__)


class Hello(Model):
    """The page's first frame: the token it was handed."""

    kind: Literal["hello"] = "hello"
    token: str


class Watch(Model):
    """Read a view, and again each time what it shows changes, under a number the page picks."""

    kind: Literal["watch"] = "watch"
    watch: int
    viewing: Viewing


class Unwatch(Model):
    """Stop reading the view watched under a number."""

    kind: Literal["unwatch"] = "unwatch"
    watch: int


type Sent = Annotated[Hello | Watch | Unwatch, Field(discriminator="kind")]
"""What the page sends the server."""


class Opened(Model):
    """What the page is told once its token is read: the document's root view, and the kinds a project's modules declare."""

    kind: Literal["opened"] = "opened"
    root: Viewing | None
    looks: Looks


class Answered(Model):
    """What a view watched answers."""

    kind: Literal["answered"] = "answered"
    watch: int
    blocks: Blocks


class Refused(Model):
    """Why a frame the page sent isn't answered: a view it can't read, or a frame the server can't."""

    kind: Literal["refused"] = "refused"
    watch: int | None
    """The watch it's about, where it's about one."""
    reason: str


type Told = Annotated[Opened | Answered | Refused, Field(discriminator="kind")]
"""What the server tells the page."""


class Read(Model):
    """What the page reads from the core and sends it: a view's answer, the kinds a project's modules declare, and every frame the socket carries, the page's types generated from its description (`described`)."""

    blocks: Blocks
    looks: Looks
    sent: Sent
    told: Told


class AsSent(GenerateJsonSchema):
    """JSON Schema of a model as it's sent: every field there, a default one among them, since dumping a model writes each; and no field titled, so a type generated from it is named after its model alone."""

    @override
    def field_title_should_be_set(
        self,
        schema: CoreSchema
        | ModelField
        | DataclassField
        | TypedDictField
        | ComputedField,
    ) -> bool:
        return False

    @override
    def field_is_required(
        self,
        field: ModelField | DataclassField | TypedDictField,
        total: bool,
    ) -> bool:
        return True


def described() -> str:
    """Describe what the page reads from the core, as JSON Schema of what's sent, which the page's types are generated from, so the two can't disagree."""
    schema = Read.model_json_schema(mode="serialization", schema_generator=AsSent)
    return json.dumps(schema, indent=2)


class Dashboard(Model, arbitrary_types_allowed=True):
    """The dashboard of a resolved declaration: its page, and what its views answer the operator."""

    resolved: Resolved
    token: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    """What the page has to say before anything is answered: rooms reach every
    port on the operator's machine, so being on localhost keeps nothing out."""
    layout: ShellLayout = ShellLayout()

    def application(self) -> FastAPI:
        """Return the server's application: the page, its assets, and the socket."""
        application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        page = self.layout.page

        @application.get("/")
        async def index() -> FileResponse:
            """Serve the page."""
            return FileResponse(page / "index.html")

        @application.websocket("/api/socket")
        async def socket(websocket: WebSocket) -> None:
            """Carry every view the page watches, once it's said the token."""
            await websocket.accept()
            await Session(dashboard=self, websocket=websocket).run()

        if (page / "assets").is_dir():
            application.mount(
                "/assets", StaticFiles(directory=page / "assets"), name="assets"
            )
        return application

    def root(self) -> Viewing | None:
        """Return the document's root view, as the core module of the declaration names it."""
        return next(
            (
                module.document
                for module in self.resolved.modules
                if isinstance(module, Core)
            ),
            None,
        )

    async def answer(self, watch: int, viewing: Viewing) -> Answered | Refused:
        """Answer `viewing`, watched under `watch`, as the operator reads it."""
        if viewing.module is None:
            return Refused(watch=watch, reason=f"`{viewing.view}` names no module")
        try:
            answered = await viewed(
                self.resolved.doors,
                self.resolved.looks,
                viewing.module,
                viewing.view,
                viewing.given,
                Operator(),
            )
        except BlockError as wrong:
            return Refused(watch=watch, reason=str(wrong))
        match answered:
            case Accepted(output=Blocks() as blocks):
                return Answered(watch=watch, blocks=blocks)
            case Accepted():
                return Refused(
                    watch=watch, reason=f"`{viewing.view}` answered no blocks"
                )
            case _:
                return Refused(watch=watch, reason=answered.rejection.reason)


class Session(Model, arbitrary_types_allowed=True):
    """One page's socket: what it watches, answered."""

    dashboard: Dashboard
    websocket: WebSocket
    sending: asyncio.Lock = Field(default_factory=asyncio.Lock)

    async def run(self) -> None:
        """Read the page's frames until it goes, each answered or refused alone, every view watched answered at once, so a slow one holds up no other."""
        async with asyncio.TaskGroup() as answering:
            await self.read(answering)

    async def read(self, answering: asyncio.TaskGroup) -> None:
        """Read the page's frames until it goes, each watched view answered as a task of `answering`."""
        reading = TypeAdapter[Sent](Sent)
        opened = False
        try:
            while True:
                text = await self.websocket.receive_text()
                try:
                    frame = reading.validate_json(text)
                except ValidationError as wrong:
                    await self.tell(
                        Refused(
                            watch=None, reason=f"a frame the server can't read: {wrong}"
                        )
                    )
                    continue
                if not opened and not isinstance(frame, Hello):
                    await self.tell(Refused(watch=None, reason="say the token first"))
                    continue
                match frame:
                    case Hello(token=token):
                        if not hmac.compare_digest(token, self.dashboard.token):
                            await self.websocket.close(
                                code=4401, reason="not the dashboard's token"
                            )
                            return
                        opened = True
                        looks = self.dashboard.resolved.looks
                        await self.tell(Opened(root=self.dashboard.root(), looks=looks))
                    case Watch(watch=watch, viewing=viewing):
                        answering.create_task(self.answered(watch, viewing))
                    case Unwatch():
                        pass
        except WebSocketDisconnect:
            return

    async def answered(self, watch: int, viewing: Viewing) -> None:
        """Answer the view watched under `watch`, and tell the page."""
        await self.tell(await self.dashboard.answer(watch, viewing))

    async def tell(self, told: Opened | Answered | Refused) -> None:
        """Send the page one frame, one at a time whichever task sends it."""
        async with self.sending:
            await self.websocket.send_text(told.model_dump_json())


async def serve(dashboard: Dashboard, port: int) -> None:
    """Serve `dashboard` on localhost's `port` until stopped, saying where to open it."""
    log.warning("lup's dashboard: http://127.0.0.1:%d/#%s", port, dashboard.token)
    config = uvicorn.Config(
        dashboard.application(), host="127.0.0.1", port=port, log_level="warning"
    )
    await uvicorn.Server(config).serve()
