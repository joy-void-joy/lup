"""What a launched Claude Code session needs around it that the CLI does not do.

A contained session runs in its repository's volume rather than the
account's home, so what it changed of the person's settings is carried
back when it closes; this is that return, in Claude Code's own files.
"""

from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from lup.providers.login import ProviderLogin
from lup.providers.user_config import UserConfig, UserConfigFile
from lup.launch.config_volume import named_file
from lup.launch.container import read_config_home
from lup.providers.claude.config_home import (
    CLAUDE_HOME_DOCUMENT,
    WORKSPACE_SETTINGS,
    ClaudeConfigHome,
)
from lup.providers.claude.home_seed import (
    KEYBINDINGS,
    ClaudeHomeReturn,
    ClaudeHomeSeed,
)
from lup.harness.image import Image
from lup.harness.notice import Notice
from lup.types import JsonObject


def carry_claude_home(
    image: Image,
    root: Path,
    login: ProviderLogin,
    seed: ClaudeHomeSeed,
    account: ClaudeConfigHome,
    config: UserConfigFile,
    personal: UserConfig,
) -> None:
    """Bring back what a contained session changed of the person's, and say what stayed.

    Read out of the volume the session ran in and compared with what this
    launch seeded, so only the session's own changes move. Where the
    volume cannot be read, nothing moves and the launch says so rather
    than leaving a changed theme to look as though it never happened.
    """
    files = read_config_home(
        image, root, login, [WORKSPACE_SETTINGS, CLAUDE_HOME_DOCUMENT, KEYBINDINGS]
    )
    settings = named_file(files, WORKSPACE_SETTINGS)
    document = named_file(files, CLAUDE_HOME_DOCUMENT)
    keybindings = named_file(files, KEYBINDINGS)
    try:
        read = [
            TypeAdapter(JsonObject).validate_json(held.content)
            for held in (settings, document)
            if held is not None
        ]
    except ValidationError:
        read = []
    if settings is None or len(read) != (2 if document is not None else 1):
        Notice(
            text=(
                "Could not read this session's Claude settings back out of "
                "its volume, so nothing it changed was returned."
            ),
            urgency="warning",
        ).say()
        return
    returned = ClaudeHomeReturn.between(
        seed,
        read[0],
        read[1] if document is not None else {},
        keybindings.text() if keybindings is not None else None,
        personal,
    )
    returned.apply(account, config)
    if returned.carried():
        Notice(
            text=(
                "Returned the Claude settings this session changed: "
                + ", ".join(returned.carried())
            ),
            urgency="detail",
        ).say()
    stayed = [
        *(f"{key} (never leaves a container)" for key in returned.withheld),
        *(f"{key} (the session's own)" for key in returned.session),
    ]
    if stayed:
        Notice(
            text="Kept in the container: " + ", ".join(stayed),
            urgency="detail",
        ).say()
