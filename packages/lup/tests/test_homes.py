"""A home of the rooms' own: each runtime's terminal on one, what a launch makes in it before the run, and the preferences carried back after."""

import json
import os
import tomllib
from pathlib import Path

import pytest

from lup.adapters.claude import Claude
from lup.adapters.codex import Codex
from lup.rooms.container import Mount
from lup.rooms.homes import inside, landed, landings
from lup.sessions.configuration import HomeLaunch, Item, configured
from lup.sessions.terminal import (
    Cli,
    Copy,
    Preference,
    Preferences,
    RuntimeHome,
    Setting,
    TerminalSettings,
)

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


def homed(tmp_path: Path, runtime: str, *, operators: bool = True) -> RuntimeHome:
    return RuntimeHome(
        directory=tmp_path / "homes" / runtime,
        login=tmp_path / "accounts" / "work" / runtime / "login",
        operators=operators,
        own=tmp_path / "profile" / runtime,
    )


def written(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# Claude Code on a home


def test_claude_on_a_home_mounts_it_and_the_login_and_nothing_of_the_operator_s(
    tmp_path: Path, home: Path
) -> None:
    room = homed(tmp_path, "claude")
    launch = tmp_path / "launch"
    own = launch / "runtime"
    at = room.directory

    terminal = Claude().terminal(
        TerminalSettings(directory=launch, cli=CLAUDE_CLI, home=room)
    )

    assert terminal.env == {
        "CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS": "0",
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CONFIG_DIR": str(at),
    }
    assert terminal.home == at
    empty_directory = own / "empty" / "directory"
    empty_file = own / "empty" / "file"
    assert terminal.mounts == [
        Mount(source=at),
        Mount(source=Path("/opt/clis/claude"), read_only=True),
        Mount(source=launch, read_only=True),
        Mount(source=own / "launch" / "settings.json", target=at / "settings.json"),
        Mount(source=launch / "claude.json", target=at / ".claude.json"),
        Mount(source=room.login, target=at / ".credentials.json"),
        Mount(source=own / "launch" / "shell-snapshots", target=at / "shell-snapshots"),
        Mount(source=own / "launch" / "session-env", target=at / "session-env"),
        Mount(source=empty_file, target=at / "CLAUDE.md", read_only=True),
        *(
            Mount(source=empty_directory, target=at / name, read_only=True)
            for name in [
                "rules",
                "skills",
                "commands",
                "agents",
                "output-styles",
                "workflows",
                "agent-memory",
                "plugins",
            ]
        ),
        Mount(source=empty_file, target=at / "keybindings.json", read_only=True),
        Mount(source=empty_directory, target=at / "themes", read_only=True),
    ]
    assert not [
        each
        for each in terminal.mounts
        if each.source.is_relative_to(home / ".claude") or each.source == home
    ]
    assert terminal.directories == [
        empty_directory,
        own / "launch" / "shell-snapshots",
        own / "launch" / "session-env",
    ]
    assert terminal.files[empty_file] == ""
    assert json.loads(terminal.files[own / "launch" / "settings.json"]) == {}
    assert terminal.copies == []
    assert terminal.left_out == []


OPERATORS = {
    "model": "sonnet",
    "theme": "dark",
    "env": {"ANTHROPIC_API_KEY": "sk-ant-x"},
    "apiKeyHelper": "~/bin/key",
    "awsAuthRefresh": "aws sso login",
    "awsCredentialExport": "~/bin/aws",
    "otelHeadersHelper": "~/bin/otel",
    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify"}]}]},
    "statusLine": {"type": "command", "command": "line", "authToken": "t"},
    "includeCoAuthoredBy": False,
}
"""The operator's own settings, a credential and its helpers among them."""


def test_claude_layers_the_profile_s_settings_over_the_operator_s_credentials_left_out(
    tmp_path: Path, home: Path
) -> None:
    operators = written(home / ".claude" / "settings.json", json.dumps(OPERATORS))
    room = homed(tmp_path, "claude")
    assert room.own is not None
    profile = written(
        room.own / "settings.json",
        json.dumps({"model": "opus", "outputStyle": "terse", "secretSauce": 1}),
    )
    launch = tmp_path / "launch"

    terminal = Claude().terminal(
        TerminalSettings(directory=launch, cli=CLAUDE_CLI, home=room)
    )

    assert json.loads(
        terminal.files[launch / "runtime" / "launch" / "settings.json"]
    ) == {
        "model": "opus",
        "theme": "dark",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify"}]}]},
        "statusLine": {"type": "command", "command": "line"},
        "includeCoAuthoredBy": False,
        "outputStyle": "terse",
    }
    assert terminal.left_out == [
        f"`env` in {operators}",
        f"`apiKeyHelper` in {operators}",
        f"`awsAuthRefresh` in {operators}",
        f"`awsCredentialExport` in {operators}",
        f"`otelHeadersHelper` in {operators}",
        f"`statusLine.authToken` in {operators}",
        f"`secretSauce` in {profile}",
    ]
    assert terminal.preferences is not None
    assert terminal.preferences.into == profile
    assert {
        each.preference.name: each.value for each in terminal.preferences.written
    } == {
        "model": "opus",
        "effortLevel": None,
        "modelSettings": None,
        "outputStyle": "terse",
        "theme": "dark",
        "editorMode": None,
        "alwaysThinkingEnabled": None,
    }


def test_claude_off_the_operator_s_layer_reads_the_profile_s_alone(
    tmp_path: Path, home: Path
) -> None:
    written(home / ".claude" / "settings.json", json.dumps({"model": "sonnet"}))
    (home / ".claude" / "skills" / "theirs").mkdir(parents=True)
    room = homed(tmp_path, "claude", operators=False)
    assert room.own is not None
    (room.own / "skills" / "mine").mkdir(parents=True)
    launch = tmp_path / "launch"

    terminal = Claude().terminal(
        TerminalSettings(directory=launch, cli=CLAUDE_CLI, home=room)
    )

    assert (
        json.loads(terminal.files[launch / "runtime" / "launch" / "settings.json"])
        == {}
    )
    assert [each.source for each in terminal.copies] == [room.own / "skills"]


def test_claude_copies_each_layer_s_configuration_and_leaves_a_link_said(
    tmp_path: Path, home: Path
) -> None:
    secret = written(tmp_path / "keys" / "id_ed25519", "PRIVATE")
    theirs = home / ".claude"
    written(theirs / "skills" / "review" / "SKILL.md", "theirs")
    written(theirs / "skills" / "shared" / "SKILL.md", "theirs")
    (theirs / "skills" / "keys").symlink_to(secret.parent)
    written(theirs / "plugins" / "installed_plugins.json", "{}")
    written(theirs / "plugins" / "data" / "tokens.json", "token")
    os.mkfifo(theirs / "plugins" / "pipe")
    (theirs / "CLAUDE.md").symlink_to(secret)
    room = homed(tmp_path, "claude")
    assert room.own is not None
    written(room.own / "skills" / "shared" / "SKILL.md", "the profile's")
    written(room.own / "CLAUDE.md", "the profile's guidance")
    launch = tmp_path / "launch"
    copied = launch / "runtime" / "configuration"

    terminal = Claude().terminal(
        TerminalSettings(directory=launch, cli=CLAUDE_CLI, home=room)
    )
    terminal.prepare()

    assert terminal.left_out == [
        f"{theirs / 'CLAUDE.md'}, which is a link lup doesn't follow"
    ]
    assert (
        Mount(
            source=copied / "skills", target=room.directory / "skills", read_only=True
        )
        in terminal.mounts
    )
    assert (copied / "skills" / "review" / "SKILL.md").read_text() == "theirs"
    assert (copied / "skills" / "shared" / "SKILL.md").read_text() == "the profile's"
    assert (copied / "skills" / "keys").is_symlink()
    assert (copied / "CLAUDE.md").read_text() == "the profile's guidance"
    assert sorted(each.name for each in (copied / "plugins").iterdir()) == [
        "installed_plugins.json"
    ]


def test_claude_s_preparation_makes_each_landing_in_the_home_replacing_a_room_s_links(
    tmp_path: Path, home: Path
) -> None:
    room = homed(tmp_path, "claude")
    at = room.directory
    at.mkdir(parents=True)
    outside = written(tmp_path / "outside" / "bashrc", "the operator's")
    (at / "settings.json").symlink_to(outside)
    (at / "skills").symlink_to(outside.parent)
    (at / "session-env").mkdir()
    written(at / "session-env" / "kept", "a room's")
    room.login.parent.mkdir(parents=True)
    room.login.touch()
    launch = tmp_path / "launch"

    terminal = Claude().terminal(
        TerminalSettings(directory=launch, cli=CLAUDE_CLI, home=room)
    )
    terminal.prepare()

    assert outside.read_text() == "the operator's"
    assert sorted(each.name for each in outside.parent.iterdir()) == ["bashrc"]
    for name in ["settings.json", ".claude.json", ".credentials.json", "CLAUDE.md"]:
        assert (at / name).is_file()
        assert not (at / name).is_symlink()
    for name in ["skills", "plugins", "shell-snapshots", "session-env"]:
        assert (at / name).is_dir()
        assert not (at / name).is_symlink()
    # What the room left where a directory is mounted stays, under the mount.
    assert (at / "session-env" / "kept").read_text() == "a room's"


# Codex on a home


def test_codex_on_a_home_mounts_it_the_login_and_its_own_and_nothing_of_the_operator_s(
    tmp_path: Path, home: Path
) -> None:
    room = homed(tmp_path, "codex")
    launch = tmp_path / "launch"
    own = launch / "runtime"
    at = room.directory

    terminal = Codex().terminal(
        TerminalSettings(directory=launch, cli=CODEX_CLI, home=room)
    )

    assert terminal.env == {"CODEX_HOME": str(at)}
    assert 'cli_auth_credentials_store="file"' in terminal.command
    assert terminal.home == at
    empty_directory = own / "empty" / "directory"
    empty_file = own / "empty" / "file"
    assert terminal.mounts == [
        Mount(source=at),
        Mount(source=CODEX_PACKAGE, read_only=True),
        Mount(
            source=launch / "requirements.toml",
            target=Path("/etc/codex/requirements.toml"),
            read_only=True,
        ),
        Mount(source=own / "launch" / "config.toml", target=at / "config.toml"),
        Mount(source=room.login, target=at / "auth.json"),
        Mount(source=own / "launch" / "shell_snapshots", target=at / "shell_snapshots"),
        Mount(source=own / "launch" / "skills", target=at / "skills"),
        Mount(source=own / "launch" / "tmp", target=at / "tmp"),
        Mount(source=empty_file, target=at / "AGENTS.md", read_only=True),
        Mount(source=empty_file, target=at / "AGENTS.override.md", read_only=True),
        Mount(source=empty_directory, target=at / "rules", read_only=True),
        Mount(source=empty_directory, target=at / "prompts", read_only=True),
    ]
    assert tomllib.loads(terminal.files[own / "launch" / "config.toml"]) == {
        "tui": {"screen_reader_detection_done": True}
    }


def test_codex_layers_its_configuration_and_profiles_with_credentials_left_out(
    tmp_path: Path, home: Path
) -> None:
    operators = written(
        home / ".codex" / "config.toml",
        """\
model = "gpt-6"
[tui]
theme = "dark"
screen_reader_detection_done = false
[shell_environment_policy]
set = { GITHUB_TOKEN = "ghp_x" }
inherit = "core"
[model_providers.corp]
base_url = "https://corp.example"
experimental_bearer_token = "b"
[otel.exporter.otlp-http]
endpoint = "https://otel.example"
headers = { x-honeycomb-team = "k" }
[mcp_servers.github]
command = "gh-mcp"
env = { DATABASE_URL = "postgres://u:p@h/d" }
""",
    )
    fast = written(
        home / ".codex" / "fast.config.toml",
        'model = "gpt-6-mini"\n[model_providers.corp]\nhttp_headers = { Authorization = "Bearer b" }\n',
    )
    room = homed(tmp_path, "codex")
    assert room.own is not None
    written(room.own / "config.toml", 'model_reasoning_effort = "high"\n')
    launch = tmp_path / "launch"
    own = launch / "runtime"

    terminal = Codex().terminal(
        TerminalSettings(directory=launch, cli=CODEX_CLI, home=room)
    )

    assert tomllib.loads(terminal.files[own / "launch" / "config.toml"]) == {
        "model": "gpt-6",
        "model_reasoning_effort": "high",
        "tui": {"theme": "dark", "screen_reader_detection_done": False},
        "shell_environment_policy": {"inherit": "core"},
        "model_providers": {"corp": {"base_url": "https://corp.example"}},
        "otel": {"exporter": {"otlp-http": {"endpoint": "https://otel.example"}}},
    }
    assert tomllib.loads(
        terminal.files[own / "configuration" / "fast.config.toml"]
    ) == {
        "model": "gpt-6-mini",
        "model_providers": {"corp": {"http_headers": {}}},
    }
    assert (
        Mount(
            source=own / "configuration" / "fast.config.toml",
            target=room.directory / "fast.config.toml",
            read_only=True,
        )
        in terminal.mounts
    )
    assert terminal.left_out == [
        f"`mcp_servers` in {operators}",
        f"`shell_environment_policy.set` in {operators}",
        f"`model_providers.corp.experimental_bearer_token` in {operators}",
        f"`otel.exporter.otlp-http.headers` in {operators}",
        f"`model_providers.corp.http_headers.Authorization` in {fast}",
    ]


def test_codex_copies_the_operator_s_own_skills_read_only_into_the_room_s_home(
    tmp_path: Path, home: Path
) -> None:
    written(home / ".agents" / "skills" / "deploy" / "SKILL.md", "theirs")
    launch = tmp_path / "launch"
    copied = launch / "runtime" / "configuration" / ".agents-skills"

    terminal = Codex().terminal(
        TerminalSettings(directory=launch, cli=CODEX_CLI, home=homed(tmp_path, "codex"))
    )
    alone = Codex().terminal(
        TerminalSettings(
            directory=launch,
            cli=CODEX_CLI,
            home=homed(tmp_path, "codex", operators=False),
        )
    )
    terminal.prepare()

    assert (
        Mount(source=copied, target=home / ".agents" / "skills", read_only=True)
        in terminal.mounts
    )
    assert (copied / "deploy" / "SKILL.md").read_text() == "theirs"
    assert not [each for each in alone.mounts if each.destination.is_relative_to(home)]


# What's made in a home, and what's copied


def test_landings_are_what_mounts_inside_the_home_land_on_and_the_way_there(
    tmp_path: Path,
) -> None:
    at = tmp_path / "home"
    source = tmp_path / "source"
    source.mkdir()
    afile = written(tmp_path / "file", "")

    assert landings(
        at,
        [
            Mount(source=at),
            Mount(source=source, target=at / "a" / "b"),
            Mount(source=afile, target=at / "a" / "b" / "inside"),
            Mount(source=afile, target=at / "c"),
            Mount(source=afile, target=tmp_path / "elsewhere"),
        ],
    ) == {at / "a": True, at / "a" / "b": True, at / "c": False}


def test_landed_never_follows_a_link_on_the_way_and_refuses_a_home_that_is_one(
    tmp_path: Path,
) -> None:
    at = tmp_path / "home"
    at.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (at / "a").symlink_to(outside)
    (at / "f").mkdir()

    landed(at, {at / "a": True, at / "a" / "b": False, at / "f": False})

    assert list(outside.iterdir()) == []
    assert (at / "a" / "b").is_file()
    assert (at / "f").is_file()
    linked = tmp_path / "linked"
    linked.symlink_to(at)
    with pytest.raises(NotADirectoryError):
        landed(linked, {linked / "x": True})


def test_a_record_inside_a_home_is_one_that_resolves_there(tmp_path: Path) -> None:
    at = tmp_path / "home"
    at.mkdir()
    elsewhere = written(tmp_path / "theirs.jsonl", "")
    (at / "linked.jsonl").symlink_to(elsewhere)
    mine = written(at / "mine.jsonl", "")

    assert inside(at, mine)
    assert not inside(at, at / "linked.jsonl")


def test_a_copy_of_a_link_is_none_and_one_of_nothing_is_nothing(
    tmp_path: Path,
) -> None:
    target = written(tmp_path / "target", "secret")
    (tmp_path / "linked").symlink_to(target)

    Copy(source=tmp_path / "linked", destination=tmp_path / "out" / "a").made()
    Copy(source=tmp_path / "missing", destination=tmp_path / "out" / "b").made()

    assert not (tmp_path / "out" / "a").exists()
    assert not (tmp_path / "out" / "b").exists()


def test_configuration_mounts_the_copy_where_a_layer_holds_the_item_else_the_empty(
    tmp_path: Path,
) -> None:
    lower = tmp_path / "lower"
    upper = tmp_path / "upper"
    (lower / "skills").mkdir(parents=True)
    written(upper / "skills", "a file where a directory goes")
    launch = HomeLaunch(directory=tmp_path / "launch")
    at = tmp_path / "home"

    placed = configured(
        [Item(name="skills"), Item(name="CLAUDE.md", directory=False)],
        [lower, upper],
        at,
        launch,
    )

    assert placed.copies == [
        Copy(source=lower / "skills", destination=launch.copied("skills"))
    ]
    assert placed.mounts == [
        Mount(source=launch.copied("skills"), target=at / "skills", read_only=True),
        Mount(source=launch.empty_file, target=at / "CLAUDE.md", read_only=True),
    ]
    assert placed.left == [f"{upper / 'skills'}, which isn't a directory"]


# The preferences carried back


def preferences(
    tmp_path: Path, syntax: str, **written_values: str | None
) -> Preferences:
    return Preferences.model_validate(
        {
            "saved": tmp_path / f"saved.{syntax}",
            "into": tmp_path / "profile" / f"settings.{syntax}",
            "syntax": syntax,
            "written": [
                Setting(preference=Preference(keys=key.split("__")), value=value)
                for key, value in written_values.items()
            ],
        }
    )


def test_a_preference_the_session_changed_is_carried_into_the_layer_keeping_the_rest(
    tmp_path: Path,
) -> None:
    carrying = preferences(tmp_path, "json", model="sonnet", theme="dark")
    written(carrying.into, json.dumps({"theme": "dark", "mine": True}))
    written(
        carrying.saved,
        json.dumps({"model": "opus", "theme": "dark", "hooks": {"Stop": []}}),
    )

    said = carrying.carried()

    assert json.loads(carrying.into.read_text()) == {
        "theme": "dark",
        "mine": True,
        "model": "opus",
    }
    assert said == [
        f'Kept `model` = "opus" in {carrying.into}, as the session saved it.'
    ]


def test_a_toml_preference_is_carried_into_its_table_keeping_the_file_s_comments(
    tmp_path: Path,
) -> None:
    carrying = preferences(tmp_path, "toml", tui__theme=None, model="gpt-6")
    written(carrying.into, '# the profile\'s own\nmodel = "gpt-6"\n')
    written(carrying.saved, 'model = "gpt-6"\n[tui]\ntheme = "light"\n')

    carrying.carried()

    text = carrying.into.read_text()
    assert text.startswith("# the profile's own\n")
    assert tomllib.loads(text) == {"model": "gpt-6", "tui": {"theme": "light"}}


def test_nothing_unchanged_too_large_or_through_a_link_is_carried(
    tmp_path: Path,
) -> None:
    carrying = preferences(tmp_path, "json", model="sonnet", theme=None)
    written(carrying.saved, json.dumps({"model": "sonnet", "theme": "x" * 5000}))

    assert carrying.carried() == [
        "Left `theme` as it was: what the session saved there is more than 4,096 bytes."
    ]
    assert not carrying.into.exists()
    carrying.saved.unlink()
    assert carrying.carried() == []
    carrying.saved.symlink_to(written(tmp_path / "elsewhere.json", '{"model": "x"}'))
    assert carrying.carried()[0].startswith(
        f"No preference was carried back from {carrying.saved}:"
    )
    assert not carrying.into.exists()


def test_a_later_layer_never_writes_through_a_link_an_earlier_one_copied(
    tmp_path: Path,
) -> None:
    keys = written(tmp_path / "host" / "authorized_keys", "the operator's")
    autostart = tmp_path / "host" / "autostart"
    autostart.mkdir()
    lower = tmp_path / "lower"
    (lower / "skills").mkdir(parents=True)
    (lower / "skills" / "notes").symlink_to(keys)
    (lower / "skills" / "tools").symlink_to(autostart)
    upper = tmp_path / "upper"
    written(upper / "skills" / "notes", "the profile's notes")
    written(upper / "skills" / "tools" / "run.sh", "the profile's tool")
    destination = tmp_path / "launch" / "skills"

    for layer in [lower, upper]:
        Copy(source=layer / "skills", destination=destination).made()

    assert keys.read_text() == "the operator's"
    assert list(autostart.iterdir()) == []
    assert not (destination / "notes").is_symlink()
    assert (destination / "notes").read_text() == "the profile's notes"
    assert (destination / "tools" / "run.sh").read_text() == "the profile's tool"


def test_a_pipe_a_room_left_at_a_file_s_landing_is_replaced_never_waited_on(
    tmp_path: Path,
) -> None:
    at = tmp_path / "home"
    at.mkdir()
    os.mkfifo(at / "settings.json")

    landed(at, {at / "settings.json": False})

    assert (at / "settings.json").is_file()


def test_a_toml_preference_keeps_the_rest_of_an_inline_table(tmp_path: Path) -> None:
    carrying = preferences(tmp_path, "toml", tui__theme=None)
    written(carrying.into, "tui = { vim = true }\n")
    written(carrying.saved, '[tui]\ntheme = "light"\n')

    carrying.carried()

    assert tomllib.loads(carrying.into.read_text()) == {
        "tui": {"vim": True, "theme": "light"}
    }
