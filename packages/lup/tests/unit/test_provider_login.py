"""Every runtime answers where it keeps a login, in its own words.

The spellings are pinned here rather than left to the adapters alone because
the point of the value is that both runtimes have one: a runtime that grew a
config home without declaring it would leave an application reaching for a
literal again, which is exactly what the seam rule forbids above the adapter.
"""

import json
import time
from pathlib import Path

import pytest
import sh

from lup.providers.claude.harness import CLAUDE_DISPATCHER
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.providers.codex.harness import CODEX_DISPATCHER
from lup.providers.codex.login import CODEX_LOGIN
from lup.policy.dispatcher import DispatcherDeclaration
from lup.providers.login import ProviderLogin

RUNTIME_LOGINS = [
    (CLAUDE_LOGIN, "CLAUDE_CONFIG_DIR", ".credentials.json"),
    (CODEX_LOGIN, "CODEX_HOME", "auth.json"),
]


@pytest.mark.parametrize(
    ("login", "config_home_env", "credentials_file"),
    RUNTIME_LOGINS,
    ids=[login.config_home_env for login, _, _ in RUNTIME_LOGINS],
)
def test_each_runtime_spells_its_own_login_location(
    login: ProviderLogin, config_home_env: str, credentials_file: str
) -> None:
    assert login.config_home_env == config_home_env
    assert login.credentials_file == credentials_file


@pytest.mark.parametrize(
    "login", [CLAUDE_LOGIN, CODEX_LOGIN], ids=lambda login: login.config_home_env
)
def test_a_login_routes_a_home_and_finds_the_credential_inside_it(
    login: ProviderLogin, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()

    assert login.environment(home) == {login.config_home_env: str(home)}
    assert login.credentials_path(home).parent == home
    assert not login.logged_in(home)

    login.credentials_path(home).write_text("{}", encoding="utf-8")

    assert login.logged_in(home)


@pytest.mark.parametrize(
    ("declaration", "login"),
    [(CLAUDE_DISPATCHER, CLAUDE_LOGIN), (CODEX_DISPATCHER, CODEX_LOGIN)],
    ids=[CLAUDE_DISPATCHER.runtime_name, CODEX_DISPATCHER.runtime_name],
)
def test_a_dispatcher_takes_its_managed_root_from_the_login(
    declaration: DispatcherDeclaration, login: ProviderLogin
) -> None:
    """The hook dispatcher and the profile system name one environment.

    Derived rather than compared: the declaration reads the login, so this
    pins that it still does instead of guarding two literals against drift.
    """
    assert declaration.managed_root_env == login.config_home_env


def renewable(filter_text: str, credential: object, tmp_path: Path) -> bool:
    """Run one runtime's renewal test the way the entrypoint runs it."""
    written = tmp_path / "credential.json"
    written.write_text(json.dumps(credential), encoding="utf-8")
    try:
        sh.Command("jq")("-e", filter_text, str(written))
    except sh.ErrorReturnCode:
        return False
    return True


@pytest.mark.parametrize(
    ("deadline", "expected"),
    [(86_400_000, True), (-86_400_000, False)],
    ids=["renewable", "past renewing"],
)
def test_claude_reads_the_refresh_deadline_rather_than_the_access_one(
    deadline: int, expected: bool, tmp_path: Path
) -> None:
    """The distinction the whole field exists for, run through real `jq`.

    An access token expires hourly and renews itself, so a test reading that
    one would call a healthy login dead every hour and re-seed over it. The
    fixture holds an expired access token in both cases on purpose: only the
    refresh deadline moves the answer.
    """
    now = int(time.time() * 1000)
    credential = {
        "claudeAiOauth": {
            "expiresAt": now - 3_600_000,
            "refreshTokenExpiresAt": now + deadline,
        }
    }

    assert renewable(CLAUDE_LOGIN.renewable, credential, tmp_path) is expected


@pytest.mark.parametrize(
    "credential",
    [{}, {"mcpOAuth": {"some-server": {"accessToken": "x"}}}],
    ids=["empty object", "other credentials but no login"],
)
def test_a_file_holding_no_claude_login_is_not_a_renewable_one(
    credential: object, tmp_path: Path
) -> None:
    """A missing deadline must answer "no", not raise and not pass.

    `jq` compares null below every number, so an absent login reads as past
    renewing -- which is the answer wanted here, and worth pinning because a
    filter written with `//` or `?` would quietly answer the other way.
    """
    assert renewable(CLAUDE_LOGIN.renewable, credential, tmp_path) is False


def test_codex_declares_no_renewal_test_because_its_login_states_no_deadline() -> None:
    """Stated rather than left blank by omission.

    Codex's stored login carries `auth_mode`, its tokens, an account id and
    `last_refresh` -- when a renewal last succeeded, never when renewing stops
    working. Reading the `id_token`'s own `exp` in its place would be worse
    than declaring nothing: that hour passes while the login is still fine, so
    every launch past the first would re-seed a working credential.
    """
    assert CODEX_LOGIN.renewable == ""
