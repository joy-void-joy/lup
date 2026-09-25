"""No profile names the default home, wherever one is registered or selected.

Claude Code reads its configuration document from ``~/.claude.json`` while
``CLAUDE_CONFIG_DIR`` is unset, and from ``<dir>/.claude.json`` once it names
a directory — ``~/.claude`` included. A profile registered at the default home
therefore opened every session on a document the account never wrote, and the
person's theme, trust records and projects looked reset. These pin the refusal
at every place a profile can be registered, selected or resolved, and that a
registration already on disk fails naming itself and the way out, while
forgetting it stays open.

Nothing here writes to the real default home: a registration naming it is
refused before anything is written, a registration already on disk is a file
under the test's own directory, and a directory profile is pointed at a home
the test makes by a login declaring that home its default.
"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

import lup.devtools.harness.launch as launch
import lup.providers.claude.usage.reader as claude_usage
from lup.devtools.harness.composition import NativeTargets
from lup.observability.usage.app import create_usage_app
from lup.devtools.harness.profile_app import create_profile_app
from lup.devtools.resolve.app import create_resolve_app
from lup.devtools.setup import create_setup_app
from lup.providers.claude.config import ClaudeProfileRegistry, ClaudeProfileSelection
from lup.providers.claude.login import CLAUDE_CONFIG_DIR, CLAUDE_LOGIN
from lup.providers.claude.profile_store import (
    AccountFile,
    ClaudeProfileNames,
    ClaudeProfileRegistrar,
)
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.login import ProviderLogin
from lup.providers.profile_tree import (
    ProfileFolders,
    TreeProfileNames,
    TreeProfileRegistrar,
)
from lup.providers.profiles import DefaultHomeProfile, ProfileDirectory

DEFAULT_HOME = CLAUDE_LOGIN.ambient_home

WAY_OUT = "leave the profile unset to use the default account"

WIDE_PLAIN_CONSOLE = {
    "FORCE_COLOR": None,
    "NO_COLOR": "1",
    "TERM": "dumb",
    "COLUMNS": "400",
}

runner = CliRunner(env=WIDE_PLAIN_CONSOLE)


@pytest.fixture
def accounts(tmp_path: Path) -> AccountFile:
    return AccountFile(tmp_path / "profiles.json")


@pytest.fixture
def directory(accounts: AccountFile) -> ProfileDirectory:
    return ProfileDirectory(
        ClaudeProfileNames(accounts), ClaudeProfileRegistrar(accounts), CLAUDE_LOGIN
    )


@pytest.fixture
def registered(accounts: AccountFile, tmp_path: Path) -> AccountFile:
    """A registry written before the refusal existed: ``main`` is the default home.

    Spelled the way a person types it, so resolution has to expand it before it
    can tell; ``work`` sits beside it to show the refusal is about ``main``.
    """
    accounts.registry_path.write_text(
        '{"profiles":{"main":{"config_dir":"~/.claude"},'
        f'"work":{{"config_dir":"{tmp_path / "work-home"}"}}}},"active":"main"}}',
        encoding="utf-8",
    )
    return accounts


def own_default(tmp_path: Path) -> ProviderLogin:
    """Claude's login, declaring a home this test made as its default."""
    home = tmp_path / "user" / ".claude"
    home.mkdir(parents=True)
    return CLAUDE_LOGIN.model_copy(update={"ambient_home": home})


def tree_directory(root: Path, login: ProviderLogin) -> ProfileDirectory:
    """Profiles kept as directories, one per account, under ``root``."""
    folders = ProfileFolders(root, login.home_subdir)
    return ProfileDirectory(
        TreeProfileNames(folders), TreeProfileRegistrar(folders), login
    )


def symlinked(root: Path, name: str, login: ProviderLogin, target: Path) -> Path:
    """A directory profile whose home is a symlink onto ``target``."""
    home = root / name / login.home_subdir
    home.parent.mkdir(parents=True)
    home.symlink_to(target, target_is_directory=True)
    return home


# The login's own answer, which every refusal below asks.


