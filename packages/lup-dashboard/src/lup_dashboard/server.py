"""The dashboard's server: the page, and its API relaying the host service's requests, on localhost alone.

`docs/dashboard.md`, *The server* and *Access*. `POST /api/ask` sends one of the
host's requests the page may send (`api.Asked`) and returns its reply;
`POST /api/watch` streams its replies as server-sent events, at once and again
each time they change. Everything else is the built page.

Rooms share the host's network, so being on localhost keeps nothing out but
other machines: every call to the API carries the dashboard's token, in its
cookie or as a bearer, and comes from the dashboard's own address. The page is
handed the token in its address's fragment, which no request carries, and trades
it for the cookie (`POST /api/session`).
"""

import secrets
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING, Annotated

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from fastapi.sse import EventSourceResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from lup.types import Model
from lup_dashboard.api import Asked, Replied
from lup_dev.host.protocol import HostError

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dashboard.host import Host


class Access(Model):
    """Who may use the dashboard: whoever holds its token, from its own address."""

    token: str
    port: int
    """The port it listens on, on localhost."""
    cookie: str = "lup-dashboard"
    """The cookie the page holds the token in, once it's traded it."""
    hosts: list[str] = ["127.0.0.1", "localhost"]
    """The names it answers to: a request naming another host, as a page served
    elsewhere rebinding its name to localhost would, is refused."""

    def origins(self) -> list[str]:
        """List the origins whose pages may call the API: the dashboard's own.

        >>> Access(token="t", port=8766).origins()
        ['http://127.0.0.1:8766', 'http://localhost:8766']
        """
        return [f"http://{host}:{self.port}" for host in self.hosts]


class About(Model):
    """What the page is served by: the dashboard, or its demo over stand-in data."""

    demo: bool


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
    cookie = APIKeyCookie(name=access.cookie, auto_error=False)
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
            access.cookie, access.token, httponly=True, samesite="strict", path="/"
        )

    @api.get("/about")
    def about() -> About:
        """Say what the page is served by: the dashboard, or its demo."""
        return About(demo=demo)

    @api.post("/ask")
    async def ask(request: Asked) -> Replied:
        """Send one of the host's requests, and return its reply."""
        return await host.ask(request)

    @api.post("/watch", response_class=EventSourceResponse)
    async def watch(request: Asked) -> AsyncIterable[Replied]:
        """Stream the host's replies to one of its requests: at once, then again each time they change."""
        async for replied in host.watch(request):
            yield replied

    @app.exception_handler(HostError)
    def unreachable(request: Request, failure: HostError) -> JSONResponse:
        """Say the host service couldn't be reached, as the API's answer."""
        del request
        return JSONResponse(status_code=503, content={"detail": str(failure)})

    app.include_router(api)
    if page is not None:
        app.frontend("/", directory=page)
    return app
