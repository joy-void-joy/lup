"""The dashboard's server: the page, and one socket carrying every view it watches.

The page opens the socket and says the token it was handed in its address's
fragment, which no request carries; the server then tells it the document's root
view and the project's kinds (`Opened`), and answers each view the page watches
(`Watch`), as the operator reads it, with its blocks or why it can't (`Answered`,
`Unanswered`), and again once what it shows changes. One socket for every watch, since
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
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, override

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, JsonValue, TypeAdapter, ValidationError
from pydantic.json_schema import GenerateJsonSchema

from lup.doors.door import Accepted, Refused
from lup.doors.parties import Operator
from lup.environment.doors import Running
from lup.environment.shell.layout import ShellLayout
from lup.environment.shell.viewing import viewed
from lup.shell.blocks import Block, BlockError, Blocks, Viewing
from lup.shell.draft import Comment, Commenting, Draft, Marked, Outcome, Quote
from lup.shell.looks import Looks
from lup.shell.wire import (
    Answered,
    Delivered,
    Drafted,
    Erase,
    Hello,
    Mark,
    Opened,
    Read,
    Send,
    Sent,
    Unanswered,
    Unwatch,
    Watch,
    Write,
)
from lup.types import Model, MutableModel

if TYPE_CHECKING:
    from pydantic_core.core_schema import (
        ComputedField,
        CoreSchema,
        DataclassField,
        ModelField,
        TypedDictField,
    )

log = logging.getLogger(__name__)


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


class Keeping(MutableModel, arbitrary_types_allowed=True):
    """The one draft, and the pages open on the dashboard, each told the draft as it changes."""

    draft: Draft = Draft()
    path: Path | None = None
    """Where the draft is kept across restarts of the server; none where it's
    kept in memory alone."""
    pages: list[Session] = []
    sending: asyncio.Lock = Field(default_factory=asyncio.Lock)
    """Held while the draft is sent, so two pages sending at once send each
    part once."""

    @classmethod
    def at(cls, path: Path) -> Keeping:
        """Return the draft kept at `path`, an empty one where none is kept there yet."""
        draft = (
            Draft.model_validate_json(path.read_text()) if path.exists() else Draft()
        )
        return cls(draft=draft, path=path)

    async def changed(self, draft: Draft, by: Session | None = None) -> None:
        """Keep `draft` in place of the draft, and tell every page open but `by`, the page that wrote the change, which holds it already.

        Told its own change back, a page would lay a copy older than what's
        been typed since over a comment being written.
        """
        self.draft = draft
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(draft.model_dump_json())
        for page in self.pages:
            if page is not by:
                await page.tell(Drafted(draft=draft))


class Dashboard(Model, arbitrary_types_allowed=True):
    """The dashboard of a running project: its page, and what its views answer the operator."""

    running: Running
    """The project's parts, made and running: what answers its views."""
    looks: Looks
    """The kinds its modules declare, which their views may name."""
    root: Viewing | None
    """The document's root view, as the core module names it (`Core.document`)."""
    kept: Keeping = Field(default_factory=Keeping)
    """The draft, and the pages open, which each change of it is told."""
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
            await Session(dashboard=self, socket=Carried(websocket=websocket)).run()

        if (page / "assets").is_dir():
            application.mount(
                "/assets", StaticFiles(directory=page / "assets"), name="assets"
            )
        return application

    async def answer(self, watch: int, viewing: Viewing) -> Answered | Unanswered:
        """Answer `viewing`, watched under `watch`, as the operator reads it."""
        if viewing.module is None:
            return Unanswered(watch=watch, reason=f"`{viewing.view}` names no module")
        try:
            answered = await viewed(
                self.running,
                self.looks,
                viewing.module,
                viewing.view,
                viewing.given,
                Operator(),
            )
        except BlockError as wrong:
            return Unanswered(watch=watch, reason=str(wrong))
        match answered:
            case Accepted(output=Blocks() as blocks):
                return Answered(watch=watch, blocks=blocks)
            case Accepted():
                return Unanswered(
                    watch=watch, reason=f"`{viewing.view}` answered no blocks"
                )
            case _:
                return Unanswered(watch=watch, reason=answered.rejection.reason)

    async def sent(self) -> Delivered:
        """Send the draft, one send at a time whichever pages ask: each comment and mark on its own, a comment that says nothing dropped rather than sent.

        Each part that went leaves the draft and each that can't stays in it
        with why, in the draft as it stands once the send ends, so what's
        written or erased while it runs is kept as it is; every page is told
        the draft. A comment on what changed since it was written stays the
        first time, saying so, and goes the next.
        """
        async with self.kept.sending:
            draft = self.kept.draft
            outcomes: dict[str, Outcome] = {
                **{
                    comment.id: (
                        await self.commented(comment)
                        if comment.words.strip()
                        else Outcome()
                    )
                    for comment in draft.comments
                },
                **{
                    mark.id: Outcome(reason=await self.acted(mark))
                    for mark in draft.marks
                },
            }
            await self.kept.changed(self.kept.draft.settled(draft, outcomes))
            said = [
                *(each.id for each in draft.comments if each.words.strip()),
                *(each.id for each in draft.marks),
            ]
            return Delivered(
                went=[part for part in said if outcomes[part].reason is None],
                stayed=[part for part in said if outcomes[part].reason is not None],
            )

    async def block(self, quote: Quote) -> Block | str:
        """Return the block `quote` is on, as its view answers at the send; why not, where it can't be read."""
        answered = await self.answer(0, quote.viewing)
        if isinstance(answered, Unanswered):
            return f"its view can't be read: {answered.reason}"
        found = next(
            (each for each in answered.blocks.every() if each.id == quote.block), None
        )
        return "what it's on is gone from its view" if found is None else found

    async def commented(self, comment: Comment) -> Outcome:
        """Send `comment` to what its block offers for comments, and say what came of it: why it stays, where it can't go, or was written on what changed since and hasn't been sent anyway once already."""
        block = await self.block(comment.on)
        if isinstance(block, str):
            return Outcome(reason=block)
        quote = comment.on
        if (
            quote.version is not None
            and block.version != quote.version
            and not comment.warned
        ):
            return Outcome(
                reason="what it's on changed since you wrote it: send again to send it anyway",
                outdated=True,
            )
        if comment.to is not None:
            # lup: defer(issue=8, why="a comment sent to a party the operator chose goes through the inbox's delivery, which #8 brings")
            return Outcome(reason="nothing delivers a comment to a chosen party yet")
        offer = next((each for each in block.offers if each.verb == "comment"), None)
        if offer is None:
            if block.reaches is not None:
                # lup: defer(issue=8, why="a comment on a block that offers none reaches its party through the inbox's delivery, which #8 brings")
                return Outcome(reason="nothing delivers a comment to a party yet")
            # lup: defer(issue=8, why="a comment on what reaches no party goes to the No agent pile, which #8's piles bring")
            return Outcome(
                reason="nothing delivers a comment that reaches no party yet"
            )
        commenting = Commenting(
            words=comment.words.strip(),
            lines=quote.lines,
            start=quote.start,
            end=quote.end,
            version=quote.version,
        )
        given: dict[str, JsonValue] = {
            **commenting.model_dump(mode="json"),
            "on": offer.given,
        }
        module = offer.module or quote.viewing.module or ""
        answered = await self.running.act(module, offer.action, given, Operator())
        return Outcome(
            reason=answered.rejection.reason if isinstance(answered, Refused) else None
        )

    async def acted(self, mark: Marked) -> str | None:
        """Run the action `mark` marks; why not, where it can't run, as on a block that changed since it was marked."""
        block = await self.block(mark.on)
        if isinstance(block, str):
            return block
        if mark.on.version is not None and block.version != mark.on.version:
            return "what it's on changed since it was marked"
        offer = mark.offer
        module = offer.module or mark.on.viewing.module or ""
        answered = await self.running.act(module, offer.action, offer.given, Operator())
        return answered.rejection.reason if isinstance(answered, Refused) else None