@pytest.mark.parametrize(
    "spelled",
    [
        DEFAULT_HOME,
        Path("~/.claude"),
        DEFAULT_HOME / "nested" / "..",
        Path(f"{DEFAULT_HOME}/"),
    ],
    ids=["absolute", "tilde", "dotdot", "trailing-separator"],
)
def test_claude_cannot_be_pointed_at_its_default_home_by_name(spelled: Path) -> None:
    assert not CLAUDE_LOGIN.nameable(spelled)


def test_a_symlink_onto_the_default_home_is_the_default_home(tmp_path: Path) -> None:
    link = tmp_path / "account"
    link.symlink_to(DEFAULT_HOME, target_is_directory=True)

    assert not CLAUDE_LOGIN.nameable(link)
    assert CLAUDE_LOGIN.nameable(tmp_path / ".claude")


def test_codex_can_be_pointed_at_its_default_home_by_name() -> None:
    """A set ``CODEX_HOME`` of ``~/.codex`` is the unset one: nothing sits beside it."""
    assert CODEX_LOGIN.nameable(CODEX_LOGIN.ambient_home)


# A typed selection, which a programmatic registry is built from.


def test_a_selection_cannot_name_the_default_home() -> None:
    with pytest.raises(ValidationError, match=WAY_OUT):
        ClaudeProfileSelection(config_directory=DEFAULT_HOME)


def test_a_registry_cannot_hold_a_named_profile_at_the_default_home() -> None:
    with pytest.raises(ValidationError) as raised:
        ClaudeProfileRegistry.model_validate(
            {"profiles": {"main": {"config_directory": "~/.claude"}}}
        )

    assert raised.value.errors()[0]["loc"] == ("profiles", "main", "config_directory")


def test_a_registry_cannot_default_to_the_default_home_by_name() -> None:
    """The same trap as a named one, so the same refusal."""
    with pytest.raises(ValidationError, match=WAY_OUT):
        ClaudeProfileRegistry.model_validate(
            {"default": {"config_directory": str(DEFAULT_HOME)}}
        )


# The personal registry, curated and resolved directly.


@pytest.mark.parametrize("spelled", [DEFAULT_HOME, Path("~/.claude")])
def test_registering_the_default_home_is_refused_before_anything_is_written(
    accounts: AccountFile, spelled: Path
) -> None:
    registrar = ClaudeProfileRegistrar(accounts)

    with pytest.raises(DefaultHomeProfile, match=WAY_OUT) as raised:
        registrar.add_profile("main", spelled)

    assert "profile 'main' cannot name the default home" in str(raised.value)
    assert not accounts.registry_path.exists()


def test_a_stored_default_home_fails_resolution_naming_itself_and_the_way_out(
    registered: AccountFile,
) -> None:
    for name in [None, "main"]:
        with pytest.raises(DefaultHomeProfile) as raised:
            registered.resolve_config_dir(name)

        refusal = str(raised.value)
        assert f"profile 'main' names the default home {DEFAULT_HOME.resolve()}" in (
            refusal
        )
        assert CLAUDE_CONFIG_DIR in refusal
        assert f"remove it (`profile remove main`) and {WAY_OUT}" in refusal


def test_a_stored_default_home_cannot_be_selected(registered: AccountFile) -> None:
    registrar = ClaudeProfileRegistrar(registered)
    registrar.set_active("work")

    with pytest.raises(DefaultHomeProfile, match="profile 'main'"):
        registrar.set_active("main")
    assert registered.load_registry().active == "work"


