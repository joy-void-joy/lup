"""Reusable setup-wizard framework for project integrations.

Walks a project's declared integrations, prompting for what each one
needs, writing the answers where the integration keeps them, and reporting
what is already configured.

Nothing here names a service: an application declares its own
``Integration`` list and composes the command tree with
:func:`create_setup_app`. Most integrations are pure data — name, command
slug, env keys, intro text, and the ``PromptField`` list to prompt for —
and their subcommand is generated from that. A bespoke flow (OAuth files,
detection, validation) supplies ``setup_func`` instead, and ``status_func``
overrides the display when env-key presence isn't the whole story.

Answers go to ``.env.local`` in the checkout, where the application reads
them -- and so can every session. An integration declared ``host_only``
keeps its keys in the operator's host store instead
(:mod:`lup.devtools.envfiles`), for a secret only a host companion may hold.
Prompts, the status table and the dashboard read and write whichever store
an integration names, and each says which one that is. Run the wizard
through ``lup-launch run setup``, so the code that asks for a secret is code
its operator approved rather than whatever a session last left in the
checkout.
"""

import webbrowser
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from lup.devtools.conversation.app import create_conversation_setup_app
from lup.devtools.envfiles import CheckoutEnv, ContainedHint, EnvFile, HostSecrets
from lup.devtools.harness.profile_app import create_profile_app
from lup.providers.profiles import ProfileDirectory
from lup.types import EnvName, EnvVars
from lup.workspace.paths import project_root

console = Console()


class IntegrationStatus(BaseModel):
    """Whether an integration is configured, with the human-readable detail."""

    ok: bool
    detail: str


PROJECT_ROOT = project_root()
ENV_LOCAL = PROJECT_ROOT / ".env.local"


# =====================================================================
# The two stores
# =====================================================================


def env_local() -> CheckoutEnv:
    """The checkout's ``.env.local``, which the application and every session read."""
    return CheckoutEnv(path=ENV_LOCAL)


def host_secrets() -> HostSecrets:
    """This project's host store, which no session reads."""
    return HostSecrets.for_checkout(PROJECT_ROOT)


def read_env_local() -> EnvVars:
    """Read .env.local values (empty dict when the file is missing)."""
    return env_local().read()


def write_env_local(values: EnvVars) -> None:
    """Update keys in .env.local, preserving existing lines, comments, order."""
    env_local().write(values)


def clear_env_file(path: Path, keys: Iterable[str]) -> None:
    """Drop keys from an env file. Idempotent — a no-op for keys it does not hold.

    The path is a parameter because an application may keep more than one env
    file — one per profile, say — and only it knows which of them a reset is
    aimed at.
    """
    CheckoutEnv(path=path).clear(keys)


def clear_env_local(keys: Iterable[str]) -> None:
    """Drop keys from .env.local, the file :func:`write_env_local` writes."""
    env_local().clear(keys)


def save_and_confirm(values: EnvVars, store: EnvFile) -> None:
    """Write values to the store they belong in, and say which one that was."""
    if values:
        store.write(values)
        console.print(f"[green]Saved to {escape(store.said())}[/]")


def mask(value: str, show: int = 6) -> str:
    """Partially reveal a secret for recognition in the status table.

    Shows the first ``show`` characters so a human can tell *which* token
    is configured at a glance, then hides the rest. This is deliberately
    not :class:`pydantic.SecretStr`, which masks every character — that
    prevents leakage but also makes two different tokens indistinguishable
    in the status display.
    """
    if len(value) <= show:
        return value
    return value[:show] + "..." + "*" * min(8, len(value) - show)


def open_browser(url: str) -> None:
    """Open a URL in the default browser, with fallback message."""
    console.print(f"  Opening [link={url}]{url}[/link]")
    try:
        webbrowser.open(url)
    except (webbrowser.Error, OSError):
        console.print(f"  [dim]Could not open browser. Go to: {url}[/dim]")


# =====================================================================
# Integration registry
# =====================================================================


class PromptField(BaseModel):
    """One env var the wizard prompts for inside a token-based setup."""

    key: str = Field(description="Env var name, e.g. 'SLACK_BOT_TOKEN'")
    prompt: str = Field(description="Prompt label shown to the user")
    secret: bool = Field(
        default=True,
        description=(
            "Hide what is typed, and the current value as the prompt default "
            "(true for tokens)"
        ),
    )
    parse: Callable[[str], object] | None = Field(
        default=None,
        description="Validator called on the entered value; rejects on raise",
    )


