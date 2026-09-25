"""A declared mode opens a session on its own terms, and a normal launch on the project's.

Driven through both launchers with this project's real declaration, up to
the argv each would open, so what is pinned is what a session would receive:
the plugin it runs on, what it is told, the posture each runtime is handed,
and what its environment says to the guards. The committed trees are never
the variant's to change, and the tests hold that too.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest
import sh
import typer

import lup.devtools.harness.launch as launch
from lup.devtools.harness.modes import (
    MODE_VARIABLE,
    claude_variant,
    codex_variant,
    compiled_mode,
    variant_of,
)
from lup.devtools.harness.posture import LaunchOverrides, SessionSettings
from lup.devtools.dev.git_guards import STANDDOWN_VARIABLE
from lup.harness.models import Harness, PromptDocument, SessionMode, TextPart
from lup.harness.posture import LaunchPosture
from lup_template.harness.catalog import portable_harness

FREE = SessionMode(
    name="free",
    description="Making something where the conventions are not the point.",
    hooks=False,
    scan_rules=False,
    posture=LaunchPosture.unattended(),
    git_guards=False,
    instructions="Commit by path; a normal session cleans up afterwards.",
)


@pytest.fixture(scope="module")
def harness() -> Harness:
    return portable_harness()


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout with nothing generated in it, and a home the variants go under."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return checkout


class Opened:
    """What one launch handed the argv builder: its words and its keywords."""

    def __init__(self) -> None:
        self.arguments: list[str] = []
        self.plugin: object = None
        # lup: ignore[dict-str-payload] — the session's environment map
        self.environment: dict[str, str] = {}
        self.read_only: dict[Path, str] = {}
        self.scope: object = None

    def record(self, *args: object, **kwargs: object) -> list[str]:
        """Stand in for ``session_argv``, keeping what a session would have got."""
        arguments, plugin, environment = args[1], args[3], args[7]
        assert isinstance(arguments, list) and isinstance(environment, dict)
        self.arguments = [str(word) for word in arguments]
        self.plugin = plugin
        self.environment = {str(key): str(value) for key, value in environment.items()}
        read_only = kwargs.get("read_only", {})
        assert isinstance(read_only, dict)
        self.read_only = {Path(host): str(inside) for host, inside in read_only.items()}
        self.scope = kwargs.get("state_scope")
        return ["true"]


def composed(harness: Harness) -> Mock:
    composition = Mock()
    composition.recipe.source = harness
    return composition


def quiet_launch(root: Path, monkeypatch: pytest.MonkeyPatch, opened: Opened) -> None:
    """Everything both launchers do that is not the subject, stood in for."""
    monkeypatch.setattr(launch, "ready_to_open", lambda *a, **k: launch.LaunchOpening())
    monkeypatch.setattr(launch, "project_root", lambda: root)
    monkeypatch.setattr(launch, "ambient_config_home", lambda *a, **k: root)
    monkeypatch.setattr(launch, "session_argv", opened.record)
    monkeypatch.setattr(launch, "session_defaults", lambda: {})
    monkeypatch.setattr(launch, "accessible_roots", lambda: [])
    monkeypatch.setattr(launch, "apply_sandbox_environment", lambda *a, **k: None)
    monkeypatch.setattr(launch, "start_harness_transcript", lambda *a, **k: Mock())
    monkeypatch.setattr(launch, "ClaudeTranscripts", lambda _home: Mock())
    monkeypatch.setattr(launch, "CodexTranscripts", lambda _home: Mock())
    monkeypatch.setattr(launch, "CodexWorktreeHomeStore", lambda: Mock())
    monkeypatch.setattr(
        launch,
        "select_codex_home",
        lambda *args: Mock(path=root / "codex-home", isolated=False),
    )
    monkeypatch.setattr(sh, "Command", lambda _name: lambda *a, **k: None)


def opened_claude(
    harness: Harness,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: SessionMode | None,
) -> Opened:
    opened = Opened()
    quiet_launch(root, monkeypatch, opened)
    profiles = Mock()
    profiles.launch_home.return_value = None
    launch.launch_claude(
        composed(harness), [], profiles, None, None, False, session_mode=mode
    )
    return opened


def opened_codex(
    harness: Harness,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: SessionMode | None,
) -> Opened:
    opened = Opened()
    quiet_launch(root, monkeypatch, opened)
    launch.launch_codex(
        composed(harness), [], None, None, None, False, False, session_mode=mode
    )
    return opened


def words_after(arguments: list[str], flag: str) -> list[str]:
    """Every value a repeated flag carried, in order."""
    return [arguments[at + 1] for at, word in enumerate(arguments) if word == flag]


def test_the_free_mode_opens_claude_on_a_variant_without_hooks(
    harness: Harness, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = opened_claude(harness, root, monkeypatch, FREE)

    variant = Path(words_after(opened.arguments, "--plugin-dir")[0])
    assert root not in variant.parents
    assert (variant / ".claude-plugin" / "plugin.json").is_file()
    assert not (variant / "hooks").exists()
    assert getattr(opened.plugin, "hooks") is None
    assert opened.read_only[variant] == variant.as_posix()


def test_the_free_mode_tells_claude_its_name_and_posture(
    harness: Harness, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = opened_claude(harness, root, monkeypatch, FREE)

    assert words_after(opened.arguments, "--permission-mode") == ["auto"]
    [line] = words_after(opened.arguments, "--append-system-prompt")
    assert line.startswith("This session was launched in the `free` mode:")
    assert "Commit by path" in line
    assert opened.environment[MODE_VARIABLE] == "free"
    assert opened.environment[STANDDOWN_VARIABLE] == "off"


def test_the_free_mode_tells_codex_its_name_and_posture(
    harness: Harness, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = opened_codex(harness, root, monkeypatch, FREE)

    configured = words_after(opened.arguments, "-c")
    assert words_after(opened.arguments, "--ask-for-approval") == ["on-request"]
    assert 'approvals_reviewer="auto_review"' in configured
    assert words_after(opened.arguments, "--sandbox") == ["danger-full-access"]
    [instructions] = [
        value for value in configured if value.startswith("developer_instructions=")
    ]
    assert "`free` mode" in instructions
    assert opened.environment[MODE_VARIABLE] == "free"
    assert opened.environment[STANDDOWN_VARIABLE] == "off"


def test_the_free_mode_installs_codex_from_a_variant_into_its_own_home(
    harness: Harness, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = opened_codex(harness, root, monkeypatch, FREE)

    [variant] = list(opened.read_only)
    plugin = variant / ".codex" / "plugins" / harness.plugins[0].name
    assert (plugin / ".codex-plugin" / "plugin.json").is_file()
    assert not (plugin / "hooks").exists()
    assert "-mode-" in getattr(opened.scope, "key")


def test_the_default_launch_keeps_the_full_policy(
    harness: Harness, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude = opened_claude(harness, root, monkeypatch, None)
    codex = opened_codex(harness, root, monkeypatch, None)

    assert words_after(claude.arguments, "--plugin-dir")[0] == str(
        root / ".claude" / "plugins" / harness.plugins[0].name
    )
    assert getattr(claude.plugin, "hooks") is not None
    assert getattr(codex.plugin, "hooks") is not None
    for opened in (claude, codex):
        assert opened.read_only == {}
        assert MODE_VARIABLE not in opened.environment
        assert STANDDOWN_VARIABLE not in opened.environment
    assert "--permission-mode" not in claude.arguments
    assert "--append-system-prompt" not in claude.arguments
    assert not any(
        value.startswith(("approvals_reviewer=", "developer_instructions="))
        for value in words_after(codex.arguments, "-c")
    )


def test_a_mode_compiles_without_touching_the_committed_trees(
    harness: Harness, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The variant lives outside the checkout, and is reused rather than rewritten."""
    first = compiled_mode(claude_variant, harness, FREE, root)
    again = compiled_mode(claude_variant, harness, FREE, root)

    assert list(root.iterdir()) == []
    assert first.plugin is not None and first.plugin == again.plugin
    assert root not in first.plugin.parents


