"""Each runtime's terminal compile: the command, variables, files and mounts, compared whole."""

import asyncio
import inspect
import json
import sys
import tomllib
from datetime import timedelta
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import JsonValue, ValidationError

from lup.adapters.claude import Claude
from lup.adapters.codex import Codex
from lup.adapters.codex.terminal import toml
from lup.events import (
    CallFinished,
    CallStarted,
    ConversationEnded,
    SessionStarted,
    TurnEnded,
)
from lup.rooms.container import Mount
from lup.sessions import bridge
from lup.sessions.errors import RuntimeMissingError
from lup.sessions.terminal import (
    Cli,
    Hook,
    RuntimeHome,
    SessionSettings,
    Terminal,
    TerminalError,
    TerminalSettings,
    ToolServer,
)

if TYPE_CHECKING:
    from lup.types import JsonObject

HOOK = ["socat", "-t", "36000", "-", "UNIX-CONNECT:/run/lup/hook.sock"]
HOOK_LINE = "socat -t 36000 - UNIX-CONNECT:/run/lup/hook.sock"
SERVER = ToolServer(
    name="lup", socket=Path("/run/lup/mcp.sock"), timeout=timedelta(hours=25)
)
MESSAGES = Path("/run/lup/messages.sock")
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
            Hook(event=SessionStarted, command=HOOK, timeout=timedelta(hours=10)),
            Hook(
                event=CallStarted,
                matcher="Edit|Write",
                command=HOOK,
                timeout=timedelta(hours=10),
            ),
            Hook(event=CallFinished, command=HOOK),
        ],
        servers=[SERVER],
        messages=MESSAGES,
        guidance=GUIDANCE,
        defaults=DEFAULTS,
        trusted=[WORKTREE, REPOSITORY],
    )
    return sample.model_copy(update=changes)


DEFAULTS = SessionSettings(
    subagent_cache=timedelta(hours=1),
    auto_memory=False,
    idle_compaction=False,
    removed_tools=["Artifact", "SendFeedback"],
    account_connectors=False,
)
"""Defaults as lup's are: every setting given."""

IMPOSED = SessionSettings(
    subagent_cache=timedelta(hours=1),
    auto_memory=False,
    idle_compaction=False,
    account_connectors=False,
)
"""A project's declaration imposing what lup's defaults hold."""


def homed(tmp_path: Path, runtime: str) -> RuntimeHome:
    """Return a home of the rooms' own for `runtime`, the operator's configuration its lowest layer."""
    return RuntimeHome(
        directory=tmp_path / "launch" / "runtime-home",
        shared=tmp_path / "homes" / runtime,
        login=tmp_path / "accounts" / "default" / runtime / "login",
        layer=tmp_path / "profile" / runtime,
    )


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
        "--mcp-config",
        str(launch / "mcp.json"),
        "--strict-mcp-config",
        "--messaging-socket-path",
        "/run/lup/messages.sock",
        "--model",
        "opus",
        "--effort",
        "high",
        "--append-system-prompt-file",
        str(launch / "guidance.md"),
        "--system-prompt-snapshot",
        "off",
    ]
    assert terminal.env == {
        "CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS": "0",
        "DISABLE_AUTOUPDATER": "1",
    }
    command = {"type": "command", "command": HOOK_LINE}
    timed = {**command, "timeout": 36000}
    assert decoded(terminal.files) == {
        launch / "settings.json": {
            "env": {
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
                "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": "1h",
            },
            "hooks": {
                "SessionStart": [{"hooks": [timed]}],
                "PreToolUse": [{"matcher": "Edit|Write", "hooks": [timed]}],
                "PostToolUse": [{"hooks": [command]}],
                "PostToolUseFailure": [{"hooks": [command]}],
            },
            "permissions": {"deny": ["Artifact", "SendFeedback"]},
            "idleCompaction": False,
            "disableClaudeAiConnectors": True,
            "crossSessionInbound": "accept",
            "skipDangerousModePermissionPrompt": True,
        },
        launch / "claude.json": {
            "hasCompletedOnboarding": True,
            "projects": {
                str(WORKTREE): {"hasTrustDialogAccepted": True},
                str(REPOSITORY): {"hasTrustDialogAccepted": True},
            },
        },
        launch / "mcp.json": {
            "mcpServers": {
                "lup": {
                    "type": "stdio",
                    "command": "python3",
                    "args": ["-I", str(launch / "mcp-bridge.py"), "/run/lup/mcp.sock"],
                    "timeout": 90_000_000,
                }
            }
        },
        launch / "mcp-bridge.py": inspect.getsource(bridge),
        launch / "guidance.md": GUIDANCE,
    }
    # Without a home, nothing of the operator's directory is read or mounted:
    # the state is the room's own home's, gone with the launch.
    assert terminal.mounts == [
        Mount(source=Path("/opt/clis/claude"), read_only=True),
        Mount(source=launch, read_only=True),
        Mount(source=launch / "claude.json", target=home / ".claude.json"),
    ]
    assert terminal.home is None
    assert terminal.preferences is None


