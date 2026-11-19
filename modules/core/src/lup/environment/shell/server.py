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
from lup.environment.shell.review import Going, reviewed
from lup.environment.shell.viewing import viewed
from lup.inbox.records import NO_AGENT
from lup.inbox.said import Pile, Reached
from lup.shell.blocks import Block, BlockError, Blocks, Fold, Offer, Viewing
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
    Reviewed,
    Send,
    Sent,
    Unanswered,
    Unwatch,
    Watch,
    Write,
)
from lup.types import Model, MutableModel
lazy from lup.core import Core
lazy from lup.inbox.part import Inboxes

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
    review: Blocks = Blocks()
    """What the next send would do with the draft, as the review in the
    page's window shows it."""
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

    def keep(self, draft: Draft) -> None:
        """Keep `draft` in place of the draft, where it's kept across restarts too."""
        self.draft = draft
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(draft.model_dump_json())


class Placed(Model):
    """A quoted block as its view answers it at a send, and whom a comment on it reaches, found through the folds holding it."""

    block: Block
    reaches: dict[str, JsonValue] | None = None


class Taken(Model):
    """What takes a comment at a send: the command it's given to, offered as its block offers one, and whom it reaches, as the review says it."""

    offer: Offer
    to: str


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
    repository: str | None = None
    """The repository the dashboard serves, whose No agent pile takes a comment
    on what reaches no party; none where nothing takes one."""

    async def changed(self, draft: Draft, by: Session | None = None) -> None:
        """Keep `draft` in place of the draft, tell every page open but `by`, the page that wrote the change, which holds it already, and lay the review out again for every page.

        Told its own change back, a page would lay a copy older than what's
        been typed since over a comment being written.
        """
        self.kept.keep(draft)
        self.kept.review = reviewed(draft, await self.going(draft))
        for page in self.kept.pages:
            if page is not by:
                await page.tell(Drafted(draft=draft))
            await page.tell(Reviewed(review=self.kept.review))

    async def going(self, draft: Draft) -> list[Going]:
        """Say where each comment of `draft` not held back goes at the next send, or why it can't, each block read once."""
        read: dict[str, Placed | str] = {}
        return [
            await self.goes(comment, read)
            for comment in draft.comments
            if not comment.held
        ]

    async def goes(self, comment: Comment, read: dict[str, Placed | str]) -> Going:
        """Say where `comment` goes at the next send, or why it can't, what it's on read once for every comment on it (`read`)."""
        key = comment.on.model_dump_json(
            include={"viewing": True, "block": True, "within": True}
        )
        if key not in read:
            read[key] = await self.placed(comment.on)
        placed = read[key]
        if isinstance(placed, str):
            return Going(part=comment.id, to="to what can't be read", stays=placed)
        taken = self.taking(comment, placed)
        if isinstance(taken, str):
            return Going(part=comment.id, to="to no one", stays=taken)
        return Going(part=comment.id, to=taken.to)

    def taking(self, comment: Comment, placed: Placed) -> Taken | str:
        """Return what takes `comment`, and whom it reaches: its block's own comment, unless the operator chose whom it reaches; else the inbox, telling the party chosen, the one what it's on reaches, or the No agent pile where it reaches none; why nothing does, where nothing does."""
        offers = placed.block.offers
        offer = next((each for each in offers if each.verb == "comment"), None)
        if comment.to is None and offer is not None:
            reaches = placed.reaches
            to = (
                f"on {comment.on.viewing.view}"
                if reaches is None
                else f"to {named(reaches)}"
            )
            return Taken(offer=offer, to=to)
        party = comment.to or placed.reaches
        if party is None and self.repository is not None:
            party = Pile(repository=self.repository, path=NO_AGENT).model_dump(
                mode="json"
            )
        if party is None:
            return "it reaches no party, and no pile takes what reaches none"
        said = named(party)
        try:
            reached = Reached.model_validate({"party": party})
        except ValidationError:
            return f"nothing tells {said} a comment"
        offer = Offer.of(Inboxes.comment_to, reached).model_copy(
            update={"module": Core.name}
        )
        return Taken(offer=offer, to=f"to {said}")

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
        first time, saying so, and goes the next. A part the operator holds
        back isn't sent, and stays as it is.
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
                    if not comment.held
                },
                **{
                    mark.id: Outcome(reason=await self.acted(mark))
                    for mark in draft.marks
                    if not mark.held
                },
            }
            await self.changed(self.kept.draft.settled(draft, outcomes))
            said = [
                *(
                    each.id
                    for each in draft.comments
                    if each.words.strip() and not each.held
                ),
                *(each.id for each in draft.marks if not each.held),
            ]
            return Delivered(
                went=[part for part in said if outcomes[part].reason is None],
                stayed=[part for part in said if outcomes[part].reason is not None],
                held=[each.id for each in [*draft.comments, *draft.marks] if each.held],
            )

    async def around(self, viewing: Viewing, block: str) -> list[Block] | str:
        """Return the block of id `block` as `viewing` answers it, then each fold holding it in that answer, innermost first; why not, where it can't be read."""

        def path(blocks: list[Block]) -> list[Block] | None:
            """Return the block of id `block` among `blocks`, then each fold holding it there; none where they hold none."""
            for each in blocks:
                if each.id == block:
                    return [each]
                if isinstance(each, Fold) and isinstance(each.content, list):
                    found = path(each.content)
                    if found is not None:
                        return [*found, each]
            return None

        answered = await self.answer(0, viewing)
        if isinstance(answered, Unanswered):
            return f"its view can't be read: {answered.reason}"
        found = path(answered.blocks.blocks)
        return "what it's on is gone from its view" if found is None else found

    async def block(self, quote: Quote) -> Block | str:
        """Return the block `quote` is on, as its view answers at the send; why not, where it can't be read."""
        around = await self.around(quote.viewing, quote.block)
        return around if isinstance(around, str) else around[0]

    async def placed(self, quote: Quote) -> Placed | str:
        """Return the block `quote` is on as its view answers at the send, and whom a comment on it reaches; why not, where it can't be read."""
        around = await self.around(quote.viewing, quote.block)
        if isinstance(around, str):
            return around
        return Placed(block=around[0], reaches=await self.reached(quote, around))

    async def reached(
        self, quote: Quote, around: list[Block]
    ) -> dict[str, JsonValue] | None:
        """Return whom a comment on the first of `around`, the block `quote` is on and the folds holding it in its view, reaches: the first of them naming a party, else the first fold the view was read under (`Quote.within`) that does, or a block holding it; none where none does."""
        for each in around:
            if each.reaches is not None:
                return each.reaches.model_dump(mode="json")
        for under in quote.within:
            outer = await self.around(under.viewing, under.block)
            found = (
                None
                if isinstance(outer, str)
                else next((each.reaches for each in outer if each.reaches), None)
            )
            if found is not None:
                return found.model_dump(mode="json")
        return None

    async def commented(self, comment: Comment) -> Outcome:
        """Send `comment` to what its block offers for comments, and say what came of it: why it stays, where it can't go, or was written on what changed since and hasn't been sent anyway once already."""
        placed = await self.placed(comment.on)
        if isinstance(placed, str):
            return Outcome(reason=placed)
        quote = comment.on
        if (
            quote.version is not None
            and placed.block.version != quote.version
            and not comment.warned
        ):
            return Outcome(
                reason="what it's on changed since you wrote it: send again to send it anyway",
                outdated=True,
            )
        taken = self.taking(comment, placed)
        if isinstance(taken, str):
            return Outcome(reason=taken)
        offer = taken.offer
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
        answered = await self.running.run(module, offer.command, given, Operator())
        return Outcome(
            reason=answered.rejection.reason if isinstance(answered, Refused) else None
        )

    async def acted(self, mark: Marked) -> str | None:
        """Run the command `mark` marks; why not, where it can't run, as on a block that changed since it was marked."""
        block = await self.block(mark.on)
        if isinstance(block, str):
            return block
        if mark.on.version is not None and block.version != mark.on.version:
            return "what it's on changed since it was marked"
        offer = mark.offer
        module = offer.module or mark.on.viewing.module or ""
        answered = await self.running.run(
            module, offer.command, offer.given, Operator()
        )
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
                    kept = dashboard.kept
                    kept.review = reviewed(
                        kept.draft, await dashboard.going(kept.draft)
                    )
                    await self.tell(Drafted(draft=kept.draft))
                    await self.tell(Reviewed(review=kept.review))
                case Watch(watch=watch, viewing=viewing):
                    answering.create_task(self.answered(watch, viewing))
                case Unwatch():
                    pass
                case Write(comment=comment):
                    kept = self.dashboard.kept
                    await self.dashboard.changed(kept.draft.written(comment), by=self)
                case Mark(marked=marked):
                    kept = self.dashboard.kept
                    await self.dashboard.changed(kept.draft.marked(marked), by=self)
                case Erase(id=part):
                    kept = self.dashboard.kept
                    await self.dashboard.changed(kept.draft.erased(part), by=self)
                case Send():
                    await self.tell(await self.dashboard.sent())

    async def answered(self, watch: int, viewing: Viewing) -> None:
        """Answer the view watched under `watch`, and tell the page."""
        await self.tell(await self.dashboard.answer(watch, viewing))

    async def tell(
        self, told: Opened | Answered | Unanswered | Drafted | Delivered | Reviewed
    ) -> None:
        """Send the page one frame, one at a time whichever task sends it."""
        async with self.sending:
            await self.socket.send(told.model_dump_json())


def named(party: JsonValue) -> str:
    """Say a party as the review and a comment's line say whom it reaches: what identifies it, as its fields give it, but which of the core's parties it is.

    >>> named({"party": "pile", "repository": "lup", "path": "no-agent"})
    'lup no-agent'
    """
    if not isinstance(party, dict):
        return str(party)
    return " ".join(str(value) for key, value in party.items() if key != "party")


async def serve(dashboard: Dashboard, port: int) -> None:
    """Serve `dashboard` on localhost's `port` until stopped, saying where to open it."""
    log.warning("lup's dashboard: http://127.0.0.1:%d/#%s", port, dashboard.token)
    config = uvicorn.Config(
        dashboard.application(), host="127.0.0.1", port=port, log_level="warning"
    )
    await uvicorn.Server(config).serve()
