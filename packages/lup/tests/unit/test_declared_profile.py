"""What an agent declaration leaves unset, the person's lup config answers.

``profile=`` names an account the way ``harness claude --profile`` does, so
one name opens the same account on Claude Code and on Codex; a model and an
effort left unnamed take the person's tier and effort before lup's own. These
pin each at the boundary a session opens through, and that a declaration's
own answer, or a session it runs inside, is never overruled by them.
"""

from pathlib import Path

import pytest
from pydantic import AnyHttpUrl

from lup.providers.claude import Claude, ClaudeCompatibleEndpoint
from lup.providers.claude.login import CLAUDE_CONFIG_DIR, CLAUDE_LOGIN
from lup.providers.claude.runtime import ClaudeSessionOpener
from lup.providers.codex import Codex
from lup.providers.codex.login import CODEX_HOME
from lup.providers.codex.runtime import CodexSessionOpener
from lup.providers.profile_tree import user_profile_directory
from lup.providers.profiles import DefaultHomeProfile, UnknownProfile
from lup.providers.user_config import UserConfigFile


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> UserConfigFile:
    """This test's person, found the way a session opening finds one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return UserConfigFile()


def writes(config: UserConfigFile, content: str) -> None:
    config.path().parent.mkdir(parents=True, exist_ok=True)
    config.path().write_text(content, encoding="utf-8")


def test_one_profile_name_is_one_account_on_both_runtimes(
    config: UserConfigFile, tmp_path: Path
) -> None:
    user_profile_directory(CLAUDE_LOGIN, config).add("work")
    work = config.profiles_root() / "work"

    claude = ClaudeSessionOpener(Claude(profile="work", cwd=tmp_path)).compiled()
    codex = CodexSessionOpener(Codex(profile="work", cwd=tmp_path)).compiled()

    assert claude.environment[CLAUDE_CONFIG_DIR] == str(work / "claude-config")
    assert codex.environment[CODEX_HOME] == str(work / "codex-home")


def test_a_named_profile_wins_over_a_home_the_environment_names(
    config: UserConfigFile, tmp_path: Path
) -> None:
    user_profile_directory(CLAUDE_LOGIN, config).add("work")

    compiled = ClaudeSessionOpener(
        Claude(profile="work", environment={CLAUDE_CONFIG_DIR: "/elsewhere"})
    ).compiled()

    assert compiled.environment[CLAUDE_CONFIG_DIR] != "/elsewhere"


def test_an_unknown_profile_is_refused_listing_the_known_ones(
    config: UserConfigFile, tmp_path: Path
) -> None:
    user_profile_directory(CLAUDE_LOGIN, config).add("work")

    for opener in [
        ClaudeSessionOpener(Claude(profile="ghost")),
        CodexSessionOpener(Codex(profile="ghost", cwd=tmp_path)),
    ]:
        with pytest.raises(
            UnknownProfile, match="unknown profile 'ghost'; known: work"
        ):
            opener.compiled()


def test_a_profile_at_claudes_default_home_stays_refused(
    config: UserConfigFile,
) -> None:
    home = config.profiles_root() / "main" / CLAUDE_LOGIN.home_subdir
    home.parent.mkdir(parents=True)
    home.symlink_to(CLAUDE_LOGIN.ambient_home, target_is_directory=True)

    with pytest.raises(DefaultHomeProfile, match="profile 'main' names the default"):
        ClaudeSessionOpener(Claude(profile="main")).compiled()


def test_naming_no_profile_stays_on_the_surrounding_account(
    config: UserConfigFile, tmp_path: Path
) -> None:
    """The person's selection is a launch's to apply, not a nested session's."""
    user_profile_directory(CLAUDE_LOGIN, config).add("work")
    assert config.load().profile == "work"

    claude = ClaudeSessionOpener(
        Claude(environment={CLAUDE_CONFIG_DIR: "/started/under"})
    ).compiled()
    codex = CodexSessionOpener(Codex(cwd=tmp_path)).compiled()

    assert claude.environment[CLAUDE_CONFIG_DIR] == "/started/under"
    assert CODEX_HOME not in codex.environment


def test_an_unnamed_model_runs_on_the_persons_tier(
    config: UserConfigFile, tmp_path: Path
) -> None:
    assert ClaudeSessionOpener(Claude()).compiled().model_id() == "opus"
    assert CodexSessionOpener(Codex(cwd=tmp_path)).compiled().model_id() == (
        "gpt-5.6-sol"
    )

    writes(config, 'tier = "balanced"\n')

    assert ClaudeSessionOpener(Claude()).compiled().model_id() == "sonnet"
    assert CodexSessionOpener(Codex(cwd=tmp_path)).compiled().model_id() == (
        "gpt-5.6-terra"
    )


def test_a_declared_model_or_endpoint_is_never_overruled_by_the_tier(
    config: UserConfigFile, tmp_path: Path
) -> None:
    writes(config, 'tier = "fast"\n')
    endpoint = ClaudeCompatibleEndpoint(base_url=AnyHttpUrl("http://localhost:8000/v1"))

    assert ClaudeSessionOpener(Claude(model="opus")).compiled().model_id() == "opus"
    assert ClaudeSessionOpener(Claude(endpoint=endpoint)).compiled().model is None
    assert (
        CodexSessionOpener(Codex(cwd=tmp_path, model="gpt-5.5")).compiled().model_id()
        == "gpt-5.5"
    )


def test_an_unnamed_effort_starts_from_the_persons_and_steps_down_to_the_models(
    config: UserConfigFile,
) -> None:
    writes(config, 'effort = "ultra"\n')

    assert ClaudeSessionOpener(Claude(model="opus")).compiled().effort == "ultra"
    assert (
        ClaudeSessionOpener(Claude(model="claude-opus-4-6")).compiled().effort == "max"
    )
    assert ClaudeSessionOpener(Claude(model="haiku")).compiled().effort is None
    assert (
        ClaudeSessionOpener(Claude(model="opus", effort="low")).compiled().effort
        == "low"
    )


def test_a_person_who_wrote_nothing_gets_lups_effort(config: UserConfigFile) -> None:
    assert ClaudeSessionOpener(Claude(model="opus")).compiled().effort == "xhigh"
    assert (
        ClaudeSessionOpener(Claude(model="claude-opus-4-6")).compiled().effort == "high"
    )
