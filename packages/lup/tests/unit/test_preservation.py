"""What the capture must tell apart: a capability that moved and one that went.

Both leave the old import path unresolvable, which is exactly why a reviewer
cannot separate them by reading a diff — so these pin the separation itself
rather than any particular walk. The walk is checked too, but for the one
property that decides what the capture is worth: a name it never recorded is a
name nothing will notice the loss of.
"""

from pathlib import Path

import pytest
import sh

from lup.devtools.dev import preservation
from lup.devtools.dev.boundaries import TrackedSource
from lup.devtools.dev.preservation import (
    Capability,
    SurfaceCapture,
    ModuleSurface,
    compare,
    surfaces,
)
from lup.devtools.project import DevProject
from lup.execution.shell import git


def capture(*modules: ModuleSurface) -> SurfaceCapture:
    return SurfaceCapture(revision="0" * 40, roots=["lup"], modules=list(modules))


def source(text: str, path: str) -> TrackedSource:
    return TrackedSource(rel=path, path=Path(path), text=text)


def test_a_name_no_module_declares_any_more_has_disappeared() -> None:
    """The failure the whole fixture exists to find."""
    divergence = compare(
        capture(ModuleSurface(module="lup.jobs.runtime", declares=["JobSpec"])),
        capture(ModuleSurface(module="lup.jobs.runtime", declares=[])),
    )

    assert [row.identity for row in divergence.disappeared] == ["JobSpec"]
    assert not divergence.intact()


def test_a_name_declared_somewhere_else_has_moved_and_does_not_fail() -> None:
    """A reorganisation is moves; reading one as a loss would make this noise."""
    divergence = compare(
        capture(ModuleSurface(module="lup.jobs.runtime", declares=["JobSpec"])),
        capture(ModuleSurface(module="lup.orchestration.jobs", declares=["JobSpec"])),
    )

    assert divergence.disappeared == []
    assert divergence.intact()
    assert [row.homes for row in divergence.relocated] == [["lup.orchestration.jobs"]]


def test_a_shared_name_casts_no_vote_in_the_migration_map() -> None:
    """``logger`` is declared forty-six times, so where it went is ambiguous."""
    before = capture(
        ModuleSurface(module="lup.jobs.runtime", declares=["logger"]),
        ModuleSurface(module="lup.client", declares=["logger"]),
    )
    after = capture(
        ModuleSurface(module="lup.orchestration.jobs", declares=["logger"]),
        ModuleSurface(module="lup.client", declares=["logger"]),
    )

    divergence = compare(before, after)

    assert divergence.disappeared == []
    assert [row.homes for row in divergence.relocated] == [
        ["lup.client", "lup.orchestration.jobs"]
    ]
    assert divergence.module_moves() == {}


def test_the_migration_map_is_the_module_pairs_the_moves_imply() -> None:
    """The same difference that proved nothing was lost repoints an importer."""
    before = capture(
        ModuleSurface(module="lup.jobs.runtime", declares=["JobSpec", "JobStore"])
    )
    after = capture(
        ModuleSurface(module="lup.orchestration.jobs", declares=["JobSpec", "JobStore"])
    )

    assert compare(before, after).module_moves() == {
        "lup.jobs.runtime": "lup.orchestration.jobs"
    }


def test_a_renamed_command_is_a_disappearance_at_the_function_declaring_it() -> None:
    """A command is walked through its own declaration rather than separately.

    Nothing imports a command by the words a reader types, and a revision's
    command list could only be read by importing it — so what stands for one
    here is the function the decorator wraps, which a rename takes with it.
    """
    divergence = compare(
        capture(ModuleSurface(module="lup.devtools.dev.app", declares=["check_cmd"])),
        capture(ModuleSurface(module="lup.devtools.dev.app", declares=["verify_cmd"])),
    )

    assert [row.identity for row in divergence.disappeared] == ["check_cmd"]
    assert [row.identity for row in divergence.arrived] == ["verify_cmd"]


