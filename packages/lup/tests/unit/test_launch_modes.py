"""Selecting an application-declared launch mode out of a passthrough vector."""

from pathlib import Path

import pytest
import typer

from lup.devtools.harness.composition import NativeTargets
from lup.devtools.harness.launch import LaunchMode, extract_launch_mode


def mode(name: str) -> LaunchMode:
    """A mode with no tree behind it; selection never builds one."""
    return LaunchMode(
        name=name,
        help=f"open a {name} session",
        targets=NativeTargets(builders={}),
    )


MODES = [mode("syra"), mode("audit")]


def test_selects_the_named_mode_and_takes_its_flag_out() -> None:
    selection = extract_launch_mode(MODES, ["--syra", "--verbose"])
    assert selection.mode is not None
    assert selection.mode.name == "syra"
    assert selection.arguments == ["--verbose"]


def test_leaves_every_other_word_in_order() -> None:
    """The rest is the caller's own command line and reaches the CLI untouched."""
    selection = extract_launch_mode(MODES, ["-p", "work", "--syra", "--model", "x"])
    assert selection.arguments == ["-p", "work", "--model", "x"]


def test_no_flag_selects_no_mode() -> None:
    selection = extract_launch_mode(MODES, ["--resume"])
    assert selection.mode is None
    assert selection.arguments == ["--resume"]


def test_two_modes_at_once_is_refused_rather_than_ordered() -> None:
    with pytest.raises(typer.BadParameter):
        extract_launch_mode(MODES, ["--syra", "--audit"])


def test_a_project_declaring_none_passes_everything_through() -> None:
    selection = extract_launch_mode([], ["--syra"])
    assert selection.mode is None
    assert selection.arguments == ["--syra"]


def test_a_mode_carries_its_model_and_record_root() -> None:
    """What the launchers read off a mode, as a declaration rather than a call."""
    declared = LaunchMode(
        name="syra",
        help="research session",
        targets=NativeTargets(builders={}),
        model=lambda provider: "fable" if provider == "claude" else "gpt-5.6-sol",
        record_root=lambda: Path("notes/research/sessions"),
    )
    assert declared.native_model("claude") == "fable"
    assert declared.record_root is not None
    assert declared.record_root() == Path("notes/research/sessions")


def test_a_mode_names_each_runtime_a_model_in_that_runtime_s_own_words() -> None:
    """One name shared between them reaches the other as an unknown model."""
    declared = LaunchMode(
        name="syra",
        help="research session",
        targets=NativeTargets(builders={}),
        model=lambda provider: "fable" if provider == "claude" else "gpt-5.6-sol",
    )
    assert declared.native_model("claude") != declared.native_model("codex")


def test_a_mode_naming_no_model_leaves_every_runtime_its_own_default() -> None:
    """Absent a declaration the launcher passes no --model at all."""
    declared = mode("audit")
    assert declared.native_model("claude") is None
    assert declared.native_model("codex") is None


def test_a_mode_can_disable_transcription_for_only_one_runtime() -> None:
    declared = LaunchMode(
        name="syra",
        help="research session",
        targets=NativeTargets(builders={}),
        transcribe_session=lambda provider: provider != "claude",
    )

    assert declared.transcribes("claude") is False
    assert declared.transcribes("codex") is True


def test_a_mode_keeps_transcription_without_an_override() -> None:
    assert mode("audit").transcribes("claude") is True


def test_a_mode_can_supply_a_safer_recursive_default() -> None:
    declared = mode("syra").model_copy(update={"max_recursive_agent": 0})

    assert declared.recursive_agent_limit(None) == 0
    assert declared.recursive_agent_limit(-1) == -1


def test_a_mode_can_select_a_tree_from_the_effective_allowance() -> None:
    selected: list[int] = []
    declared = LaunchMode(
        name="syra",
        help="research session",
        targets=NativeTargets(builders={}),
        recursive_targets=lambda allowance: (
            selected.append(allowance) or NativeTargets(builders={})
        ),
    )

    declared.targets_at(0)

    assert selected == [0]
