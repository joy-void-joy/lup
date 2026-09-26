"""A launch in a project it has never seen opens the way the person left it.

The complaint this answers: every new repository reset the account, the
theme and the defaults, because each was kept per checkout or left to a CLI
starting from nothing. A launch reads them from the person's lup config
instead, so a fresh project inherits them; a project's mode and a flag on the
command line still overrule it, in that order.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest
import sh
import typer

import lup.devtools.harness.launch as launch
import lup.providers.profile_tree as profile_tree
from lup.providers.claude.config_home import (
    ClaudeConfigHome,
    load_document,
    save_document,
    selected_config_home,
)
from lup.providers.claude.login import CLAUDE_CONFIG_DIR, CLAUDE_LOGIN
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.codex.preferences import CodexSettingsReturn
from lup.providers.profile_tree import profile_directory
from lup.providers.user_config import UserConfigFile
from lup.types import EnvVars
from lup.providers.claude.usage.reader import ClaudeUsageReader, claude_usage_entry
from lup.providers.codex.usage.reader import CodexUsageReader, codex_usage_entry
from tests.unit.test_launch_effort_default import Transcript, composition


class Launched:
    """What the stubbed CLI was started with, argv and environment."""

    def __init__(self) -> None:
        self.arguments: list[str] = []
        self.settings: dict[str, object] = {}
        self.environment: dict[str, str] = {}


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> UserConfigFile:
    """A person's config home, found the way a launch finds one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return UserConfigFile()


def writes(config: UserConfigFile, content: str) -> None:
    config.path().parent.mkdir(parents=True, exist_ok=True)
    config.path().write_text(content, encoding="utf-8")


@pytest.fixture
def launched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Launched:
    """Stub every launch side effect and keep what each CLI would be handed."""
    seen = Launched()
    project = tmp_path / "fresh-project"
    project.mkdir()

    def argv(
        name: str, arguments: list[str], *args: object, **kwargs: object
    ) -> list[str]:
        del args, kwargs
        seen.arguments = list(arguments)
        return [name]

    def settings_document(
        _plugin: object,
        sandbox: object = None,
        accessible: object = (),
        settings: dict[str, object] | None = None,
    ) -> list[str]:
        del sandbox, accessible
        seen.settings = dict(settings or {})
        return []

    def started(_name: str) -> object:
        def run(*args: object, _env: dict[str, str], **kwargs: object) -> None:
            del args, kwargs
            seen.environment = dict(_env)

        return run

    monkeypatch.setattr(
        launch,
        "ready_to_open",
        lambda *a, **k: launch.LaunchOpening(sandbox=launch.LaunchSandbox.INNER),
    )
    monkeypatch.setattr(launch, "project_root", lambda: project)
    monkeypatch.setattr(profile_tree, "project_root", lambda: project)
    monkeypatch.setattr(launch, "carry_claude_home", lambda *a, **k: None)
    monkeypatch.setattr(launch, "ambient_config_home", lambda *a, **k: tmp_path)
    monkeypatch.setattr(launch, "session_argv", argv)
    monkeypatch.setattr(launch, "claude_sandbox_arguments", settings_document)
    monkeypatch.setattr(
        launch,
        "codex_sandbox_arguments",
        lambda _plugin, _environment, _args, sandbox=None, accessible=[]: [],
    )
    monkeypatch.setattr(launch, "non_interactive_environment", lambda _env: {})
    monkeypatch.setattr(launch, "apply_sandbox_environment", lambda *a, **k: None)
    monkeypatch.setattr(launch, "ClaudeTranscripts", lambda _home: Mock())
    monkeypatch.setattr(launch, "CodexTranscripts", lambda _home: Mock())
    monkeypatch.setattr(
        launch,
        "CodexWorktreeHomeStore",
        lambda **_: Mock(
            publish=Mock(return_value=False),
            return_settings=Mock(return_value=CodexSettingsReturn()),
        ),
    )
    monkeypatch.setattr(
        launch,
        "select_codex_home",
        lambda *args: Mock(path=tmp_path / "home", isolated=False),
    )
    monkeypatch.setattr(launch, "codex_login_preflight", lambda *args: None)
    monkeypatch.setattr(launch, "accessible_roots", lambda: [])
    monkeypatch.setattr(
        launch, "start_harness_transcript", lambda *args, **kwargs: Transcript()
    )
    monkeypatch.setattr(sh, "Command", started)
    return seen


