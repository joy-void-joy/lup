"""What a declared kind is called and what it accepts, read off its declaration.

Two surfaces take a kind by name and fields by object — the console and the
tool group — and both have to agree with what the type will validate. So the
name is the literal the type spells for itself, and the fields are its own
declaration minus what the store stamps, computed from the class rather than
written beside it where they could drift.
"""

from pydantic.fields import FieldInfo

from lup.ledger.models import LedgerEdge, LedgerNode


def kind_of(declared: type[LedgerNode] | type[LedgerEdge]) -> str:
    """The kind a declared type records itself under.

    The `kind` field's default is the literal the type spells, so a word a
    caller passes is matched against what the type would write, not against a
    class name somebody has to know.
    """
    return str(declared.model_fields["kind"].default)


def by_kind[T: LedgerNode | LedgerEdge](declared: list[type[T]]) -> dict[str, type[T]]:
    """Each declared type under the kind it answers to."""
    return {kind_of(each): each for each in declared}


def spelled(field: FieldInfo) -> str:
    """One field's type as a caller reads it: the class name, or the alias whole."""
    annotation = field.annotation
    return annotation.__name__ if isinstance(annotation, type) else str(annotation)


def declared_fields(declared: type[LedgerNode] | type[LedgerEdge]) -> list[str]:
    """Each field a caller may pass, spelled with its type and its default.

    The stamped ones — id, author, time, kind, endpoints, attachments — are left
    out because a caller cannot set them, and listing them would invite a
    payload the store then overrules.
    """
    stamped = {"id", "kind", "author", "at", "attachments", "source", "target"}
    return [
        f"{name}: {spelled(field)}"
        + ("" if field.is_required() else f" = {field.default!r}")
        for name, field in declared.model_fields.items()
        if name not in stamped
    ]


def summary_of(declared: type[LedgerNode] | type[LedgerEdge]) -> str:
    """The first line of a type's own docstring, which is what it is for."""
    lines = (declared.__doc__ or "").strip().splitlines()
    return lines[0] if lines else ""