def test_a_mode_keeping_its_hooks_opens_on_the_committed_plugin(
    harness: Harness, root: Path
) -> None:
    gated = SessionMode(name="gated", description="A named normal session.")

    assert variant_of(harness, gated) == harness
    assert compiled_mode(claude_variant, harness, gated, root).plugin is None
    assert compiled_mode(codex_variant, harness, gated, root).plugin is None


GUIDED = SessionMode(
    name="guided",
    description="A session told something else first.",
    guidance=PromptDocument(
        parts=[TextPart(text="# Guided\n\nMake the piece.\n")],
        source="tests/unit/test_launch_modes.py",
    ),
)


def test_a_mode_guidance_is_mounted_over_each_runtime_committed_document(
    harness: Harness, root: Path
) -> None:
    claude = compiled_mode(claude_variant, harness, GUIDED, root)
    codex = compiled_mode(codex_variant, harness, GUIDED, root)

    [(claude_file, claude_target)] = claude.overlays.items()
    [(codex_file, codex_target)] = codex.overlays.items()
    assert claude_target == (root / ".claude" / "CLAUDE.md").as_posix()
    assert codex_target == (root / "AGENTS.md").as_posix()
    for rendered in (claude_file, codex_file):
        assert root not in rendered.parents
        assert "Make the piece." in rendered.read_text(encoding="utf-8")
    assert claude.plugin is None and codex.plugin is None


