"""A launch records its own invocation, so a session can spell its reopening.

A mount registered mid-session takes effect only at the next launch, and the
session proposing the registration is the one that knows why it wants it. What
it cannot know without a record is *which* launch to repeat — profile, sandbox
posture, flags — because nothing else remembers them once the process is up.
So the launcher writes its argv into the same ledger the dispatcher already
reads, and the reopening is that record plus the one flag that reaches the
same conversation instead of a fresh one.
"""

import json
import sys
from pathlib import Path

import pytest

from lup.devtools.harness.preflight import (
    LaunchSentinels,
    record_preflight,
    reopened,
)
from lup.harness.models import HookSet
from lup.policy.assets.host import measured_boundary
from lup.policy.profiles import compile_boundary, depended_on, measured


def recorded(root: Path, launch: list[str] | None = None) -> tuple[Path, str]:
    """One launch's ledger, written the way settle_boundary writes it."""
    declared = HookSet(id="hooks.probe", policy_ids=[])
    boundary = compile_boundary(declared, contained=False)
    preflight = measured(boundary, depended_on(declared, False), [])
    sentinels = LaunchSentinels()
    return record_preflight(preflight, sentinels, root, launch), sentinels.nonce


def test_the_ledger_carries_the_invocation_that_wrote_it(tmp_path: Path) -> None:
    """The record is the argv, not a reconstruction that would drift from it."""
    written, _ = recorded(tmp_path, ["harness", "claude", "--sandbox", "inner"])

    assert json.loads(written.read_text())["launch"] == [
        "harness",
        "claude",
        "--sandbox",
        "inner",
    ]


def test_the_invocation_defaults_to_the_launchers_own_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The launcher is the process, so its argv is the invocation."""
    monkeypatch.setattr(sys, "argv", ["lup-devtools", "harness", "codex", "-p", "dev"])

    written, _ = recorded(tmp_path)

    assert json.loads(written.read_text())["launch"] == [
        "harness",
        "codex",
        "-p",
        "dev",
    ]


def test_the_session_reads_its_own_launch_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The round trip the reopen hint stands on, through the dispatcher's reader."""
    _, nonce = recorded(tmp_path, ["harness", "claude"])
    monkeypatch.setenv("LUP_BOUNDARY_NONCE", nonce)

    assert measured_boundary(tmp_path)["launch"] == ["harness", "claude"]


def test_reopening_reaches_the_same_conversation() -> None:
    """A verbatim repeat opens a fresh session and orphans the one that asked."""
    assert reopened(["harness", "claude", "-p", "dev"]) == [
        "harness",
        "claude",
        "-p",
        "dev",
        "--continue",
    ]


def test_a_launch_already_resuming_is_repeated_as_it_stands() -> None:
    """A second resume flag would hand the runtime two answers to one question."""
    assert reopened(["harness", "claude", "--resume"]) == [
        "harness",
        "claude",
        "--resume",
    ]
    assert reopened(["harness", "codex", "--session", "abc"]) == [
        "harness",
        "codex",
        "--session",
        "abc",
    ]
