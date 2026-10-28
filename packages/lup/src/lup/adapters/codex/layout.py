"""Where Codex's adapter keeps what it stores: lup's own Codex home, beside the operator's.

Every ask runs Codex under a home of lup's own, `$XDG_STATE_HOME/lup/codex`, so the
operator's configuration, MCP servers, hooks, skills, `AGENTS.md` and history don't
reach a call from code. Its one link to the operator's home is their login:
`auth.json` in lup's home is a symbolic link to theirs (`$CODEX_HOME/auth.json`, or
`~/.codex/auth.json`). Codex rewrites that file in place, so a refresh writes through
the link to the one real copy, and logging out from lup's home removes only the link.

A terminal session runs in a home of the launch's own on a home of the rooms'
own instead (`CodexHome`), its configuration copied from the operator's, with
the launch's managed requirements, a file of the launch's own, mounted where
Codex reads them.
"""

from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

from lup.sessions.configuration import Item
from lup.sessions.errors import RuntimeMissingError
from lup.sessions.terminal import Preference
from lup.types import Model

if TYPE_CHECKING:
    from lup.adapters.codex.settings import CodexSettings

MANAGED_REQUIREMENTS = Path("/etc/codex/requirements.toml")
"""Where Codex reads the system's requirements on Linux, managed hooks among them."""


class CodexLayout(Model):
    """lup's own Codex home, and the operator's, whose login it links to."""

    home: Path
    """lup's own Codex home: no configuration of its own, the operator's login linked in."""
    operator_home: Path
    """The operator's Codex home, where their login is kept."""
    user_skills: Path | None = None
    """The operator's own skills, `~/.agents/skills`, which Codex reads from the
    home directory beside its own; none where they're not looked for."""

    @classmethod
    def of(cls, settings: CodexSettings) -> CodexLayout:
        """Place both homes where the settings say, or at their defaults, and the operator's skills in their home."""
        state = settings.xdg_state_home or Path.home() / ".local" / "state"
        operator = settings.codex_home or Path.home() / ".codex"
        return cls(
            home=state / "lup" / "codex",
            operator_home=operator.absolute(),
            user_skills=Path.home() / ".agents" / "skills",
        )

    @property
    def login(self) -> Path:
        """The login in lup's home: a link to the operator's."""
        return self.home / "auth.json"

    @property
    def operator_login(self) -> Path:
        """The operator's login, as Codex keeps it in a file."""
        return self.operator_home / "auth.json"

    @property
    def operator_config(self) -> Path:
        """The operator's own Codex configuration."""
        return self.operator_home / "config.toml"

    @property
    def bundled(self) -> Path:
        """The directory of the Codex CLI the SDK pins: the binary, and the helpers beside it."""
        found = find_spec("codex_cli_bin")
        origin = None if found is None else found.origin
        package = None if origin is None else Path(origin).parent
        if package is None or not (package / "bin" / "codex").is_file():
            message = (
                "the Codex CLI the SDK pins isn't installed: reinstall the "
                "`lup[codex]` extra, or give the CLI's path"
            )
            raise RuntimeMissingError(message)
        return package

    @property
    def bundled_cli(self) -> Path:
        """The Codex CLI the SDK pins, inside `bundled`."""
        return self.bundled / "bin" / "codex"


class CodexHome(Model):
    """What Codex keeps in its home, as a launch lays it out on a home of the rooms' own (`lup.sessions.terminal.RuntimeHome`).

    The directory is the launch's own: every file Codex reads there as
    configuration or state is the launch's, `.env` among them, whose variables
    Codex 0.162.0 sets in what it runs, and its SQLite state, where its goals
    and queued input are kept. Only `shared` is linked into the home the rooms
    share, from which Codex resumes a thread by its id. Read in Codex's docs
    (`agents-md`, `config-basic`, `build-skills`, 2026-10-27) and measured on
    0.162.0 in a room (`docs/field-notes.md`, *A home of the rooms' own*).
    """

    directory: Path
    configuration: list[Item] = [
        Item(name="AGENTS.md", directory=False),
        Item(name="AGENTS.override.md", directory=False),
        Item(name="rules"),
        Item(name="prompts"),
    ]
    """Each item of configuration copied in from the layers."""
    shared: list[Item] = [
        Item(name="sessions"),
        Item(name="archived_sessions"),
        Item(name="history.jsonl", directory=False),
        Item(name="session_index.jsonl", directory=False),
    ]
    """The history the rooms given the home share: each thread's rollout, the
    prompts typed, and the threads' names."""
    preferences: list[Preference] = [
        Preference(keys=["model"]),
        Preference(keys=["model_reasoning_effort"]),
        Preference(keys=["plan_mode_reasoning_effort"]),
        Preference(keys=["model_verbosity"]),
        Preference(keys=["personality"]),
        Preference(keys=["tui", "theme"]),
    ]
    """What a session saves in its configuration that a launch carries back:
    `/model`'s choice, its effort, and the like."""

    @property
    def config(self) -> Path:
        """Where Codex reads its configuration and saves its preferences."""
        return self.directory / "config.toml"

    @property
    def login(self) -> Path:
        """Where Codex reads its login: the account's file, mounted there."""
        return self.directory / "auth.json"

    def profile(self, name: str) -> Path:
        """Say where Codex reads its own profile `name`, which `--profile` layers over its configuration."""
        return self.directory / name


class CodexLaunch(Model):
    """The files a launch writes for Codex, in its own directory."""

    directory: Path

    @property
    def user_skills(self) -> Path:
        """The launch's copy of the operator's own skills, mounted read-only where Codex reads them in the room's home."""
        return self.directory / "agents-skills"

    @property
    def requirements(self) -> Path:
        """The launch's managed requirements: lup's hooks, and no others."""
        return self.directory / "requirements.toml"