def flag(arguments: list[str], name: str) -> str | None:
    """The value following ``name`` on a command line, where it appears."""
    return arguments[arguments.index(name) + 1] if name in arguments else None


def claude(
    config: UserConfigFile, model: str | None = None, effort: str | None = None
) -> None:
    """``harness claude`` in the fresh project, over the person's accounts."""
    launch.launch_claude(
        composition(),
        [],
        profile_directory(CLAUDE_LOGIN, config),
        None,
        model,
        False,
        effort=effort,
    )


def test_a_person_who_wrote_nothing_launches_on_lups_defaults(
    config: UserConfigFile, launched: Launched
) -> None:
    claude(config)

    assert flag(launched.arguments, "--model") == "opus"
    assert flag(launched.arguments, "--effort") == "xhigh"
    assert CLAUDE_CONFIG_DIR not in launched.environment


def test_a_fresh_project_inherits_the_persons_account_theme_and_defaults(
    config: UserConfigFile, launched: Launched
) -> None:
    home = (
        profile_directory(CLAUDE_LOGIN, config).add("work", scope="global").config_dir
    )
    writes(
        config,
        'profile = "work"\ntier = "balanced"\neffort = "high"\n\n'
        '[theme]\nclaude = "light-daltonized"\n',
    )

    claude(config)

    assert flag(launched.arguments, "--model") == "sonnet"
    assert flag(launched.arguments, "--effort") == "high"
    assert load_document(home / ".claude.json")["theme"] == "light-daltonized"
    assert launched.environment[CLAUDE_CONFIG_DIR] == str(home)


def test_a_flag_on_the_command_line_overrules_the_person(
    config: UserConfigFile, launched: Launched
) -> None:
    writes(config, 'tier = "balanced"\neffort = "high"\n')

    claude(config, model="opus", effort="max")

    assert flag(launched.arguments, "--model") == "opus"
    assert flag(launched.arguments, "--effort") == "max"


def test_the_persons_effort_steps_down_to_one_the_model_takes(
    config: UserConfigFile, launched: Launched
) -> None:
    """A default adapts where a named effort would be refused."""
    writes(config, 'effort = "ultra"\n')

    claude(config, model="claude-opus-4-6")

    assert flag(launched.arguments, "--effort") == "max"


def test_codex_launches_on_the_persons_tier_and_effort(
    config: UserConfigFile, launched: Launched
) -> None:
    writes(config, 'tier = "balanced"\neffort = "high"\n')

    launch.launch_codex(composition(), [], None, None, None, False, False)

    assert flag(launched.arguments, "--model") == "gpt-5.6-terra"
    assert 'model_reasoning_effort="high"' in launched.arguments


def test_a_config_lup_cannot_read_refuses_the_launch_naming_it(
    config: UserConfigFile, launched: Launched
) -> None:
    writes(config, 'tier = "enormous"\n')

    with pytest.raises(typer.BadParameter, match=str(config.path())):
        claude(config)
    assert launched.arguments == []


@pytest.fixture
def account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ClaudeConfigHome:
    """The operator's default Claude home, for this test alone."""
    home = ClaudeConfigHome(
        directory=tmp_path / "user" / ".claude",
        document=tmp_path / "user" / ".claude.json",
    )

    def selected(environment: EnvVars) -> ClaudeConfigHome:
        if environment.get(CLAUDE_CONFIG_DIR):
            return selected_config_home(environment)
        return home

    monkeypatch.setattr(launch, "selected_config_home", selected)
    return home


def test_claude_fills_lups_theme_only_where_the_account_names_none(
    config: UserConfigFile, launched: Launched, account: ClaudeConfigHome
) -> None:
    claude(config)

    assert load_document(account.document) == {"theme": "dark-daltonized"}
    assert "theme" not in launched.settings


def test_claude_leaves_a_theme_the_account_already_has(
    config: UserConfigFile, launched: Launched, account: ClaudeConfigHome
) -> None:
    save_document(account.document, {"theme": "light", "editorMode": "vim"})

    claude(config)

    assert load_document(account.document) == {"theme": "light", "editorMode": "vim"}