class Integration(BaseModel):
    """A single integration the setup wizard can configure.

    Most integrations are *token-based*: they print instructions, maybe
    open a browser, then prompt for a handful of env vars. Those are
    described declaratively via ``intro``/``browser_url``/``fields`` and
    run by :meth:`run` — adding one is filling in this shape, not copying
    a function. Integrations with bespoke flows (OAuth file handling,
    timezone detection) instead supply ``setup_func``.
    """

    name: str = Field(description="Display name (e.g., 'Slack', 'Google')")
    command: str = Field(description="Subcommand slug, e.g. 'slack' or 'api-key'")
    help: str = Field(description="One-line help for the subcommand")
    env_keys: list[str] = Field(description="Env vars to check for status display")
    intro: str | None = Field(
        default=None, description="Instructions printed before prompting"
    )
    browser_url: str | None = Field(
        default=None, description="URL to open while the user follows the intro"
    )
    fields: list[PromptField] = Field(
        default=[], description="Env vars to prompt for, in order"
    )
    setup_func: Callable[[], EnvVars] | None = Field(
        default=None,
        description="Bespoke interactive flow, used instead of the declarative fields",
    )
    status_func: Callable[[EnvVars], IntegrationStatus] | None = Field(
        default=None,
        description="Custom status checker (default: checks env_keys)",
    )
    host_only: bool = Field(
        default=False,
        description=(
            "Keep every key this integration writes in the operator's host "
            "store, outside every checkout, rather than in .env.local: for a "
            "secret only a host companion may hold and no session may read"
        ),
    )

    def keys(self) -> list[str]:
        """Every key this integration reads or asks for, once each."""
        return list(dict.fromkeys([*self.env_keys, *(f.key for f in self.fields)]))

    def store(self) -> EnvFile:
        """Where this integration's answers are kept."""
        return host_secrets() if self.host_only else env_local()

    def misplaced(self, local: EnvVars) -> list[str]:
        """This integration's host-only keys found in ``.env.local``, where sessions read them."""
        return [key for key in self.keys() if key in local] if self.host_only else []

    def misplacement(self, local: EnvVars) -> str:
        """The sentence saying a host-only key sits in ``.env.local``, or nothing."""
        found = self.misplaced(local)
        if not found:
            return ""
        return (
            f"{', '.join(found)} also in .env.local, which every session reads: "
            f"`lup-launch run setup {self.command}` moves it"
        )

    def refusal(self) -> str:
        """Why this integration cannot be set up in this process, or nothing.

        A host-only integration inside a container: its answers would land in
        the container's own configuration, not the host store, so it is
        refused before anybody types a secret into the session.
        """
        if not self.host_only:
            return ""
        return ContainedHint().refusal(f"setup {self.command}")

    def run(self) -> EnvVars:
        """Run the setup flow and return env vars to write."""
        refused = self.refusal()
        if refused:
            console.print(f"[red]{escape(refused)}[/]")
            raise typer.Exit(1)
        self.offer_move()
        if self.setup_func is not None:
            return self.setup_func()
        return self.run_prompts()

    def offer_move(self) -> None:
        """Offer to take this integration's host-only keys out of ``.env.local``.

        Written to the host store before they are cleared from the checkout,
        so an interruption between the two leaves a copy too many rather than
        none. Where the host store holds a value of its own, that one stays.
        """
        local = env_local()
        present = local.read()
        found = self.misplaced(present)
        if not found:
            return
        store = host_secrets()
        console.print(
            f"[yellow]{', '.join(found)} is in .env.local, inside the checkout, "
            f"where every session can read it. {self.name} keeps it in "
            f"{escape(store.said())}.[/]"
        )
        if not typer.confirm("Move it there?", default=True):
            return
        held = store.read()
        store.write({key: present[key] for key in found if key not in held})
        local.clear(found)
        console.print(f"[green]Moved to {escape(store.said())}[/]")

    def run_prompts(self) -> EnvVars:
        """Standard token flow: header, reconfigure check, intro, prompts."""
        console.print()
        console.rule(f"[bold]{self.name}[/]")
        store = self.store()
        console.print(f"[dim]Kept in {escape(store.said())}[/]")
        console.print()

        env = store.read()
        # Gate re-entry only for secrets, which can't be shown as defaults;
        # non-secret fields echo their current value, so re-walking is cheap.
        guards_secret = any(f.secret for f in self.fields)
        configured = all(env.get(k) for k in self.env_keys)
        if guards_secret and configured:
            console.print("[green]Already configured.[/]")
            if not typer.confirm("Reconfigure?", default=False):
                return {}

        if self.intro:
            console.print(self.intro)
        if self.browser_url:
            open_browser(self.browser_url)
        console.print()

        values: EnvVars = {}
        for field in self.fields:
            current = env.get(field.key, "")
            raw = typer.prompt(
                field.prompt,
                default=current,
                show_default=bool(current) and not field.secret,
                hide_input=field.secret,
            ).strip()
            if not raw:
                continue
            if field.parse is not None:
                try:
                    field.parse(raw)
                except ValueError:
                    console.print(f"  [yellow]Skipping {field.key}: invalid value[/]")
                    continue
            values[field.key] = raw
        return values

    def check_status(self, env: EnvVars) -> IntegrationStatus:
        """Whether this integration is configured, and the detail to show.

        An integration declaring no env keys cannot be judged from the
        environment at all — it configures a file, a download, a roster. It
        says so rather than being read as configured: ``all([])`` is true, so
        the obvious spelling reports every such integration green and then
        raises reaching for a value that is not there.
        """
        if self.status_func:
            return self.status_func(env)
        if not self.env_keys:
            return IntegrationStatus(ok=False, detail="nothing in the environment says")
        values = [env.get(k, "") for k in self.env_keys]
        if all(values):
            return IntegrationStatus(ok=True, detail=mask(values[0]))
        return IntegrationStatus(ok=False, detail="not configured")


