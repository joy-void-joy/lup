"""Each runtime's terminal compile: the command, variables, files and mounts, compared whole."""

import asyncio
import json
import sys
import tomllib
from datetime import timedelta
from importlib.util import find_spec
from pathlib import Path

import pytest
from pydantic import JsonValue, ValidationError

from lup.adapters.claude import Claude
from lup.adapters.codex import Codex
from lup.adapters.codex.terminal import toml
from lup.rooms.container import Mount
from lup.sessions.errors import RuntimeMissingError
from lup.sessions.terminal import (
    Cli,
    Hook,
    SessionSettings,
    TerminalError,
    TerminalSettings,
)

HOOK = ["socat", "-t", "36000", "-", "UNIX-CONNECT:/run/lup/hook.sock"]
HOOK_LINE = "socat -t 36000 - UNIX-CONNECT:/run/lup/hook.sock"
WORKTREE = Path("/srv/lup.git/tree/dev")
REPOSITORY = Path("/srv/lup.git")
GUIDANCE = '# lup\nWork in the room; "quotes" and a tab\tsurvive.\n'
CLAUDE_CLI = Cli(program=Path("/opt/clis/claude"))
CODEX_PACKAGE = Path("/opt/clis/codex/0.162.1")
CODEX_CLI = Cli(program=CODEX_PACKAGE / "bin" / "codex", directory=CODEX_PACKAGE)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return home


def settings(directory: Path, cli: Cli | None, **changes: object) -> TerminalSettings:
    sample = TerminalSettings(
        directory=directory,
        cli=cli,
        hooks=[
            Hook(event="session-started", command=HOOK, timeout=timedelta(hours=10)),
            Hook(
                event="call-started",
                matcher="Edit|Write",
                command=HOOK,
                timeout=timedelta(hours=10),
            ),
            Hook(event="call-finished", command=HOOK),
        ],
        guidance=GUIDANCE,
        session=SessionSettings(
            subagent_cache=timedelta(hours=1),
            auto_memory=False,
            removed_tools=["Artifact", "SendFeedback"],
        ),
        trusted=[WORKTREE, REPOSITORY],
    )
    return sample.model_copy(update=changes)


def nothing(name: str) -> None:
    """Find no module, as when an extra isn't installed."""
    del name


def decoded(files: dict[Path, str]) -> dict[Path, object]:
    def read(path: Path, text: str) -> object:
        match path.suffix:
            case ".json":
                return json.loads(text)
            case ".toml":
                return tomllib.loads(text)
            case _:
                return text

    return {path: read(path, text) for path, text in files.items()}


# Claude Code


def test_claude_compiles_its_flags_settings_state_and_mounts(
    tmp_path: Path, home: Path
) -> None:
    launch = tmp_path / "launch"
    terminal = Claude(model="opus", effort="high").terminal(
        settings(launch, CLAUDE_CLI)
    )

    assert terminal.command == [
        "/opt/clis/claude",
        "--setting-sources",
        "user",
        "--settings",
        str(launch / "settings.json"),
        "--permission-mode",
        "bypassPermissions",
        "--model",
        "opus",
        "--effort",
        "high",
        "--append-system-prompt-file",
        str(launch / "guidance.md"),
    ]
    assert terminal.env == {
        "CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS": "0",
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": "1h",
    }
    command = {"type": "command", "command": HOOK_LINE}
    timed = {**command, "timeout": 36000}
    assert decoded(terminal.files) == {
        launch / "settings.json": {
            "hooks": {
                "SessionStart": [{"hooks": [timed]}],
                "PreToolUse": [{"matcher": "Edit|Write", "hooks": [timed]}],
                "PostToolUse": [{"hooks": [command]}],
                "PostToolUseFailure": [{"hooks": [command]}],
            },
            "permissions": {"deny": ["Artifact", "SendFeedback"]},
            "disableClaudeAiConnectors": True,
            "skipDangerousModePermissionPrompt": True,
        },
        launch / "claude.json": {
            "hasCompletedOnboarding": True,
            "projects": {
                str(WORKTREE): {"hasTrustDialogAccepted": True},
                str(REPOSITORY): {"hasTrustDialogAccepted": True},
            },
        },
        launch / "guidance.md": GUIDANCE,
    }
    assert terminal.mounts == [
        Mount(source=home / ".claude"),
        Mount(source=Path("/opt/clis/claude"), read_only=True),
        Mount(source=launch, read_only=True),
        Mount(source=launch / "claude.json", target=home / ".claude.json"),
    ]