def test_claude_leaves_a_theme_the_accounts_settings_hold(
    config: UserConfigFile, launched: Launched, account: ClaudeConfigHome
) -> None:
    """Claude Code reads the settings' theme first, so that one is the account's."""
    settings = account.directory / "settings.json"
    save_document(settings, {"theme": "light-ansi"})

    claude(config)

    assert load_document(settings) == {"theme": "light-ansi"}
    assert not account.document.exists()


def test_a_theme_the_config_names_wins_over_the_accounts(
    config: UserConfigFile, launched: Launched, account: ClaudeConfigHome
) -> None:
    save_document(account.document, {"theme": "light", "editorMode": "vim"})
    writes(config, '[theme]\nclaude = "dark-ansi"\n')

    claude(config)

    assert load_document(account.document) == {
        "theme": "dark-ansi",
        "editorMode": "vim",
    }


def test_a_named_theme_is_written_where_the_account_keeps_its_own(
    config: UserConfigFile, launched: Launched, account: ClaudeConfigHome
) -> None:
    settings = account.directory / "settings.json"
    save_document(settings, {"theme": "light", "model": "opus"})
    writes(config, '[theme]\nclaude = "dark-ansi"\n')

    claude(config)

    assert load_document(settings) == {"theme": "dark-ansi", "model": "opus"}
    assert not account.document.exists()


