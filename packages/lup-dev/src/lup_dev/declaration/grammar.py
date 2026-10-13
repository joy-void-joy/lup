"""The grammar every kind of a declaration is written in: a selection, recorded.

A selection is where a kind's entries start from and the operations changing
them, kept as they were written (`docs/declaration.md`, *One grammar for every
kind*):
- `Kind()` starts from the value below: what an earlier layer gave, or the
  module's own default where nothing is below;
- `Kind.default()`, `Kind.all()`, `Kind.only(…)` and `Kind.of(…)` start over;
- `.add`, `.drop` and `.replace` change what it started from, each returning a
  selection with the operation recorded after the others.

Everything a declaration writes is a change on the value below it. A module, or a
model of settings such as `Session` (a `Layer`), applies the fields it set
(`applied`). A selection layers by its start: over the selection below, one
starting from below keeps below's start and adds its operations after below's,
and one starting over replaces it. It's resolved into entries only when the
declaration is read, against the defaults of the module holding it, so
`Rules.default().drop(…)` takes whatever a later release adds to the default, and
`Rules.only(…)` doesn't.
"""

from functools import reduce
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from lup.types import Model
from lup_dev.declaration.errors import ProjectError


def listed(names: list[str]) -> str:
    """Name each of `names` in backticks, for a message.

    >>> listed(["ruff", "pytest", "pyright"])
    '`ruff`, `pytest` and `pyright`'
    >>> listed([])
    'none'
    """
    if not names:
        return "none"
    *first, last = [f"`{name}`" for name in names]
    if not first:
        return last
    return f"{', '.join(first)} and {last}"


def set_fields(model: Model) -> list[str]:
    """List the fields `model` was given, in the order they're declared.

    A field given, even at its default value, counts as given.
    """
    return [
        field for field in type(model).model_fields if field in model.model_fields_set
    ]


def applied[M: Model](layer: M, below: M, fields: list[str]) -> M:
    """Return `below` with `layer`'s `fields` on it, each a change on below's.

    A field holding a selection or a `Layer` composes over below's, as a layer
    itself; any other takes below's place. Every other field stays as below has
    it (`docs/declaration.md`, *The verbs on modules*). Modules and `Layer`s
    layer this way, by the fields they set.
    """
    update = {
        field: value.over(getattr(below, field))
        if issubclass(type(value := getattr(layer, field)), Selection | Layer)
        else value
        for field in fields
    }
    return below.model_copy(update=update)


class Layer(Model):
    """A model of settings a declaration changes field by field, as a module is.

    Over the one below, the fields it set apply, each a change on below's (a
    selection it holds composing over below's), and the rest stay as below has
    them: so a layer setting one field keeps whatever below holds in the others.

    >>> class Volume(Layer):
    ...     level: int = 5
    ...     muted: bool = False
    >>> Volume(muted=True).over(Volume(level=9))
    Volume(level=9, muted=True)
    """

    def over(self, below: Self) -> Self:
        """Return this layer over `below`: the fields it set, on below's."""
        return applied(self, below, set_fields(self))


class Anchor(Model):
    """Where entries go among their kind's entries, from every module.

    Before or after another entry of the kind, by its name, whichever module holds
    it; with neither, in the order of their modules in `Modules`, and within one
    module in the order written.
    """

    before: str | None = None
    after: str | None = None

    @model_validator(mode="after")
    def one_side(self) -> Self:
        """Refuse an entry placed both before one entry and after another."""
        if self.before is not None and self.after is not None:
            message = (
                f"an entry goes `before={self.before!r}` or `after={self.after!r}`, "
                "not both"
            )
            raise ProjectError(message)
        return self

    def anchored(self) -> dict[str, str | None]:
        """Return where this goes, as the update that puts another entry there."""
        return {"before": self.before, "after": self.after}


class Below(Model):
    """Start from the value below: `Kind()`."""

    kind: Literal["below"] = "below"


class Default(Model):
    """Start from the defaults: `Kind.default()`.

    lup's for `Modules`; inside a module, the module's own for the part.
    """

    kind: Literal["default"] = "default"


class All(Model):
    """Start from every entry lup ships, where that's more than the default."""

    kind: Literal["all"] = "all"


class Only(Model):
    """Start from these known entries and no other, by name: `Kind.only(…)`."""

    kind: Literal["only"] = "only"
    names: list[str]


class Of[E](Anchor):
    """Start from these entries, with no defaults: `Kind.of(…)`."""

    kind: Literal["of"] = "of"
    entries: list[E]


class Add[E](Anchor):
    """Add entries beside the ones there: `.add(…)`."""

    verb: Literal["add"] = "add"
    entries: list[E]


class Drop(Model):
    """Leave out the entries of these names: `.drop(…)`."""

    verb: Literal["drop"] = "drop"
    names: list[str]
    why: str | None = None


