"""The store's promises: what a module keeping records can count on.

Each is checked through the harness, as lup's start resolves a declaration
(`README.md` here).
"""

from datetime import UTC, datetime

import lup
from lup import LupError, Module, Modules, Node, Part, Project, ProjectError, Recorded
from lup.store import Database, Kinds
from lup.testing import Testing, raises


class Note(Node):
    """A note an example module keeps."""

    kind: str = "example:note"
    text: str = ""


class Notes(Module):
    """Keeping notes: an example module declaring a kind of record."""

    name = "notes"
    kinds: Recorded = Recorded.of(Note)


class Jottings(Module):
    """Keeping jottings, as notes: an example module declaring the same kind as `Notes`."""

    name = "jottings"
    kinds: Recorded = Recorded.of(Note)


class UndoneError(LupError):
    """What a promise raises in a transaction, to roll it back."""


class StorePromises(Part):
    """What a module keeping records in the store can count on."""

    @lup.promise
    async def a_kind_of_record_is_one_modules(self, by: Testing) -> None:
        """A kind of record two modules declare fails the load, naming both, rather than one module reading the other's records as its own."""
        await by.started(Project(modules=Modules.default().add(Notes())))
        with raises(ProjectError) as refused:
            await by.started(
                Project(modules=Modules.default().add(Notes(), Jottings()))
            )
        about = refused.raised().about
        assert "notes" in about
        assert "jottings" in about

    @lup.promise
    async def a_write_rolled_back_is_never_read(self, by: Testing) -> None:
        """What a transaction wrote, then rolled back, reads as never written, even where it was read before the rollback."""
        database = Database.opened(":memory:", Kinds(nodes=[Note]))
        written = Note(
            repository="notes",
            by=None,
            at=datetime(2026, 1, 1, tzinfo=UTC),
            text=by.any(str),
        )
        with raises(UndoneError), database.writing():
            kept = database.kept(written)
            assert database.nodes("notes", Note) == [kept]
            message = "rolled back"
            raise UndoneError(message)
        assert database.nodes("notes", Note) == []
        database.close()