def test_claude_runs_a_turns_end_hook_at_stopfailure_too_once_whoever_failed(
    tmp_path: Path, home: Path
) -> None:
    """`StopFailure` runs in place of `Stop` or `SubagentStop` where a turn ends on an error from the model's API, its matcher filtering by the error's kind alone: registered with both ends it would run twice."""
    launch = tmp_path / "launch"
    ends = [
        Hook(event=TurnEnded, command=HOOK),
        Hook(event=ConversationEnded, command=HOOK),
    ]
    terminal = Claude().terminal(settings(launch, CLAUDE_CLI, hooks=ends))
    command = {"type": "command", "command": HOOK_LINE}
    assert json.loads(terminal.files[launch / "settings.json"])["hooks"] == {
        "Stop": [{"hooks": [command]}],
        "StopFailure": [{"hooks": [command]}],
        "SubagentStop": [{"hooks": [command]}],
    }


def test_claude_loads_no_server_and_moves_no_socket_where_lup_gives_none(
    tmp_path: Path, home: Path
) -> None:
    launch = tmp_path / "launch"
    terminal = Claude().terminal(
        settings(launch, CLAUDE_CLI, servers=[], messages=None)
    )

    assert not [
        flag for flag in terminal.command if "mcp" in flag or "messaging" in flag
    ]
    assert launch / "mcp.json" not in terminal.files
    assert launch / "mcp-bridge.py" not in terminal.files
    assert "crossSessionInbound" not in lup_settings(terminal, launch)


def test_claude_waits_on_a_server_with_no_timeout_as_it_would(
    tmp_path: Path, home: Path
) -> None:
    launch = tmp_path / "launch"
    terminal = Claude().terminal(
        TerminalSettings(
            directory=launch,
            cli=CLAUDE_CLI,
            servers=[ToolServer(name="tools", socket=Path("/run/tools.sock"))],
        )
    )

    assert json.loads(terminal.files[launch / "mcp.json"]) == {
        "mcpServers": {
            "tools": {
                "type": "stdio",
                "command": "python3",
                "args": ["-I", str(launch / "mcp-bridge.py"), "/run/tools.sock"],
            }
        }
    }


def test_claude_loads_each_server_that_pushes_as_a_channel_its_flag_before_strict(
    tmp_path: Path, home: Path
) -> None:
    pushing = ToolServer(name="lup", socket=Path("/run/lup/mcp.sock"), pushes=True)
    quiet = ToolServer(name="tools", socket=Path("/run/tools.sock"))
    launch = tmp_path / "launch"
    terminal = Claude().terminal(
        TerminalSettings(directory=launch, cli=CLAUDE_CLI, servers=[pushing, quiet])
    )

    start = terminal.command.index("--mcp-config")
    assert terminal.command[start : start + 5] == [
        "--mcp-config",
        str(launch / "mcp.json"),
        "--dangerously-load-development-channels",
        "server:lup",
        "--strict-mcp-config",
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
        defaults=SessionSettings(),
    )

    kept = Claude(model="opus").terminal(bare)
    replaced = Claude(model="opus", system_prompt="You narrate.").terminal(bare)

    assert "--system-prompt-file" not in kept.command
    assert "--append-system-prompt-file" not in kept.command
    assert "--system-prompt-snapshot" not in kept.command
    assert "--effort" not in kept.command
    assert replaced.command[-2:] == [
        "--system-prompt-file",
        str(launch / "system-prompt.md"),
    ]
    assert replaced.files[launch / "system-prompt.md"] == "You narrate."
    written = json.loads(kept.files[launch / "settings.json"])
    assert written["env"] == {
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0",
        "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": "5m",
    }
    assert written["permissions"] == {"deny": []}


