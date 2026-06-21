"""Interactive setup wizard for project integrations.

Walks through configuring external services, API keys, and local
settings. Writes results to ``.env.local`` and provides a status
overview of what's configured.

This is a **TEMPLATE**. Replace the example integrations with your
domain's actual services. The framework (env helpers, status display,
wizard flow, registry) is reusable as-is.

Usage::

    $ uv run lup-devtools setup          # Full walkthrough
    $ uv run lup-devtools setup status   # Show what's configured
    $ uv run lup-devtools setup slack    # Just one integration

Customization:
    1. Define ``setup_<name>()`` functions that return ``dict[str, str]``
    2. Register them in ``INTEGRATIONS`` with a name and status checker
    3. Optionally add individual subcommands via ``@app.command``
    4. Shell helpers live in ``lup_template.devtools.utils`` (e.g.
       ``copy_to_clipboard`` for wizard steps that hand the user a value)
"""

import shutil
import webbrowser
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import lup.profiles as profiles
from lup.paths import project_root

app = typer.Typer(
    help="Interactive setup wizard",
    pretty_exceptions_show_locals=False,
    invoke_without_command=True,
)

console = Console()

PROJECT_ROOT = project_root()
ENV_LOCAL = PROJECT_ROOT / ".env.local"
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"

profile_app = typer.Typer(no_args_is_help=True, help="Manage Claude account profiles")
app.add_typer(profile_app, name="profile")


# =====================================================================
# .env.local helpers
# =====================================================================


def read_env_local() -> dict[str, str]:
    # claude: this seems extremely hacky. Why do we need it when we already have config? Seems like reinventing the wheel there
    """Parse .env.local into a dict. Returns empty dict if file missing."""
    if not ENV_LOCAL.exists():
        return {}
    values: dict[str, str] = {}
    for line in ENV_LOCAL.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def write_env_local(values: dict[str, str]) -> None:
    """Update keys in .env.local, preserving existing lines, comments, order.

    Existing ``KEY=...`` lines are rewritten in place; new keys are appended.
    Comments, blank lines, and ordering are left untouched.
    """
    # claude: I'm unsure we should do it like that this seems brittle maybe?
    # claude: But at least this one is straightforward to understand
    if not values:
        return

    remaining = dict(values)
    lines = ENV_LOCAL.read_text().splitlines() if ENV_LOCAL.exists() else []
    out: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.partition("=")[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)

    for key, value in remaining.items():
        out.append(f"{key}={value}")

    ENV_LOCAL.write_text("\n".join(out) + "\n")


def save_and_confirm(values: dict[str, str]) -> None:
    """Write values to .env.local and print confirmation."""
    if values:
        write_env_local(values)
        console.print("[green]Saved to .env.local[/]")


def mask(value: str, show: int = 6) -> str:
    """Mask a secret string, showing only the first few characters."""  # claude: this seems a bit superfluous when we could use pydantic-setting's SecretStr instead?
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


def detect_system_timezone() -> (
    str
):  # claude: Yes okay, but like, using str manipulation for that seems brittle? Likewise parsing /etc/localtime, what if I'm on windows? Surely there's an actual builtin or a package for that
    """Detect the system's IANA timezone name."""
    try:
        local_now = datetime.now(timezone.utc).astimezone()
        tz_name = local_now.tzname()
        localtime = Path("/etc/localtime")
        if localtime.is_symlink():
            target = str(localtime.resolve())
            if "zoneinfo/" in target:
                return target.split("zoneinfo/", 1)[1]
        return tz_name or ""
    except OSError:
        return ""


# =====================================================================
# Integration registry
# =====================================================================


class Integration(BaseModel):
    """A single integration that the setup wizard can configure."""

    name: str = Field(description="Display name (e.g., 'Slack', 'Google')")
    env_keys: list[str] = Field(description="Env vars to check for status display")
    setup_func: Callable[[], dict[str, str]] = Field(
        description="Interactive function that returns env vars to write"
    )
    status_func: Callable[[dict[str, str]], tuple[bool, str]] | None = Field(
        default=None,
        description="Custom status checker (default: checks env_keys)",
    )

    def check_status(self, env: dict[str, str]) -> tuple[bool, str]:
        """Return (is_configured, detail_string)."""
        if self.status_func:
            return self.status_func(env)
        values = [env.get(k, "") for k in self.env_keys]
        if all(values):
            return True, mask(values[0])
        return False, "not configured"


