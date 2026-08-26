"""Provider commands for retaining authenticated AI conversations."""

import asyncio
import logging
from pathlib import Path

import typer
from pydantic import BaseModel

from lup.devtools.conversation.browser import login, require_playwright
from lup.devtools.conversation.checkpoint import checkpoint_delivery
from lup.devtools.conversation.errors import ConversationDownloadError
from lup.providers.profiles import ProfileDirectory
from lup.workspace.paths import project_root

logger = logging.getLogger(__name__)


class BrowserDirectories(BaseModel, frozen=True):
    """The selected browser state followed by compatible persisted states."""

    primary: Path
    fallbacks: tuple[Path, ...] = ()

    def candidates(self) -> tuple[Path, ...]:
        """Every state a headless download may try, in preference order."""
        return (self.primary, *self.fallbacks)


def browser_directory(
    root: Path,
    provider: str,
    profiles: ProfileDirectory | None,
    profile: str | None,
) -> Path:
    """Resolve explicit, active, then unprofiled browser state."""
    if profiles is not None:
        try:
            selected = profiles.state_dir(profile, f"{provider}-web")
        except KeyError as error:
            raise typer.BadParameter(str(error), param_hint="--profile") from error
        if selected is not None:
            return selected
    elif profile is not None:
        raise typer.BadParameter(
            "this project declares no named profiles", param_hint="--profile"
        )
    return root / ".lup" / "conversations" / f"{provider}-web"


def browser_directories(
    root: Path,
    provider: str,
    profiles: ProfileDirectory | None,
    profile: str | None,
) -> BrowserDirectories:
    """Resolve selected state plus persisted unprofiled compatibility state."""
    primary = browser_directory(root, provider, profiles, profile)
    unprofiled = root / ".lup" / "conversations" / f"{provider}-web"
    legacy = root / ".lup" / "conversations" / f"{provider}-browser"
    fallbacks = (legacy,) if primary == unprofiled and legacy.exists() else ()
    return BrowserDirectories(primary=primary, fallbacks=fallbacks)


async def authenticated_chatgpt(
    url: str, root: Path, directories: BrowserDirectories, output: Path
) -> Path:
    """Download through stored states, refusing when explicit setup is needed."""
    require_playwright()
    from lup.devtools.conversation.chatgpt import (
        ChatGPTAuthenticationRequired,
        ConversationReference,
        download_chatgpt,
    )

    reference = ConversationReference(value=url)
    authentication_error: ChatGPTAuthenticationRequired | None = None
    for directory in directories.candidates():
        try:
            return await download_chatgpt(
                reference, root=root, directory=directory, output=output
            )
        except ChatGPTAuthenticationRequired as error:
            authentication_error = error
    raise ChatGPTAuthenticationRequired(
        "The ChatGPT browser login is missing or expired. Run "
        "`uv run lup-devtools setup conversation chatgpt`, then retry."
    ) from authentication_error


async def authenticated_claude(
    url: str, root: Path, directories: BrowserDirectories, output: Path
) -> Path:
    """Download through stored states, refusing when explicit setup is needed."""
    require_playwright()
    from lup.devtools.conversation.claude import (
        ClaudeAuthenticationRequired,
        ConversationReference,
        download_claude,
    )

    reference = ConversationReference(value=url)
    authentication_error: ClaudeAuthenticationRequired | None = None
    for directory in directories.candidates():
        try:
            return await download_claude(
                reference, root=root, directory=directory, output=output
            )
        except ClaudeAuthenticationRequired as error:
            authentication_error = error
    raise ClaudeAuthenticationRequired(
        "The Claude browser login is missing or expired. Run "
        "`uv run lup-devtools setup conversation claude`, then retry."
    ) from authentication_error


def setup_browser_login(
    provider: str,
    label: str,
    page_url: str,
    profiles: ProfileDirectory | None,
    profile: str | None,
) -> None:
    """Open the explicit setup flow for one provider's selected browser state."""
    root = project_root()
    directories = browser_directories(root, provider, profiles, profile)
    asyncio.run(login(directories.primary, page_url, label))
    typer.echo(f"Saved the {label} browser login")


def create_conversation_setup_app(
    profiles: ProfileDirectory | None = None,
) -> typer.Typer:
    """Build the explicit interactive-login tree mounted beneath setup."""
    application = typer.Typer(
        no_args_is_help=True,
        help="Authenticate browser sessions used for conversation retention",
    )

    @application.command("chatgpt")
    def chatgpt_login(
        profile: str | None = typer.Option(
            None,
            "--profile",
            help="Named profile whose ChatGPT web session should be authenticated",
        ),
    ) -> None:
        """Open a browser to authenticate ChatGPT conversation access."""
        setup_browser_login(
            "chatgpt", "ChatGPT", "https://chatgpt.com/", profiles, profile
        )

    @application.command("claude")
    def claude_login(
        profile: str | None = typer.Option(
            None,
            "--profile",
            help="Named profile whose Claude web session should be authenticated",
        ),
    ) -> None:
        """Open a browser to authenticate Claude conversation access."""
        setup_browser_login("claude", "Claude", "https://claude.ai/", profiles, profile)

    return application


def report(destination: Path, provider: str, root: Path) -> None:
    """Checkpoint a retained delivery and report its repository path."""
    checkpoint_delivery(root, destination, provider=provider)
    try:
        displayed = destination.relative_to(root)
    except ValueError:
        displayed = destination
    typer.echo(f"Retained {provider} conversation at {displayed}")


def create_conversation_app(
    profiles: ProfileDirectory | None = None,
) -> typer.Typer:
    """Build the conversation command tree over a project's profile directory."""
    application = typer.Typer(no_args_is_help=True)

    @application.command("chatgpt")
    def chatgpt_cmd(
        url: str = typer.Argument(
            help="A chatgpt.com/c/... conversation or /share/... URL", metavar="URL"
        ),
        profile: str | None = typer.Option(
            None,
            "--profile",
            help="Named profile whose ChatGPT web session should be reused",
        ),
        output: Path = typer.Option(
            Path("tmp/conversations"),
            "--output",
            "-o",
            help="Directory under which provider and conversation ids are stored",
        ),
    ) -> None:
        """Retain a ChatGPT conversation and all downloadable attachments."""
        root = project_root()
        directories = browser_directories(root, "chatgpt", profiles, profile)
        try:
            target = output if output.is_absolute() else root / output
            destination = asyncio.run(
                authenticated_chatgpt(url, root, directories, target)
            )
        except ConversationDownloadError as error:
            logger.exception("Could not retain the ChatGPT conversation")
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error
        report(destination, "chatgpt", root)

    @application.command("claude")
    def claude_cmd(
        url: str = typer.Argument(
            help="A claude.ai/chat/... conversation or /share/... URL", metavar="URL"
        ),
        profile: str | None = typer.Option(
            None,
            "--profile",
            help="Named profile whose Claude web session should be reused",
        ),
        output: Path = typer.Option(
            Path("tmp/conversations"),
            "--output",
            "-o",
            help="Directory under which provider and conversation ids are stored",
        ),
    ) -> None:
        """Retain a Claude conversation and its API-provided attachment content."""
        root = project_root()
        directories = browser_directories(root, "claude", profiles, profile)
        try:
            target = output if output.is_absolute() else root / output
            destination = asyncio.run(
                authenticated_claude(url, root, directories, target)
            )
        except ConversationDownloadError as error:
            logger.exception("Could not retain the Claude conversation")
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error
        report(destination, "claude", root)

    return application


app = create_conversation_app()