def test_claude_replaces_its_prompt_only_when_the_declaration_gives_one(
    tmp_path: Path, home: Path
) -> None:
    launch = tmp_path / "launch"
    bare = settings(
        launch,
        CLAUDE_CLI,
        guidance=None,
        session=SessionSettings(auto_memory=True, subagent_cache=timedelta(minutes=5)),
    )

    kept = Claude(model="opus").terminal(bare)
    replaced = Claude(model="opus", system_prompt="You narrate.").terminal(bare)

    assert "--system-prompt-file" not in kept.command
    assert "--append-system-prompt-file" not in kept.command
    assert "--effort" not in kept.command
    assert replaced.command[-2:] == [
        "--system-prompt-file",
        str(launch / "system-prompt.md"),
    ]
    assert replaced.files[launch / "system-prompt.md"] == "You narrate."
    assert kept.env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "0"
    assert kept.env["CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL"] == "5m"
    deny = json.loads(kept.files[launch / "settings.json"])["permissions"]["deny"]
    assert deny == []


def test_claude_fetches_the_account_s_connectors_only_when_asked(
    tmp_path: Path, home: Path
) -> None:
    launch = tmp_path / "launch"

    def written(session: SessionSettings) -> object:
        terminal = Claude(model="opus").terminal(
            settings(launch, CLAUDE_CLI, session=session)
        )
        return json.loads(terminal.files[launch / "settings.json"])

    off = written(SessionSettings())
    on = written(SessionSettings(account_connectors=True))

    assert isinstance(off, dict)
    assert off["disableClaudeAiConnectors"] is True
    assert isinstance(on, dict)
    assert "disableClaudeAiConnectors" not in on
    assert on["permissions"] == {"deny": []}


def test_claude_leaves_memory_and_cache_to_the_runtime_when_unset(
    tmp_path: Path, home: Path
) -> None:
    terminal = Claude(model="opus").terminal(
        settings(tmp_path / "launch", CLAUDE_CLI, session=SessionSettings())
    )

    assert terminal.env == {
        "CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS": "0",
        "DISABLE_AUTOUPDATER": "1",
    }


def test_claude_follows_a_moved_config_directory(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    moved = tmp_path / "claude-work"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(moved))
    launch = tmp_path / "launch"

    terminal = Claude(model="opus").terminal(settings(launch, CLAUDE_CLI))

    assert terminal.env["CLAUDE_CONFIG_DIR"] == str(moved)
    assert terminal.mounts[0] == Mount(source=moved)
    assert terminal.mounts[-1] == Mount(
        source=launch / "claude.json", target=moved / ".claude.json"
    )


def test_claude_runs_the_cli_its_sdk_bundles_without_one_given(
    tmp_path: Path, home: Path
) -> None:
    found = find_spec("claude_agent_sdk")
    assert found is not None
    assert found.origin is not None
    bundled = Path(found.origin).parent / "_bundled" / "claude"

    terminal = Claude(model="opus").terminal(settings(tmp_path / "launch", None))

    assert terminal.command[0] == str(bundled)
    assert Mount(source=bundled, read_only=True) in terminal.mounts


