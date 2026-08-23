"""Provider commands for retaining authenticated AI conversations."""

import asyncio
import logging
from pathlib import Path

import typer

from lup.devtools.conversation.browser import login, require_playwright
from lup.devtools.conversation.checkpoint import checkpoint_delivery
from lup.devtools.conversation.errors import ConversationDownloadError
from lup.runtime.profiles import ProfileDirectory
from lup.workspace.paths import project_root

logger = logging.getLogger(__name__)


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


async def authenticated_chatgpt(
    url: str, root: Path, directory: Path, output: Path
) -> Path:
    """Download through stored state, opening the requested page once if needed."""
    require_playwright()
    from lup.devtools.conversation.chatgpt import (
        ChatGPTAuthenticationRequired,
        ConversationReference,
        download_chatgpt,
    )

    reference = ConversationReference(value=url)
    try:
        return await download_chatgpt(
            reference, root=root, directory=directory, output=output
        )
    except ChatGPTAuthenticationRequired:
        await login(directory, reference.page_url(), "ChatGPT")
        return await download_chatgpt(
            reference, root=root, directory=directory, output=output
        )


async def authenticated_claude(
    url: str, root: Path, directory: Path, output: Path
) -> Path:
    """Download through stored state, opening the requested page once if needed."""
    require_playwright()
    from lup.devtools.conversation.claude import (
        ClaudeAuthenticationRequired,
        ConversationReference,
        download_claude,
    )

    reference = ConversationReference(value=url)
    try:
        return await download_claude(
            reference, root=root, directory=directory, output=output
        )
    except ClaudeAuthenticationRequired:
        await login(directory, reference.page_url(), "Claude")
        return await download_claude(
            reference, root=root, directory=directory, output=output
        )


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
        directory = browser_directory(root, "chatgpt", profiles, profile)
        try:
            target = output if output.is_absolute() else root / output
            destination = asyncio.run(
                authenticated_chatgpt(url, root, directory, target)
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
        directory = browser_directory(root, "claude", profiles, profile)
        try:
            target = output if output.is_absolute() else root / output
            destination = asyncio.run(
                authenticated_claude(url, root, directory, target)
            )
        except ConversationDownloadError as error:
            logger.exception("Could not retain the Claude conversation")
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error
        report(destination, "claude", root)

    return application


app = create_conversation_app()
