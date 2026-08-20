"""The type-resolution port the codescan grammar judges its sites against.

A grammar rule decides a site by what the symbol at one position *resolves
to* — `.get` reaching `dict` in typeshed is a mapping access, the same
spelling reaching `httpx.Client` is an HTTP request. Answering that needs a
type checker, which no library module may embed: `lup.codescan` stays
importable from the auditor with nothing but the standard library and
pydantic, and the hermetic hook kernel could not carry an inference engine at
all.

So the capability is a port. The audit depends on this ABC; the pyright
language-server client that implements it lives in devtools, is injected at
the call site, and is absent whenever the checker is not installed — in which
case the grammar resolves nothing and every rule keeps its broad regex
verdict. Positions are 1-based lines with 0-based UTF-8 column offsets, the
coordinates `ast` reports, so the library never speaks a protocol's encoding.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel


class SourcePosition(BaseModel, frozen=True):
    """One symbol's position in one Python file, in `ast` coordinates."""

    path: Path
    line: int
    """1-based line number, as `ast` reports `lineno`."""

    column: int
    """0-based UTF-8 column offset, as `ast` reports `col_offset`."""


class DefinitionSite(BaseModel, frozen=True):
    """Where a resolved symbol is declared, as the oracle reports it.

    The path may lead anywhere the checker looks — a project module, an
    installed package, a typeshed stub — and the grammar reads the declaring
    class out of it rather than trusting a rendered type name.
    """

    path: Path
    line: int
    """1-based line the declaration starts on."""


class SourceBuffer(BaseModel, frozen=True):
    """The text a position's file holds, which need not be the text on disk.

    An audit reads its own copy of a file, and a checker asked about a path
    would read that path again. Where the two differ the answer is about
    something nobody audited — and they differ exactly when it matters most,
    because an edit is judged before it is written.

    Carrying the text keeps them the same by construction. The path stays the
    file's own, so imports, the module's name, and everything resolved through
    either are unchanged: this is the buffer an editor holds for a file with
    unsaved changes, and a checker is built to be told about one.
    """

    path: Path
    text: str


# lup: defer: a rule whose subject is a member no source declares wants
# `textDocument/typeDefinition` on the receiver rather than the query below.
# A synthesized member — a `TypedDict`'s `get`, a dataclass `__init__` —
# resolves to nothing here, which is indistinguishable from a receiver the
# checker could not type at all. That query is asked at the *last name* in
# the receiver (`self.spawned`, never `self`, which answers with the
# enclosing class), and has no answer for a call receiver, whose result no
# position denotes. No rule needs it today: `dict-get` does not, because
# `.get` on a `TypedDict` is how an optional key is read and is not a defect.
class DefinitionOracle(ABC):
    """Resolves the declarations of the symbols named at source positions.

    The question is asked of the member, not of the receiver, and that is what
    makes one query enough: a receiver can only reach `dict.get` by being a
    dict, so resolving the member settles the type without asking about it.
    It also answers where nothing else can — a call expression has no position
    that denotes its result, so `make().get(k)` is typed by `get` or not at
    all.
    """

    @abstractmethod
    def definitions(
        self,
        positions: list[SourcePosition],
        buffers: list[SourceBuffer] | None = None,
    ) -> list[list[DefinitionSite]]:
        """Each position's declarations, in order; empty where none resolve.

        Batched because resolution costs a checker session, not a lookup: one
        call answers a whole repository sweep. An unresolvable position yields
        an empty list rather than an error, which the grammar reads as "no
        evidence" and treats as a site it cannot refute.

        *buffers* is what the caller holds for the files it asks about. A path
        it names nothing for is read from disk, which is every path the caller
        did not itself supply — an installed package, a typeshed stub, a
        module the edited one imports.
        """
