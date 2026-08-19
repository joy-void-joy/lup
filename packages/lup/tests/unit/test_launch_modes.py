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
        model="fable",
        record_root=lambda: Path("notes/research/sessions"),
    )
    assert declared.model == "fable"
    assert declared.record_root is not None
    assert declared.record_root() == Path("notes/research/sessions")
