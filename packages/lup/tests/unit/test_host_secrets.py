"""A host-only secret lives on the operator's machine, and nowhere a session reads.

Two halves, each over real files. The store: where it is, that it is its
owner's alone from the moment it exists, and that a write replaces it whole
or not at all. The wizard: a host-only integration's answers land in the
store and nothing of them lands in the checkout, whichever surface took them
-- a prompt, the walk, a key by name, the dashboard -- and one left in
``.env.local`` is reported and moved. Who the store's values reach is
``test_host_companions``'s.
"""

import stat
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from rich.console import Console
from typer.testing import CliRunner

from lup.devtools import setup
from lup.devtools.dashboard.app import create_dashboard
from lup.devtools.dashboard.wizard import WizardView
from lup.devtools.envfiles import CheckoutEnv, HostSecrets
from lup.devtools.setup import Integration, PromptField, create_setup_app
from lup.trust.approved import APPROVED_TREE_ENV

KEY = "GEMINI_API_KEY"
SECRET = "AIza-typed-by-the-operator"

GEMINI = Integration(
    name="Gemini",
    command="gemini",
    help="Set the Gemini key the listener calls with.",
    env_keys=[KEY],
    fields=[PromptField(key=KEY, prompt=KEY)],
    host_only=True,
)
"""A host-only integration, as a project with a listener companion declares it."""

TIMEZONE = Integration(
    name="Timezone",
    command="timezone",
    help="Set the timezone.",
    env_keys=["AGENT_TIMEZONE"],
    fields=[PromptField(key="AGENT_TIMEZONE", prompt="AGENT_TIMEZONE", secret=False)],
)
"""An ordinary integration beside it, answered into ``.env.local``."""


def mode(path: Path) -> int:
    """A path's permission bits."""
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """This machine's configuration home, under the test's own directory."""
    home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.delenv(APPROVED_TREE_ENV, raising=False)
    return home