# =====================================================================
# TEMPLATE integrations — replace these with your domain's services
# =====================================================================

# claude: Probably need some todos here. I'd like /init to have a step where it explicitely gathers (like dev currently gathers the "# claude:" comments) all TODOs and places where it has to make a decision


def setup_slack() -> dict[str, str]:
    # claude: the type is extreme code smell. You defined an integration basemodel, so probably you can make a decorator, or at least have the return type be uniform
    """Walk through Slack bot token configuration.

    TEMPLATE: Replace with your Slack app's manifest and scopes.
    """
    console.print()
    console.rule("[bold]Slack[/]")
    console.print()

    env = read_env_local()

    if env.get("SLACK_BOT_TOKEN") and env.get("SLACK_APP_TOKEN"):
        console.print("[green]Already configured.[/]")
        if not typer.confirm("Reconfigure?", default=False):
            return {}

    console.print(
        "  [bold]Create a Slack app:[/]\n"
        '  1. Go to api.slack.com/apps > "Create New App" > "From a manifest"\n'
        "  2. Pick your workspace, paste your app manifest (JSON tab)\n"
        "  3. Install to workspace\n"
        "  4. Copy the Bot User OAuth Token and App-Level Token\n"
    )
    open_browser("https://api.slack.com/apps?new_app=1")
    console.print()

    values: dict[str, str] = {}

    app_token = typer.prompt(
        "SLACK_APP_TOKEN (xapp-...)",
        default=env.get("SLACK_APP_TOKEN", ""),
        show_default=False,
    ).strip()
    if app_token:
        values["SLACK_APP_TOKEN"] = app_token

    bot_token = typer.prompt(
        "SLACK_BOT_TOKEN (xoxb-...)",
        default=env.get("SLACK_BOT_TOKEN", ""),
        show_default=False,
    ).strip()
    if bot_token:
        values["SLACK_BOT_TOKEN"] = bot_token

    # claude: Yeah, this all feels very hacky and copy-pasty where we could have something more general

    user_id = typer.prompt(
        "SLACK_USER_ID (your Slack user ID, or email for lookup)",
        default=env.get("SLACK_USER_ID", ""),
        show_default=False,
    ).strip()
    if user_id:
        values["SLACK_USER_ID"] = user_id

    return values


def slack_status(env: dict[str, str]) -> tuple[bool, str]:
    """Custom status check for Slack."""
    ok = bool(env.get("SLACK_BOT_TOKEN") and env.get("SLACK_APP_TOKEN"))
    if ok:
        return True, mask(env["SLACK_BOT_TOKEN"])
    return False, "not configured"


def setup_google() -> dict[str, str]:
    """Walk through Google OAuth setup (Gmail, Calendar, etc).

    TEMPLATE: Replace with your Google API scopes and services.
    """
    console.print()
    console.rule("[bold]Google (OAuth)[/]")
    console.print()

    token_path = CREDENTIALS_DIR / "token.json"
    creds_path = CREDENTIALS_DIR / "google.json"

    if token_path.exists():
        console.print("[green]Already authorized.[/]")
        if not typer.confirm("Re-authorize?", default=False):
            return {"GMAIL_CREDENTIALS_PATH": str(creds_path)}

    if not creds_path.exists():
        console.print(
            "  [bold]Step 1:[/] Create a Google Cloud project\n"
            "  [bold]Step 2:[/] Enable the APIs you need (Gmail, Calendar, etc.)\n"
            "  [bold]Step 3:[/] Configure OAuth consent screen\n"
            "  [bold]Step 4:[/] Add yourself as a test user\n"
            "  [bold]Step 5:[/] Create OAuth client ID (Desktop app)\n"
            "  [bold]Step 6:[/] Download the credentials JSON\n"
        )
        open_browser("https://console.cloud.google.com/apis/credentials")
        console.print()

        source = typer.prompt("Path to downloaded credentials JSON").strip()
        source_path = Path(source).expanduser().resolve()

        if not source_path.exists():
            console.print(f"[red]File not found:[/] {source_path}")
            raise typer.Abort()

        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, creds_path)
        console.print(f"  Copied to [bold]{creds_path}[/]")
    else:
        console.print(f"  Using existing credentials at [bold]{creds_path}[/]")

    console.print(
        "\n  [dim]To complete authorization, run your project's OAuth flow\n"
        "  with the credentials file above.[/]\n"
    )

    return {"GMAIL_CREDENTIALS_PATH": str(creds_path)}