def test_forgetting_a_stored_default_home_restores_the_default_account(
    registered: AccountFile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The way out the refusal names has to be open, and has to arrive."""
    monkeypatch.delenv(CLAUDE_CONFIG_DIR, raising=False)
    registrar = ClaudeProfileRegistrar(registered)

    registrar.remove_profile("main")

    assert registered.resolve_config_dir() == CLAUDE_LOGIN.ambient_home
    assert ClaudeProfileNames(registered).names() == ["work"]


# The directory a launcher, a resolver run and the command trees hold.


def test_the_directory_refuses_the_default_home_before_the_origin_sees_it(
    directory: ProfileDirectory,
) -> None:
    with pytest.raises(DefaultHomeProfile, match=WAY_OUT):
        directory.add("main", DEFAULT_HOME)

    assert directory.entries() == []


def test_a_stored_default_home_is_refused_wherever_it_would_be_launched(
    registered: AccountFile,
) -> None:
    """Named or merely active, for a launch, a run's account, or a selection.

    Adding it again without a home is refused too, before anything is
    written: what the name already holds is the default home.
    """
    directory = ProfileDirectory(
        ClaudeProfileNames(registered), ClaudeProfileRegistrar(registered), CLAUDE_LOGIN
    )
    stored = registered.registry_path.read_bytes()

    for refused in [
        lambda: directory.launch_home(None),
        lambda: directory.launch_home("main"),
        lambda: directory.account(None),
        lambda: directory.use("main"),
        lambda: directory.add("main"),
    ]:
        with pytest.raises(DefaultHomeProfile, match="profile remove main"):
            refused()

    assert registered.registry_path.read_bytes() == stored
    assert directory.launch_home("work") == registered.registry_path.parent / (
        "work-home"
    )
    assert [entry.name for entry in directory.entries()] == ["main", "work"]


def test_pointing_a_stored_default_home_elsewhere_repairs_it(
    registered: AccountFile, tmp_path: Path
) -> None:
    """The other way out: the name keeps working, on a home of its own."""
    directory = ProfileDirectory(
        ClaudeProfileNames(registered), ClaudeProfileRegistrar(registered), CLAUDE_LOGIN
    )

    directory.add("main", tmp_path / "main-home")

    assert directory.launch_home(None) == tmp_path / "main-home"


def test_the_directory_forgets_a_stored_default_home_and_then_names_none(
    registered: AccountFile,
) -> None:
    directory = ProfileDirectory(
        ClaudeProfileNames(registered), ClaudeProfileRegistrar(registered), CLAUDE_LOGIN
    )

    removed = directory.remove("main")

    assert removed.config_dir == Path.home() / ".claude"
    assert directory.launch_home(None) is None
    assert directory.account(None).variables == {}


def test_a_directory_profile_is_refused_the_default_home_rather_than_advised_to_link(
    tmp_path: Path,
) -> None:
    """Its own refusal would say to symlink that path, which is the trap itself."""
    login = own_default(tmp_path)
    tree = tree_directory(tmp_path / "profiles", login)

    with pytest.raises(DefaultHomeProfile, match=WAY_OUT) as raised:
        tree.add("main", login.ambient_home)

    assert "symlink" not in str(raised.value)
    assert not (tmp_path / "profiles").exists()


def test_a_directory_profile_symlinked_onto_the_default_home_is_refused(
    tmp_path: Path,
) -> None:
    login = own_default(tmp_path)
    root = tmp_path / "profiles"
    symlinked(root, "main", login, login.ambient_home)
    tree = tree_directory(root, login)

    for refused in [
        lambda: tree.add("main"),
        lambda: tree.use("main"),
        lambda: tree.launch_home("main"),
        lambda: tree.account("main"),
    ]:
        with pytest.raises(DefaultHomeProfile, match="profile 'main' names"):
            refused()

    assert [entry.name for entry in tree.entries()] == ["main"]
    assert tree.names.active_profile() is None, "a refused add selected it anyway"


def test_a_codex_directory_profile_may_link_its_default_home(tmp_path: Path) -> None:
    """Codex keeps nothing beside its home, so naming it is naming nothing."""
    login = CODEX_LOGIN.model_copy(
        update={"ambient_home": tmp_path / "user" / ".codex"}
    )
    login.ambient_home.mkdir(parents=True)
    root = tmp_path / "profiles"
    home = symlinked(root, "main", login, login.ambient_home)

    assert tree_directory(root, login).launch_home("main") == home


# The command trees and entry points a person reaches all of this through.


def test_the_profile_command_tree_refuses_adding_the_default_home(
    directory: ProfileDirectory, accounts: AccountFile
) -> None:
    result = runner.invoke(
        create_profile_app(directory),
        ["add", "main", "--config-dir", "~/.claude"],
    )

    assert result.exit_code != 0
    assert "profile 'main' cannot name the default home" in result.output
    assert WAY_OUT in result.output
    assert not accounts.registry_path.exists()


def test_the_profile_command_tree_refuses_selecting_a_stored_default_home(
    registered: AccountFile,
) -> None:
    directory = ProfileDirectory(
        ClaudeProfileNames(registered), ClaudeProfileRegistrar(registered), CLAUDE_LOGIN
    )

    result = runner.invoke(create_profile_app(directory), ["use", "main"])

    assert result.exit_code != 0
    assert "profile remove main" in result.output


def test_the_setup_wizard_refuses_adding_the_default_home(
    directory: ProfileDirectory, accounts: AccountFile
) -> None:
    result = runner.invoke(
        create_setup_app([], directory),
        ["profile", "add", "main", "--config-dir", str(DEFAULT_HOME)],
    )

    assert result.exit_code != 0
    assert WAY_OUT in result.output
    assert not accounts.registry_path.exists()


def test_a_launch_refuses_a_stored_default_home_as_a_bad_parameter(
    registered: AccountFile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run ``launch_claude`` as far as the profile it exports, and no further."""
    directory = ProfileDirectory(
        ClaudeProfileNames(registered), ClaudeProfileRegistrar(registered), CLAUDE_LOGIN
    )
    plugin = Mock()
    plugin.name = "lup"
    composition = Mock()
    composition.recipe.source.plugins = [plugin]
    monkeypatch.setattr(launch, "ready_to_open", lambda *a, **k: launch.LaunchOpening())
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(
        launch,
        "claude_sandbox_arguments",
        lambda _plugin, sandbox=launch.LaunchSandbox.INNER, accessible=[], settings=None: [],
    )
    monkeypatch.setattr(launch, "non_interactive_environment", lambda _env: {})
    monkeypatch.setattr(launch, "apply_sandbox_environment", lambda *a, **k: None)
    monkeypatch.setattr(launch, "accessible_roots", lambda *a: [])
    session = Mock(side_effect=AssertionError("a refused profile opened a session"))
    monkeypatch.setattr(launch, "start_harness_transcript", session)

    with pytest.raises(typer.BadParameter, match="profile remove main"):
        launch.launch_claude(composition, [], directory, None, None, False)


def test_a_resolver_run_refuses_a_stored_default_home_before_it_starts(
    registered: AccountFile,
) -> None:
    """Refused in this terminal, including for a run that would have detached."""
    directory = ProfileDirectory(
        ClaudeProfileNames(registered), ClaudeProfileRegistrar(registered), CLAUDE_LOGIN
    )
    app = create_resolve_app(Mock(), NativeTargets(builders={}), profiles=directory)

    for arguments in [["--profile", "main"], ["--detach", "--adapter", "claude"]]:
        result = runner.invoke(app, arguments)

        assert result.exit_code == 2, result.output
        assert "profile remove main" in result.output


def test_the_usage_display_reports_a_stored_default_home_as_a_failed_read(
    registered: AccountFile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading an account's usage resolves its profile too, and says so the same way.

    As a failed read rather than a traceback, so ``--json`` still answers a
    parser with an error object on stdout.
    """
    monkeypatch.setattr(claude_usage, "AccountFile", lambda: registered)
    root = typer.Typer()
    root.add_typer(create_usage_app([claude_usage.claude_usage_entry()]), name="usage")

    shown = runner.invoke(root, ["usage", "claude", "--profile", "main"])
    emitted = runner.invoke(root, ["usage", "claude", "--json"])
    unknown = runner.invoke(root, ["usage", "claude", "--profile", "ghost"])

    assert shown.exit_code == 1, shown.output
    assert "profile remove main" in shown.output
    assert emitted.exit_code == 1, emitted.output
    assert "profile remove main" in json.loads(emitted.stdout)["error"]
    assert unknown.exit_code == 1, unknown.output
    assert "unknown Claude profile 'ghost'" in unknown.output
