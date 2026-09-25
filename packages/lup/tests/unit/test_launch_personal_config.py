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
from lup.providers.claude.login import CLAUDE_CONFIG_DIR, CLAUDE_LOGIN
from lup.providers.profile_tree import user_profile_directory
from lup.providers.user_config import UserConfigFile
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
            publish=Mock(return_value=False), return_settings=Mock(return_value=[])
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
        user_profile_directory(CLAUDE_LOGIN, config),
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


def test_a_fresh_project_inherits_the_persons_tier_effort_and_account(
    config: UserConfigFile, launched: Launched
) -> None:
    home = user_profile_directory(CLAUDE_LOGIN, config).add("work").config_dir
    writes(
        config,
        'profile = "work"\ntier = "balanced"\neffort = "high"\n',
    )

    claude(config)

    assert flag(launched.arguments, "--model") == "sonnet"
    assert flag(launched.arguments, "--effort") == "high"
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


def test_claude_draws_the_persons_theme_lups_by_default(
    config: UserConfigFile, launched: Launched
) -> None:
    claude(config)
    assert launched.settings["theme"] == "dark-daltonized"

    writes(config, '[theme]\nclaude = "light-ansi"\n')
    claude(config, model="opus", effort="max")

    assert launched.settings["theme"] == "light-ansi"
    assert launched.settings.get("ultracode") is None


def test_codex_draws_the_persons_theme_over_a_home_lup_made(
    config: UserConfigFile,
    launched: Launched,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        launch,
        "select_codex_home",
        lambda *args: Mock(path=tmp_path / "home", isolated=True),
    )
    writes(config, '[theme]\ncodex = "dracula"\n')

    launch.launch_codex(composition(), [], None, None, None, False, False)

    assert 'tui.theme="dracula"' in launched.arguments


def test_codex_leaves_a_home_the_operator_brought_its_own_theme(
    config: UserConfigFile, launched: Launched
) -> None:
    launch.launch_codex(composition(), [], None, None, None, False, False)

    assert not any(argument.startswith("tui.theme=") for argument in launched.arguments)


def test_codex_derives_its_worktree_home_from_the_selected_account(
    config: UserConfigFile,
    launched: Launched,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One name, one account: the profile a Claude launch opens, on Codex too."""
    user_profile_directory(CLAUDE_LOGIN, config).add("work")
    stores: list[dict[str, object]] = []

    def store(**named: object) -> Mock:
        stores.append(named)
        return Mock(
            publish=Mock(return_value=False), return_settings=Mock(return_value=[])
        )

    monkeypatch.setattr(launch, "CodexWorktreeHomeStore", store)

    launch.launch_codex(composition(), [], None, None, None, False, False)

    assert stores == [{"account_home": config.profiles_root() / "work" / "codex-home"}]
