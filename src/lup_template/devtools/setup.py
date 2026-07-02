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
    1. Append an ``Integration`` to ``INTEGRATIONS``. A token-based one is
       pure data: name, command slug, env keys, intro text, and the
       ``PromptField`` list to ask for. Its subcommand is generated for you.
    2. For a bespoke flow (OAuth files, detection, validation), pass a
       ``setup_func`` returning ``EnvValues`` instead of declarative fields.
    3. Override status display with ``status_func`` when env-key presence
       isn't the whole story.
    4. Shell helpers live in ``lup_template.devtools.utils`` (e.g.
       ``copy_to_clipboard`` for wizard steps that hand the user a value)
"""

import shutil
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfoNotFoundError

import typer
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from tzlocal import get_localzone_name

import lup.profiles as profiles
from lup.paths import project_root

app = typer.Typer(
    help="Interactive setup wizard",
    pretty_exceptions_show_locals=False,
    invoke_without_command=True,
)

console = Console()

# Env vars an integration wants written to .env.local, keyed by name.
type EnvValues = dict[str, str]

PROJECT_ROOT = project_root()
ENV_LOCAL = PROJECT_ROOT / ".env.local"
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"

profile_app = typer.Typer(no_args_is_help=True, help="Manage Claude account profiles")
app.add_typer(profile_app, name="profile")


# =====================================================================
# .env.local helpers
# =====================================================================


def read_env_local() -> EnvValues:
    """Parse .env.local into a dict. Returns empty dict if file missing.

    The wizard owns the file as editable text, not just values: it reads
    the raw entries here so it can round-trip them through
    :func:`write_env_local` while preserving comments and ordering.
    pydantic-settings only *reads* config into the running process, so it
    cannot serve a tool whose job is to *write* .env.local back out.
    """
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


def write_env_local(values: EnvValues) -> None:
    """Update keys in .env.local, preserving existing lines, comments, order.

    Existing ``KEY=...`` lines are rewritten in place; new keys are appended.
    Comments, blank lines, and ordering are left untouched. This is the
    write half that pydantic-settings does not provide.
    """
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


def save_and_confirm(values: EnvValues) -> None:
    """Write values to .env.local and print confirmation."""
    if values:
        write_env_local(values)
        console.print("[green]Saved to .env.local[/]")


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


def detect_system_timezone() -> str:
    """Detect the system's IANA timezone name, or "" if undetermined.

    Delegates to ``tzlocal``, which reads the right source for each
    platform (``/etc/localtime`` on Linux, the registry on Windows,
    system preferences on macOS) instead of string-munging just one.
    """
    try:
        return get_localzone_name()
    except ZoneInfoNotFoundError:
        return ""


# =====================================================================
# Integration registry
# =====================================================================


class PromptField(BaseModel):
    """One env var the wizard prompts for inside a token-based setup."""

    key: str = Field(description="Env var name, e.g. 'SLACK_BOT_TOKEN'")
    prompt: str = Field(description="Prompt label shown to the user")
    secret: bool = Field(
        default=True,
        description="Hide the current value as the prompt default (true for tokens)",
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
        default_factory=list, description="Env vars to prompt for, in order"
    )
    setup_func: Callable[[], EnvValues] | None = Field(
        default=None,
        description="Bespoke interactive flow, used instead of the declarative fields",
    )
    status_func: Callable[[EnvValues], tuple[bool, str]] | None = Field(
        default=None,
        description="Custom status checker (default: checks env_keys)",
    )

    def run(self) -> EnvValues:
        """Run the setup flow and return env vars to write."""
        if self.setup_func is not None:
            return self.setup_func()
        return self.run_prompts()

    def run_prompts(self) -> EnvValues:
        """Standard token flow: header, reconfigure check, intro, prompts."""
        console.print()
        console.rule(f"[bold]{self.name}[/]")
        console.print()

        env = read_env_local()
        # Gate re-entry only for secrets, which can't be shown as defaults;
        # non-secret fields echo their current value, so re-walking is cheap.
        guards_secret = any(f.secret for f in self.fields)
        if guards_secret and all(env.get(k) for k in self.env_keys):
            console.print("[green]Already configured.[/]")
            if not typer.confirm("Reconfigure?", default=False):
                return {}

        if self.intro:
            console.print(self.intro)
        if self.browser_url:
            open_browser(self.browser_url)
        console.print()

        values: EnvValues = {}
        for field in self.fields:
            current = env.get(field.key, "")
            raw = typer.prompt(
                field.prompt,
                default=current,
                show_default=bool(current) and not field.secret,
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

    def check_status(self, env: EnvValues) -> tuple[bool, str]:
        """Return (is_configured, detail_string)."""
        if self.status_func:
            return self.status_func(env)
        values = [env.get(k, "") for k in self.env_keys]
        if all(values):
            return True, mask(values[0])
        return False, "not configured"


# =====================================================================
# TEMPLATE: example integration flows below (Slack, Google, timezone) —
# replace these setup/status functions with your domain's services
# =====================================================================


def slack_status(env: EnvValues) -> tuple[bool, str]:
    """Custom status check for Slack."""
    ok = bool(env.get("SLACK_BOT_TOKEN") and env.get("SLACK_APP_TOKEN"))
    if ok:
        return True, mask(env["SLACK_BOT_TOKEN"])
    return False, "not configured"


def setup_google() -> EnvValues:
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


def google_status(_env: EnvValues) -> tuple[bool, str]:
    """Custom status check for Google OAuth."""
    token_path = CREDENTIALS_DIR / "token.json"
    creds_path = CREDENTIALS_DIR / "google.json"
    if token_path.exists():
        return True, "authorized"
    if creds_path.exists():
        return False, "credentials present, not yet authorized"
    return False, "not configured"


def codex_backend_status(env: EnvValues) -> tuple[bool, str]:
    """Rates present = budget caps enforceable on codex/openai."""
    rates = [
        key
        for key in ("CODEX_USD_PER_MTOK_INPUT", "CODEX_USD_PER_MTOK_OUTPUT")
        if env.get(key)
    ]
    if len(rates) == 2:
        return True, "rates set (budget caps enforceable)"
    return False, "no rates (budget caps unavailable on codex/openai)"


def setup_timezone() -> EnvValues:
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


def timezone_status(env: EnvValues) -> tuple[bool, str]:
    """Custom status check for timezone (not-configured is OK, just shows system default)."""
    tz = env.get("AGENT_TIMEZONE", "")
    if tz:
        return True, tz
    return False, "system default"


# =====================================================================
# Integration registry — order matters (services first, timezone last)
#
# TEMPLATE: Replace these with your domain's actual integrations. A
# token-based one is just data: name, env keys, intro, browser URL, and
# the fields to prompt for. Bespoke flows pass ``setup_func`` instead.
# =====================================================================

# lup: Yeah, I really like this part
INTEGRATIONS: list[Integration] = [
    Integration(
        name="Slack",
        command="slack",
        help="Set up Slack tokens.",
        env_keys=["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
        intro=(
            "  [bold]Create a Slack app:[/]\n"
            '  1. Go to api.slack.com/apps > "Create New App" > "From a manifest"\n'
            "  2. Pick your workspace, paste your app manifest (JSON tab)\n"
            "  3. Install to workspace\n"
            "  4. Copy the Bot User OAuth Token and App-Level Token\n"
        ),
        browser_url="https://api.slack.com/apps?new_app=1",
        fields=[
            PromptField(key="SLACK_APP_TOKEN", prompt="SLACK_APP_TOKEN (xapp-...)"),
            PromptField(key="SLACK_BOT_TOKEN", prompt="SLACK_BOT_TOKEN (xoxb-...)"),
            PromptField(
                key="SLACK_USER_ID",
                prompt="SLACK_USER_ID (your Slack user ID, or email for lookup)",
            ),
        ],
        status_func=slack_status,
    ),
    Integration(
        name="Google (OAuth)",
        command="google",
        help="Set up Google OAuth.",
        env_keys=["GMAIL_CREDENTIALS_PATH"],
        setup_func=setup_google,
        status_func=google_status,
    ),
    Integration(
        name="Notion",
        command="notion",
        help="Set up Notion integration.",
        env_keys=["NOTION_TOKEN"],
        intro=(
            "  Create an [bold]Internal[/] Notion integration:\n"
            "  1. Go to notion.so/profile/integrations/internal\n"
            "  2. Enter a name, keep type as Internal, submit\n"
            "  3. Copy the Internal Integration Secret\n"
            "  4. Share pages: open page > ... > Connections > add your integration\n"
        ),
        browser_url="https://www.notion.so/profile/integrations/internal",
        fields=[
            PromptField(key="NOTION_TOKEN", prompt="NOTION_TOKEN (secret_...)"),
            PromptField(
                key="NOTION_ALLOWED_PARENT_ID",
                prompt="NOTION_ALLOWED_PARENT_ID (page/DB ID for writes, optional)",
            ),
        ],
    ),
    Integration(
        name="Example API",
        command="api-key",
        help="Set up Example API key.",
        env_keys=["EXAMPLE_API_KEY"],
        intro="  Sign up and get an API key from the service provider.\n",
        fields=[PromptField(key="EXAMPLE_API_KEY", prompt="EXAMPLE_API_KEY")],
    ),
    Integration(
        name="Codex/OpenAI pricing",
        command="codex",
        help="Set Codex/OpenAI per-MTok pricing (enables budget caps).",
        env_keys=["CODEX_USD_PER_MTOK_INPUT", "CODEX_USD_PER_MTOK_OUTPUT"],
        intro=(
            "  Budget caps on AGENT_SDK=codex/openai need per-MTok USD rates\n"
            "  (the Codex SDK reports tokens, not cost). Leave blank to skip —\n"
            "  a budget without rates fails loudly at session start.\n"
        ),
        fields=[
            PromptField(
                key="CODEX_USD_PER_MTOK_INPUT",
                prompt="CODEX_USD_PER_MTOK_INPUT",
                secret=False,
                parse=float,
            ),
            PromptField(
                key="CODEX_USD_PER_MTOK_OUTPUT",
                prompt="CODEX_USD_PER_MTOK_OUTPUT",
                secret=False,
                parse=float,
            ),
            PromptField(
                key="CODEX_USD_PER_MTOK_CACHED_INPUT",
                prompt="CODEX_USD_PER_MTOK_CACHED_INPUT",
                secret=False,
                parse=float,
            ),
        ],
        status_func=codex_backend_status,
    ),
    Integration(
        name="Timezone",
        command="timezone",
        help="Set timezone.",
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
# One per registered integration (e.g. `lup-devtools setup slack`),
# generated from INTEGRATIONS so a new entry gets its subcommand for free.
# =====================================================================


def make_setup_command(integration: Integration) -> Callable[[], None]:
    """Build a zero-arg Typer command that runs one integration's setup."""

    def run_one() -> None:
        save_and_confirm(integration.run())

    return run_one


for _integration in INTEGRATIONS:
    app.command(_integration.command, help=_integration.help)(
        make_setup_command(_integration)
    )


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
        values = integration.run()
        if values:
            write_env_local(values)

    console.print()
    console.rule("[bold green]Setup complete[/]")
    console.print()
    console.print(build_status_table())
    console.print()