def lup_settings(terminal: Terminal, launch: Path) -> JsonObject:
    written: JsonValue = json.loads(terminal.files[launch / "settings.json"])
    assert isinstance(written, dict)
    return written


def test_claude_fetches_the_account_s_connectors_only_when_asked(
    tmp_path: Path, home: Path
) -> None:
    launch = tmp_path / "launch"

    def written(session: SessionSettings) -> JsonObject:
        terminal = Claude(model="opus").terminal(
            settings(launch, CLAUDE_CLI, session=session)
        )
        return lup_settings(terminal, launch)

    assert written(SessionSettings())["disableClaudeAiConnectors"] is True
    assert written(SessionSettings(account_connectors=False))[
        "disableClaudeAiConnectors"
    ]
    assert (
        written(SessionSettings(account_connectors=True))["disableClaudeAiConnectors"]
        is False
    )


def test_claude_leaves_every_session_setting_to_the_runtime_when_none_is_given(
    tmp_path: Path, home: Path
) -> None:
    launch = tmp_path / "launch"
    terminal = Claude(model="opus").terminal(
        settings(launch, CLAUDE_CLI, defaults=SessionSettings())
    )

    assert terminal.env == {
        "CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS": "0",
        "DISABLE_AUTOUPDATER": "1",
    }
    written = lup_settings(terminal, launch)
    assert written["env"] == {}
    assert written["permissions"] == {"deny": []}
    assert "disableClaudeAiConnectors" not in written


def own(home: Path, settings: JsonObject) -> None:
    """Write the operator's own Claude Code settings."""
    (home / ".claude").mkdir(exist_ok=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(settings))


THEIRS: JsonObject = {
    "theme": "dark",
    "autoMemoryEnabled": True,
    "idleCompaction": True,
    "disableClaudeAiConnectors": False,
    "env": {"CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": "5m"},
    "permissions": {"deny": ["WebFetch"]},
}
"""The operator's own settings, setting each session setting lup has a default for."""


def test_claude_passes_lup_s_defaults_only_where_the_operator_sets_none(
    tmp_path: Path, home: Path
) -> None:
    own(home, THEIRS)
    launch = tmp_path / "launch"

    written = lup_settings(
        Claude().terminal(settings(launch, CLAUDE_CLI, home=homed(tmp_path, "claude"))),
        launch,
    )

    # Their `env` is left out of the room's settings, so the cache it set is
    # lup's to set.
    assert written["env"] == {"CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": "1h"}
    assert "idleCompaction" not in written
    assert "disableClaudeAiConnectors" not in written
    assert written["permissions"] == {"deny": ["Artifact", "SendFeedback"]}


def test_claude_imposes_what_the_declaration_sets_over_the_operator_s_own(
    tmp_path: Path, home: Path
) -> None:
    own(home, THEIRS)
    launch = tmp_path / "launch"

    written = lup_settings(
        Claude().terminal(
            settings(
                launch, CLAUDE_CLI, session=IMPOSED, home=homed(tmp_path, "claude")
            )
        ),
        launch,
    )

    assert written["env"] == {
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": "1h",
    }
    assert written["idleCompaction"] is False
    assert written["disableClaudeAiConnectors"] is True


