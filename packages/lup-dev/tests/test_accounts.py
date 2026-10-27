"""Accounts: listed by the logins they hold, and logged out by emptying each login in place."""

import os
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.accounts import AccountError, Accounts, RuntimeLogin
from lup_dev.adapters import claude, codex
from lup_dev.layout import AccountsLayout

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def placed(directory: Path) -> Path:
    """Where a made-up runtime keeps its login in a home of its own."""
    return directory / "login.json"


def accounts(tmp_path: Path) -> Accounts:
    """Accounts under the test's directory, for two made-up runtimes."""
    return Accounts(
        layout=AccountsLayout(home=tmp_path / "accounts"),
        runtimes=[
            RuntimeLogin(name="first", login=placed),
            RuntimeLogin(name="second", login=placed),
        ],
    )


def signed_in(kept: Accounts, name: str, runtime: str) -> Path:
    """Write a login for `runtime` in the account `name`, mode 600, as a sign-in does; return where."""
    login = placed(kept.layout.account(name).runtime(runtime))
    login.parent.mkdir(parents=True, exist_ok=True)
    login.write_text('{"token": "made up"}')
    login.chmod(0o600)
    return login


def test_default_is_listed_with_no_account_made_yet(tmp_path: Path) -> None:
    assert accounts(tmp_path).listed() == ["default: no login"]


def test_each_account_is_listed_by_the_logins_it_holds(tmp_path: Path) -> None:
    kept = accounts(tmp_path)
    signed_in(kept, "work", "first")
    signed_in(kept, "home", "first")
    signed_in(kept, "home", "second")
    signed_in(kept, "default", "second")
    (kept.layout.home / ".hidden").mkdir()
    (kept.layout.home / "stray.txt").write_text("not an account")
    assert kept.listed() == [
        "default: a login for `second`, none for `first`",
        "home: a login for `first` and `second`",
        "work: a login for `first`, none for `second`",
    ]


def test_an_empty_login_file_is_no_login(tmp_path: Path) -> None:
    kept = accounts(tmp_path)
    signed_in(kept, "work", "first").write_bytes(b"")
    assert kept.listed() == ["default: no login", "work: no login"]


def test_logout_empties_each_login_in_place_so_a_mount_of_it_sees_it_emptied(
    tmp_path: Path,
) -> None:
    kept = accounts(tmp_path)
    first = signed_in(kept, "work", "first")
    second = signed_in(kept, "work", "second")
    # A hard link shares the file as a single-file mount does: removing the
    # account's file would leave it holding the login.
    mounted = tmp_path / "room-home" / "login.json"
    mounted.parent.mkdir()
    os.link(first, mounted)

    said = kept.logout("work")

    assert said == [
        (
            f"Logged `work` out of `first`: its login at {first} is emptied, so a "
            "launch on the account signs in again. It isn't revoked with the provider."
        ),
        (
            f"Logged `work` out of `second`: its login at {second} is emptied, so a "
            "launch on the account signs in again. It isn't revoked with the provider."
        ),
    ]
    assert first.read_bytes() == b""
    assert mounted.read_bytes() == b""
    assert first.stat().st_ino == mounted.stat().st_ino
    assert first.stat().st_mode & 0o777 == 0o600
    assert kept.listed() == ["default: no login", "work: no login"]


def test_logout_of_one_runtime_leaves_the_others(tmp_path: Path) -> None:
    kept = accounts(tmp_path)
    signed_in(kept, "work", "first")
    second = signed_in(kept, "work", "second")
    assert kept.logout("work", "first")[0].startswith("Logged `work` out of `first`")
    assert second.read_text() == '{"token": "made up"}'
    assert kept.logout("work", "first") == [
        "`work` holds no login for `first`: nothing to log out."
    ]


def test_logout_of_an_account_holding_nothing_says_so(tmp_path: Path) -> None:
    assert accounts(tmp_path).logout("spare") == [
        "`spare` holds no login for `first` and `second`: nothing to log out."
    ]


def test_a_malformed_account_or_an_unknown_runtime_is_refused(tmp_path: Path) -> None:
    kept = accounts(tmp_path)
    with pytest.raises(AccountError, match="can't name a profile or an account"):
        kept.logout("../elsewhere")
    with pytest.raises(AccountError) as unknown:
        kept.logout("work", "third")
    assert str(unknown.value) == (
        "no runtime is called `third`: the runtimes are `first` and `second`"
    )


def test_each_adapter_places_its_login_as_its_sign_in_writes_it(tmp_path: Path) -> None:
    assert claude.adapter().login(tmp_path) == tmp_path / ".credentials.json"
    assert codex.adapter().login(tmp_path) == tmp_path / "auth.json"


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """lup's data under the test's directory, outside any runtime's session; return where accounts are kept."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    return tmp_path / "data" / "lup" / "accounts"


def test_the_commands_list_and_log_out_each_runtime_s_login(data: Path) -> None:
    login = data / "work" / "claude" / ".credentials.json"
    login.parent.mkdir(parents=True)
    login.write_text("{}")

    listed = runner.invoke(cli.app, ["account", "list"])
    assert listed.exit_code == 0, listed.output
    assert listed.output.splitlines() == [
        "default: no login",
        "work: a login for `claude`, none for `codex`",
    ]

    out = runner.invoke(cli.app, ["account", "logout", "work", "claude"])
    assert out.exit_code == 0, out.output
    assert login.read_bytes() == b""


def test_logout_is_refused_inside_an_agent_s_session(
    data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    login = data / "work" / "codex" / "auth.json"
    login.parent.mkdir(parents=True)
    login.write_text("{}")
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    result = runner.invoke(cli.app, ["account", "logout", "work"])
    assert isinstance(result.exception, AccountError)
    assert login.read_text() == "{}"
