"""Compile Claude Code's settings keys into the types its flow decisions are typed against.

The model catalog's two moments, for the settings schema. Reading the keys
needs the CLI installed, and the gate must not, so `uv run lup-devtools dev
settings` reads the program and rewrites the snapshot committed beside the
provider (``settings_schema.json``), and generation — `harness generate
all`, and `dev check` after it — recompiles ``settings_keys.py`` from that
snapshot alone. The flow tables in :mod:`lup.providers.claude.preferences`
are typed against the compiled keys, so a key a table names that the CLI
does not take is a type error, and `dev check` refuses a key the CLI takes
that no table names. `dev settings --check` asks the CLI whether it moved.

Backs `lup-devtools dev settings` (wired in `lup.devtools.dev.app`).

Examples::

    $ uv run lup-devtools dev settings           # read the CLI, rewrite both
    $ uv run lup-devtools dev settings --check   # fail where the CLI moved
"""

import json
from functools import partial
from pathlib import Path

from pydantic import BaseModel

from lup.devtools.dev.library import VENDORED_SRC
from lup.devtools.dev.model_catalog import fitted
from lup.devtools.harness.drift import RepositoryWriter
from lup.formats.banner import REGENERATE_COMMAND, GeneratedBanner
from lup.harness.materialization import write_generated_file
from lup.harness.models import Artifact
from lup.providers.settings_schema import (
    SNAPSHOT_NAME,
    SettingsSchema,
    installed_settings_schema,
)
from lup.workspace.paths import project_root

# lup: ignore[constant-declaration] — the command a reader types, whose words are
# the CLI's own rather than a preference this module holds
SETTINGS_COMMAND = "uv run lup-devtools dev settings"
"""The command that reads the CLI's settings keys into their snapshot."""


class SettingsSchemaSource(BaseModel, frozen=True):
    """Where the snapshot and the module compiled from it are committed."""

    directory: Path = Path(VENDORED_SRC) / "lup" / "providers" / "claude"
    """The provider package, relative to the repository root."""

    def snapshot(self) -> Path:
        """Where the keys the CLI last reported are committed."""
        return self.directory / SNAPSHOT_NAME

    def module(self) -> Path:
        """Where the types compiled from that snapshot are committed."""
        return self.directory / "settings_keys.py"

    def compiled(self, schema: SettingsSchema) -> str:
        """The module these keys compile to, beneath no banner yet."""

        def literal(name: str, keys: list[str], said: str) -> str:
            quoted = [json.dumps(key) for key in keys]
            return fitted(f"type {name} = Literal", quoted, "") + f'"""{said}"""\n'

        return (
            '"""Every key Claude Code\'s settings and configuration document take.\n'
            "\n"
            f"Compiled from ``{SNAPSHOT_NAME}`` beside this module, which\n"
            f"``{SETTINGS_COMMAND}`` last read out of ``{schema.observed}``.\n"
            '"""\n'
            "\n"
            "from typing import Literal\n"
            "\n"
            + literal(
                "ClaudeSettingKey",
                schema.settings,
                "A key of the schema every Claude Code settings file is checked against.",
            )
            + "\n"
            + literal(
                "ClaudeDocumentKey",
                schema.document,
                "A key `claude config` accepts for the global configuration document.",
            )
        )

    def artifact(self, schema: SettingsSchema) -> Artifact:
        """The compiled module as one generated file, beneath its banner."""
        return Artifact.generated(
            path=self.module(),
            body=self.compiled(schema),
            semantic_id="settings.claude",
            banner=GeneratedBanner(
                source=self.snapshot().as_posix(),
                command=REGENERATE_COMMAND,
                notes=[f"`{SETTINGS_COMMAND}` reads that snapshot from the CLI."],
            ),
        )


def write_settings_keys(
    source: SettingsSchemaSource, root: Path | None = None, *, check: bool = False
) -> Path:
    """Write or verify the compiled module against its committed snapshot."""
    checkout = root or project_root()
    schema = SettingsSchema.read(checkout / source.snapshot())
    return write_generated_file(
        source.artifact(schema), checkout, REGENERATE_COMMAND, check=check
    )


def settings_writers(source: SettingsSchemaSource) -> list[RepositoryWriter]:
    """The compiled module as a generated file the gate keeps current."""
    return [partial(write_settings_keys, source)]


def refresh_settings_schema(
    source: SettingsSchemaSource, root: Path, *, check: bool
) -> list[str]:
    """Read the CLI, and rewrite the snapshot and module unless checking.

    Answers one line per key the CLI added or dropped, and, when checking,
    one more where the compiled module no longer says what the snapshot
    does. Checking writes nothing; refreshing answers the same lines as what
    moved.
    """
    live = installed_settings_schema()
    snapshot = root / source.snapshot()
    committed = (
        SettingsSchema.read(snapshot)
        if snapshot.is_file()
        else SettingsSchema(observed="", settings=[], document=[])
    )
    moved = committed.drift(live)
    if not check:
        snapshot.write_text(live.text(), encoding="utf-8")
        write_settings_keys(source, root)
        return moved
    try:
        write_settings_keys(source, root, check=True)
    except RuntimeError as behind:
        return [*moved, f"  ! {behind}"]
    return moved
