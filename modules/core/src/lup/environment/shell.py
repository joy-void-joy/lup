"""The shell's environment side: what a project's modules declare for their views to name, and answering a view.

Resolving a declaration gathers every module's tones, fold kinds and mark kinds
(`Looks.of`), refusing two that share a name, or two fold kinds that share a
letter, since the page has one table of them and one set of keys. Answering a
view (`viewed`) calls it through its door and checks that its blocks name only
what its module or the core declares, so a view naming a kind nobody declares
fails as it's answered rather than drawing wrong (`README.md` in `lup/shell/`,
*Kinds*).
"""

from typing import TYPE_CHECKING, Literal

from lup.core import Core
from lup.declaration.errors import ProjectError
from lup.declaration.grammar import Named, listed
from lup.shell.blocks import BlockError, Blocks, Code, Diff, Fold, Line
from lup.shell.kinds import FoldKind, Folds, MarkKind, Marks, Tone, Tones
from lup.shell.view import ViewDoor
from lup.types import Model

if TYPE_CHECKING:
    from pydantic import JsonValue

    from lup.declaration.module import Module
    from lup.doors.door import Accepted, Refused
    from lup.doors.parties import Party
    from lup.environment.doors import Running


class Owned[K](Model):
    """A kind a module declares, with the module's name."""

    module: str
    kind: K


class Used(Model):
    """A kind a view's blocks name: what it is, and its name."""

    what: Literal["tone", "fold kind", "mark kind"]
    name: str


class Looks(Model):
    """Every tone, fold kind and mark kind a project's modules declare, each with its module: what their views may name."""

    tones: list[Owned[Tone]] = []
    folds: list[Owned[FoldKind]] = []
    marks: list[Owned[MarkKind]] = []

    @classmethod
    def of(cls, modules: list[Module]) -> Looks:
        """Return what `modules` declare, the core's first.

        Raise `ProjectError` where two modules declare kinds of one name, two
        fold kinds take one letter, or a tone takes the look of a tone neither
        the core nor its module declares.
        """

        def owned[K](selection: type[Named[K]]) -> list[Owned[K]]:
            return [
                Owned(module=module.name, kind=kind)
                for module in modules
                for kind in module.held(selection)
            ]

        looks = cls(tones=owned(Tones), folds=owned(Folds), marks=owned(Marks))
        apart(
            "tone",
            [Owned(module=each.module, kind=each.kind.name) for each in looks.tones],
        )
        apart(
            "fold kind",
            [Owned(module=each.module, kind=each.kind.name) for each in looks.folds],
        )
        apart(
            "fold kind's letter",
            [Owned(module=each.module, kind=each.kind.letter) for each in looks.folds],
        )
        apart(
            "mark kind",
            [Owned(module=each.module, kind=each.kind.name) for each in looks.marks],
        )
        for each in looks.tones:
            like = each.kind.like
            if like is not None and like not in looks.named(looks.tones, each.module):
                message = (
                    f"the tone `{each.kind.name}` of `{each.module}` takes the look "
                    f"of `{like}`, which neither the core nor `{each.module}` declares"
                )
                raise ProjectError(message, about=[each.module])
        return looks

    def named[K: Tone | FoldKind | MarkKind](
        self, owned: list[Owned[K]], module: str
    ) -> list[str]:
        """Return the names of the kinds in `owned` that a view of the module named `module` may name: the core's and its own."""
        return [each.kind.name for each in owned if each.module in [Core.name, module]]

    def checked(self, blocks: Blocks, module: str) -> None:
        """Raise `BlockError` where `blocks`, answered by a view of the module named `module`, name a tone, a fold kind or a mark kind neither the core nor that module declares."""
        every = blocks.every()
        spans = [
            *blocks.summary,
            *(
                span
                for block in every
                if isinstance(block, Line)
                for span in block.spans
            ),
            *(
                span
                for block in every
                if isinstance(block, Fold)
                for span in block.summary
            ),
        ]
        used = [
            *(Used(what="tone", name=span.tone) for span in spans),
            *(
                Used(what="fold kind", name=block.kind)
                for block in every
                if isinstance(block, Fold)
            ),
            *(
                Used(what="mark kind", name=mark.kind)
                for block in every
                if isinstance(block, Code | Diff)
                for mark in block.marks
            ),
        ]
        allowed = {
            "tone": self.named(self.tones, module),
            "fold kind": self.named(self.folds, module),
            "mark kind": self.named(self.marks, module),
        }
        unknown = [
            f"the {each.what} `{each.name}`"
            for each in dict.fromkeys(used)
            if each.name not in allowed[each.what]
        ]
        if unknown:
            message = (
                f"a view of `{module}` names {listed(unknown)}, which neither the "
                f"core nor `{module}` declares"
            )
            raise BlockError(message, about=[module])


def apart(what: str, named: list[Owned[str]]) -> None:
    """Raise `ProjectError` where two modules give one name of `what`, naming both: each of `named` is a name, with the module giving it."""
    pairs = [
        (one, other)
        for at, one in enumerate(named)
        for other in named[at + 1 :]
        if one.kind == other.kind
    ]
    if pairs:
        clashes = [
            f"`{one.kind}` by `{one.module}` and `{other.module}`"
            for one, other in pairs
        ]
        about = [each.module for pair in pairs for each in pair]
        message = f"a {what} is one module's, and {'; '.join(clashes)} share one"
        raise ProjectError(message, about=list(dict.fromkeys(about)))


async def viewed(
    doors: Running,
    looks: Looks,
    module: str,
    view: str,
    given: JsonValue,
    by: Party,
) -> Accepted | Refused:
    """Answer the view `view` of the module named `module` for `given`, read by `by`, and say what came of it.

    Raise `BlockError` where what it answers names a kind neither the core nor
    its module declares: the view's fault, not the caller's.
    """
    answered = await doors.reached(ViewDoor, module, view, given, by)
    output = getattr(answered, "output", None)
    if isinstance(output, Blocks):
        looks.checked(output, module)
    return answered