class Replace[E](Model):
    """Put an entry in place of the one of this name: `.replace(…)`."""

    verb: Literal["replace"] = "replace"
    name: str
    entry: E
    why: str | None = None


class Edit[E](Model):
    """Put a layer on the entry of the same name: `.edit(…)`, on modules."""

    verb: Literal["edit"] = "edit"
    entry: E
    why: str | None = None


class Placed[E](Anchor):
    """An entry as a selection resolves it: where it goes, and who put it there."""

    entry: E
    position: int = 0
    """The place in its selection's chain of what put it there: 0 for the start,
    then one for each operation."""
    why: str | None = None
    """The reason given with what put it there."""


class Selection[E](Model):
    """A kind's entries: where they start from, and the operations changing them.

    Each kind is a subclass binding its entry, and saying how an entry is named
    where it differs from the entry itself (`named`).
    """

    start: Annotated[
        Below | Default | All | Only | Of[E], Field(discriminator="kind")
    ] = Below()
    operations: list[
        Annotated[Add[E] | Drop | Replace[E] | Edit[E], Field(discriminator="verb")]
    ] = []

    @classmethod
    def starting(cls, start: Below | Default | All | Only | Of[E]) -> Self:
        """Return a selection starting from `start`, with no operations yet."""
        return cls(start=start)

    @classmethod
    def default(cls) -> Self:
        """Start from the defaults: lup's, or inside a module, the module's own."""
        return cls.starting(Default())

    @classmethod
    def all(cls) -> Self:
        """Start from every entry lup ships, where that's more than the default."""
        return cls.starting(All())

    def add(
        self, *entries: E, before: str | None = None, after: str | None = None
    ) -> Self:
        """Add `entries` beside the ones there; a name already there is an error."""
        return self.then(Add(entries=list(entries), before=before, after=after))

    def drop(self, *names: str, why: str | None = None) -> Self:
        """Leave out the entries named `names`; a name not there is an error."""
        return self.then(Drop(names=list(names), why=why))

    def replace(self, name: str, entry: E, why: str | None = None) -> Self:
        """Put `entry` in place of the one named `name`, which must be there."""
        return self.then(Replace(name=name, entry=entry, why=why))

    def then(self, operation: Add[E] | Drop | Replace[E] | Edit[E]) -> Self:
        """Return this selection with `operation` recorded after its own."""
        return type(self)(start=self.start, operations=[*self.operations, operation])

    def named(self, entry: E) -> str:
        """Return the name `entry` goes by among its kind's: itself, for names."""
        return str(entry)

    def over(self, below: Self) -> Self:
        """Return this selection as a layer over `below`.

        Starting from the value below, it keeps below's start and records its
        operations after below's; starting over, it replaces below whole.
        """
        if not isinstance(self.start, Below):
            return self
        operations = [*below.operations, *self.operations]
        return type(self)(start=below.start, operations=operations)

    def resolve(self, defaults: list[E], known: list[E]) -> list[Placed[E]]:
        """Resolve this selection into its entries, each with where it goes.

        `defaults` are what `Kind()` and `Kind.default()` start from, `known` what
        `Kind.all()` starts from and `Kind.only(…)` picks from. Raise
        `ProjectError` on a name that isn't there, naming the ones that are, and
        on adding a name that's already there.
        """
        entries = self.started(defaults, known)
        for position, operation in enumerate(self.operations, start=1):
            entries = self.applied(entries, operation, position)
        return entries

    def started(self, defaults: list[E], known: list[E]) -> list[Placed[E]]:
        """Return the entries this selection starts from, as its start says."""
        match self.start:
            case Below() | Default():
                chosen = [Placed(entry=entry) for entry in defaults]
            case All():
                chosen = [Placed(entry=entry) for entry in known]
            case Only(names=names):
                by_name = {self.named(entry): entry for entry in known}
                self.present("only", names, list(by_name))
                chosen = [Placed(entry=by_name[name]) for name in names]
            case Of(entries=entries, before=before, after=after):
                chosen = [
                    Placed(entry=entry, before=before, after=after) for entry in entries
                ]
        names = [self.named(each.entry) for each in chosen]
        twice = [name for at, name in enumerate(names) if name in names[:at]]
        if twice:
            kind = type(self).__name__
            message = f"`{kind}` starts from {listed(twice)} more than once"
            raise ProjectError(message)
        return [self.placed(each) for each in chosen]

    def applied(
        self,
        entries: list[Placed[E]],
        operation: Add[E] | Drop | Replace[E] | Edit[E],
        position: int,
    ) -> list[Placed[E]]:
        """Return `entries` with `operation`, at `position` in the chain, applied."""
        names = [self.named(each.entry) for each in entries]
        kind = type(self).__name__
        match operation:
            case Add(entries=added, before=before, after=after):
                adding = [self.named(entry) for entry in added]
                there = [
                    name
                    for at, name in enumerate(adding)
                    if name in names or name in adding[:at]
                ]
                if there:
                    message = (
                        f"`{kind}.add` names {listed(there)}, already there: "
                        "`.replace` puts another in its place"
                    )
                    raise ProjectError(message)
                return [
                    *entries,
                    *(
                        self.placed(
                            Placed(
                                entry=entry,
                                before=before,
                                after=after,
                                position=position,
                            )
                        )
                        for entry in added
                    ),
                ]
            case Drop(names=dropped):
                self.present("drop", dropped, names)
                return [
                    each for each in entries if self.named(each.entry) not in dropped
                ]
            case Replace(name=name, entry=entry, why=why):
                self.present("replace", [name], names)
                renamed = self.named(entry)
                if renamed != name and renamed in names:
                    message = (
                        f"`{kind}.replace` puts `{renamed}` in place of `{name}`, "
                        f"but `{renamed}` is already there"
                    )
                    raise ProjectError(message)
                put = Placed(entry=entry, position=position, why=why)
                return [
                    self.placed(put.model_copy(update=each.anchored()))
                    if self.named(each.entry) == name
                    else each
                    for each in entries
                ]
            case Edit(entry=entry, why=why):
                name = self.named(entry)
                self.present("edit", [name], names)
                layer = Placed(entry=entry, position=position, why=why)
                return [
                    self.edited(each, layer) if self.named(each.entry) == name else each
                    for each in entries
                ]

    def placed(self, placed: Placed[E]) -> Placed[E]:
        """Return an entry as it's placed in the chain: as it is, for most kinds."""
        return placed

    def edited(self, below: Placed[E], layer: Placed[E]) -> Placed[E]:
        """Return the entry `below` with `layer` on it.

        For most kinds, `layer` takes its place where `below` was.
        """
        return layer.model_copy(update=below.anchored())

    def present(self, verb: str, names: list[str], there: list[str]) -> None:
        """Raise `ProjectError` where `.verb` names an entry that isn't there."""
        missing = [name for name in names if name not in there]
        if not missing:
            return
        kind = type(self).__name__
        message = (
            f"`{kind}.{verb}` names {listed(missing)}, which isn't there; "
            f"there are {listed(there)}"
        )
        raise ProjectError(message)

    def ordered(self, placed: list[Placed[E]]) -> list[E]:
        """Order this kind's entries from every module, by their anchors.

        Entries placed `before=` or `after=` another go there, whichever module
        holds it, in the order they're written; the rest keep the order they come
        in. An anchor that names no entry, or anchors that only place each other,
        raise `ProjectError`.
        """
        names = [self.named(each.entry) for each in placed]
        kind = type(self).__name__
        unknown = [
            anchor
            for each in placed
            for anchor in [each.before, each.after]
            if anchor is not None and anchor not in names
        ]
        if unknown:
            message = (
                f"`{kind}` places entries by {listed(unknown)}, which isn't there; "
                f"there are {listed(names)}"
            )
            raise ProjectError(message)

        def inserted(order: list[Placed[E]], each: Placed[E]) -> list[Placed[E]]:
            there = [self.named(one.entry) for one in order]
            match each:
                case Placed(before=str() as before):
                    at = there.index(before)
                case Placed(after=str() as after):
                    anchor = there.index(after)
                    at = next(
                        (
                            index
                            for index in range(anchor + 1, len(order))
                            if order[index].after != after
                        ),
                        len(order),
                    )
                case _:
                    at = len(order)
            return [*order[:at], each, *order[at:]]

        order = [each for each in placed if each.before is None and each.after is None]
        waiting: list[Placed[E]] = [
            each for each in placed if each.before is not None or each.after is not None
        ]
        while waiting:
            there = [self.named(each.entry) for each in order]
            ready: list[Placed[E]] = [
                each for each in waiting if (each.before or each.after) in there
            ]
            if not ready:
                stuck = [self.named(each.entry) for each in waiting]
                message = (
                    f"`{kind}` places {listed(stuck)} only by each other, "
                    "so none of them has a place"
                )
                raise ProjectError(message)
            order = reduce(inserted, ready, order)
            waiting = [each for each in waiting if each not in ready]
        return [each.entry for each in order]


class Named[E](Selection[E]):
    """A selection whose entries carry no settings of their own to choose by.

    `Kind.only(…)` picks known entries by name, and `Kind.of(…)` gives a module's
    own entries.
    """

    @classmethod
    def of(
        cls, *entries: E, before: str | None = None, after: str | None = None
    ) -> Self:
        """Start from `entries`, with no defaults: a module's own."""
        return cls.starting(Of(entries=list(entries), before=before, after=after))

    @classmethod
    def only(cls, *names: str) -> Self:
        """Start from the known entries named `names`, and no other."""
        return cls.starting(Only(names=list(names)))
