"""Who a launched session is on its repository's roster, and what it is called.

Two facts with different standing. The **id** is the launcher's claim: it is
minted where both runtimes pass through and exported into the environment the
CLI is started with, so the session's tool server and its hooks — separate
processes with no channel between them — answer to one address rather than to
one each. The **name** is a display detail, and only one runtime has anywhere
to put it.

That asymmetry is the point of the split rather than a gap in it. What a peer
is addressed by lives in lup's own `names.jsonl`, so a runtime with no
launch-time name flag loses nothing: the roster answers to the same name on
both, and renaming goes through the same command.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

import lup.devtools.harness.launch as launch
from lup.coordination.identity import MEMBER_ENV


def composition() -> Mock:
    """A composition carrying the one plugin each launcher reads first."""
    plugin = Mock()
    plugin.name = "lup"
    plugin.marketplace = "test"
    built = Mock()
    built.recipe.source.plugins = [plugin]
    return built


@pytest.fixture
def uncontained(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything an uncontained `session_argv` reaches that is not its subject."""
    monkeypatch.setattr(launch, "accessible_roots", lambda _told: [])
    monkeypatch.setattr(launch, "settle_boundary", lambda *a, **k: None)
    monkeypatch.setattr(launch, "say_opening", lambda *a, **k: None)


def opened(environment: dict[str, str], tmp_path: Path) -> list[str]:
    """Build the argv for one uncontained session against this environment."""
    return launch.session_argv(
        "claude",
        ["--model", "opus"],
        composition(),
        Mock(),
        tmp_path,
        Mock(),
        launch.LaunchSandbox.INNER,
        environment,
    )


@pytest.mark.usefixtures("uncontained")
def test_a_launched_session_is_given_a_member_id(tmp_path: Path) -> None:
    """The launcher's claim, in the environment the CLI is started with.

    `sh` is handed this same dictionary as the child's environment, so a value
    here is what the session's tool server and hooks read — which is what lets
    them agree on one address without talking to each other.
    """
    environment: dict[str, str] = {}

    argv = opened(environment, tmp_path)

    assert argv == ["claude", "--model", "opus"]
    assert environment[MEMBER_ENV]


@pytest.mark.usefixtures("uncontained")
def test_two_launches_are_two_members(tmp_path: Path) -> None:
    """Two sessions in one worktree are two peers, which is the case the id holds.

    The worktree names them and does not identify them: a derived id would
    make these one member, and one of them would read the other's inbox.
    """
    first: dict[str, str] = {}
    second: dict[str, str] = {}

    opened(first, tmp_path)
    opened(second, tmp_path)

    assert first[MEMBER_ENV] != second[MEMBER_ENV]


@pytest.mark.usefixtures("uncontained")
def test_an_operator_s_own_address_is_not_handed_to_what_they_launch(
    tmp_path: Path,
) -> None:
    """An inherited value is replaced rather than respected.

    The variable means "a launcher minted this and can prove it". An operator
    who happened to have it exported would otherwise hand their own roster
    address to every session they start, and two peers would answer to one id
    — the one thing a durable id exists to rule out.
    """
    environment = {MEMBER_ENV: "the-operators-own-address"}

    opened(environment, tmp_path)

    assert environment[MEMBER_ENV] != "the-operators-own-address"


def test_the_runtime_display_name_follows_the_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the runtime shows agrees with what the roster answers to.

    A person watching several sessions is distinguishing between checkouts, so
    the worktree is the name — the same one `derived_cli_name` puts on the
    roster for a session nobody renamed.
    """
    worktree = tmp_path / "feat-coordination"
    worktree.mkdir()
    captured: list[list[str]] = []  # lup: ignore[empty-collection] — argv record

    launched(worktree, monkeypatch, captured, extra=[])

    assert "--name" in captured[0]
    assert captured[0][captured[0].index("--name") + 1] == "feat-coordination"


def test_a_caller_who_named_their_own_session_still_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The derived name is a default, and defaults come before what was asked for.

    Both spellings reach the runtime, and the later one is the caller's.
    """
    worktree = tmp_path / "feat-coordination"
    worktree.mkdir()
    captured: list[list[str]] = []  # lup: ignore[empty-collection] — argv record

    launched(worktree, monkeypatch, captured, extra=["--name", "the-one-i-meant"])

    argv = captured[0]
    assert argv.index("the-one-i-meant") > argv.index("feat-coordination")


def launched(
    worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    captured: list[list[str]],
    extra: list[str],
) -> None:
    """Run `launch_claude` far enough to read the argv it built, and no further."""
    import sh

    profiles = Mock()
    profiles.launch_home.return_value = None
    monkeypatch.setattr(launch, "ready_to_open", lambda *a, **k: launch.LaunchOpening())
    monkeypatch.setattr(launch, "project_root", lambda: worktree)
    monkeypatch.setattr(launch, "ambient_config_home", lambda *a, **k: worktree)
    monkeypatch.setattr(
        launch,
        "session_argv",
        lambda name, arguments, *a, **k: captured.append(arguments) or [name],
    )
    monkeypatch.setattr(
        launch,
        "claude_sandbox_arguments",
        lambda _plugin, sandbox=launch.LaunchSandbox.INNER, accessible=[]: [],
    )
    monkeypatch.setattr(launch, "non_interactive_environment", lambda _env: {})
    monkeypatch.setattr(
        launch, "apply_sandbox_environment", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(launch, "ClaudeTranscripts", lambda _home: Mock())
    monkeypatch.setattr(launch, "accessible_roots", lambda *a: [])
    monkeypatch.setattr(
        launch, "start_harness_transcript", lambda *args, **kwargs: Mock()
    )
    monkeypatch.setattr(sh, "Command", lambda _name: lambda *args, **kwargs: None)

    launch.launch_claude(composition(), extra, profiles, None, None, False)
