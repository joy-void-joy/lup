"""The dashboard's server: the page, and its API relaying the host service's requests, on localhost alone.

`docs/dashboard.md`, *The server* and *Access*. `POST /api/ask` sends one of the
host's requests the page may send (`api.Asked`) and returns its reply. The
page's watches are carried on one socket, `/api/socket`, each started and
stopped by its frames and its replies sent at once and again each time they
change (`Relay`): one connection however many it holds, where a browser keeps
six to a host. Everything else is the built page.

Rooms share the host's network, so being on localhost keeps nothing out but
other machines: every call to the API carries the dashboard's token, in its
cookie or as a bearer, and comes from the dashboard's own address. The page is
handed the token in its address's fragment, which no request carries, and trades
it for the cookie (`POST /api/session`).
"""

import asyncio
import hashlib
import secrets
from typing import TYPE_CHECKING, Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
)
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param
from pydantic import Field, TypeAdapter
from starlette.middleware.trustedhost import TrustedHostMiddleware

from lup.types import Model, MutableModel
from lup_dashboard.api import (
    Asked,
    Ended,
    Framed,
    Replied,
    Unwatch,
    Watch,
    Watched,
)
from lup_dashboard.host import Host
from lup_dev.host.protocol import HostError
from lup_dev.inbox.protocol import AnswerApproval, Reviewed, SendDraft, Settled
from lup_dev.inbox.store import Approval, Item

if TYPE_CHECKING:
    from pathlib import Path


class Access(Model):
    """Who may use the dashboard: whoever holds its token, from its own address."""

    token: str
    port: int
    """The port it listens on, on localhost."""
    hosts: list[str] = ["127.0.0.1", "localhost"]
    """The names it answers to: a request naming another host, as a page served
    elsewhere rebinding its name to localhost would, is refused."""

    def cookie(self) -> str:
        """Name the cookie the page holds the token in, once it's traded it: one per port, since a browser shares localhost's cookies across its ports, and two dashboards' would overwrite each other.

        >>> Access(token="t", port=8766).cookie()
        'lup-dashboard-8766'
        """
        return f"lup-dashboard-{self.port}"

    def origins(self) -> list[str]:
        """List the origins whose pages may call the API: the dashboard's own.

        >>> Access(token="t", port=8766).origins()
        ['http://127.0.0.1:8766', 'http://localhost:8766']
        """
        return [f"http://{host}:{self.port}" for host in self.hosts]


class About(Model):
    """What the page is served by: the dashboard, or its demo over stand-in data, and which build of the page it serves."""

    demo: bool
    build: str | None = None
    """The page's build as the dashboard serves it, a digest of its `index.html`, which
    names each of its assets by their content's hash; none where no page is
    served. A page served by another build reloads itself on reconnecting."""


class Relay(MutableModel, arbitrary_types_allowed=True):
    """The page's watches on its one socket: each a task sending the host's replies, numbered as the page numbered the watch, until it's stopped or the socket closes."""

    host: Host
    websocket: WebSocket
    watching: dict[int, asyncio.Task[None]] = {}
    sending: asyncio.Lock = Field(default_factory=asyncio.Lock)
    """Held while a frame is sent, so two watches' frames never interleave."""

    async def run(self) -> None:
        """Read the page's frames until it goes, starting and stopping its watches; then stop every one left."""
        try:
            async for text in self.websocket.iter_text():
                match TypeAdapter[Framed](Framed).validate_json(text):
                    case Watch(number=number, request=request):
                        self.stop(number)
                        relaying = asyncio.create_task(self.relayed(number, request))
                        self.watching = {**self.watching, number: relaying}
                    case Unwatch(number=number):
                        self.stop(number)
        finally:
            for number in list(self.watching):
                self.stop(number)

    async def relayed(self, number: int, request: Asked) -> None:
        """Send the host's replies to `request` as watch `number`'s, until the watch ends; then say why it ended, for the page to watch it again later."""
        try:
            async for replied in self.host.watch(request):
                await self.sent(Watched(number=number, reply=replied))
        except HostError as failure:
            await self.sent(Ended(number=number, why=str(failure)))
            return
        await self.sent(Ended(number=number, why="the host service closed the watch"))

    async def sent(self, frame: Watched | Ended) -> None:
        """Send one frame to the page."""
        async with self.sending:
            await self.websocket.send_text(frame.model_dump_json())

    def stop(self, number: int) -> None:
        """Stop watch `number`, where it runs."""
        relaying = self.watching.get(number)
        if relaying is not None:
            relaying.cancel()
        self.watching = {
            each: task for each, task in self.watching.items() if each != number
        }


