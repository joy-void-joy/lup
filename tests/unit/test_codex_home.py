"""Worktree-scoped Codex home selection and first-use initialization."""

import json
import plistlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
import tomlkit
from tomlkit.items import Table

from lup.types import EnvVars
from lup.adapters.codex.home import (
    HOOKS_MANIFEST,
    CodexWorktreeHomeStore,
    declared_hook_records,
    login_state,
    select_codex_home,
    trust_project,
    untrusted_hooks,
)
from lup.adapters.codex.marketplace import CodexMarketplace
from lup.adapters.codex.theme import (
    TextMateStyle,
    TextMateThemeDocument,
    claude_daltonized_theme,
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

# Nanosecond precision, as the runtime actually writes it.
SEEDED_CREDENTIAL = (
    '{"auth_mode": "chatgpt", "tokens": {"refresh_token": "seeded"},'
    ' "last_refresh": "2026-07-23T22:11:59.592425868Z"}'
)
ROTATED_CREDENTIAL = (
    '{"auth_mode": "chatgpt", "tokens": {"refresh_token": "rotated"},'
    ' "last_refresh": "2026-08-05T19:23:03.507636146Z"}'
)


def credential_expiring(expiry: datetime) -> str:
    """An auth record whose access token states one expiry."""
    # Signed only so the token parses; the adapter never verifies it.
    token = jwt.encode({"exp": expiry}, key="x" * 32, algorithm="HS256")
    return json.dumps(
        {
            "auth_mode": "chatgpt",
            "tokens": {"access_token": token},
            "last_refresh": "2026-07-23T22:11:59.592425868Z",
        }
    )


def account_home_with(credential: str, root: Path) -> Path:
    """Build an account home holding one credential."""
    account = root / "account"
    account.mkdir()
    (account / "auth.json").write_text(credential, encoding="utf-8")
    return account


def test_worktree_home_is_stable_and_lives_in_the_checkout(tmp_path: Path) -> None:
    """Two checkouts are two homes, and each sits inside the checkout it serves.

    What a shared root needed a path digest to guarantee, distinct checkouts
    now give for free — so the assertion is where the home is, not what it is
    named."""
    store = CodexWorktreeHomeStore(account_home=tmp_path / "account")
    first = tmp_path / "tree" / "first"
    second = tmp_path / "tree" / "second"
    first.mkdir(parents=True)
    second.mkdir()

    assert store.home_for(first) == store.home_for(first)
    assert store.home_for(first) != store.home_for(second)
    assert store.home_for(first) == first / ".lup" / "codex-home"
    assert first in store.home_for(first).parents


def test_a_worktree_below_a_project_answers_with_the_project_home(
    tmp_path: Path,
) -> None:
    """One checkout keeps one home, reached from anywhere inside it.

    A session opened in a subdirectory must not open a second home beneath
    itself — the credential would be seeded twice and the two would rotate
    independently."""
    root = tmp_path / "project"
    (root / "src" / "deep").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[tool.lup]\nversion = "1.0.0"\n', encoding="utf-8"
    )
    store = CodexWorktreeHomeStore(account_home=tmp_path / "account")

    assert store.home_for(root / "src" / "deep") == root / ".lup" / "codex-home"
    assert store.home_for(root) == store.home_for(root / "src" / "deep")


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
    store = CodexWorktreeHomeStore(account)

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


def test_claude_daltonized_theme_uses_truecolor_palette() -> None:
    theme = claude_daltonized_theme()
    rules = {
        rule.name: rule.settings
        for rule in theme.document.settings
        if rule.name is not None
    }
    assert theme.document.settings[0].settings.foreground == "#F8F8F2"
    assert rules["Comments"].foreground == "#75715E"
    assert rules["Keywords and operators"].foreground == "#F92672"
    assert rules["Storage"].foreground == "#66D9EF"
    assert rules["Strings"].foreground == "#E6DB74"
    assert rules["Numbers and constants"].foreground == "#BE84FF"
    assert rules["Diff additions"] == TextMateStyle(
        background="#001B29", foreground="#51A0C8"
    )
    assert rules["Diff deletions"] == TextMateStyle(
        background="#3D0100", foreground="#DC5A5A"
    )


