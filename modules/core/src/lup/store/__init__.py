"""The store: the records every module keeps its state as, the kinds they're read as, and the database keeping them.

A module's promises reach the database and its kinds from here (`Database`,
`Kinds`), loaded only once they're read, so importing lup loads no database.
Its reasons are in `README.md` here.
"""

lazy from lup.store.database import Database
lazy from lup.store.records import Kinds

__all__ = ["Database", "Kinds"]
