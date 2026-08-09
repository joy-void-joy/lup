"""Serve the reusable setup registry through a local web dashboard.

The CLI wizard and dashboard deliberately share ``setup.INTEGRATIONS`` and
the same env-file helpers. A domain customizes setup once; both interfaces
then expose the same fields, status checks, and bespoke-flow fallbacks.
"""

import webbrowser
from importlib import resources
from typing import Annotated, Literal

import typer
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from lup.types import EnvVars
from lup.web.loopback import guard_loopback_host, refuse_non_loopback
from lup_template.devtools import setup


class DashboardField(BaseModel):
    """One declarative setup field safe to expose in the browser."""

    model_config = ConfigDict(frozen=True)

    key: str
    prompt: str
    secret: bool


class DashboardIntegration(BaseModel):
    """Browser-facing projection of one setup integration."""

    model_config = ConfigDict(frozen=True)

    name: str
    command: str
    help: str
    configured: bool
    detail: str
    mode: Literal["form", "cli"]
    fields: list[DashboardField]


class DashboardState(BaseModel):
    """Complete setup progress shown by the dashboard."""

    model_config = ConfigDict(frozen=True)

    configured: int
    total: int
    integrations: list[DashboardIntegration]


class IntegrationUpdate(BaseModel):
    """Allowlisted env values submitted for one declarative integration."""

    values: EnvVars = Field(description="Environment values keyed by setup field")


def dashboard_integration(
    integration: setup.Integration, env: EnvVars
) -> DashboardIntegration:
    """Project one integration into status plus browser-safe field metadata."""
    status = integration.check_status(env)
    fields = [
        DashboardField(key=field.key, prompt=field.prompt, secret=field.secret)
        for field in integration.fields
    ]
    mode: Literal["form", "cli"] = (
        "form" if fields and integration.setup_func is None else "cli"
    )
    return DashboardIntegration(
        name=integration.name,
        command=integration.command,
        help=integration.help,
        configured=status.ok,
        detail=status.detail,
        mode=mode,
        fields=fields,
    )


def dashboard_state() -> DashboardState:
    """Read current setup progress from the shared integration registry."""
    env = setup.read_env_local()
    integrations = [
        dashboard_integration(integration, env) for integration in setup.INTEGRATIONS
    ]
    return DashboardState(
        configured=sum(item.configured for item in integrations),
        total=len(integrations),
        integrations=integrations,
    )


def find_integration(command: str) -> setup.Integration:
    """Resolve a setup command or return a typed HTTP not-found response."""
    integration = next(
        (item for item in setup.INTEGRATIONS if item.command == command), None
    )
    if integration is None:
        raise HTTPException(status_code=404, detail="Unknown setup integration")
    return integration


def save_integration(command: str, update: IntegrationUpdate) -> DashboardState:
    """Persist only fields declared by one browser-configurable integration."""
    integration = find_integration(command)
    allowed = {field.key for field in integration.fields}
    if integration.setup_func is not None or not allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Run `uv run lup-devtools setup {command}` for this workflow",
        )
    unknown = set(update.values) - allowed  # lup: ignore[set-shape] — key diff
    if unknown:
        names = ", ".join(sorted(unknown))
        raise HTTPException(status_code=400, detail=f"Fields not allowed: {names}")
    setup.write_env_local(update.values)
    return dashboard_state()


def create_dashboard(url: str) -> FastAPI:
    """Build the local FastAPI app over the canonical setup registry.

    The page writes environment values, including the fields declared secret,
    so it keeps the supervisor's posture rather than a weaker one: what a
    surface is worth attacking is decided by what it writes, and this one
    writes the user's credentials.
    """
    dashboard = FastAPI(title="Lup setup", docs_url=None, redoc_url=None)
    guard_loopback_host(dashboard, url)
    html = (
        resources.files("lup_template.devtools.dashboard")
        .joinpath("assets/index.html")
        .read_text("utf-8")
    )

    @dashboard.get("/", response_class=HTMLResponse)
    async def dashboard_home() -> HTMLResponse:
        return HTMLResponse(html)

    @dashboard.get("/api/setup")
    async def setup_status() -> DashboardState:
        return dashboard_state()

    @dashboard.put("/api/setup/{command}")
    async def update_setup(command: str, update: IntegrationUpdate) -> DashboardState:
        return save_integration(command, update)

    return dashboard


app = typer.Typer(
    help="Host the local setup dashboard",
    invoke_without_command=True,
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def serve_dashboard(
    context: typer.Context,
    host: Annotated[str, typer.Option(help="Interface to bind")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="TCP port to bind")] = 8765,
    open_page: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the dashboard in a browser")
    ] = True,
) -> None:
    """Run the setup dashboard from the same registry as the CLI wizard."""
    if context.invoked_subcommand is not None:
        return
    try:
        refuse_non_loopback(host, "setup dashboard")
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    url = f"http://{host}:{port}"
    typer.echo(f"Lup setup dashboard: {url}")
    if open_page:
        webbrowser.open(url)
    uvicorn.run(create_dashboard(url), host=host, port=port)
