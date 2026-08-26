"""What the ledger must tell apart: a capability that moved and one that went.

Both leave the old import path unresolvable, which is exactly why a reviewer
cannot separate them by reading a diff — so these pin the separation itself
rather than any particular walk. The walk is checked too, but for the one
property that decides what the ledger is worth: a name it never recorded is a
name nothing will notice the loss of.
"""

from pathlib import Path

from lup.devtools.dev.boundaries import TrackedSource
from lup.devtools.dev.preservation import (
    Capability,
    CapabilityKind,
    Ledger,
    ModuleSurface,
    compare,
    surfaces,
)


def ledger(*modules: ModuleSurface, commands: list[str] | None = None) -> Ledger:
    return Ledger(
        revision="0" * 40,
        roots=["lup"],
        commands=commands or [],
        modules=list(modules),
    )


def source(text: str, path: str) -> TrackedSource:
    return TrackedSource(rel=path, path=Path(path), text=text)


def test_a_name_no_module_declares_any_more_has_disappeared() -> None:
    """The failure the whole fixture exists to find."""
    divergence = compare(
        ledger(ModuleSurface(module="lup.jobs.runtime", declares=["JobSpec"])),
        ledger(ModuleSurface(module="lup.jobs.runtime", declares=[])),
    )

    assert [row.identity for row in divergence.disappeared] == ["JobSpec"]
    assert not divergence.intact()


def test_a_name_declared_somewhere_else_has_moved_and_does_not_fail() -> None:
    """A reorganisation is moves; reading one as a loss would make this noise."""
    divergence = compare(
        ledger(ModuleSurface(module="lup.jobs.runtime", declares=["JobSpec"])),
        ledger(ModuleSurface(module="lup.orchestration.jobs", declares=["JobSpec"])),
    )

    assert divergence.disappeared == []
    assert divergence.intact()
    assert [row.homes for row in divergence.relocated] == [["lup.orchestration.jobs"]]


def test_a_shared_name_casts_no_vote_in_the_migration_map() -> None:
    """``logger`` is declared forty-six times, so where it went is ambiguous."""
    before = ledger(
        ModuleSurface(module="lup.jobs.runtime", declares=["logger"]),
        ModuleSurface(module="lup.client", declares=["logger"]),
    )
    after = ledger(
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
    before = ledger(
        ModuleSurface(module="lup.jobs.runtime", declares=["JobSpec", "JobStore"])
    )
    after = ledger(
        ModuleSurface(module="lup.orchestration.jobs", declares=["JobSpec", "JobStore"])
    )

    assert compare(before, after).module_moves() == {
        "lup.jobs.runtime": "lup.orchestration.jobs"
    }


def test_a_renamed_command_is_a_disappearance_at_the_path_a_reader_types() -> None:
    """A caller depends on the words, so changing them is not a move."""
    divergence = compare(
        ledger(commands=["dev check"]), ledger(commands=["dev verify"])
    )

    assert [row.identity for row in divergence.disappeared] == ["dev check"]
    assert [row.identity for row in divergence.arrived] == ["dev verify"]


def test_arrival_is_reported_without_failing_the_run() -> None:
    """What the range added is worth seeing; it is not what the gate is for."""
    divergence = compare(
        ledger(ModuleSurface(module="lup.client", declares=["Client"])),
        ledger(ModuleSurface(module="lup.client", declares=["Client", "Session"])),
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


def test_every_captured_entry_carries_the_kind_that_resolves_it() -> None:
    """The flattening both halves of the comparison run over."""
    entries = list(
        ledger(
            ModuleSurface(module="lup.client", declares=["Client"]),
            commands=["dev check"],
        ).capabilities()
    )

    assert entries == [
        Capability(kind=CapabilityKind.COMMAND, identity="dev check", location=""),
        Capability(
            kind=CapabilityKind.EXPORT, identity="Client", location="lup.client"
        ),
    ]
