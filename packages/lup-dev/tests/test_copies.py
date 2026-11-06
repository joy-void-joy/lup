"""Which copies of `lup-dev` a repository keeps, and the launcher that reaches them when the one running can't run (`lup_dev/copies.py`, `docs/trust.md`, *The way back*)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from filelock import FileLock

from lup.programs import run
from lup_dev.approval import Approval, ReleaseTool, WorkspaceTool
from lup_dev.copies import Copies, Kept, launcher, removable
from lup_dev.layout import CopyLayout, JudgeLayout

AT = datetime(2026, 11, 6, 12, tzinfo=UTC)
TOOL = WorkspaceTool(name="lup-dev", package=Path("packages/lup-dev"), members=[])


def approval(commit: str, at: int = 0) -> Approval:
    return Approval(
        commit=commit,
        fingerprint=f"zone of {commit}",
        paths=[],
        tool=TOOL,
        time=AT + timedelta(hours=at),
    )


@pytest.fixture
def copies(tmp_path: Path) -> Copies:
    return Copies(layout=JudgeLayout(home=tmp_path / "judges" / "lup"), keeping=2)


def installed(copies: Copies, name: str) -> CopyLayout:
    """A copy with its command, as uv leaves one."""
    copy = copies.layout.named(name)
    copy.bin.mkdir(parents=True)
    copy.command("lup-dev").write_text(f'#!/bin/sh\necho {name} ran with "$@"\n')
    copy.command("lup-dev").chmod(0o755)
    return copy


def record(
    copies: Copies, name: str, at: int, *, answered: bool = True, commit: str = ""
) -> Kept:
    """Install the copy `name`, approved at hour `at`, which last answered then, or never."""
    installed(copies, name)
    kept = Kept(
        name=name,
        repository=Path("/repo.git"),
        approval=approval(commit or f"{name}-commit", at),
        subject=f"the copy {name}",
        answered=AT + timedelta(hours=at) if answered else None,
    )
    copies.recorded(kept)
    return kept


def named(paths: list[Path]) -> list[str]:
    return sorted(each.name for each in paths)


def test_the_last_that_answered_are_kept_and_the_rest_removed(copies: Copies) -> None:
    for at, name in enumerate(["oldest", "older", "new", "newest"]):
        record(copies, name, at)
    copies.switch(copies.layout.named("newest"))
    assert [each.name for each in copies.kept()] == ["newest", "new"]
    assert named(copies.unused([])) == ["older", "oldest"]


def test_what_ran_last_decides_not_what_was_approved_last(copies: Copies) -> None:
    for at, name in enumerate(["first", "second", "third"]):
        record(copies, name, at)
    copies.recorded(
        Kept(
            name="first",
            repository=Path("/repo.git"),
            approval=approval("first-commit"),
            answered=AT + timedelta(days=1),
        )
    )
    copies.switch(copies.layout.named("first"))
    assert [each.name for each in copies.kept()] == ["first", "third"]
    assert named(copies.unused([])) == ["second"]


def test_a_copy_that_never_answered_goes_unless_a_commit_pins_it(
    copies: Copies,
) -> None:
    record(copies, "running", 3)
    record(copies, "tried", 2, answered=False)
    record(copies, "on-trial", 1, answered=False)
    copies.switch(copies.layout.named("running"))
    copies.pin(["on-trial-commit"])
    assert copies.pinned() == ["on-trial-commit"]
    assert [each.name for each in copies.kept()] == ["running", "on-trial"]
    assert named(copies.unused([])) == ["tried"]


def test_pinning_says_the_whole_list_so_a_commit_unpinned_goes(copies: Copies) -> None:
    for at, name in enumerate(["old", "pinned", "newer", "newest"]):
        record(copies, name, at)
    copies.switch(copies.layout.named("newest"))
    copies.pin(["old-commit"])
    assert named(copies.unused([])) == ["pinned"]
    copies.pin([])
    assert named(copies.unused([])) == ["old", "pinned"]


def test_a_pins_file_that_doesnt_read_pins_nothing(copies: Copies) -> None:
    copies.layout.home.mkdir(parents=True)
    copies.layout.pins.write_text("{not json")
    assert copies.pinned() == []


def test_the_copy_restore_runs_from_and_any_process_stay(copies: Copies) -> None:
    for at, name in enumerate(["from-restore", "a-process", "older", "new", "newest"]):
        record(copies, name, at)
    copies.switch(copies.layout.named("newest"))
    copies.back(copies.layout.named("from-restore"))
    process = copies.layout.named("a-process").command("lup-dev")
    assert named(copies.unused([process])) == ["older"]


def test_a_copy_from_before_copies_were_kept_has_no_record_and_goes(
    copies: Copies,
) -> None:
    installed(copies, "before")
    record(copies, "now", 0)
    copies.switch(copies.layout.named("now"))
    assert named(copies.unused([])) == ["before"]
    assert copies.running() is not None


def test_one_judging_from_before_copies_were_kept_has_no_record(copies: Copies) -> None:
    copy = installed(copies, "before")
    copies.switch(copy)
    assert copies.current() == copy.home.resolve()
    assert copies.running() is None
    assert copies.unused([]) == []


def test_nothing_is_chosen_while_a_copy_is_being_installed(copies: Copies) -> None:
    for at, name in enumerate(["old", "older", "new", "newest"]):
        record(copies, name, at)
    copies.switch(copies.layout.named("newest"))
    with FileLock(copies.layout.lock):
        assert copies.unused([]) == []


def test_every_repository_keeps_its_own(tmp_path: Path) -> None:
    judges = tmp_path / "judges"
    ours = Copies(layout=JudgeLayout(home=judges / "ours"), keeping=1)
    theirs = Copies(layout=JudgeLayout(home=judges / "theirs"))
    record(ours, "kept", 1)
    record(ours, "replaced", 0)
    ours.switch(ours.layout.named("kept"))
    theirs.switch(installed(theirs, "runs"))
    installed(theirs, "a-release-replaced")
    assert named(removable(judges, [])) == ["a-release-replaced"]
    assert named(ours.unused([])) == ["replaced"]


def test_a_project_s_release_is_not_kept(copies: Copies) -> None:
    release = ReleaseTool(name="lup-dev", version="0.4.0", registry="r", pins={})
    assert not release.lups_own()
    copies.switch(installed(copies, "now"))
    installed(copies, "before")
    assert named(copies.unused([])) == ["before"]


def test_the_history_keeps_the_last_of_each_commit_and_passes_over_what_it_cant_read(
    copies: Copies,
) -> None:
    record(copies, "one", 0)
    with copies.layout.history.open("a") as appended:
        appended.write('{"a later lup": "wrote this"}\n')
        appended.write("not even json\n")
    later = Kept(
        name="one-again",
        repository=Path("/repo.git"),
        approval=approval("one-commit"),
        subject="the same commit, built again",
    )
    copies.recorded(later)
    assert [each.name for each in copies.history()] == ["one-again"]
    assert copies.of("one-commit") == later
    assert copies.of("none") is None


def test_a_field_a_later_lup_added_reads_all_the_same(copies: Copies) -> None:
    kept = record(copies, "one", 0)
    line = kept.model_dump_json()
    copies.layout.history.write_text(line.replace("{", '{"later": 1, ', 1) + "\n")
    assert copies.history() == [kept]


def test_a_copy_gone_stays_in_the_history_to_be_built_again(copies: Copies) -> None:
    kept = record(copies, "gone", 0)
    copies.place(kept).command("lup-dev").unlink()
    copies.place(kept).bin.rmdir()
    copies.place(kept).home.rmdir()
    assert not copies.there(kept)
    assert copies.history() == [kept]
    assert copies.kept() == []


class Launched:
    """The person's command, over a repository's copies."""

    def __init__(self, copies: Copies, tmp_path: Path) -> None:
        self.copies = copies
        self.directory = tmp_path / "bin"
        self.host = tmp_path / "data" / "host-copies"
        self.host.parent.mkdir(parents=True)
        copies.commands(self.directory, "lup-dev", self.host)

    def ran(self, *arguments: str) -> str:
        return run(self.directory / "lup-dev", *arguments).text().strip()


@pytest.fixture
def launched(copies: Copies, tmp_path: Path) -> Launched:
    return Launched(copies, tmp_path)


def test_every_command_runs_the_copy_that_judges(
    copies: Copies, launched: Launched
) -> None:
    copies.switch(installed(copies, "current"))
    copies.back(installed(copies, "before"))
    assert launched.ran("sessions", "--all") == "current ran with sessions --all"
    assert launched.ran() == "current ran with"


def test_restore_runs_the_copy_that_answered_before(
    copies: Copies, launched: Launched
) -> None:
    copies.switch(installed(copies, "current"))
    copies.back(installed(copies, "before"))
    assert launched.ran("restore") == "before ran with restore"
    assert launched.ran("restore", "abc", "--ledger") == (
        "before ran with restore abc --ledger"
    )


def test_restore_runs_though_the_copy_that_judges_cant(
    copies: Copies, launched: Launched
) -> None:
    broken = installed(copies, "broken")
    broken.command("lup-dev").write_text("#!/bin/sh\nexit 3\n")
    copies.switch(broken)
    copies.back(installed(copies, "before"))
    assert launched.ran("restore") == "before ran with restore"
    assert run(launched.directory / "lup-dev", "sessions", ok=[3]).status == 3


def test_restore_runs_the_copy_that_judges_where_none_answered_before(
    copies: Copies, launched: Launched
) -> None:
    copies.switch(installed(copies, "only"))
    assert launched.ran("restore") == "only ran with restore"


def test_a_home_with_a_space_is_quoted(tmp_path: Path) -> None:
    written = launcher(tmp_path / "with space", "lup-dev")
    assert "'" in written.splitlines()[4]


def test_the_commands_replace_uvs_link_once_and_leave_it_after(
    copies: Copies, tmp_path: Path
) -> None:
    directory = tmp_path / "bin"
    directory.mkdir()
    uvs = tmp_path / "uv-tool" / "lup-dev"
    uvs.parent.mkdir()
    uvs.write_text("#!/bin/sh\n")
    (directory / "lup-dev").symlink_to(uvs)
    host = tmp_path / "host-copies"
    copies.layout.home.mkdir(parents=True)

    copies.commands(directory, "lup-dev", host)

    command = directory / "lup-dev"
    assert not command.is_symlink()
    assert command.read_text() == launcher(copies.layout.home, "lup-dev")
    assert command.stat().st_mode & 0o111
    assert uvs.is_file()
    assert host.resolve() == copies.layout.home.resolve()
    before = command.stat().st_mtime_ns
    copies.commands(directory, "lup-dev", host)
    assert command.stat().st_mtime_ns == before
