"""Claude Code's settings keys, read out of its program and held to a decision each.

A key read wrongly is a preference that never travels, or a hook that does; a
key nobody decided about is one the gate has to name. These pin the reader
against the shapes a minified program actually has — nested template code,
regular expressions holding brackets, values deeper than the object — the
snapshot's drift lines, and the gate's refusal of an undecided key.
"""

import json
import stat
from pathlib import Path

import pytest

import lup.providers.claude.preferences as preferences
from lup.devtools.dev.settings_schema import SettingsSchemaSource, write_settings_keys
from lup.providers.claude.settings_schema import ScriptScan, claude_settings_schema
from lup.providers.settings_schema import SettingsSchema, unclassified_settings

PROGRAM = (
    'var a=1;function f(){return d({$schema:o().optional().describe("JSON Schema '
    'reference for Claude Code settings"),hooks:z({PreToolUse:o()}).describe('
    '"Custom commands"),spellcheck:o().describe(`Which: ${k.map((c)=>`"${c}"`).'
    'join(", ")}, {x:1}`),theme:o().regex(/^[{(]x:$/u).optional(),"editorMode":'
    'z(["normal","vim"]),verbose:O().optional()}).passthrough()}'
    'var Bzn=["apiKeyHelper","theme","shiftEnterKeyBindingInstalled","diffTool"];'
)


def test_the_scan_keeps_only_the_objects_own_keys() -> None:
    program = PROGRAM.encode()
    keys: list[str] = []

    ScriptScan(program).walk(program.index(b"{$schema"), keys)

    assert keys == ["$schema", "hooks", "spellcheck", "theme", "editorMode", "verbose"]


def test_the_reader_finds_the_schema_and_the_document_keys(tmp_path: Path) -> None:
    program = tmp_path / "claude"
    program.write_text(
        f"#!/bin/sh\necho '9.9.9 (Claude Code)'\nexit 0\n{PROGRAM}\n", encoding="utf-8"
    )
    program.chmod(program.stat().st_mode | stat.S_IXUSR)

    schema = claude_settings_schema(program)

    assert schema.observed == "9.9.9 (Claude Code)"
    assert schema.settings == [
        "$schema",
        "hooks",
        "spellcheck",
        "theme",
        "editorMode",
        "verbose",
    ]
    assert schema.document == [
        "apiKeyHelper",
        "theme",
        "shiftEnterKeyBindingInstalled",
        "diffTool",
    ]


def test_a_program_without_the_schema_is_refused_naming_what_moved(
    tmp_path: Path,
) -> None:
    program = tmp_path / "claude"
    program.write_text("#!/bin/sh\n", encoding="utf-8")

    with pytest.raises(ValueError, match="carries no settings schema"):
        claude_settings_schema(program)


def test_drift_names_each_key_added_and_dropped() -> None:
    committed = SettingsSchema(observed="1", settings=["a", "b"], document=["x"])
    live = SettingsSchema(observed="2", settings=["b", "c"], document=["x", "y"])

    assert committed.drift(live) == ["  + c", "  - a", "  + document y"]
    assert live.drift(live) == []


def test_every_key_the_snapshot_holds_has_a_decision() -> None:
    """The gate's own claim, which a CLI refresh adding a key breaks."""
    assert unclassified_settings() == []


def test_a_key_no_decision_names_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    flows = {key: flow for key, flow in preferences.SETTINGS_FLOWS.items()}
    flows.pop("verbose")
    monkeypatch.setattr(preferences, "SETTINGS_FLOWS", flows)

    assert unclassified_settings() == ["verbose"]
    assert preferences.setting_flow("verbose") == "withheld"


def test_the_compiled_key_types_say_what_the_snapshot_does(tmp_path: Path) -> None:
    source = SettingsSchemaSource(directory=Path("claude"))
    (tmp_path / "claude").mkdir()
    snapshot = SettingsSchema(
        observed="9.9.9", settings=["$schema", "theme"], document=["diffTool"]
    )
    (tmp_path / source.snapshot()).write_text(snapshot.text(), encoding="utf-8")

    written = write_settings_keys(source, tmp_path)

    compiled = written.read_text(encoding="utf-8")
    assert 'type ClaudeSettingKey = Literal["$schema", "theme"]' in compiled
    assert 'type ClaudeDocumentKey = Literal["diffTool"]' in compiled
    assert write_settings_keys(source, tmp_path, check=True) == written
    assert json.loads((tmp_path / source.snapshot()).read_text())["observed"] == "9.9.9"