def test_prepare_generates_theme_without_selecting_it(tmp_path: Path) -> None:
    account = tmp_path / "account"
    account.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account)
    theme = claude_daltonized_theme()
    parsed_theme = TextMateThemeDocument.model_validate(
        plistlib.loads(theme.render().encode("utf-8"))
    )
    assert parsed_theme == theme.document

    scoped = store.prepare(worktree)
    generated = scoped / "themes" / "claude-daltonized.tmTheme"

    assert generated.read_text(encoding="utf-8") == theme.render()
    config = tomlkit.parse((scoped / "config.toml").read_text(encoding="utf-8"))
    assert "tui" not in config

    generated.write_text("stale", encoding="utf-8")
    store.prepare(worktree)

    assert generated.read_text(encoding="utf-8") == theme.render()


def test_prepare_preserves_scoped_state_after_first_use(tmp_path: Path) -> None:
    account = tmp_path / "account"
    account.mkdir()
    (account / "auth.json").write_text("account-auth", encoding="utf-8")
    (account / "config.toml").write_text(ACCOUNT_CONFIG, encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account)
    scoped = store.prepare(worktree)
    (scoped / "auth.json").write_text("scoped-auth", encoding="utf-8")
    (scoped / "config.toml").write_text('model = "scoped"\n', encoding="utf-8")
    session = scoped / "sessions" / "saved.jsonl"
    session.parent.mkdir()
    session.write_text("saved\n", encoding="utf-8")
    (account / "auth.json").write_text("different-account-auth", encoding="utf-8")

    assert store.prepare(worktree) == scoped
    assert (scoped / "auth.json").read_text(encoding="utf-8") == "scoped-auth"
    settings = tomlkit.parse((scoped / "config.toml").read_text(encoding="utf-8"))
    assert settings["model"] == "scoped"
    assert session.read_text(encoding="utf-8") == "saved\n"