def application(
    host: Host, access: Access, page: Path | None, *, demo: bool = False
) -> FastAPI:
    """Build the dashboard's server: its API relaying to `host`, open to `access`, and the built page in `page`; none serves the API alone, for its description. A demo says so (`GET /api/about`)."""
    app = FastAPI(
        title="lup's dashboard",
        openapi_url="/api/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=access.hosts)
    cookie = APIKeyCookie(name=access.cookie(), auto_error=False)
    bearer = HTTPBearer(auto_error=False)

    def authorized(
        held: Annotated[str | None, Depends(cookie)],
        given: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
        origin: Annotated[str | None, Header()] = None,
    ) -> None:
        """Refuse a call without the dashboard's token, in its cookie or as a bearer, or from a page of another origin."""
        if origin is not None and origin not in access.origins():
            raise HTTPException(status_code=403, detail=f"not from {origin}")
        token = held or (None if given is None else given.credentials) or ""
        if not secrets.compare_digest(token.encode(), access.token.encode()):
            raise HTTPException(
                status_code=401, detail="the dashboard's token is needed"
            )

    api = APIRouter(prefix="/api", dependencies=[Depends(authorized)])

    @api.post("/session", status_code=204)
    def session(response: Response) -> None:
        """Trade the token the page was handed for the cookie it calls the API with."""
        response.set_cookie(
            access.cookie(), access.token, httponly=True, samesite="strict", path="/"
        )

    @api.get("/about")
    def about() -> About:
        """Say what the page is served by: the dashboard, or its demo, and the page's build as it stands on disk, read again each time."""
        index = None if page is None else page / "index.html"
        build = (
            None
            if index is None or not index.is_file()
            else hashlib.sha256(index.read_bytes()).hexdigest()
        )
        return About(demo=demo, build=build)

    @api.post("/ask")
    async def ask(request: Asked) -> Replied:
        """Send one of the host's requests, and return its reply; an approval of a host zone approved here, by its answer or by sending the draft, is acted on, as the operator's terminal acts on it (`Host.settle`)."""
        replied = await host.ask(request)
        match request, replied:
            case (
                AnswerApproval(number=number, approved=True),
                Settled(item=Item(reason=Approval())),
            ):
                await host.settle(number)
            case SendDraft(), Reviewed(approved=approved):
                for item in approved:
                    if isinstance(item.reason, Approval):
                        await host.settle(item.number)
            case _:
                pass
        return replied

    @app.websocket("/api/socket")
    async def socket(
        websocket: WebSocket,
        held: Annotated[str | None, Cookie(alias=access.cookie())] = None,
        authorization: Annotated[str | None, Header()] = None,
        origin: Annotated[str | None, Header()] = None,
    ) -> None:
        """Carry the page's watches on one socket (`Relay`); closed at once for a page of another origin (4403) or without the token (4401), which the page tells from the dashboard being out of reach."""
        await websocket.accept()
        if origin is not None and origin not in access.origins():
            await websocket.close(code=4403, reason=f"not from {origin}")
            return
        _, given = get_authorization_scheme_param(authorization)
        token = held or given or ""
        if not secrets.compare_digest(token.encode(), access.token.encode()):
            await websocket.close(code=4401, reason="the dashboard's token is needed")
            return
        await Relay(host=host, websocket=websocket).run()

    @app.exception_handler(HostError)
    def unreachable(request: Request, failure: HostError) -> JSONResponse:
        """Say the host service couldn't be reached, as the API's answer."""
        del request
        return JSONResponse(status_code=503, content={"detail": str(failure)})

    app.include_router(api)
    if page is not None:
        app.frontend("/", directory=page)
    return app
