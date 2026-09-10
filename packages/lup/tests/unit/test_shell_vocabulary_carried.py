"""Behavior tests for holding an environment to the vocabulary a policy declares.

The defect these pin is not a missing program, which any launch would survive.
It is that the absence of one does not read as an absence: a shell spends exit
code 127 the same way it spends every other non-zero code, so
``cmp -s A B && echo IDENTICAL || echo DIFFERS`` answers ``DIFFERS`` about two
byte-identical files when nothing named ``cmp`` is on ``PATH``. So the
assertions below are about what gets *said*, and only incidentally about what
gets installed.
"""

from os import defpath
from pathlib import Path

import pytest

from lup.harness.requirements import (
    HostFacts,
    Manifest,
    MisleadingAbsence,
    VocabularyProbe,
)
from lup.harness.toolchain import shell_vocabulary_requirement
from lup.policy.survey import allowed_programs
from lup.policy.vocabulary import default_vocabulary

ABSENT = "lup-no-such-program-anywhere"
"""A word chosen so no machine running this suite can carry it."""


def test_the_offered_vocabulary_declares_the_comparison_tools() -> None:
    """The words whose absence was measured are the ones the table promises."""
    offered = allowed_programs(default_vocabulary())
    assert "diff" in offered
    assert "cmp" in offered


def test_shell_builtins_are_not_asked_of_any_environment() -> None:
    """A table judges ``cd`` and ``eval``; no image installs either."""
    offered = allowed_programs(default_vocabulary())
    assert "cd" not in offered
    assert "eval" not in offered
    assert "export" not in offered


def test_only_what_the_table_allows_is_promised() -> None:
    """A command that raises a question was never a promise to keep."""
    offered = allowed_programs(default_vocabulary())
    assert "sudo" not in offered
    assert "docker" not in offered


def test_a_carried_vocabulary_proves_itself() -> None:
    outcome = VocabularyProbe(vocabulary=["sh", "cat"]).run()
    assert outcome.proved
    assert outcome.exercised


def test_an_absent_word_is_named_rather_than_merely_counted() -> None:
    """The finding a reader acts on is which word, not how many."""
    outcome = VocabularyProbe(vocabulary=["sh", ABSENT]).run()
    assert not outcome.proved
    assert outcome.exercised
    assert ABSENT in outcome.detail
    assert "sh" not in outcome.detail.split(":")[-1].split()


def test_every_absent_word_is_reported_in_one_finding() -> None:
    """Eight absences are one fact about a stale image, not eight capabilities."""
    outcome = VocabularyProbe(vocabulary=[ABSENT, "sh", f"{ABSENT}-two"]).run()
    assert ABSENT in outcome.detail
    assert f"{ABSENT}-two" in outcome.detail


def test_the_probe_names_every_word_it_will_ask_for() -> None:
    probe = VocabularyProbe(vocabulary=["diff", "cmp"])
    assert probe.programs() == ["diff", "cmp"]


def test_the_probe_runs_inside_whatever_opening_starts() -> None:
    """An image-side reading has to be taken in the image, not in the launcher."""
    placed = VocabularyProbe(vocabulary=["diff"]).given(HostFacts())
    contained = placed.behind(["docker", "run", "--rm", "image"])
    assert contained.command[:4] == ["docker", "run", "--rm", "image"]
    assert contained.contained


def test_a_misleading_absence_is_costly_without_refusing() -> None:
    """A session can work around what it was told; it cannot work around silence."""
    absence = MisleadingAbsence(
        capability="comparing two files",
        mistaken_for="the files differing",
    )
    assert not absence.refuses()
    assert absence.costly()
    assert "the files differing" in absence.consequence()


def test_the_requirement_reports_the_absent_program_by_name() -> None:
    entry = shell_vocabulary_requirement(vocabulary=["sh", ABSENT])
    found = entry.check({})
    assert not found.working
    assert not found.refuses()
    spoken = " ".join(notice.text for notice in found.alarms())
    assert ABSENT in spoken
    assert "shell fallbacks hide a missing-command error" in spoken


def test_a_carried_vocabulary_says_nothing_at_a_launch() -> None:
    """An alarm that fires on a healthy image is one people learn to skip."""
    entry = shell_vocabulary_requirement(vocabulary=["sh"])
    assert entry.check({}).alarms() == []


def test_what_the_probe_asks_for_is_what_the_image_installs() -> None:
    """Declared and installed are one fact, which is the whole mechanism here."""
    entry = shell_vocabulary_requirement(vocabulary=["diff", "cmp"])
    installed = [item.name for item in Manifest(requirements=[entry]).packages()]
    assert "diffutils" in installed


def test_the_vocabulary_is_verified_where_a_session_runs() -> None:
    """The launch selects the session's environment."""
    entry = shell_vocabulary_requirement(vocabulary=["diff"])
    assert entry.where == "session"
    assert entry.at_launch


def test_host_absence_does_not_warn_when_the_container_has_the_command(
    tmp_path: Path,
) -> None:
    program = tmp_path / ABSENT
    program.write_text("#!/bin/sh\nexit 0\n")
    program.chmod(0o755)

    roster = Manifest(requirements=[shell_vocabulary_requirement(vocabulary=[ABSENT])])
    host = roster.check({})
    assert not host[0].working

    assert roster.check({}, contained=True) == []
    inside = roster.check_inside(
        {}, ["env", f"PATH={tmp_path}:{defpath}"], setting_up=False
    )
    assert inside[0].working

    assert inside[0].location == "image"
    assert inside[0].alarms() == []


def test_missing_host_commands_get_host_installation_advice() -> None:
    roster = Manifest(requirements=[shell_vocabulary_requirement(vocabulary=[ABSENT])])
    finding = roster.check({})[0]
    spoken = "\n".join(notice.text for notice in finding.alarms())

    assert "shell commands (host): check failed" in spoken
    assert f"Missing commands: {ABSENT}" in spoken
    assert "Install the missing commands on the host" in spoken

    assert "image" not in spoken
    assert "Rebuild" not in spoken


def test_missing_container_commands_get_image_advice() -> None:
    roster = Manifest(requirements=[shell_vocabulary_requirement(vocabulary=[ABSENT])])
    finding = roster.check_inside({}, ["env"], setting_up=False)[0]
    spoken = "\n".join(notice.text for notice in finding.alarms())

    assert "shell commands (container): check failed" in spoken
    assert f"Missing commands: {ABSENT}" in spoken
    assert "launcher already builds changed images" in spoken

    assert "Install the missing commands on the host" not in spoken
    assert not finding.refuses()


def test_explicit_host_requirement_is_checked_for_contained_launches() -> None:
    roster = Manifest(
        requirements=[shell_vocabulary_requirement(vocabulary=[ABSENT], where="both")]
    )
    assert not roster.check({}, contained=True)[0].working


@pytest.mark.parametrize(
    "opening", [["sh", "-c", "exit 125", "probe"], ["lup-no-such-container-engine"]]
)
def test_container_start_failure_does_not_prescribe_installing_commands(
    opening: list[str],
) -> None:
    roster = Manifest(requirements=[shell_vocabulary_requirement(vocabulary=[ABSENT])])
    finding = roster.check_inside({}, opening, setting_up=False)[0]
    spoken = "\n".join(notice.text for notice in finding.alarms())

    assert "shell commands (container): check could not run" in spoken
    assert "Result unknown" in spoken
    assert "Missing commands:" not in spoken

    assert "Fix:" not in spoken