def test_claude_turns_idle_compaction_off_and_an_imposed_on_outranks_the_operator_s_off(
    tmp_path: Path, home: Path
) -> None:
    launch = tmp_path / "launch"

    def compacting(session: SessionSettings) -> JsonValue:
        terminal = Claude().terminal(
            settings(
                launch, CLAUDE_CLI, session=session, home=homed(tmp_path, "claude")
            )
        )
        return lup_settings(terminal, launch).get("idleCompaction")

    assert compacting(SessionSettings()) is False
    own(home, {"idleCompaction": False})
    assert compacting(SessionSettings(idle_compaction=True)) is True
    own(home, {"idleCompaction": True})
    assert compacting(SessionSettings()) is None


def test_claude_leaves_the_operator_s_env_to_lup_s_defaults_since_it_reaches_no_room(
    tmp_path: Path, home: Path
) -> None:
    own(
        home,
        {
            "env": {
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0",
                "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
            },
            "subagentPromptCacheTtl": "5m",
        },
    )
    launch = tmp_path / "launch"

    written = lup_settings(
        Claude().terminal(settings(launch, CLAUDE_CLI, home=homed(tmp_path, "claude"))),
        launch,
    )

    # Their key sets the cache; the variables in their `env` set nothing.
    assert written["env"] == {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    assert written["disableClaudeAiConnectors"] is True


def test_claude_refuses_operator_settings_that_dont_read(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    moved = tmp_path / "claude-work"
    moved.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(moved))
    (moved / "settings.json").write_text(json.dumps({"autoMemoryEnabled": "maybe"}))
    homing = settings(tmp_path / "launch", CLAUDE_CLI, home=homed(tmp_path, "claude"))

    with pytest.raises(TerminalError, match="layered for the room don't read"):
        Claude().terminal(homing)
    (moved / "settings.json").write_text("{")
    with pytest.raises(TerminalError, match="doesn't read as json"):
        Claude().terminal(homing)


def test_claude_copies_from_a_moved_config_directory_and_names_the_home_in_its_place(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    moved = tmp_path / "claude-work"
    (moved / "skills").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(moved))
    launch = tmp_path / "launch"
    room = homed(tmp_path, "claude")

    terminal = Claude(model="opus").terminal(settings(launch, CLAUDE_CLI, home=room))
    bare = Claude(model="opus").terminal(settings(launch, CLAUDE_CLI))

    assert terminal.env["CLAUDE_CONFIG_DIR"] == str(room.directory)
    assert [each.source for each in terminal.copies] == [moved / "skills"]
    assert Mount(source=moved) not in terminal.mounts
    assert "CLAUDE_CONFIG_DIR" not in bare.env
    assert bare.mounts[-1] == Mount(
        source=launch / "claude.json", target=home / ".claude.json"
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

    terminal = Claude(effort="high").terminal(
        settings(tmp_path / "launch", CLAUDE_CLI, home=homed(tmp_path, "claude"))
    )

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

    # Without a home, nothing of the operator's Codex home is read or mounted:
    # their servers aren't there to turn off.

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
        (
            f'mcp_servers={{lup = {{command = "python3",args = ["-I", "{launch / "mcp-bridge.py"}", '
            '"/run/lup/mcp.sock"],'
            'tool_timeout_sec = 90000,default_tools_approval_mode = "approve"}}'
        ),
        "-c",
        "project_doc_max_bytes=0",
    ]
    assert terminal.env == {}
    command = {"type": "command", "command": HOOK_LINE}
    timed = {**command, "timeout": 36000}
    assert decoded(terminal.files) == {
        launch / "requirements.toml": {
            "allow_managed_hooks_only": True,
            "additional_developer_instructions": GUIDANCE,
            "hooks": {
                "SessionStart": [{"hooks": [timed]}],
                "PreToolUse": [{"matcher": "Edit|Write", "hooks": [timed]}],
                "PostToolUse": [{"hooks": [command]}],
            },
        },
        launch / "mcp-bridge.py": inspect.getsource(bridge),
    }
    assert terminal.mounts == [
        Mount(source=CODEX_PACKAGE, read_only=True),
        Mount(
            source=launch / "requirements.toml",
            target=Path("/etc/codex/requirements.toml"),
            read_only=True,
        ),
        Mount(source=launch / "mcp-bridge.py", read_only=True),
    ]


def test_every_codex_override_parses_as_toml_rather_than_falling_back_to_text(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text('[mcp_servers.node_repl]\ncommand = "x"\n')
    terminal = Codex(model="gpt-6.1-sol", system_prompt="You narrate.").terminal(
        settings(tmp_path / "launch", CODEX_CLI, home=homed(tmp_path, "codex"))
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
        "mcp_servers": {
            "lup": {
                "command": "python3",
                "args": [
                    "-I",
                    str(tmp_path / "launch" / "mcp-bridge.py"),
                    "/run/lup/mcp.sock",
                ],
                "tool_timeout_sec": 90000,
                "default_tools_approval_mode": "approve",
            },
        },
        "project_doc_max_bytes": 0,
        "cli_auth_credentials_store": "file",
    }


def test_codex_serves_lup_s_tools_where_the_operator_has_no_server(
    tmp_path: Path, codex_home: Path
) -> None:
    terminal = Codex().terminal(
        TerminalSettings(
            directory=tmp_path / "launch",
            cli=CODEX_CLI,
            servers=[ToolServer(name="tools", socket=Path("/run/tools.sock"))],
            messages=MESSAGES,
        )
    )

    assert terminal.command[-4:] == [
        "-c",
        (
            'mcp_servers={tools = {command = "python3",'
            f'args = ["-I", "{tmp_path / "launch" / "mcp-bridge.py"}", '
            '"/run/tools.sock"],default_tools_approval_mode = "approve"}}'
        ),
        "-c",
        "project_doc_max_bytes=0",
    ]
    assert not [argument for argument in terminal.command if "messag" in argument]


def test_codex_has_no_way_for_a_server_to_push_and_loads_it_as_any_other(
    tmp_path: Path, codex_home: Path
) -> None:
    pushing = ToolServer(name="tools", socket=Path("/run/tools.sock"), pushes=True)
    quiet = pushing.model_copy(update={"pushes": False})
    directory = tmp_path / "launch"

    assert (
        Codex()
        .terminal(
            TerminalSettings(directory=directory, cli=CODEX_CLI, servers=[pushing])
        )
        .command
        == Codex()
        .terminal(TerminalSettings(directory=directory, cli=CODEX_CLI, servers=[quiet]))
        .command
    )


def test_codex_leaves_the_operator_s_servers_out_lup_s_namesake_among_them(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text(
        '[mcp_servers.lup]\nurl = "https://lup.example/mcp"\n'
    )
    launch = tmp_path / "launch"
    room = homed(tmp_path, "codex")

    terminal = Codex().terminal(settings(launch, CODEX_CLI, home=room))

    served = [each for each in terminal.command if each.startswith("mcp_servers=")]
    assert len(served) == 1
    assert "url" not in served[0]
    written = tomllib.loads(terminal.files[room.directory / "config.toml"])
    assert "mcp_servers" not in written
    assert [(each.said, each.why) for each in terminal.left_out] == [
        (f"`mcp_servers` in {codex_home / 'config.toml'}", "command")
    ]


CODEX_MARKERS = len(
    "<managed_developer_instructions>\n"
    "These managed developer instructions replace all previously provided managed "
    "developer instructions.\n\n"
    "\n</managed_developer_instructions>"
)
"""The bytes Codex counts around its managed instructions toward their limit:
the markers it sends them between, and the notice opening them at a resume where
they changed (`validate_managed_developer_instructions`, rust-v0.163.0)."""


def test_codex_refuses_guidance_past_what_it_takes_naming_its_size_and_the_limit(
    tmp_path: Path, codex_home: Path
) -> None:
    most = 10_000 * 4 - CODEX_MARKERS
    fits = "é" * (most // 2) + "a" * (most % 2)
    past = f"{fits}a"
    launch = tmp_path / "launch"

    terminal = Codex().terminal(settings(launch, CODEX_CLI, guidance=fits))
    with pytest.raises(TerminalError) as refused:
        Codex().terminal(settings(launch, CODEX_CLI, guidance=past))

    written = tomllib.loads(terminal.files[launch / "requirements.toml"])
    assert written["additional_developer_instructions"] == fits
    assert len(fits.encode()) == most
    assert str(refused.value) == (
        "the guidance is 39,832 bytes, 40,001 as Codex sends it between its "
        "markers: about 10,001 estimated tokens at 4 bytes each, past the 10,000 "
        "Codex takes as managed developer instructions, so it wouldn't start. "
        "Shorten the guidance's sections to launch Codex."
    )


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
        "features.plugins=false",
        "-c",
        "project_doc_max_bytes=0",
    ]
    assert terminal.files == {
        launch / "requirements.toml": "allow_managed_hooks_only = true\n\n[hooks]\n"
    }


def features(terminal: Terminal) -> list[str]:
    """Return the `-c` overrides switching a feature lup's session settings switch."""
    return [
        argument
        for argument in terminal.command
        if argument.startswith(
            (
                "features.memories",
                "features.memory_tool",
                "features.apps",
                "features.connectors",
            )
        )
    ]


def test_codex_keeps_the_account_s_apps_only_when_asked(
    tmp_path: Path, codex_home: Path
) -> None:
    def overrides(session: SessionSettings) -> list[str]:
        terminal = Codex().terminal(
            TerminalSettings(
                directory=tmp_path / "launch",
                cli=CODEX_CLI,
                session=session,
            )
        )
        return features(terminal)

    assert overrides(SessionSettings()) == []
    assert overrides(SessionSettings(account_connectors=False)) == [
        "features.apps=false"
    ]
    assert overrides(SessionSettings(account_connectors=True)) == ["features.apps=true"]


def test_codex_passes_lup_s_defaults_only_where_the_operator_sets_none(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text(
        "[features]\nmemories = true\nconnectors = true\n"
    )

    terminal = Codex().terminal(
        settings(tmp_path / "launch", CODEX_CLI, home=homed(tmp_path, "codex"))
    )

    assert features(terminal) == []


def test_codex_imposes_what_the_declaration_sets_by_every_key_the_operator_uses(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text(
        "[features]\nmemory_tool = true\nconnectors = true\napps = true\n"
    )

    terminal = Codex().terminal(
        settings(
            tmp_path / "launch",
            CODEX_CLI,
            session=IMPOSED,
            home=homed(tmp_path, "codex"),
        )
    )

    assert features(terminal) == [
        "features.memories=false",
        "features.memory_tool=false",
        "features.apps=false",
        "features.connectors=false",
    ]


def test_codex_has_no_idle_compaction_to_turn_off(
    tmp_path: Path, codex_home: Path
) -> None:
    for session in [SessionSettings(), SessionSettings(idle_compaction=True)]:
        terminal = Codex().terminal(
            settings(tmp_path / "launch", CODEX_CLI, session=session)
        )
        # The launch's directory, in each path to the bridge, holds the test's name.
        assert not any(
            "compact" in argument.replace(str(tmp_path), "")
            for argument in terminal.command
        )


def test_codex_reads_the_operator_s_default_home_as_its_lowest_layer(
    tmp_path: Path, home: Path
) -> None:
    (home / ".codex" / "rules").mkdir(parents=True)
    room = homed(tmp_path, "codex")

    terminal = Codex(model="gpt-6.1-sol").terminal(
        TerminalSettings(directory=tmp_path / "launch", cli=CODEX_CLI, home=room)
    )
    bare = Codex(model="gpt-6.1-sol").terminal(
        TerminalSettings(directory=tmp_path / "launch", cli=CODEX_CLI)
    )

    assert terminal.env == {"CODEX_HOME": str(room.directory)}
    assert [each.source for each in terminal.copies] == [home / ".codex" / "rules"]
    assert Mount(source=home / ".codex") not in [*terminal.mounts, *bare.mounts]
    assert bare.env == {}


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
    assert terminal.mounts[0] == Mount(source=package, read_only=True)


def test_codex_given_one_file_mounts_it_alone(tmp_path: Path, codex_home: Path) -> None:
    alone = Cli(program=Path("/opt/clis/codex-alone"))

    terminal = Codex(model="gpt-6.1-sol").terminal(
        TerminalSettings(directory=tmp_path / "launch", cli=alone)
    )

    assert terminal.command[0] == "/opt/clis/codex-alone"
    assert terminal.mounts[0] == Mount(
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

    with pytest.raises(TerminalError, match="doesn't read as toml"):
        Codex(model="gpt-6.1-sol").terminal(
            TerminalSettings(
                directory=tmp_path / "launch",
                cli=CODEX_CLI,
                home=homed(tmp_path, "codex"),
            )
        )


def test_codex_with_no_model_leaves_the_operator_s_to_codex(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text(
        'model = "gpt-6-astra"\nmodel_reasoning_effort = "ultra"\n'
    )

    terminal = Codex().terminal(
        TerminalSettings(
            directory=tmp_path / "launch", cli=CODEX_CLI, home=homed(tmp_path, "codex")
        )
    )

    assert "--model" not in terminal.command
    assert not any(argument.startswith("model") for argument in terminal.command[1:])


def test_codex_refuses_an_operator_config_that_doesnt_read(
    tmp_path: Path, codex_home: Path
) -> None:
    (codex_home / "config.toml").write_text("features = 6\n")

    with pytest.raises(TerminalError, match="layered for the room doesn't read"):
        Codex().terminal(
            TerminalSettings(
                directory=tmp_path / "launch",
                cli=CODEX_CLI,
                home=homed(tmp_path, "codex"),
            )
        )


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
        Hook(event=CallStarted, command=HOOK, timeout=timedelta(seconds=1.5))
    with pytest.raises(ValidationError, match="whole seconds"):
        Hook(event=CallStarted, command=HOOK, timeout=timedelta(0))


def test_a_tool_server_is_on_an_absolute_socket_and_times_out_after_whole_seconds() -> (
    None
):
    socket = Path("/run/lup/mcp.sock")
    with pytest.raises(ValidationError, match="whole seconds"):
        ToolServer(name="lup", socket=socket, timeout=timedelta(milliseconds=1500))
    with pytest.raises(ValidationError, match="absolute"):
        ToolServer(name="lup", socket=Path("mcp.sock"))


def test_two_tool_servers_of_one_name_are_refused() -> None:
    twice = [SERVER, SERVER.model_copy(update={"socket": Path("/run/other.sock")})]
    with pytest.raises(ValidationError, match="more than one tool server is named lup"):
        TerminalSettings(directory=Path("/launch"), servers=twice)


def test_a_prompt_cache_lives_five_minutes_or_an_hour() -> None:
    with pytest.raises(ValidationError, match="five minutes or an hour"):
        SessionSettings(subagent_cache=timedelta(minutes=10))


def test_a_terminal_passes_what_s_imposed_and_the_defaults_the_person_sets_none_of(
    tmp_path: Path,
) -> None:
    given = TerminalSettings(
        directory=tmp_path,
        session=SessionSettings(auto_memory=True, removed_tools=[]),
        defaults=DEFAULTS,
    )

    assert given.passed([]) == SessionSettings(
        subagent_cache=timedelta(hours=1),
        auto_memory=True,
        idle_compaction=False,
        removed_tools=[],
        account_connectors=False,
    )
    assert given.passed(["auto_memory", "account_connectors"]) == SessionSettings(
        subagent_cache=timedelta(hours=1),
        auto_memory=True,
        idle_compaction=False,
        removed_tools=[],
    )
    assert TerminalSettings(directory=tmp_path).passed([]) == SessionSettings()
    with pytest.raises(TerminalError, match="memory aren't session settings"):
        given.passed(["memory"])


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