def test_claude_refuses_without_its_bundled_cli(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("lup.adapters.claude.layout.find_spec", nothing)

    with pytest.raises(RuntimeMissingError, match="lup\\[claude\\]"):
        Claude(model="opus").terminal(settings(tmp_path / "launch", None))


def test_claude_with_no_model_leaves_the_operator_s_to_claude_code(
    tmp_path: Path, home: Path
) -> None:
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps({"model": "opus[1m]"}))

    terminal = Claude(effort="high").terminal(settings(tmp_path / "launch", CLAUDE_CLI))

    assert "--model" not in terminal.command
    assert terminal.command[terminal.command.index("--effort") + 1] == "high"


# Codex


@pytest.fixture
def codex_home(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    return codex_home


def test_codex_compiles_its_flags_overrides_requirements_and_mounts(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text(
        'model = "gpt-6.1-sol"\n'
        "[mcp_servers.node_repl]\n"
        'command = "/Applications/ChatGPT.app/node_repl"\n'
        '[mcp_servers."docs.search"]\n'
        'url = "https://docs.example/mcp"\n'
    )
    launch = tmp_path / "launch"
    terminal = Codex(model="gpt-6.1-sol", effort="high").terminal(
        settings(launch, CODEX_CLI)
    )

    assert terminal.command == [
        "/opt/clis/codex/0.162.1/bin/codex",
        "--no-daemon",
        "--dangerously-bypass-approvals-and-sandbox",
        "--model",
        "gpt-6.1-sol",
        "-c",
        'model_reasoning_effort="high"',
        "-c",
        (
            'projects={"/srv/lup.git/tree/dev" = {trust_level = "trusted"},'
            '"/srv/lup.git" = {trust_level = "trusted"}}'
        ),
        "-c",
        "features.memories=false",
        "-c",
        "check_for_update_on_startup=false",
        "-c",
        "features.apps=false",
        "-c",
        "features.plugins=false",
        "-c",
        'mcp_servers={node_repl = {enabled = false},"docs.search" = {enabled = false}}',
        "-c",
        "developer_instructions=" + json.dumps(GUIDANCE),
        "-c",
        "project_doc_max_bytes=0",
    ]
    assert terminal.env == {"CODEX_HOME": str(codex_home)}
    command = {"type": "command", "command": HOOK_LINE}
    timed = {**command, "timeout": 36000}
    assert decoded(terminal.files) == {
        launch / "requirements.toml": {
            "allow_managed_hooks_only": True,
            "hooks": {
                "SessionStart": [{"hooks": [timed]}],
                "PreToolUse": [{"matcher": "Edit|Write", "hooks": [timed]}],
                "PostToolUse": [{"hooks": [command]}],
            },
        }
    }
    assert terminal.mounts == [
        Mount(source=codex_home),
        Mount(source=CODEX_PACKAGE, read_only=True),
        Mount(
            source=launch / "requirements.toml",
            target=Path("/etc/codex/requirements.toml"),
            read_only=True,
        ),
    ]


def test_every_codex_override_parses_as_toml_rather_than_falling_back_to_text(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text('[mcp_servers.node_repl]\ncommand = "x"\n')
    terminal = Codex(model="gpt-6.1-sol", system_prompt="You narrate.").terminal(
        settings(tmp_path / "launch", CODEX_CLI)
    )

    overrides = [
        argument
        for flag, argument in zip(terminal.command, terminal.command[1:], strict=False)
        if flag == "-c"
    ]
    parsed = {}
    for override in overrides:
        key, _, value = override.partition("=")
        parsed[key] = tomllib.loads(f"_x_ = {value}")["_x_"]

    assert parsed == {
        "instructions": "You narrate.",
        "projects": {
            str(WORKTREE): {"trust_level": "trusted"},
            str(REPOSITORY): {"trust_level": "trusted"},
        },
        "features.memories": False,
        "check_for_update_on_startup": False,
        "features.apps": False,
        "features.plugins": False,
        "mcp_servers": {"node_repl": {"enabled": False}},
        "developer_instructions": GUIDANCE,
        "project_doc_max_bytes": 0,
    }


def test_codex_without_an_operator_config_or_settings_turns_off_only_its_own(
    tmp_path: Path, codex_home: Path
) -> None:
    launch = tmp_path / "launch"
    bare = TerminalSettings(directory=launch, cli=CODEX_CLI)

    terminal = Codex(model="gpt-6.1-sol").terminal(bare)

    assert terminal.command == [
        "/opt/clis/codex/0.162.1/bin/codex",
        "--no-daemon",
        "--dangerously-bypass-approvals-and-sandbox",
        "--model",
        "gpt-6.1-sol",
        "-c",
        "check_for_update_on_startup=false",
        "-c",
        "features.apps=false",
        "-c",
        "features.plugins=false",
        "-c",
        "project_doc_max_bytes=0",
    ]
    assert terminal.files == {
        launch / "requirements.toml": "allow_managed_hooks_only = true\n\n[hooks]\n"
    }


def test_codex_keeps_the_account_s_apps_only_when_asked(
    tmp_path: Path, codex_home: Path
) -> None:
    def overrides(session: SessionSettings) -> list[str]:
        terminal = Codex(model="gpt-6.1-sol").terminal(
            TerminalSettings(
                directory=tmp_path / "launch",
                cli=CODEX_CLI,
                session=session,
            )
        )
        return terminal.command

    assert "features.apps=false" in overrides(SessionSettings())
    assert not any(
        argument.startswith("features.apps")
        for argument in overrides(SessionSettings(account_connectors=True))
    )


def test_codex_uses_the_operators_default_home(tmp_path: Path, home: Path) -> None:
    terminal = Codex(model="gpt-6.1-sol").terminal(
        TerminalSettings(directory=tmp_path / "launch", cli=CODEX_CLI)
    )

    assert terminal.env == {"CODEX_HOME": str(home / ".codex")}
    assert terminal.mounts[0] == Mount(source=home / ".codex")


def test_codex_runs_the_cli_its_sdk_pins_without_one_given(
    tmp_path: Path, codex_home: Path
) -> None:
    found = find_spec("codex_cli_bin")
    assert found is not None
    assert found.origin is not None
    package = Path(found.origin).parent

    terminal = Codex(model="gpt-6.1-sol").terminal(
        TerminalSettings(directory=tmp_path / "launch")
    )

    assert terminal.command[0] == str(package / "bin" / "codex")
    assert terminal.mounts[1] == Mount(source=package, read_only=True)


def test_codex_given_one_file_mounts_it_alone(tmp_path: Path, codex_home: Path) -> None:
    alone = Cli(program=Path("/opt/clis/codex-alone"))

    terminal = Codex(model="gpt-6.1-sol").terminal(
        TerminalSettings(directory=tmp_path / "launch", cli=alone)
    )

    assert terminal.command[0] == "/opt/clis/codex-alone"
    assert terminal.mounts[1] == Mount(
        source=Path("/opt/clis/codex-alone"), read_only=True
    )


def test_codex_refuses_without_its_pinned_cli(
    tmp_path: Path, codex_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("lup.adapters.codex.layout.find_spec", nothing)

    with pytest.raises(RuntimeMissingError, match="lup\\[codex\\]"):
        Codex(model="gpt-6.1-sol").terminal(
            TerminalSettings(directory=tmp_path / "launch")
        )


def test_codex_refuses_an_operator_config_that_isnt_toml(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text("[mcp_servers\n")

    with pytest.raises(TerminalError, match="isn't valid TOML"):
        Codex(model="gpt-6.1-sol").terminal(
            TerminalSettings(directory=tmp_path / "launch", cli=CODEX_CLI)
        )


def test_codex_with_no_model_leaves_the_operator_s_to_codex(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text(
        'model = "gpt-6-astra"\nmodel_reasoning_effort = "ultra"\n'
    )

    terminal = Codex().terminal(
        TerminalSettings(directory=tmp_path / "launch", cli=CODEX_CLI)
    )

    assert "--model" not in terminal.command
    assert not any(argument.startswith("model") for argument in terminal.command[1:])


def test_codex_refuses_an_operator_config_that_doesnt_read(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text("mcp_servers = 6\n")

    with pytest.raises(TerminalError, match="doesn't read"):
        Codex().terminal(TerminalSettings(directory=tmp_path / "launch", cli=CODEX_CLI))


def without(monkeypatch: pytest.MonkeyPatch, sdk: str, runtime: str) -> None:
    """Hide a runtime's SDK and its modules, as when its extra isn't installed, and forget the adapter module importing it."""
    for name in [*sys.modules]:
        if name == sdk or name.startswith(f"{sdk}."):
            monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, sdk, None)
    monkeypatch.delitem(sys.modules, runtime, raising=False)


def test_claude_compiles_without_its_sdk_and_an_ask_names_the_extra(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    without(monkeypatch, "claude_agent_sdk", "lup.adapters.claude.runtime")

    terminal = Claude(model="opus").terminal(settings(tmp_path / "launch", CLAUDE_CLI))

    assert terminal.command[0] == str(CLAUDE_CLI.program)
    with pytest.raises(RuntimeMissingError, match="lup\\[claude\\]"):
        asyncio.run(Claude(model="opus").ask("Say hello."))


def test_codex_compiles_without_its_sdk_and_an_ask_names_the_extra(
    tmp_path: Path, codex_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    without(monkeypatch, "openai_codex", "lup.adapters.codex.runtime")

    terminal = Codex(model="gpt-6.1-sol").terminal(
        TerminalSettings(directory=tmp_path / "launch", cli=CODEX_CLI)
    )

    assert terminal.command[0] == str(CODEX_CLI.program)
    with pytest.raises(RuntimeMissingError, match="lup\\[codex\\]"):
        asyncio.run(Codex(model="gpt-6.1-sol").ask("Say hello."))


def test_toml_values_read_back_as_written() -> None:
    value: JsonValue = {
        "unicode": "naïve 🎧",
        "escapes": 'a "quote", a \\ and a\nnewline, a delete \x7f character',
        "numbers": [0, -3, 12, 1.5],
        "nested": {"dotted.key": {"flag": True, "tables": [{"in": "an array"}]}},
    }

    written = toml(value)

    assert "\n" not in written
    assert tomllib.loads(f"v = {written}")["v"] == value


def test_toml_refuses_what_it_cant_write() -> None:
    with pytest.raises(TerminalError, match="has no TOML value"):
        toml({"unset": None})


# The neutral terms


def test_a_hook_times_out_after_whole_seconds() -> None:
    with pytest.raises(ValidationError, match="whole seconds"):
        Hook(event="call-started", command=HOOK, timeout=timedelta(seconds=1.5))
    with pytest.raises(ValidationError, match="whole seconds"):
        Hook(event="call-started", command=HOOK, timeout=timedelta(0))


def test_a_prompt_cache_lives_five_minutes_or_an_hour() -> None:
    with pytest.raises(ValidationError, match="five minutes or an hour"):
        SessionSettings(subagent_cache=timedelta(minutes=10))


def test_terminal_paths_are_absolute() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        TerminalSettings(directory=Path("launch"))
    with pytest.raises(ValidationError, match="absolute"):
        TerminalSettings(directory=Path("/launch"), trusted=[Path("tree/dev")])
    with pytest.raises(ValidationError, match="absolute"):
        Cli(program=Path("bin/codex"))


def test_a_cli_runs_from_inside_the_directory_it_ships_in() -> None:
    with pytest.raises(ValidationError, match="isn't inside"):
        Cli(program=Path("/opt/elsewhere/codex"), directory=CODEX_PACKAGE)
