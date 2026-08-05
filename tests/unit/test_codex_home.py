"""Worktree-scoped Codex home selection and first-use initialization."""

from pathlib import Path

import pytest
import tomlkit
from tomlkit.items import Table

from lup.types import EnvVars
from lup_template.devtools.harness.codex_home import (
    CodexWorktreeHomeStore,
    select_codex_home,
)


ACCOUNT_CONFIG = """\
model = "gpt-personal"

[features]
hooks = true

[hooks]
PreToolUse = []

[hooks.state."lup@account:hooks/hooks.json:pre_tool_use:0:0"]
enabled = true

[marketplaces.account]
source_type = "local"
source = "/account"

[plugins."lup@account"]
enabled = true
"""

PROFILE_CONFIG = """\
model_reasoning_effort = "high"

[plugins."lup@account"]
enabled = true
"""


def test_worktree_home_is_stable_and_path_scoped(tmp_path: Path) -> None:
    store = CodexWorktreeHomeStore(
        account_home=tmp_path / "account",
        scoped_root=tmp_path / "scoped",
    )
    first = tmp_path / "tree" / "first"
    second = tmp_path / "tree" / "second"
    first.mkdir(parents=True)
    second.mkdir()

    assert store.home_for(first) == store.home_for(first)
    assert store.home_for(first) != store.home_for(second)
    assert store.home_for(first).name.startswith("first-")


def test_prepare_seeds_auth_and_sanitized_personal_settings(tmp_path: Path) -> None:
    account = tmp_path / "account"
    account.mkdir()
    auth = account / "auth.json"
    auth.write_text('{"token": "secret"}\n', encoding="utf-8")
    auth.chmod(0o600)
    (account / "config.toml").write_text(ACCOUNT_CONFIG, encoding="utf-8")
    (account / "review.config.toml").write_text(PROFILE_CONFIG, encoding="utf-8")
    worktree = tmp_path / "tree" / "dev"
    worktree.mkdir(parents=True)
    store = CodexWorktreeHomeStore(account, tmp_path / "scoped")

    scoped = store.prepare(worktree, profile="review")

    assert (scoped / "auth.json").read_bytes() == auth.read_bytes()
    assert (scoped / "auth.json").stat().st_mode & 0o777 == 0o600
    assert scoped.stat().st_mode & 0o777 == 0o700
    config = tomlkit.parse((scoped / "config.toml").read_text(encoding="utf-8"))
    assert config["model"] == "gpt-personal"
    assert config["features"]["hooks"] is True
    assert "marketplaces" not in config
    assert "plugins" not in config
    hooks = config.item("hooks")
    assert isinstance(hooks, Table)
    assert "PreToolUse" in hooks
    # Trust is seeded, unlike installed state. The runtime will not run a
    # plugin's hooks until they are reviewed, so a scoped home that dropped
    # this installs the policy plugin and then runs ungoverned — present,
    # never consulted, and silent about it.
    state = hooks.item("state")
    assert isinstance(state, Table)
    assert "lup@account:hooks/hooks.json:pre_tool_use:0:0" in state
    profile = tomlkit.parse((scoped / "review.config.toml").read_text(encoding="utf-8"))
    assert profile["model_reasoning_effort"] == "high"
    assert "plugins" not in profile


def test_prepare_preserves_scoped_state_after_first_use(tmp_path: Path) -> None:
    account = tmp_path / "account"
    account.mkdir()
    (account / "auth.json").write_text("account-auth", encoding="utf-8")
    (account / "config.toml").write_text(ACCOUNT_CONFIG, encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account, tmp_path / "scoped")
    scoped = store.prepare(worktree)
    (scoped / "auth.json").write_text("scoped-auth", encoding="utf-8")
    (scoped / "config.toml").write_text('model = "scoped"\n', encoding="utf-8")
    session = scoped / "sessions" / "saved.jsonl"
    session.parent.mkdir()
    session.write_text("saved\n", encoding="utf-8")
    (account / "auth.json").write_text("different-account-auth", encoding="utf-8")

    assert store.prepare(worktree) == scoped
    assert (scoped / "auth.json").read_text(encoding="utf-8") == "scoped-auth"
    assert (scoped / "config.toml").read_text(encoding="utf-8") == (
        'model = "scoped"\n'
    )
    assert session.read_text(encoding="utf-8") == "saved\n"


def test_explicit_home_and_environment_bypass_scoped_initialization(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(
        account_home=tmp_path / "account",
        scoped_root=tmp_path / "scoped",
    )
    configured = tmp_path / "configured"
    environment: EnvVars = {"CODEX_HOME": str(configured)}

    from_environment = select_codex_home(None, environment, worktree, store=store)
    explicit = select_codex_home(
        tmp_path / "explicit", environment, worktree, store=store
    )

    assert from_environment.path == configured
    assert from_environment.isolated is False
    assert explicit.path == tmp_path / "explicit"
    assert explicit.isolated is False
    assert not (tmp_path / "scoped").exists()


def test_default_selection_prepares_the_scoped_home(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(
        account_home=tmp_path / "account",
        scoped_root=tmp_path / "scoped",
    )

    selection = select_codex_home(None, {}, worktree, store=store)

    assert selection.path == store.home_for(worktree)
    assert selection.isolated is True
    assert selection.path.is_dir()


def test_profile_name_cannot_escape_the_scoped_home(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(
        account_home=tmp_path / "account",
        scoped_root=tmp_path / "scoped",
    )

    with pytest.raises(ValueError, match="invalid Codex profile name"):
        store.prepare(worktree, profile="../outside")
