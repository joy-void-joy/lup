"""The type-resolution port the codescan rules judge their sites against.

A rule with a family decides a site by what its subject *is* — `.get` on a
`dict` is a mapping access, the same spelling on an `httpx.Client` is an HTTP
request. Answering that needs a type checker, which no library module may
embed: `lup.codescan` stays importable from the auditor with nothing but the
standard library and pydantic, and the hermetic hook kernel could not carry
an inference engine at all.

So the capability is a port. The audit depends on this ABC; the pyright
language-server client that implements it lives in devtools, is injected at
the call site, and is absent whenever the checker is not installed — in which
case nothing resolves and every rule keeps its unresolved verdict.

**The port answers declarations, not coordinates.** A checker replies to a
protocol request with a file and a line, and a caller handed those has to
re-derive what they mean: parse the file, find the enclosing class, read its
bases, decide whether the answer was even a class. That is a slice of a type
checker written on top of a type checker, and it belongs to whoever knows how
the checker answers rather than to the rules. So the shape crossing this
boundary is a `Declaration` — a class with its inheritance, a module-level
function, or nothing — and how many protocol requests it took to build one is
the implementation's business.

Positions are 1-based lines with 0-based UTF-8 column offsets, the
coordinates `ast` reports, so the library never speaks a protocol's encoding.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel

from lup.codescan.common import TypeFamily


class SourcePosition(BaseModel, frozen=True):
    """One symbol's position in one Python file, in `ast` coordinates."""

    path: Path
    line: int
    """1-based line number, as `ast` reports `lineno`."""

    column: int
    """0-based UTF-8 column offset, as `ast` reports `col_offset`."""


class SymbolQuery(BaseModel, frozen=True):
    """The symbols of one site, in the order a resolver should try them.

    ``member`` is the attribute the site is named for, and is asked first
    because resolving it walks the inheritance chain for free: a receiver can
    only reach `dict.get` by being a dict, however many classes sit between,
    so the declaration that comes back is already the one family membership
    is about.

    ``receiver`` is the fallback, and answers the two things the member
    cannot. A member no source declares — a `TypedDict`'s `get`, a dataclass
    `__init__` — resolves to nothing at all, which is indistinguishable from
    a receiver the checker could not type; and a receiver whose type comes
    from somewhere the member does not mention is still named by its own
    position. It is absent where the receiver ends in no name — a subscript,
    a call — because only a name denotes a symbol a checker can answer about.
    """

    member: SourcePosition
    receiver: SourcePosition | None = None


class SourceBuffer(BaseModel, frozen=True):
    """The text a path holds, which need not be the text on disk.

    An audit reads its own copy of a file, and a checker asked about a path
    would read that path again. Where the two differ the answer is about
    something nobody audited — and they differ exactly when it matters most,
    because an edit is judged before it is written.

    Carrying the text keeps them the same by construction, everywhere the
    resolution looks: the position the checker is asked about, and the
    declaration it reports back, are both read from what the caller holds.
    The path stays the file's own, so imports, the module's name, and
    everything resolved through either are unchanged: this is the buffer an
    editor holds for a file with unsaved changes, and a checker is built to
    be told about one.
    """

    path: Path
    text: str


class ClassDeclaration(BaseModel, frozen=True):
    """A resolved declaration that is a class, and what it inherits.

    ``bases`` is transitive and unqualified — every class this one descends
    from, named as a declaration names it rather than as a site spells it.
    Transitive because a family is about what something *is*: a project's
    `Bag(dict)` and the `DeepBag(Bag)` beneath it are both mappings, and a
    membership test reading one level would call the second a stranger.

    Unqualified because family membership is about the class a declaration
    names — `MutableMapping`, whether written bare or as
    `collections.abc.MutableMapping`.
    """

    name: str
    bases: list[str]
    path: Path
    line: int

    def in_family(self, family: TypeFamily) -> bool:
        """Whether this class is the family, or descends from it."""
        return self.name in family.classes or any(
            base in family.classes for base in self.bases
        )

    def settled(self) -> bool:
        """Yes: a class is an answer about what a subject is."""
        return True

    def supertypes(self) -> list[str]:
        """What a subject inheriting this one thereby also is."""
        return [self.name, *self.bases]

    def refutation(self, subject: str, family: TypeFamily) -> str:
        """Why a site resolving here is not what its rule is about."""
        return (
            f"`{subject}` resolves to `{self.name}` declared at "
            f"{self.path.as_posix()}:{self.line}, outside the {family.name} family"
        )