@pytest.fixture
def checkout(tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout named adlib, which the wizard answers into."""
    root = tmp_path / "adlib"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "adlib"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    monkeypatch.setattr(setup, "PROJECT_ROOT", root)
    monkeypatch.setattr(setup, "ENV_LOCAL", root / ".env.local")
    # Wide and plain, so a path or a sentence reads as one line to assert on.
    monkeypatch.setattr(setup, "console", Console(width=1000, color_system=None))
    return root


def store_path(config: Path) -> Path:
    return config / "lup" / "secrets" / "adlib.env"


def holding(root: Path, value: str) -> list[Path]:
    """Every file under a directory whose bytes contain a value."""
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and value.encode("utf-8") in path.read_bytes()
    ]


# -- the store ---------------------------------------------------------------


def test_the_store_is_named_for_the_project_under_the_config_home(
    checkout: Path, config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert HostSecrets.for_checkout(checkout).path == store_path(config)

    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/config")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert HostSecrets.for_checkout(checkout).path == (
        tmp_path / "home" / ".config" / "lup" / "secrets" / "adlib.env"
    )


def test_the_project_is_named_by_the_manifest_its_operator_approved(
    checkout: Path, config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session renaming the checkout's project cannot point the launch at another store."""
    export = tmp_path / "export"
    export.mkdir()
    (export / "pyproject.toml").write_text(
        '[project]\nname = "adlib"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "somebody-else"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    monkeypatch.setenv(APPROVED_TREE_ENV, str(export))

    assert HostSecrets.for_checkout(checkout).path == store_path(config)


def test_the_store_is_its_owners_alone_whatever_was_there_first(
    config: Path,
) -> None:
    directory = config / "lup" / "secrets"
    directory.mkdir(parents=True, mode=0o755)
    directory.chmod(0o755)
    loose = directory / "adlib.env"
    loose.write_text("OLD=1\n", encoding="utf-8")
    loose.chmod(0o644)

    HostSecrets.of("adlib").write({KEY: SECRET})

    assert mode(directory) == 0o700
    assert mode(loose) == 0o600
    assert HostSecrets.of("adlib").read() == {"OLD": "1", KEY: SECRET}


def test_a_fresh_store_is_made_private(config: Path) -> None:
    store = HostSecrets.of("adlib")

    store.write({KEY: SECRET})

    assert mode(store.path.parent) == 0o700
    assert mode(store.path) == 0o600


def test_a_write_replaces_the_store_whole_and_keeps_what_it_did_not_touch(
    config: Path,
) -> None:
    store = HostSecrets.of("adlib")
    store.write({"FIRST": "one"})
    store.path.write_text("# the operator's note\nFIRST=one\n", encoding="utf-8")
    before = store.path.stat().st_ino

    store.write({KEY: SECRET})

    assert store.path.stat().st_ino != before
    assert store.path.read_text(encoding="utf-8") == (
        f"# the operator's note\nFIRST=one\n{KEY}={SECRET}\n"
    )
    assert sorted(item.name for item in store.path.parent.iterdir()) == ["adlib.env"]


def test_an_edit_that_fails_leaves_the_store_as_it_was(config: Path) -> None:
    """Half an edit is never what a reader meets, and its copy does not linger."""
    store = HostSecrets.of("adlib")
    store.write({"FIRST": "one"})

    def interrupted(staging: Path) -> None:
        staging.write_text("FIRST=one\nSECOND=half", encoding="utf-8")
        raise OSError("the disk filled")

    with pytest.raises(OSError, match="the disk filled"):
        store.edited(interrupted)

    assert store.read() == {"FIRST": "one"}
    assert sorted(item.name for item in store.path.parent.iterdir()) == ["adlib.env"]


def test_clearing_a_key_the_store_lacks_changes_nothing(config: Path) -> None:
    store = HostSecrets.of("adlib")
    store.write({"FIRST": "one"})
    before = store.path.stat().st_ino

    store.clear([KEY])

    assert store.path.stat().st_ino == before


def test_a_new_env_local_is_its_owners_and_an_old_one_keeps_its_mode(
    tmp_path: Path,
) -> None:
    fresh = CheckoutEnv(path=tmp_path / "fresh" / ".env.local")
    fresh.path.parent.mkdir()
    fresh.write({"AGENT_TIMEZONE": "UTC"})
    shared = CheckoutEnv(path=tmp_path / ".env.local")
    shared.path.write_text("AGENT_TIMEZONE=UTC\n", encoding="utf-8")
    shared.path.chmod(0o640)

    shared.write({"AGENT_MODEL": "strongest"})

    assert mode(fresh.path) == 0o600
    assert mode(shared.path) == 0o640


# -- the wizard ----------------------------------------------------------------


def invoked(arguments: list[str], answers: str = "") -> str:
    """Run the setup command tree over the two integrations, answering its prompts."""
    result = CliRunner().invoke(
        create_setup_app([GEMINI, TIMEZONE]), arguments, input=answers
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_a_host_only_answer_lands_in_the_store_and_nowhere_in_the_checkout(
    checkout: Path, config: Path
) -> None:
    said = invoked(["gemini"], f"{SECRET}\n")

    assert HostSecrets.of("adlib").read() == {KEY: SECRET}
    assert holding(checkout, SECRET) == []
    assert not (checkout / ".env.local").exists()
    assert SECRET not in said
    assert f"Saved to host store ({store_path(config)})" in said


def test_the_walk_puts_each_answer_where_its_integration_keeps_it(
    checkout: Path, config: Path
) -> None:
    invoked([], f"{SECRET}\nEurope/Paris\n")

    assert HostSecrets.of("adlib").read() == {KEY: SECRET}
    assert CheckoutEnv(path=checkout / ".env.local").read() == {
        "AGENT_TIMEZONE": "Europe/Paris"
    }
    assert holding(checkout, SECRET) == []


def test_a_key_set_by_name_goes_to_the_store_with_the_typing_hidden(
    checkout: Path, config: Path
) -> None:
    said = invoked(["secret", KEY], f"{SECRET}\n")

    assert HostSecrets.of("adlib").read() == {KEY: SECRET}
    assert SECRET not in said
    assert holding(checkout, SECRET) == []


def test_a_key_set_by_name_must_be_one(checkout: Path, config: Path) -> None:
    result = CliRunner().invoke(
        create_setup_app([GEMINI]), ["secret", "not-a-name"], input="x\n"
    )

    assert result.exit_code == 2
    assert not store_path(config).exists()


def test_the_status_says_which_store_each_integration_keeps_its_keys_in(
    checkout: Path, config: Path
) -> None:
    HostSecrets.of("adlib").write({KEY: SECRET})

    said = invoked(["status"])

    [gemini] = [line for line in said.splitlines() if "Gemini" in line]
    [timezone] = [line for line in said.splitlines() if "Timezone" in line]
    assert "OK" in gemini and "host store" in gemini
    assert SECRET not in said and SECRET[:6] in gemini
    assert ".env.local" in timezone
    assert f"Host store: {store_path(config)}" in said


def test_a_host_only_key_left_in_env_local_is_reported_and_moved(
    checkout: Path, config: Path
) -> None:
    (checkout / ".env.local").write_text(
        f"AGENT_TIMEZONE=UTC\n{KEY}={SECRET}\n", encoding="utf-8"
    )

    reported = invoked(["status"])
    moved = invoked(["gemini"], "y\nn\n")

    assert "also in .env.local" in reported
    assert "lup-launch run setup gemini" in reported
    assert "Move it there?" in moved
    assert HostSecrets.of("adlib").read() == {KEY: SECRET}
    assert CheckoutEnv(path=checkout / ".env.local").read() == {"AGENT_TIMEZONE": "UTC"}
    assert holding(checkout, SECRET) == []


def test_a_move_keeps_the_value_the_store_already_holds(
    checkout: Path, config: Path
) -> None:
    HostSecrets.of("adlib").write({KEY: "the host's own"})
    (checkout / ".env.local").write_text(f"{KEY}={SECRET}\n", encoding="utf-8")

    invoked(["gemini"], "y\nn\n")

    assert HostSecrets.of("adlib").read() == {KEY: "the host's own"}
    assert CheckoutEnv(path=checkout / ".env.local").read() == {}


def test_a_declined_move_leaves_both_files_alone(checkout: Path, config: Path) -> None:
    (checkout / ".env.local").write_text(f"{KEY}={SECRET}\n", encoding="utf-8")

    invoked(["gemini"], "n\n\n")

    assert CheckoutEnv(path=checkout / ".env.local").read() == {KEY: SECRET}
    assert not store_path(config).exists()


# -- the dashboard ---------------------------------------------------------------

BASE_URL = "http://127.0.0.1:8765"


def dashboard() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=create_dashboard(BASE_URL, [GEMINI, TIMEZONE])),
        base_url=BASE_URL,
    )


async def test_the_dashboard_writes_a_host_only_answer_to_the_store(
    checkout: Path, config: Path
) -> None:
    async with dashboard() as http:
        response = await http.post(
            "/api/wizard/gemini/run?scope=env",
            json={"answers": [{"key": KEY, "value": SECRET}]},
        )
        drawn = await http.get("/api/wizard?scope=env")

    assert response.json()["outcome"]["ok"]
    assert "host store" in response.json()["outcome"]["message"]
    assert HostSecrets.of("adlib").read() == {KEY: SECRET}
    assert holding(checkout, SECRET) == []
    view = WizardView.model_validate(drawn.json())
    [gemini] = [step for step in view.steps if step.slug == "gemini"]
    [timezone] = [step for step in view.steps if step.slug == "timezone"]
    assert gemini.standing.done
    assert "kept in host store" in gemini.standing.detail
    assert SECRET not in gemini.standing.detail
    assert "kept in .env.local" in timezone.standing.detail


async def test_the_dashboard_reports_a_host_only_key_left_in_env_local(
    checkout: Path, config: Path
) -> None:
    (checkout / ".env.local").write_text(f"{KEY}={SECRET}\n", encoding="utf-8")

    async with dashboard() as http:
        drawn = await http.get("/api/wizard?scope=env")

    view = WizardView.model_validate(drawn.json())
    [gemini] = [step for step in view.steps if step.slug == "gemini"]
    assert not gemini.standing.done
    assert "lup-launch run setup gemini" in gemini.standing.detail
