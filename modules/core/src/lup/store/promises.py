"""The store's promises: what a module keeping records can count on.

Each is checked through the harness, as lup's start resolves a declaration
(`README.md` here).
"""

import lup
from lup import Module, Modules, Node, Part, Project, ProjectError, Recorded
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