def build_status_table(integrations: list[Integration]) -> Table:
    """Build a rich table showing configuration status, and where each is kept.

    Each integration is judged on the store it names, so a host-only key
    counts as configured only where the host store holds it; one left in
    ``.env.local`` is said beside it, with the command that moves it.
    """
    local = read_env_local()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Status", width=3)
    table.add_column("Integration", min_width=30)
    table.add_column("Kept in")
    table.add_column("Detail", style="dim")
    for integration in integrations:
        store = integration.store()
        status = integration.check_status(store.read())
        status_text = "[green]OK[/]" if status.ok else "[red]--[/]"
        detail = "; ".join(
            part for part in (status.detail, integration.misplacement(local)) if part
        )
        table.add_row(status_text, integration.name, store.label(), detail)
    return table


def say_status(integrations: list[Integration]) -> None:
    """Print the status table, and where the host store is when anything uses it."""
    console.print(build_status_table(integrations))
    if any(integration.host_only for integration in integrations):
        console.print(f"  Host store: {host_secrets().path}", markup=False)


def make_setup_command(integration: Integration) -> Callable[[], None]:
    """Build a zero-argument command that runs one integration's setup."""

    def run_one() -> None:
        save_and_confirm(integration.run(), integration.store())

    return run_one


def create_setup_app(
    integrations: list[Integration],
    profiles: ProfileDirectory | None = None,
) -> typer.Typer:
    """Build the setup command tree over a project's declared integrations.

    A project that keeps Claude accounts supplies the directory over its own
    origin, and setup curates exactly the roster its launches select from.
    """
    app = typer.Typer(
        help="Interactive setup wizard",
        pretty_exceptions_show_locals=False,
        invoke_without_command=True,
    )
    app.add_typer(create_conversation_setup_app(profiles), name="conversation")
    if profiles is not None:
        app.add_typer(create_profile_app(profiles), name="profile")
    # The dashboard is this wizard seen through a browser — the same declared
    # integrations rendered for somebody who would rather click than answer
    # prompts. Beneath it rather than beside it because neither is usable
    # without the other: the page serves this wizard's declarations, and a
    # project that kept the page and dropped the wizard would be hosting a
    # form over nothing. Imported where it is mounted, because serving it is
    # the `web` extra and a module-level import would make that extra a
    # requirement of running `setup` at all.
    from lup.devtools.dashboard.app import create_dashboard_app

    app.add_typer(
        create_dashboard_app(integrations),
        name="dashboard",
        help="Host the local setup dashboard",
    )

    @app.command("status")
    def status() -> None:
        """Show current integration status."""
        console.print()
        say_status(integrations)
        active = profiles.active() if profiles is not None else None
        if active is not None:
            console.print(f"  Active profile: [bold]{active.name}[/]")
        console.print()

    @app.command("secret")
    def secret(
        keys: Annotated[
            list[str],
            typer.Argument(help="The env keys to set, such as GEMINI_API_KEY"),
        ],
    ) -> None:
        """Set host-only keys by name, into the host store no session reads.

        For a key a host companion names that no integration declares: each
        is asked for with the typing hidden, and a blank answer keeps what the
        store holds.
        """
        try:
            named = TypeAdapter(list[EnvName]).validate_python(keys)
        except ValidationError as error:
            raise typer.BadParameter(
                "name each key in capitals, digits and underscores, such as "
                "GEMINI_API_KEY"
            ) from error
        refused = ContainedHint().refusal(" ".join(["setup", "secret", *named]))
        if refused:
            console.print(f"[red]{escape(refused)}[/]")
            raise typer.Exit(1)
        store = host_secrets()
        held = store.read()
        console.print(f"[dim]Kept in {escape(store.said())}[/]")
        answered = {
            key: typer.prompt(
                key,
                default=held[key] if key in held else "",
                show_default=False,
                hide_input=True,
            ).strip()
            for key in named
        }
        save_and_confirm(
            {key: value for key, value in answered.items() if value}, store
        )

    for integration in integrations:
        app.command(integration.command, help=integration.help)(
            make_setup_command(integration)
        )

    @app.callback(invoke_without_command=True)
    def main(context: typer.Context) -> None:
        """Walk through all integrations, skipping configured entries."""
        if context.invoked_subcommand is not None:
            return
        console.print()
        console.print(
            Panel(
                "[bold]Project setup[/]\n"
                "\n"
                "Walking through all integrations.\n"
                "Press [bold]Ctrl+C[/] to exit, [bold]Enter[/] to skip a field.",
                expand=False,
            )
        )
        say_status(integrations)
        for integration in integrations:
            # Skipped rather than ending the walk: the others belong here.
            refused = integration.refusal()
            if refused:
                said = f"{integration.name}: {refused}"
                console.print(f"[yellow]{escape(said)}[/]")
                continue
            save_and_confirm(integration.run(), integration.store())
        console.print()
        console.rule("[bold green]Setup complete[/]")
        console.print()
        say_status(integrations)
        console.print()

    return app
