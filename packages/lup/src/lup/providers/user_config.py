"""What one person has decided for every project they run lup in.

A checkout holds what everyone working on it shares, and nothing about the
person running it: which account they sign in as, how their terminal is
drawn, how hard and on which model a session thinks when nobody said. Kept in
a checkout, each of those starts over in the next one — a new repository
opened signed out, in the runtime's default theme. So they live once per
person, at ``$XDG_CONFIG_HOME/lup`` (``~/.config/lup`` where that is unset)::

    config.toml         the decisions below
    profiles/<name>/    one account per name, a home per runtime inside it

Every field carries lup's own answer, so a person who writes nothing gets it
and one line changes one answer. The same precedence holds wherever a value is
chosen: lup's default, then this file, then what the project declares, then
what the invocation names — each overruling the one before, so this file never
decides what a project or a flag already did.

Read where a run starts rather than cached, so an edit reaches the next launch
with nothing to restart; and refused when it does not parse, because a
decision silently dropped reads exactly like one never made.
"""

from pathlib import Path

import tomlkit
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings
from tomlkit.exceptions import TOMLKitError

from lup.channels.models import write_atomic
from lup.harness.models import NativeName
from lup.providers.claude.theme import ClaudeTheme
from lup.providers.codex.theme import claude_daltonized_theme
from lup.providers.selection import SessionEffort
from lup.types import ModelTier


class UserTheme(BaseModel, frozen=True, extra="forbid"):
    """How each runtime's interface is drawn, in that runtime's own name for it.

    A name per runtime rather than one for both, because the two share no
    vocabulary: Claude Code ships its themes, and Codex reads TextMate files
    by name. lup's default is one colorblind palette on both — Claude Code's
    own, and the port of it lup installs into every Codex home it makes.
    """

    claude: ClaudeTheme = "dark-daltonized"
    codex: NativeName = Field(default_factory=lambda: claude_daltonized_theme().slug)


class UserConfig(BaseModel, frozen=True, extra="forbid"):
    """One person's standing answers, each defaulting to lup's own."""

    profile: str | None = None
    """The account a launch runs as when none is named: a directory under
    ``profiles/``, holding that account's home for each runtime. Unset, a
    launch keeps whichever home its environment already selects."""

    theme: UserTheme = UserTheme()

    effort: SessionEffort | None = None
    """How hard a session thinks when nothing names an effort. Unset, the
    model's default: ``xhigh`` where its catalog row takes it, the row's
    highest rung below that otherwise. Named, it is the rung a session starts
    from before stepping down to one the model takes, so a model lacking it
    still opens rather than being refused a default."""

    tier: ModelTier = "strongest"
    """The model a session runs on when nothing names one, as a portable tier
    each runtime spells in its own lineup; ``inherit`` leaves the runtime's."""


class UserConfigHome(BaseSettings):
    """Where the XDG base directory specification says a person's config lives.

    Its one variable, read the specification's way: an absolute path moves
    every program's configuration, and an empty or relative one is ignored in
    favour of ``~/.config``.
    """

    xdg_config_home: str = ""

    def directory(self) -> Path:
        """lup's own directory under that base."""
        named = Path(self.xdg_config_home)
        base = named if named.is_absolute() else Path.home() / ".config"
        return base / "lup"


class UserConfigFile:
    """The directory holding one person's decisions and the accounts they name."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = home if home is not None else UserConfigHome().directory()

    def path(self) -> Path:
        """The file :class:`UserConfig` is read from and written to."""
        return self.home / "config.toml"

    def profiles_root(self) -> Path:
        """Where each named account keeps its directory."""
        return self.home / "profiles"

    def document(self) -> tomlkit.TOMLDocument:
        """The file as written, comments and order included, or an empty one."""
        path = self.path()
        if not path.is_file():
            return tomlkit.document()
        try:
            return tomlkit.parse(path.read_text(encoding="utf-8"))
        except TOMLKitError as error:
            raise ValueError(f"{path} is not valid TOML: {error}") from error

    def load(self) -> UserConfig:
        """What this person decided, lup's default wherever they decided nothing."""
        try:
            return UserConfig.model_validate(self.document().unwrap())
        except ValidationError as error:
            raise ValueError(
                f"{self.path()} holds a setting lup cannot read: {error}"
            ) from error

    def select_profile(self, name: str | None) -> None:
        """Record the account a launch naming none runs as, changing nothing else.

        Written through the parsed document, so a person's comments and the
        order they wrote things in survive a selection made by a command.
        """
        document = self.document()
        if name is None:
            document.pop("profile", None)
        else:
            document["profile"] = name
        UserConfig.model_validate(document.unwrap())
        write_atomic(self.path(), tomlkit.dumps(document).encode("utf-8"))