def google_status(_env: dict[str, str]) -> tuple[bool, str]:
    """Custom status check for Google OAuth."""
    token_path = CREDENTIALS_DIR / "token.json"
    creds_path = CREDENTIALS_DIR / "google.json"
    if token_path.exists():
        return True, "authorized"
    if creds_path.exists():
        return False, "credentials present, not yet authorized"
    return False, "not configured"


def setup_notion() -> dict[str, str]:
    """Walk through Notion integration token setup.

    TEMPLATE: Replace with your Notion integration's specific setup.
    """
    console.print()
    console.rule("[bold]Notion[/]")
    console.print()

    env = read_env_local()

    if env.get("NOTION_TOKEN"):
        console.print("[green]Already configured.[/]")
        if not typer.confirm("Reconfigure?", default=False):
            return {}

    console.print(
        "  Create an [bold]Internal[/] Notion integration:\n"
        "  1. Go to notion.so/profile/integrations/internal\n"
        "  2. Enter a name, keep type as Internal, submit\n"
        "  3. Copy the Internal Integration Secret\n"
        "  4. Share pages: open page > ... > Connections > add your integration\n"
    )
    open_browser("https://www.notion.so/profile/integrations/internal")
    console.print()

    values: dict[str, str] = {}

    token = typer.prompt(
        "NOTION_TOKEN (secret_...)",
        default=env.get("NOTION_TOKEN", ""),
        show_default=False,
    ).strip()
    if token:
        values["NOTION_TOKEN"] = token

    parent_id = typer.prompt(
        "NOTION_ALLOWED_PARENT_ID (page/DB ID for writes, optional)",
        default=env.get("NOTION_ALLOWED_PARENT_ID", ""),
        show_default=False,
    ).strip()
    if parent_id:
        values["NOTION_ALLOWED_PARENT_ID"] = parent_id

    return values


def setup_api_key() -> dict[str, str]:
    """Walk through a generic API key configuration.

    TEMPLATE: Replace with your domain's specific API service.
    This example shows a simple key-based service (like AskNews, Exa, etc).
    """
    console.print()
    console.rule("[bold]Example API Service[/]")
    console.print()

    env = read_env_local()

    if env.get("EXAMPLE_API_KEY"):
        console.print("[green]Already configured.[/]")
        if not typer.confirm("Reconfigure?", default=False):
            return {}

    console.print("  Sign up and get an API key from the service provider.\n")

    key = typer.prompt(
        "EXAMPLE_API_KEY",
        default=env.get("EXAMPLE_API_KEY", ""),
        show_default=False,
    ).strip()

    if key:
        return {"EXAMPLE_API_KEY": key}
    return {}


def setup_codex_backend() -> dict[str, str]:
    """Walk through Codex/OpenAI backend pricing configuration.

    The Codex runtime reports token counts, never cost — budget caps
    (``AGENT_MAX_BUDGET_USD``) on ``AGENT_SDK=codex``/``openai`` need
    per-MTok USD rates for the configured model. Claude-only projects
    can skip this entirely.
    """
    # claude: Why do we need this?
    console.print()
    console.rule("[bold]Codex/OpenAI backend pricing[/]")
    console.print()

    env = read_env_local()

    console.print(
        "  Budget caps on AGENT_SDK=codex/openai need per-MTok USD rates\n"
        "  (the Codex SDK reports tokens, not cost). Leave blank to skip —\n"
        "  a budget without rates fails loudly at session start.\n"
    )

    values: dict[str, str] = {}
    for key in (
        "CODEX_USD_PER_MTOK_INPUT",
        "CODEX_USD_PER_MTOK_OUTPUT",
        "CODEX_USD_PER_MTOK_CACHED_INPUT",
    ):
        raw = typer.prompt(
            key,
            default=env.get(key, ""),
            show_default=bool(env.get(key)),
        ).strip()
        if not raw:
            continue
        try:
            float(raw)
        except ValueError:
            console.print(f"  [yellow]Skipping {key}: not a number[/]")
            continue
        values[key] = raw
    return values