def test_a_mode_guidance_names_where_it_is_declared() -> None:
    """A rendered file names its declaring module, so the declaration asks for one."""
    with pytest.raises(ValueError, match="names the module declaring it"):
        SessionMode(
            name="guided",
            description="A session told something else first.",
            guidance=PromptDocument(parts=[TextPart(text="Make the piece.")]),
        )


def test_a_mode_without_guidance_keeps_the_committed_document(
    harness: Harness, root: Path
) -> None:
    assert compiled_mode(claude_variant, harness, FREE, root).overlays == {}
    assert compiled_mode(codex_variant, harness, FREE, root).overlays == {}


def test_a_mode_guidance_is_held_to_the_budget(harness: Harness, root: Path) -> None:
    """At declaration, where the prose is measured, and at launch, where it is rendered."""
    oversized = PromptDocument(
        parts=[TextPart(text="x" * 40_000)], source="tests/unit/test_launch_modes.py"
    )

    with pytest.raises(ValueError, match="the guided mode's guidance is"):
        Harness(
            generator_version="0",
            plugins=[],
            guidance=PromptDocument(parts=[]),
            modes=[GUIDED.model_copy(update={"guidance": oversized})],
        )
    with pytest.raises(typer.BadParameter, match="--mode guided: rendered guidance"):
        compiled_mode(
            claude_variant,
            harness,
            GUIDED.model_copy(update={"guidance": oversized}),
            root,
        )


def test_a_flag_outranks_the_mode_and_the_mode_the_machine(harness: Harness) -> None:
    machine = SessionSettings.resolved(harness, {"permission_mode": "default"})
    moded = SessionSettings.resolved(
        harness, {"permission_mode": "default"}, LaunchOverrides(), FREE
    )
    flagged = SessionSettings.resolved(
        harness,
        {"permission_mode": "default"},
        LaunchOverrides(permission_mode="plan", approvals_reviewer="user"),
        FREE,
    )

    assert machine.permission_mode is not None
    assert (machine.permission_mode.value, machine.permission_mode.origin) == (
        "default",
        "machine",
    )
    assert moded.permission_mode is not None and moded.approvals_reviewer is not None
    assert moded.permission_mode.origin == "mode"
    assert moded.approvals_reviewer.value == "auto_review"
    assert (
        flagged.permission_mode is not None and flagged.approvals_reviewer is not None
    )
    assert flagged.permission_mode.value == "plan"
    assert flagged.approvals_reviewer.origin == "flag"


def test_the_free_mode_is_refused_on_the_host(
    harness: Harness, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every knob it turns off is the container's to stand in for."""
    opened = Opened()
    quiet_launch(root, monkeypatch, opened)

    with pytest.raises(typer.BadParameter, match="--sandbox outer"):
        launch.launch_claude(
            composed(harness),
            [],
            Mock(),
            None,
            None,
            False,
            sandbox=launch.LaunchSandbox.INNER,
            session_mode=FREE,
        )
    assert opened.arguments == []