def test_arrival_is_reported_without_failing_the_run() -> None:
    """What the range added is worth seeing; it is not what the gate is for."""
    divergence = compare(
        capture(ModuleSurface(module="lup.client", declares=["Client"])),
        capture(ModuleSurface(module="lup.client", declares=["Client", "Session"])),
    )

    assert [row.identity for row in divergence.arrived] == ["Session"]
    assert divergence.intact()


def test_a_method_is_its_own_capability() -> None:
    """Qualifying by scope is what keeps one class's loss from another's cover."""
    walked = list(
        surfaces(
            [
                source(
                    "class Client:\n"
                    "    def close(self) -> None: ...\n"
                    "class Session:\n"
                    "    def close(self) -> None: ...\n",
                    "packages/lup/src/lup/client.py",
                )
            ],
            {"lup"},
        )
    )

    assert walked[0].declares == [
        "Client",
        "Client.close",
        "Session",
        "Session.close",
    ]


def test_a_module_no_root_can_import_is_not_a_surface() -> None:
    """A generated tree is derived; counting it would report every regeneration."""
    walked = list(
        surfaces(
            [
                source("MARKER = 1\n", ".claude/plugins/lup/hooks/runtime/kernel.py"),
                source("MARKER = 1\n", "packages/lup/src/lup/client.py"),
            ],
            {"lup"},
        )
    )

    assert [one.module for one in walked] == ["lup.client"]


def test_a_module_mid_merge_is_one_surface_however_many_stages_it_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The index holds a conflicted path three times; the walk reads one file.

    Built the way the duplication was met: both sides of a merge edit one
    line, the merge stops, and the working copy is restored from one side
    without being staged — so the file on disk parses clean while the index
    still carries every stage of it.
    """
    work = tmp_path / "repo"
    (work / "src/pkg").mkdir(parents=True)
    module = work / "src/pkg/mod.py"
    build = sh.Command("git").bake(
        "-C",
        str(work),
        "-c",
        "commit.gpgsign=false",
        "-c",
        "user.email=preservation@example.test",
        "-c",
        "user.name=Preservation Test",
        _tty_out=False,
    )
    build("init", "-b", "main")
    module.write_text("VALUE = 1\n", encoding="utf-8")
    build("add", "--all")
    build("commit", "-m", "base")
    build("switch", "-c", "theirs")
    module.write_text("VALUE = 2\n", encoding="utf-8")
    build("commit", "-am", "theirs")
    build("switch", "main")
    module.write_text("VALUE = 3\n", encoding="utf-8")
    build("commit", "-am", "ours")
    build("merge", "theirs", _ok_code=[0, 1])
    build("restore", "--ours", "--", "src/pkg/mod.py")
    monkeypatch.chdir(work)
    assert len(git.lines("ls-files", "--unmerged")) == 3

    walked = preservation.surface_now(DevProject(package="pkg"))

    assert [one.module for one in walked.modules] == ["pkg.mod"]
    assert walked.modules[0].declares == ["VALUE"]


def test_every_entry_carries_the_module_that_resolves_it() -> None:
    """The flattening both halves of the comparison run over."""
    entries = list(
        capture(ModuleSurface(module="lup.client", declares=["Client"])).capabilities()
    )

    assert entries == [Capability(identity="Client", location="lup.client")]


def test_a_name_only_its_own_function_can_reach_is_not_a_surface() -> None:
    """A command wired onto an app inside a factory is that factory's own.

    No importer can name it however it is spelled, so its going is not a
    break anybody downstream could have met — and counting it would ask for a
    migration to be declared for a rename nobody outside the file can see.
    """
    walked = list(
        surfaces(
            [
                source(
                    "def create_app():\n"
                    "    @app.command('check')\n"
                    "    def check_cmd() -> None: ...\n"
                    "    return app\n",
                    "src/lup/app.py",
                )
            ],
            {"lup"},
        )
    )

    assert walked[0].declares == ["create_app"]