def codex_backend_status(env: dict[str, str]) -> tuple[bool, str]:
    """Rates present = budget caps enforceable on codex/openai."""
    # claude: Same question here, this feels like just a continuation of the last function?
    # claude: Also, we need a generate setup function for claude/codex login, see how we do it in https://github.com/joy-void-joy/inkwell/tree/dev

    rates = [
        key
        for key in ("CODEX_USD_PER_MTOK_INPUT", "CODEX_USD_PER_MTOK_OUTPUT")
        if env.get(key)
    ]
    if len(rates) == 2:
        return True, "rates set (budget caps enforceable)"
    return False, "no rates (budget caps unavailable on codex/openai)"


def setup_timezone() -> dict[str, str]:
    """Walk through timezone configuration."""
    console.print()
    console.rule("[bold]Timezone[/]")
    console.print()

    env = read_env_local()
    system_tz = detect_system_timezone()
    current = env.get("AGENT_TIMEZONE", "")
    default = current or system_tz

    if system_tz:
        console.print(f"  Detected: [bold]{system_tz}[/]")

    tz = typer.prompt(
        "AGENT_TIMEZONE",
        default=default,
        show_default=bool(default),
    ).strip()

    if tz:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(tz)
            console.print(f"  [green]Valid[/] — {tz}")
        except (KeyError, ModuleNotFoundError):
            console.print(
                f"  [yellow]Warning:[/] '{tz}' may not be a valid IANA timezone"
            )
        return {"AGENT_TIMEZONE": tz}

    return {}


def timezone_status(env: dict[str, str]) -> tuple[bool, str]:
    """Custom status check for timezone (not-configured is OK, just shows system default)."""
    tz = env.get("AGENT_TIMEZONE", "")
    if tz:
        return True, tz
    return False, "system default"


# =====================================================================
# Integration registry — order matters (services first, timezone last)
#
# TEMPLATE: Replace these with your domain's actual integrations.
# Each entry needs: display name, env keys to check, setup function,
# and optionally a custom status checker.
# =====================================================================