def test_a_claude_sessions_theme_change_stays_the_accounts(
    config: UserConfigFile,
    launched: Launched,
    account: ClaudeConfigHome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host session runs in the account's own home, so /theme lands there.

    Nothing after the session writes the document back, so a change the
    account took meanwhile — here another process setting its editor mode —
    survives beside the session's theme, and the next launch keeps both.
    """

    def session(_name: str) -> object:
        def run(*args: object, _env: dict[str, str], **kwargs: object) -> None:
            del args, _env, kwargs
            chosen = {**load_document(account.document), "theme": "light"}
            save_document(account.document, {**chosen, "editorMode": "vim"})

        return run

    monkeypatch.setattr(sh, "Command", session)

    claude(config)

    assert load_document(account.document) == {"theme": "light", "editorMode": "vim"}
    claude(config)
    assert load_document(account.document)["theme"] == "light"


def test_a_contained_claude_launch_leaves_the_accounts_theme_alone(
    config: UserConfigFile,
    launched: Launched,
    account: ClaudeConfigHome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its session runs in the repository's config volume, not the account."""
    monkeypatch.setattr(
        launch,
        "ready_to_open",
        lambda *a, **k: launch.LaunchOpening(sandbox=launch.LaunchSandbox.OUTER),
    )

    claude(config)

    assert not account.document.exists()
    assert "theme" not in launched.settings


def test_codex_hands_the_named_theme_to_the_home_not_the_command_line(
    config: UserConfigFile,
    launched: Launched,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A launch-wide override would outrank the session's own /theme."""
    writes(config, '[theme]\ncodex = "dracula"\n')
    stores: list[dict[str, object]] = []

    def store(**named: object) -> Mock:
        stores.append(named)
        return Mock(
            publish=Mock(return_value=False),
            return_settings=Mock(return_value=CodexSettingsReturn()),
        )

    monkeypatch.setattr(launch, "CodexWorktreeHomeStore", store)

    launch.launch_codex(composition(), [], None, None, None, False, False)

    assert stores == [
        {
            "account_home": CODEX_LOGIN.ambient_home,
            "theme": "dracula",
            "editor": None,
            "settings": {},
        }
    ]
    assert not any("tui.theme" in argument for argument in launched.arguments)


def test_codex_derives_its_worktree_home_from_the_selected_account(
    config: UserConfigFile,
    launched: Launched,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One name, one account: the profile a Claude launch opens, on Codex too."""
    profile_directory(CLAUDE_LOGIN, config).add("work", scope="global")
    stores: list[dict[str, object]] = []

    def store(**named: object) -> Mock:
        stores.append(named)
        return Mock(
            publish=Mock(return_value=False),
            return_settings=Mock(return_value=CodexSettingsReturn()),
        )

    monkeypatch.setattr(launch, "CodexWorktreeHomeStore", store)

    launch.launch_codex(composition(), [], None, None, None, False, False)

    assert stores == [
        {
            "account_home": config.profiles_root() / "work" / "codex-home",
            "theme": None,
            "editor": None,
            "settings": {},
        }
    ]


@pytest.mark.parametrize("named", ["work", None], ids=["named", "selected"])
def test_the_usage_display_reads_the_account_a_launch_opens(
    config: UserConfigFile, launched: Launched, named: str | None
) -> None:
    """One resolution for both, so a name cannot read one account and open another."""
    accounts = profile_directory(CLAUDE_LOGIN, config)
    accounts.add("personal", scope="global")
    accounts.add("work", scope="global")
    accounts.use("work", "global")
    claude_reader = claude_usage_entry().open(named)
    codex_reader = codex_usage_entry().open(named)

    launch.launch_claude(composition(), [], accounts, named, None, False)

    assert isinstance(claude_reader, ClaudeUsageReader)
    assert isinstance(codex_reader, CodexUsageReader)
    assert str(claude_reader.config_dir) == launched.environment[CLAUDE_CONFIG_DIR]
    assert codex_reader.home == config.profiles_root() / "work" / "codex-home"


@pytest.mark.parametrize("named", ["work", None], ids=["named", "selected"])
def test_the_usage_display_and_a_launch_agree_on_the_checkouts_own_profile(
    config: UserConfigFile, launched: Launched, tmp_path: Path, named: str | None
) -> None:
    """A checkout's profile of a name wins over the global one, for both."""
    accounts = profile_directory(CLAUDE_LOGIN, config)
    accounts.add("work", scope="global")
    accounts.add("work")
    accounts.use("work")
    kept = tmp_path / "fresh-project" / ".lup" / "profiles" / "work"
    claude_reader = claude_usage_entry().open(named)
    codex_reader = codex_usage_entry().open(named)

    launch.launch_claude(composition(), [], accounts, named, None, False)

    assert isinstance(claude_reader, ClaudeUsageReader)
    assert isinstance(codex_reader, CodexUsageReader)
    assert launched.environment[CLAUDE_CONFIG_DIR] == str(kept / "claude-config")
    assert str(claude_reader.config_dir) == launched.environment[CLAUDE_CONFIG_DIR]
    assert codex_reader.home == kept / "codex-home"


def test_a_launch_opens_a_checkouts_profile_and_says_nothing_of_moving_it(
    config: UserConfigFile,
    launched: Launched,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A checkout's own profiles are read where they are, with no notice."""
    kept = tmp_path / "fresh-project" / ".lup" / "profiles"
    (kept / "work" / CLAUDE_LOGIN.home_subdir).mkdir(parents=True)
    (kept / ".active").write_text("work\n", encoding="utf-8")

    claude(config)

    said = capsys.readouterr()
    assert launched.environment[CLAUDE_CONFIG_DIR] == str(
        kept / "work" / CLAUDE_LOGIN.home_subdir
    )
    assert "migrate" not in said.out + said.err
    assert str(kept) not in said.out + said.err


def test_codex_derives_its_worktree_home_from_the_checkouts_selected_account(
    config: UserConfigFile,
    launched: Launched,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The checkout's ``.active`` beats the config file's selection on Codex too."""
    accounts = profile_directory(CODEX_LOGIN, config)
    accounts.add("me", scope="global")
    accounts.add("work")
    accounts.use("work")
    kept = tmp_path / "fresh-project" / ".lup" / "profiles" / "work"
    stores: list[dict[str, object]] = []

    def store(**named: object) -> Mock:
        stores.append(named)
        return Mock(
            publish=Mock(return_value=False),
            return_settings=Mock(return_value=CodexSettingsReturn()),
        )

    monkeypatch.setattr(launch, "CodexWorktreeHomeStore", store)

    launch.launch_codex(composition(), [], None, None, None, False, False)

    assert config.load().profile == "me"
    assert stores == [
        {
            "account_home": kept / "codex-home",
            "theme": None,
            "editor": None,
            "settings": {},
        }
    ]