def test_a_scoped_home_trusts_the_checkout_it_was_made_for(tmp_path: Path) -> None:
    """Untrusted, the runtime reads none of a project's own configuration.

    Which is where a generated tree declares its tool servers, so the gap
    shows up as a session with no instruments rather than as an error.
    """
    account = tmp_path / "account"
    account.mkdir()
    (account / "config.toml").write_text(ACCOUNT_CONFIG, encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    scoped = CodexWorktreeHomeStore(account).prepare(worktree)

    config = tomlkit.parse((scoped / "config.toml").read_text(encoding="utf-8"))
    projects = config.item("projects")
    assert isinstance(projects, Table)
    assert projects[str(worktree.resolve())]["trust_level"] == "trusted"
    assert config["model"] == "gpt-personal"


def test_a_home_made_before_the_trust_was_written_gets_it_on_next_use(
    tmp_path: Path,
) -> None:
    """A home that predates this is exactly the one silently serving nothing."""
    account = tmp_path / "account"
    account.mkdir()
    (account / "config.toml").write_text(ACCOUNT_CONFIG, encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account)
    scoped = store.prepare(worktree)
    (scoped / "config.toml").write_text('model = "scoped"\n', encoding="utf-8")

    store.prepare(worktree)

    config = tomlkit.parse((scoped / "config.toml").read_text(encoding="utf-8"))
    projects = config.item("projects")
    assert isinstance(projects, Table)
    assert str(worktree.resolve()) in projects


def test_a_trust_the_operator_already_recorded_is_left_alone(tmp_path: Path) -> None:
    """Their decision about their own checkout, whatever they decided."""
    account = tmp_path / "account"
    account.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    scoped = CodexWorktreeHomeStore(account).home_for(worktree)
    scoped.mkdir(parents=True)
    (scoped / "config.toml").write_text(
        f'[projects."{worktree.resolve()}"]\ntrust_level = "on-request"\n',
        encoding="utf-8",
    )

    assert not trust_project(scoped, worktree)
    config = tomlkit.parse((scoped / "config.toml").read_text(encoding="utf-8"))
    projects = config.item("projects")
    assert isinstance(projects, Table)
    assert projects[str(worktree.resolve())]["trust_level"] == "on-request"


def test_an_explicit_home_is_never_written_to(tmp_path: Path) -> None:
    """An operator's own home carries their decisions, not ours."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    explicit = tmp_path / "personal"
    explicit.mkdir()

    selection = select_codex_home(explicit, {}, worktree)

    assert selection.path == explicit
    assert not selection.isolated
    assert not (explicit / "config.toml").exists()


def test_explicit_home_and_environment_bypass_scoped_initialization(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account_home=tmp_path / "account")
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
    assert not (worktree / ".lup").exists()


def test_default_selection_prepares_the_scoped_home(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account_home=tmp_path / "account")

    selection = select_codex_home(None, {}, worktree, store=store)

    assert selection.path == store.home_for(worktree)
    assert selection.isolated is True
    assert selection.path.is_dir()


def test_a_rotated_account_login_reaches_a_stale_scoped_home(tmp_path: Path) -> None:
    account = account_home_with(ROTATED_CREDENTIAL, tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account)
    scoped = store.prepare(worktree)
    (scoped / "auth.json").write_text(SEEDED_CREDENTIAL, encoding="utf-8")

    assert store.prepare(worktree) == scoped
    assert (scoped / "auth.json").read_text(encoding="utf-8") == ROTATED_CREDENTIAL


def test_a_rotation_inside_a_scoped_home_returns_to_the_account(
    tmp_path: Path,
) -> None:
    account = account_home_with(SEEDED_CREDENTIAL, tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account)
    scoped = store.prepare(worktree)
    (scoped / "auth.json").write_text(ROTATED_CREDENTIAL, encoding="utf-8")

    assert store.publish(worktree) is True
    assert (account / "auth.json").read_text(encoding="utf-8") == ROTATED_CREDENTIAL


def test_publishing_an_unrotated_login_changes_nothing(tmp_path: Path) -> None:
    account = account_home_with(SEEDED_CREDENTIAL, tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account)
    store.prepare(worktree)

    assert store.publish(worktree) is False


def test_an_unreadable_credential_is_never_overwritten(tmp_path: Path) -> None:
    account = account_home_with("not-json", tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account)
    scoped = store.prepare(worktree)
    (scoped / "auth.json").write_text(ROTATED_CREDENTIAL, encoding="utf-8")

    assert store.prepare(worktree) == scoped
    assert (scoped / "auth.json").read_text(encoding="utf-8") == ROTATED_CREDENTIAL


def test_a_home_with_no_record_holds_no_login(tmp_path: Path) -> None:
    assert login_state(tmp_path).usable_at(datetime.now(UTC)) is False


def test_a_login_is_usable_until_the_issuer_says_otherwise(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    expiry = now + timedelta(days=5)
    (tmp_path / "auth.json").write_text(credential_expiring(expiry), encoding="utf-8")

    state = login_state(tmp_path)

    assert state.present is True
    assert state.expires_at == expiry.replace(microsecond=0)
    assert state.usable_at(now) is True
    assert state.usable_at(expiry + timedelta(seconds=1)) is False


def test_a_lapsed_login_is_caught_before_a_session_starts(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    lapsed = credential_expiring(now - timedelta(days=7))
    (tmp_path / "auth.json").write_text(lapsed, encoding="utf-8")

    assert login_state(tmp_path).usable_at(now) is False


def test_a_record_stating_no_expiry_is_left_to_the_runtime(tmp_path: Path) -> None:
    (tmp_path / "auth.json").write_text(SEEDED_CREDENTIAL, encoding="utf-8")

    assert login_state(tmp_path).usable_at(datetime.now(UTC)) is True


def test_profile_name_cannot_escape_the_scoped_home(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account_home=tmp_path / "account")

    with pytest.raises(ValueError, match="invalid Codex profile name"):
        store.prepare(worktree, profile="../outside")


def plugin_declaring(root: Path, events: dict[str, int]) -> CodexMarketplace:
    """A plugin whose manifest declares one matcher per named event.

    The count is how many hooks that matcher carries, because a record names
    the hook's place inside the event rather than the event alone.
    """
    manifest = root / HOOKS_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "hooks": {
                    event: [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"type": "command", "command": "policy.py"}
                                for _ in range(count)
                            ],
                        }
                    ]
                    for event, count in events.items()
                }
            }
        ),
        encoding="utf-8",
    )
    return CodexMarketplace(name="proj", plugin="lup", source=root)


def home_trusting(root: Path, records: dict[str, bool]) -> Path:
    """A Codex home whose config records trust the way the runtime writes it."""
    root.mkdir(parents=True, exist_ok=True)
    document = tomlkit.document()
    state = tomlkit.table(is_super_table=True)
    for record, enabled in records.items():
        entry = tomlkit.table()
        entry["trusted_hash"] = "sha256:whatever-this-was-when-reviewed"
        entry["enabled"] = enabled
        state[record] = entry
    hooks = tomlkit.table()
    hooks["state"] = state
    document["hooks"] = hooks
    (root / "config.toml").write_text(tomlkit.dumps(document), encoding="utf-8")
    return root


def test_a_home_trusting_every_declared_hook_would_run_them_all(
    tmp_path: Path,
) -> None:
    """The governed reading, so the refusal cannot pass by being unable to fail."""
    marketplace = plugin_declaring(
        tmp_path / "plugin", {"PreToolUse": 1, "PermissionRequest": 1}
    )
    home = home_trusting(
        tmp_path / "home",
        {
            "lup@proj:hooks/hooks.json:pre_tool_use:0:0": True,
            "lup@proj:hooks/hooks.json:permission_request:0:0": True,
        },
    )

    assert untrusted_hooks(home, marketplace) == []


def test_a_trusted_hook_without_an_enabled_override_uses_the_native_default(
    tmp_path: Path,
) -> None:
    marketplace = plugin_declaring(tmp_path / "plugin", {"PreToolUse": 1})
    record = "lup@proj:hooks/hooks.json:pre_tool_use:0:0"
    home = home_trusting(tmp_path / "home", {record: True})
    document = tomlkit.parse((home / "config.toml").read_text(encoding="utf-8"))
    del document["hooks"]["state"][record]["enabled"]
    (home / "config.toml").write_text(tomlkit.dumps(document), encoding="utf-8")

    assert untrusted_hooks(home, marketplace) == []


def test_a_home_trusting_one_event_of_three_names_the_other_two(
    tmp_path: Path,
) -> None:
    """The measured case, and why a plugin being installed proves nothing.

    An operator's home carried trust for `pre_tool_use` alone. A shell command
    is gated by `permission_request`, so the session ran the command the
    policy refuses — while carrying that policy, enabled, and reading exactly
    like a governed session.
    """
    marketplace = plugin_declaring(
        tmp_path / "plugin",
        {"PreToolUse": 1, "PostToolUse": 1, "PermissionRequest": 1},
    )
    home = home_trusting(
        tmp_path / "home", {"lup@proj:hooks/hooks.json:pre_tool_use:0:0": True}
    )

    assert untrusted_hooks(home, marketplace) == [
        "lup@proj:hooks/hooks.json:post_tool_use:0:0",
        "lup@proj:hooks/hooks.json:permission_request:0:0",
    ]


def test_a_hook_trusted_and_then_disabled_is_one_that_will_not_run(
    tmp_path: Path,
) -> None:
    """Trust and enablement are two records, and either one off is a skip."""
    marketplace = plugin_declaring(tmp_path / "plugin", {"PreToolUse": 1})
    home = home_trusting(
        tmp_path / "home", {"lup@proj:hooks/hooks.json:pre_tool_use:0:0": False}
    )

    assert untrusted_hooks(home, marketplace) == [
        "lup@proj:hooks/hooks.json:pre_tool_use:0:0"
    ]


def test_every_hook_of_a_matcher_is_asked_about_separately(tmp_path: Path) -> None:
    """A record names the hook's place, so a matcher carrying two needs two."""
    marketplace = plugin_declaring(tmp_path / "plugin", {"PreToolUse": 2})
    home = home_trusting(
        tmp_path / "home", {"lup@proj:hooks/hooks.json:pre_tool_use:0:0": True}
    )

    assert untrusted_hooks(home, marketplace) == [
        "lup@proj:hooks/hooks.json:pre_tool_use:0:1"
    ]


def test_a_home_that_has_recorded_nothing_trusts_nothing(tmp_path: Path) -> None:
    """A scoped home on its first use, which is where this was found."""
    marketplace = plugin_declaring(tmp_path / "plugin", {"PreToolUse": 1})

    assert untrusted_hooks(tmp_path / "empty", marketplace) == [
        "lup@proj:hooks/hooks.json:pre_tool_use:0:0"
    ]


def test_an_event_this_cannot_ask_about_is_refused_rather_than_skipped(
    tmp_path: Path,
) -> None:
    """An event added to the manifest and unknown here must not read as trusted.

    What this check exists to close is a hook that does not run while nothing
    says so, and quietly omitting an unrecognized event from the question
    would rebuild exactly that, one layer up.
    """
    marketplace = plugin_declaring(tmp_path / "plugin", {"SessionStart": 1})

    with pytest.raises(ValueError, match="cannot ask about"):
        untrusted_hooks(tmp_path / "home", marketplace)


def test_a_plugin_declaring_no_hooks_has_nothing_to_trust(tmp_path: Path) -> None:
    """A project whose plugin carries only skills is not refused over hooks."""
    root = tmp_path / "plugin"
    root.mkdir()

    marketplace = CodexMarketplace(name="proj", plugin="lup", source=root)

    assert declared_hook_records(marketplace) == []
    assert untrusted_hooks(tmp_path / "home", marketplace) == []