# claude: Yeah, I really like this part
INTEGRATIONS: list[Integration] = [
    Integration(
        name="Slack",
        env_keys=["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
        setup_func=setup_slack,
        status_func=slack_status,
    ),
    Integration(
        name="Google (OAuth)",
        env_keys=["GMAIL_CREDENTIALS_PATH"],
        setup_func=setup_google,
        status_func=google_status,
    ),
    Integration(name="Notion", env_keys=["NOTION_TOKEN"], setup_func=setup_notion),
    Integration(
        name="Example API", env_keys=["EXAMPLE_API_KEY"], setup_func=setup_api_key
    ),
    Integration(
        name="Codex/OpenAI pricing",
        env_keys=["CODEX_USD_PER_MTOK_INPUT", "CODEX_USD_PER_MTOK_OUTPUT"],
        setup_func=setup_codex_backend,
        status_func=codex_backend_status,
    ),
    Integration(
        name="Timezone",
        env_keys=["AGENT_TIMEZONE"],
        setup_func=setup_timezone,
        status_func=timezone_status,
    ),
]


# =====================================================================
# Status display
# =====================================================================


def build_status_table() -> Table:
    """Build a rich table showing configuration status."""
    env = read_env_local()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Status", width=3)
    table.add_column("Integration", min_width=30)
    table.add_column("Detail", style="dim")

    for integration in INTEGRATIONS:
        ok, detail = integration.check_status(env)
        status_str = "[green]OK[/]" if ok else "[red]--[/]"
        table.add_row(status_str, integration.name, detail)

    return table


@app.command("status")
def status() -> None:
    """Show current integration status."""
    console.print()
    console.print(build_status_table())
    active = profiles.active_profile()
    if active:
        console.print(f"  Active Claude profile: [bold]{active}[/]")
    console.print()


# =====================================================================
# Individual subcommands
#
# TEMPLATE: Add @app.command() for each integration so users can
# run them individually (e.g., `lup-devtools setup slack`).
# =====================================================================


@app.command("slack")
def slack_cmd() -> None:
    """Set up Slack tokens."""
    save_and_confirm(setup_slack())


@app.command("google")
def google_cmd() -> None:
    """Set up Google OAuth."""
    save_and_confirm(setup_google())


@app.command("notion")
def notion_cmd() -> None:
    """Set up Notion integration."""
    save_and_confirm(setup_notion())


@app.command("api-key")
def api_key_cmd() -> None:
    """Set up Example API key."""
    save_and_confirm(setup_api_key())


@app.command("codex")
def codex_cmd() -> None:
    """Set Codex/OpenAI per-MTok pricing (enables budget caps)."""
    save_and_confirm(setup_codex_backend())


@app.command("timezone")
def timezone_cmd() -> None:
    """Set timezone."""
    save_and_confirm(setup_timezone())


# =====================================================================
# Claude profiles
#
# A profile maps a name to a Claude config dir (CLAUDE_CONFIG_DIR) — its
# own login and usage data. The `claude` runner launches under the active
# profile and `claude usage` reports on it. The registry is machine-wide.
# =====================================================================


@profile_app.command("list")
def profile_list_cmd() -> None:
    """List Claude profiles; the active one is marked."""
    registry = profiles.load_registry()
    active = registry.get("active")
    profs = registry.get("profiles") or {}
    if not profs:
        console.print(
            "[dim]No profiles. Add one: "
            "lup-devtools setup profile add <name> --config-dir <path>[/dim]"
        )
        return
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("", width=2)
    table.add_column("Profile", min_width=16)
    table.add_column("Config dir", style="dim")
    for name, prof in profs.items():
        marker = "[green]●[/]" if name == active else " "
        table.add_row(marker, name, prof["config_dir"])
    console.print()
    console.print(table)
    console.print()


@profile_app.command("add")
def profile_add_cmd(
    name: Annotated[str, typer.Argument(help="Profile name")],
    config_dir: Annotated[
        Path | None,
        typer.Option(
            "--config-dir", help="Claude config dir (default: ~/.claude-<name>)"
        ),
    ] = None,
) -> None:
    """Register a Claude profile pointing at its own config dir."""
    target = (config_dir or Path.home() / f".claude-{name}").expanduser()
    profiles.add_profile(name, target)
    console.print(f"[green]Added profile {name!r}[/] -> {target}")
    console.print(f"[dim]Log in to it: CLAUDE_CONFIG_DIR={target} claude /login[/dim]")


@profile_app.command("use")
def profile_use_cmd(
    name: Annotated[str, typer.Argument(help="Profile name")],
) -> None:
    """Set the active profile."""
    try:
        profiles.set_active(name)
    except KeyError as e:
        console.print(f"[red]No such profile: {name}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]Active profile: {name}[/]")


@profile_app.command("remove")
def profile_remove_cmd(
    name: Annotated[str, typer.Argument(help="Profile name")],
) -> None:
    """Remove a profile from the registry (leaves its config dir on disk)."""
    profiles.remove_profile(name)
    console.print(f"Removed profile {name!r}")


# =====================================================================
# Full wizard (default command)
# =====================================================================


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Walk through all integrations, skipping what's already configured."""
    if ctx.invoked_subcommand is not None:
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

    console.print(build_status_table())

    for integration in INTEGRATIONS:
        values = integration.setup_func()
        if values:
            write_env_local(values)

    console.print()
    console.rule("[bold green]Setup complete[/]")
    console.print()
    console.print(build_status_table())
    console.print()