class Socket(ABC):
    """A page's socket, as the server reads and writes it: over the network, or in memory for the harness."""

    @abstractmethod
    async def received(self) -> str | None:
        """Return the page's next frame, as it sent it; none once it's gone."""

    @abstractmethod
    async def send(self, text: str) -> None:
        """Send the page a frame."""

    @abstractmethod
    async def close(self, code: int, reason: str) -> None:
        """Close the socket, saying why."""


class Carried(Socket, Model, arbitrary_types_allowed=True):
    """A page's socket over the network: a WebSocket of the server's."""

    websocket: WebSocket

    @override
    async def received(self) -> str | None:
        try:
            return await self.websocket.receive_text()
        except WebSocketDisconnect:
            return None

    @override
    async def send(self, text: str) -> None:
        await self.websocket.send_text(text)

    @override
    async def close(self, code: int, reason: str) -> None:
        await self.websocket.close(code=code, reason=reason)


class Session(Model, arbitrary_types_allowed=True):
    """One page's socket: what it watches, answered."""

    dashboard: Dashboard
    socket: Socket
    sending: asyncio.Lock = Field(default_factory=asyncio.Lock)

    async def run(self) -> None:
        """Read the page's frames until it goes, each answered or refused alone, every view watched answered at once, so a slow one holds up no other."""
        kept = self.dashboard.kept
        try:
            async with asyncio.TaskGroup() as answering:
                await self.read(answering)
        finally:
            kept.pages = [page for page in kept.pages if page is not self]

    async def read(self, answering: asyncio.TaskGroup) -> None:
        """Read the page's frames until it goes, each watched view answered as a task of `answering`."""
        reading = TypeAdapter[Sent](Sent)
        opened = False
        while (text := await self.socket.received()) is not None:
            try:
                frame = reading.validate_json(text)
            except ValidationError as wrong:
                await self.tell(
                    Unanswered(
                        watch=None, reason=f"a frame the server can't read: {wrong}"
                    )
                )
                continue
            if not opened and not isinstance(frame, Hello):
                await self.tell(Unanswered(watch=None, reason="say the token first"))
                continue
            match frame:
                case Hello(token=token):
                    if not hmac.compare_digest(token, self.dashboard.token):
                        await self.socket.close(4401, "not the dashboard's token")
                        return
                    opened = True
                    dashboard = self.dashboard
                    await self.tell(Opened(root=dashboard.root, looks=dashboard.looks))
                    dashboard.kept.pages = [*dashboard.kept.pages, self]
                    await self.tell(Drafted(draft=dashboard.kept.draft))
                case Watch(watch=watch, viewing=viewing):
                    answering.create_task(self.answered(watch, viewing))
                case Unwatch():
                    pass
                case Write(comment=comment):
                    kept = self.dashboard.kept
                    await kept.changed(kept.draft.written(comment), by=self)
                case Mark(marked=marked):
                    kept = self.dashboard.kept
                    await kept.changed(kept.draft.marked(marked), by=self)
                case Erase(id=part):
                    kept = self.dashboard.kept
                    await kept.changed(kept.draft.erased(part), by=self)
                case Send():
                    await self.tell(await self.dashboard.sent())

    async def answered(self, watch: int, viewing: Viewing) -> None:
        """Answer the view watched under `watch`, and tell the page."""
        await self.tell(await self.dashboard.answer(watch, viewing))

    async def tell(
        self, told: Opened | Answered | Unanswered | Drafted | Delivered
    ) -> None:
        """Send the page one frame, one at a time whichever task sends it."""
        async with self.sending:
            await self.socket.send(told.model_dump_json())


async def serve(dashboard: Dashboard, port: int) -> None:
    """Serve `dashboard` on localhost's `port` until stopped, saying where to open it."""
    log.warning("lup's dashboard: http://127.0.0.1:%d/#%s", port, dashboard.token)
    config = uvicorn.Config(
        dashboard.application(), host="127.0.0.1", port=port, log_level="warning"
    )
    await uvicorn.Server(config).serve()
