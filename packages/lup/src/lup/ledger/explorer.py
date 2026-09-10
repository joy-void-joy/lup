"""The ledger explorer: a data explorer over the log, served or exported.

The worked example this answers was an 18 MB single HTML file — curated
trails as list and detail, every record searchable, a topic register, browser
history for every view, the whole dataset embedded so a memo attachment opened
with no server behind it. This is that shape over the ledger, generic over
whatever kinds a project declared: the page is the TypeScript surface Vite
built into `lup.web`'s package data, and what it reads is the same view
models the tool group returns, served here as JSON routes or embedded whole
for an export.

**Two ways to open it, one page.** `serve` answers the routes on the loopback
and the page fetches them; `export` writes one self-contained file. The data
rides in an attribute of the mount point, escaped by the standard library, so
a node whose text happens to contain a closing tag cannot break the page it is
shown on; the script and the stylesheet ride inline, a ``<script>`` and a
``<style>`` element holding the served bundle's own bytes, which the build
made safe to inline when it built them.
"""

from datetime import datetime
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException

from lup.channels.models import utc_now
from lup.coordination.identity import mint_member_id
from lup.coordination.refs import ActorRef
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerEdge, LedgerNode
from lup.ledger.store import LedgerPlacement, SharedStore
from lup.ledger.views import (
    ExportView,
    GraphView,
    KindsView,
    NodeDetail,
    graph_view,
    kinds_view,
    node_detail,
)
from lup.web.serve import BundleAssets, bundle_app, bundle_assets, serve_local_page

# lup: ignore[constant-declaration] — an identity this repository defines: the
# bun workspace entry and the bundle it builds to are both named by this word
SURFACE = "explorer"
"""Which built surface this is, under `lup.web`'s bundles.

An identity of the layout rather than a choice: the bun workspace's entry and
the bundle it builds to are both named by this word, and a caller spelling it
differently would serve nothing.
"""


def opened(root: Path, placement: LedgerPlacement) -> LedgerStore:
    """The store, opened to read; a reader mints a console identity like the CLI."""
    return LedgerStore(root, ActorRef(kind="console", id=mint_member_id()), placement)


def since_moment(spelling: str) -> datetime | None:
    """An ISO 8601 moment from a query parameter, or a refusal a client reads."""
    if not spelling:
        return None
    try:
        return datetime.fromisoformat(spelling)
    except ValueError as invalid:
        raise HTTPException(
            status_code=422, detail=f"since must be ISO 8601: {invalid}"
        ) from invalid


def explorer_app(
    url: str,
    root: Path,
    classes: list[type[LedgerNode]],
    edges: list[type[LedgerEdge]],
    bundles: Path | None = None,
    placement: LedgerPlacement = SharedStore(),
) -> FastAPI:
    """The explorer over one repository's log: its page, and the routes it reads.

    Every route serializes a `lup.ledger.views` model, so what the page is
    typed against is exactly what the tool group returns.
    """
    application = bundle_app("Ledger explorer", url, SURFACE, bundles)

    @application.get("/api/graph")
    async def graph(kind: str = "", standing: str = "", since: str = "") -> GraphView:
        return graph_view(
            opened(root, placement),
            classes,
            kind=kind,
            standing=standing,
            since=since_moment(since),
        )

    @application.get("/api/node/{spelling}")
    async def node(spelling: str) -> NodeDetail:
        store = opened(root, placement)
        found = store.resolve(spelling, classes)
        if found is None:
            raise HTTPException(
                status_code=404, detail=f"no node has the id or slug {spelling!r}"
            )
        return node_detail(store, classes, found)

    @application.get("/api/kinds")
    async def kinds() -> KindsView:
        return kinds_view(classes, edges)

    return application


def export_view(
    root: Path,
    classes: list[type[LedgerNode]],
    edges: list[type[LedgerEdge]],
    placement: LedgerPlacement = SharedStore(),
) -> ExportView:
    """The whole log as one value, for a page that cannot ask for more later."""
    store = opened(root, placement)
    return ExportView(
        graph=graph_view(store, classes),
        details=[
            node_detail(store, classes, node) for node in store.all_nodes(classes)
        ],
        kinds=kinds_view(classes, edges),
        exported_at=utc_now(),
    )


def export_page(view: ExportView, assets: BundleAssets) -> str:
    """One self-contained page: the bundle inline, the log as an attribute.

    Assembled from the bundle's pieces rather than by editing its own
    `index.html`, whose asset paths only a server answers. The script and
    the stylesheet are the served bundle's bytes verbatim, inside a
    `<script type="module">` and a `<style>` element: the build escaped
    every `</script`, `<!--` and `</style` when it built them and proved the
    script still parses (`lup.web.build.escape_for_inlining`), so nothing
    here has to. The app reads the attribute before it would fetch, so the
    same bundle serves both ways.
    """
    styles = "".join(f"<style>{style}</style>\n" for style in assets.styles)
    scripts = "".join(
        f'<script type="module">{script}</script>\n' for script in assets.scripts
    )
    data = escape(view.model_dump_json(), quote=True)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        "<title>Ledger explorer</title>\n"
        f"{styles}"
        "</head>\n"
        "<body>\n"
        f'<div id="root" data-lup-export="{data}"></div>\n'
        f"{scripts}"
        "</body>\n"
        "</html>\n"
    )


def export_explorer(
    root: Path,
    classes: list[type[LedgerNode]],
    edges: list[type[LedgerEdge]],
    destination: Path,
    bundles: Path | None = None,
    placement: LedgerPlacement = SharedStore(),
) -> Path:
    """Write the explorer as one file holding the log as it is now.

    The result opens from a file, mails as an attachment, and shows exactly
    what the log held when it was written — the page says when.
    """
    page = export_page(
        export_view(root, classes, edges, placement), bundle_assets(SURFACE, bundles)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
    return destination


def serve_explorer(
    root: Path,
    classes: list[type[LedgerNode]],
    edges: list[type[LedgerEdge]],
    host: str,
    port: int,
    open_page: bool = True,
    placement: LedgerPlacement = SharedStore(),
) -> None:
    """Bind the loopback and serve the explorer over this repository's log."""
    serve_local_page(
        lambda url: explorer_app(url, root, classes, edges, placement=placement),
        "Ledger explorer",
        host,
        port,
        open_page,
    )
