"""Standing a local-only page up, once, for every surface that has one.

:mod:`lup.web.loopback` already argued that binding loopback and checking the
``Host`` header belong together, and that a surface skipping the second had no
way of knowing it had. It then left the half that *invokes* them to each
application — so the supervisor and the setup dashboard each wrote their own
construct-guard-open-run sequence, and a third surface would have written a
third, with the same one line to forget.

What is shared is the whole sequence: refuse a non-loopback bind, build the
URL the guard will answer for, say where the page is, open it, serve it. What
differs is only the routes, which arrive as a factory taking the URL — it has
to, because the ``Host`` values a page answers for are derived from the port
it ends up on.
"""

import mimetypes
import webbrowser
from collections.abc import Callable
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath

import typer
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from lup.web.loopback import guard_loopback_host, refuse_non_loopback


def bundle_root(surface: str, bundles: Path | None = None) -> Traversable:
    """Where one built surface sits: under ``lup.web``'s package data, or a tree named.

    Refused with the command that builds it where nothing is built, so a
    missing bundle is a clear sentence rather than a directory listing or a
    file-not-found somewhere inside a request.
    """
    root: Traversable = (
        bundles / surface
        if bundles is not None
        else resources.files("lup.web").joinpath("bundles", surface)
    )
    if not root.joinpath("index.html").is_file():
        raise ValueError(
            f"no bundle is built for the {surface!r} surface; run"
            " `uv run lup-devtools harness generate all` with bun installed"
        )
    return root


class BundleAssets(BaseModel, frozen=True):
    """The pieces of one built surface a page carries inline: its scripts and styles."""

    scripts: list[str]
    styles: list[str]


def bundle_assets(surface: str, bundles: Path | None = None) -> BundleAssets:
    """One built surface's scripts and stylesheets, read whole, in name order.

    For a page that has to carry the surface itself — an export opened from a
    file, with no server to answer for ``assets/``. The build emits one
    script and one stylesheet per surface, so a name order is an order.
    """
    root = bundle_root(surface, bundles)
    found = sorted(
        (entry for entry in root.joinpath("assets").iterdir() if entry.is_file()),
        key=lambda entry: entry.name,
    )
    return BundleAssets(
        scripts=[
            entry.read_text(encoding="utf-8")
            for entry in found
            if PurePosixPath(entry.name).suffix == ".js"
        ],
        styles=[
            entry.read_text(encoding="utf-8")
            for entry in found
            if PurePosixPath(entry.name).suffix == ".css"
        ],
    )


def bundle_app(
    title: str, url: str, surface: str, bundles: Path | None = None
) -> FastAPI:
    """A Host-guarded app serving one built surface: its page and its assets.

    The third shape beside a generated page and an edited asset: a bundle
    Vite built from TypeScript into ``lup.web``'s package data, under
    ``bundles/<surface>/``. Served by name rather than mounted as a directory,
    so a request reaches exactly one file the bundle declares and nothing
    else the package holds — and a missing bundle is a clear refusal naming
    the command that builds it, not a directory listing.
    """
    root = bundle_root(surface, bundles)
    index = root.joinpath("index.html")
    application = page_app(title, url, index.read_text(encoding="utf-8"))

    @application.get("/assets/{name}")
    async def asset(name: str) -> Response:
        # One plain filename under the bundle's own assets, nothing deeper:
        # a name carrying a separator is refused before it reaches the tree.
        if Path(name).name != name:
            raise HTTPException(status_code=404)
        found = root.joinpath("assets", name)
        if not found.is_file():
            raise HTTPException(status_code=404)
        media_type, _encoding = mimetypes.guess_type(name)
        return Response(
            content=found.read_bytes(),
            media_type=media_type or "application/octet-stream",
        )

    return application


def page_app(title: str, url: str, html: str) -> FastAPI:
    """A Host-guarded app serving one page of HTML at ``/``.

    Takes the markup rather than a package to read it from, so a surface that
    *generates* its page has somewhere to hand it. That is the safer of the two
    by construction: an asset file has to be named in ``package-data`` to reach
    a wheel, and one that is not turns every request to ``/`` into a
    ``FileNotFoundError`` that nothing catches until somebody opens the page.

    The docs routes are off because a local-only page has no audience for
    them and they widen what an attacker reaching this origin can enumerate.
    """
    application = FastAPI(title=title, docs_url=None, redoc_url=None)
    guard_loopback_host(application, url)

    @application.get("/", response_class=HTMLResponse)
    async def home() -> HTMLResponse:
        return HTMLResponse(html)

    return application


def local_page_app(title: str, package: str, url: str) -> FastAPI:
    """A Host-guarded app serving one package's ``assets/index.html`` at ``/``.

    For a page that genuinely is a file somebody edits. A generated one should
    reach :func:`page_app` directly rather than being written out to be read
    back, which is the round trip that loses the file on the way to a wheel.
    """
    html = resources.files(package).joinpath("assets/index.html").read_text("utf-8")
    return page_app(title, url, html)


def serve_local_page(
    build: Callable[[str], FastAPI],
    surface: str,
    host: str,
    port: int,
    open_page: bool = True,
) -> None:
    """Bind loopback and serve one page, announcing where it came up.

    ``surface`` names this page in the refusal a bad ``--host`` earns and in
    the line pointing a reader at it, so the message says which of several
    local surfaces is being talked about.

    Raises ``ValueError`` when ``host`` is not a loopback address — the
    caller is a CLI and turns that into whatever its own framework spells a
    bad parameter as.
    """
    refuse_non_loopback(host, surface)
    url = f"http://{host}:{port}"
    typer.echo(f"{surface}: {url}")
    if open_page:
        webbrowser.open(url)
    uvicorn.run(build(url), host=host, port=port)
