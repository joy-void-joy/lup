"""Which of a person's Codex settings a session may carry back out of its home.

Claude Code's decisions (:mod:`lup.providers.claude.preferences`), for Codex's
configuration. A session runs in a home lup derives — a worktree's on the host,
or its repository's volume in a container — and at every launch that home is
given the account's settings with the person's lup config winning. What a
session changes there comes back only where it is the person's: a display or
input preference, the portable ones (the theme, the editor mode) to the lup
config, the rest to the account's ``config.toml``. The model and effort a
session picked stay its own; anything that runs a program, reaches further or
records the runtime's own state never leaves.

Unlike Claude Code, Codex ships no settings schema lup can read — its program
carries a parser, not a list — so the decisions here are a list of what
returns and what is the session's, and every other key is withheld. A key a
newer Codex added stays in the home until somebody decides otherwise.

Measured on Codex 0.156.1, in a pseudo-terminal against a private home:
``/theme`` writes ``tui.theme`` to ``config.toml`` (``theme =
"coldark-dark"`` under ``[tui]``), and ``tui.vim_mode_default = true`` opens the
composer in vim mode (the footer reads ``Vim: Insert``); without it the
footer carries no mode at all.
"""

from collections.abc import Iterator

from pydantic import BaseModel

from lup.providers.settings_schema import SettingFlow
from lup.providers.user_config import UserConfig
from lup.types import JsonObject, JsonValue

# lup: ignore[constant-declaration] — a decision per Codex key, made once here;
# a key it does not name stays in the home it was written in
RETURNING: list[tuple[str, ...]] = [
    ("tui", "theme"),
    ("tui", "vim_mode_default"),
    ("tui", "keymap"),
    ("tui", "alternate_screen"),
    ("tui", "animations"),
    ("tui", "auto_recap"),
    ("tui", "disable_paste_burst"),
    ("tui", "effects"),
    ("tui", "fullscreen_transcript"),
    ("tui", "notifications"),
    ("tui", "notification_method"),
    ("tui", "pet"),
    ("tui", "pet_anchor"),
    ("tui", "question_esc_back"),
    ("tui", "raw_output_mode"),
    ("tui", "rendering"),
    ("tui", "session_picker_view"),
    ("tui", "show_tooltips"),
    ("tui", "status_line"),
    ("tui", "status_line_use_colors"),
    ("tui", "terminal_resize_reflow_max_rows"),
    ("tui", "terminal_title"),
    ("file_opener",),
    ("hide_agent_reasoning",),
    ("show_raw_agent_reasoning",),
    ("disable_paste_burst",),
]
"""Display and input preferences: a session's change to one returns to the person."""

# lup: ignore[constant-declaration] — the settings a session picks for itself
SESSION: list[tuple[str, ...]] = [
    ("model",),
    ("model_reasoning_effort",),
    ("model_reasoning_summary",),
    ("model_verbosity",),
    ("plan_mode_reasoning_effort",),
    ("service_tier",),
]
"""The model and how hard it thinks, the session's own: never carried back."""


class PortableSetting(BaseModel, frozen=True):
    """One Codex setting a lup config holds for every project, and its place there."""

    codex: tuple[str, ...]
    lup: tuple[str, ...]


# lup: ignore[constant-declaration] — the Codex keys the lup config names in
# its own words
PORTABLE = [
    PortableSetting(codex=("tui", "theme"), lup=("theme", "codex")),
    PortableSetting(codex=("tui", "vim_mode_default"), lup=("editor",)),
]
"""The Codex settings a lup config holds, which both directions translate."""


def codex_setting_flow(path: tuple[str, ...]) -> SettingFlow:
    """Where a change to one setting goes: named, or under a named table."""

    def under(listed: list[tuple[str, ...]]) -> bool:
        return any(path[: len(named)] == named for named in listed)

    if under(RETURNING):
        return "returns"
    if under(SESSION):
        return "session"
    return "withheld"


class SettingChange(BaseModel, frozen=True):
    """One personal setting a session changed: set to ``value``, or removed.

    ``None`` stands for removed: TOML has no null, so no setting can hold it.
    """

    path: tuple[str, ...]
    value: JsonValue | None = None

    def name(self) -> str:
        """The setting as a person writes its key."""
        return ".".join(self.path)


def changed_settings(
    before: JsonObject, after: JsonObject, prefix: tuple[str, ...] = ()
) -> Iterator[SettingChange]:
    """Every leaf a session set or removed, table by table."""
    for key in sorted({*before, *after}):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        if isinstance(old, dict) and isinstance(new, dict):
            yield from changed_settings(old, new, (*prefix, key))
        else:
            yield SettingChange(path=(*prefix, key), value=new)


def setting_leaves(
    table: JsonObject, prefix: tuple[str, ...] = ()
) -> Iterator[SettingChange]:
    """Every leaf of a nested table, each as the setting it sets."""
    for key, value in table.items():
        if isinstance(value, dict):
            yield from setting_leaves(value, (*prefix, key))
        else:
            yield SettingChange(path=(*prefix, key), value=value)


def held_at(table: JsonObject, path: tuple[str, ...]) -> bool:
    """Whether a nested table holds a value at that path."""
    match path:
        case (key,):
            return key in table
        case (key, *rest):
            inner = table.get(key)
            return isinstance(inner, dict) and held_at(inner, tuple(rest))
        case _:
            return False


class CodexSettingsReturn(BaseModel, frozen=True):
    """Where every setting a Codex session changed goes, and what stays behind."""

    portable: dict[tuple[str, ...], JsonValue | None] = {}
    """Changes for the person's lup config, at the dotted path it holds each."""

    account: list[SettingChange] = []
    """Changes for the account's ``config.toml``."""

    withheld: list[str] = []
    """Settings a session changed that never leave its home."""

    session: list[str] = []
    """Settings a session changed that were its own to change."""

    @classmethod
    def sorted_out(
        cls, changes: list[SettingChange], personal: UserConfig
    ) -> "CodexSettingsReturn":
        """Sort a session's changes by flow, and each returning one by destination.

        A portable setting goes to the lup config, in its words there — the
        vim default as the editor mode it spells; one the person's
        ``[codex.settings]`` table holds goes back into that table, which
        would otherwise hide the account's copy; anything else returning goes
        to the account.
        """
        returning = [
            change for change in changes if codex_setting_flow(change.path) == "returns"
        ]

        def portable(change: SettingChange) -> tuple[str, ...]:
            named = [held.lup for held in PORTABLE if held.codex == change.path]
            if named:
                return named[0]
            if held_at(personal.codex.settings, change.path):
                return ("codex", "settings", *change.path)
            return ()

        def spelled(change: SettingChange) -> JsonValue | None:
            if change.path == ("tui", "vim_mode_default") and change.value is not None:
                return "vim" if change.value else "normal"
            return change.value

        return cls(
            portable={
                portable(change): spelled(change)
                for change in returning
                if portable(change)
            },
            account=[change for change in returning if not portable(change)],
            withheld=[
                change.name()
                for change in changes
                if codex_setting_flow(change.path) == "withheld"
            ],
            session=[
                change.name()
                for change in changes
                if codex_setting_flow(change.path) == "session"
            ],
        )

    def carried(self) -> list[str]:
        """The dotted names of everything this return writes somewhere."""
        return [
            *(".".join(path) for path in self.portable),
            *(change.name() for change in self.account),
        ]