class FunctionDeclaration(BaseModel, frozen=True):
    """A resolved declaration that is a function, belonging to no class at all.

    A module-qualified receiver produces one: `httpx.get` resolves to a `def`
    at column zero in `httpx/_api.py`, where `client.get` resolves to a
    method inside `class Client`. Both are equally strong evidence about what
    the call is, and reading only the class one left every module-qualified
    receiver with no declaration — indistinguishable, to the engine, from a
    symbol the checker could not resolve.

    Membership is decided against declaring classes, and a function is not
    one, so this is outside every family by construction rather than by a
    lookup that could accidentally succeed.
    """

    name: str
    path: Path
    line: int

    def in_family(self, family: TypeFamily) -> bool:
        """Never: a family is a set of classes, and this declaration is not one."""
        return False

    def settled(self) -> bool:
        """Yes: a module-level function is as much an answer as a class is."""
        return True

    def supertypes(self) -> list[str]:
        """None: a function is not something another declaration can inherit."""
        return []

    def refutation(self, subject: str, family: TypeFamily) -> str:
        """Why a site resolving here is not what its rule is about."""
        return (
            f"`{subject}` resolves to the module-level `{self.name}` declared "
            f"at {self.path.as_posix()}:{self.line}, outside the "
            f"{family.name} family"
        )


class UnknownDeclaration(BaseModel, frozen=True):
    """No declaration: the checker could not say what this subject is.

    Its own answer rather than an absent one, because *why* nothing came back
    is what a reader needs. An unannotated parameter, a value inferred as
    `Any`, a package shipping no stubs, a checker that never started — each
    leaves a site the rule cannot speak about, and each says so in its own
    words.
    """

    reason: str = "the checker inferred no type"
    """Why nothing came back, defaulting to the ordinary case: it has no type."""

    def in_family(self, family: TypeFamily) -> bool:
        """Never: nothing is shown, and a family is membership shown."""
        return False

    def settled(self) -> bool:
        """No: this is the answer that says another question is worth asking."""
        return False

    def supertypes(self) -> list[str]:
        """None: nothing was resolved, so nothing is known to be inherited."""
        return []

    def refutation(self, subject: str, family: TypeFamily) -> str:
        """Why a site resolving to nothing is not one this rule can stand on."""
        return (
            f"{self.reason} for `{subject}`, so nothing puts it in the "
            f"{family.name} family"
        )


type Declaration = ClassDeclaration | FunctionDeclaration | UnknownDeclaration
"""What a subject resolves to, in the terms family membership is read in."""


class TypeOracle(ABC):
    """Resolves what the subjects named at source positions are declared as.

    What a subject *is declared as*, and never what its type resolves to.
    Telling a synthesized member from a receiver the checker could not type —
    the ambiguity :class:`SymbolQuery` describes — would take
    ``textDocument/typeDefinition``, which is a different question with
    limits of its own: it is asked at the *last name* in the receiver, since
    asking at ``self`` answers with the enclosing class, and it has no answer
    at all for a call receiver, whose result no position denotes. No rule
    here needs it, and one that did would own those limits.
    """

    @abstractmethod
    def declarations(
        self,
        queries: list[SymbolQuery],
        buffers: list[SourceBuffer] | None = None,
    ) -> list[Declaration]:
        """What each query's subject is declared as, in order.

        Batched because resolution costs a checker session, not a lookup: one
        call answers a whole repository sweep. A query nothing can be shown
        about yields an :class:`UnknownDeclaration` rather than an error,
        which the rules read as "no evidence" and treat as a site they cannot
        speak about — and every way an implementation can fail resolves to
        the same thing, so a sweep degrades instead of raising.

        *buffers* is what the caller holds for the files it asks about. A
        path it names nothing for is read from disk, which is every path the
        caller did not itself supply — an installed package, a typeshed stub,
        a module the edited one imports.
        """
