"""`Done`: what a command answers, the data of what it did, and the one line the command line prints of it.

A command's answer derives from `Done` and gives `line`, a template over its own
fields, each named in braces as `str.format` reads one (`"sent to {to},
@{comment}"`). The class is refused as it's defined where `line` names something
that isn't one of its fields or breaks onto a second line, so the line says
nothing the data doesn't hold, in one line. Where the answer differs, the command
answers a union of `Done`s, and which class it is chooses the line: the line is
never built by the command's code.

What's printed of it is `shown`: the line, each field's value as its JSON says
it, set forward, and under it, a line each, every `Done` a field holds that the
line doesn't name, as `lup new`'s answer holds one for each program missing.
It's made where the command is answered, which has the class
(`lup.running.wire.replied`), since the command line has only the plan and the
answer's data.
"""

from string import Formatter
from types import UnionType
from typing import ClassVar, get_args

from pydantic import BaseModel, JsonValue
from pydantic_core import to_json

from lup.doors.door import Annotation, DoorError, is_model
from lup.types import Model
lazy from lup.shell.blocks import Blocks, Line, Span


class Placed(Model):
    """A run of a `Done`'s line: its template's own words, then the field named after them, where one is, and how it's formatted."""

    words: str
    field: str | None = None
    spec: str = ""


def placed(line: str) -> list[Placed]:
    """Return the runs of `line`, a template, in order, as `str.format` reads it.

    Raise `ValueError` where it isn't a template `str.format` reads.

    >>> [(each.words, each.field) for each in placed("sent to {to}, @{comment}")]
    [('sent to ', 'to'), (', @', 'comment')]
    """
    return [
        Placed(words=parsed[0], field=parsed[1], spec=parsed[2] or "")
        for parsed in Formatter().parse(line)
    ]


def worded(value: JsonValue, spec: str = "") -> str:
    """Return a field's value, as its JSON says it, as a `Done`'s line says it: words and numbers as they are, several joined by commas, nothing as `none`, and anything else as its JSON.

    >>> worded(["a", "b"]), worded(None), worded(3), worded("1a2b3c4d", ".4")
    ('a, b', 'none', '3', '1a2b')
    """
    match value:
        case None:
            return "none"
        case list():
            return ", ".join(worded(each, spec) for each in value)
        case dict():
            return to_json(value).decode()
        case _:
            return format(value, spec)


class Done(Model):
    """What a command did: the data of it, and the one line the command line prints of it, `line`, a template over its own fields."""

    line: ClassVar[str] = ""
    """What it did, in one line, each field it names in braces: `sent to {to},
    @{comment}`. Each class deriving from `Done` gives its own."""

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Refuse a `Done` whose line is missing, breaks onto a second line, or names something that isn't one of its fields."""
        super().__pydantic_init_subclass__(**kwargs)
        name = cls.__qualname__
        if not cls.line:
            message = (
                f"`{name}` says what a command did in its `line`, which it doesn't give"
            )
            raise DoorError(message)
        if "\n" in cls.line:
            message = (
                f"`{name}.line` breaks onto a second line: a `Done` says what it "
                "did in one"
            )
            raise DoorError(message)
        try:
            runs = placed(cls.line)
        except ValueError as unread:
            message = f"`{name}.line` isn't a template `str.format` reads: {unread}"
            raise DoorError(message) from unread
        unknown = [
            each.field
            for each in runs
            if each.field is not None and each.field not in cls.model_fields
        ]
        if unknown:
            fields = ", ".join(f"`{each}`" for each in cls.model_fields) or "none"
            said = ", ".join(f"`{{{each}}}`" for each in unknown)
            message = (
                f"`{name}.line` names {said}, which isn't a field of `{name}`: "
                f"its fields are {fields}"
            )
            raise DoorError(message)

    def spans(self) -> list[Span]:
        """Return its line in spans: its template's own words plain, each field's value set forward."""
        data = self.model_dump(mode="json")
        return [
            span
            for each in placed(self.line)
            for span in [
                *([Span(text=each.words)] if each.words else []),
                *(
                    []
                    if each.field is None
                    else [Span(text=worded(data[each.field], each.spec), tone="strong")]
                ),
            ]
        ]

    def held(self) -> list[Done]:
        """Return each `Done` its fields hold that its line doesn't name, in the fields' order: what's printed under its line."""
        named = [each.field for each in placed(self.line)]

        def within(value: BaseModel | list[BaseModel] | JsonValue) -> list[Done]:
            match value:
                case Done():
                    return [value]
                case list():
                    return [each for each in value if isinstance(each, Done)]
                case _:
                    return []

        return [
            each
            for field in type(self).model_fields
            if field not in named
            for each in within(getattr(self, field))
        ]

    def shown(self) -> Blocks:
        """Return what the command line prints of it: its line, then each `Done` it holds, a line each, set in under it."""

        def lines(done: Done, depth: int) -> list[list[Span]]:
            indent = [Span(text="  " * depth)] if depth else []
            return [
                [*indent, *done.spans()],
                *(line for each in done.held() for line in lines(each, depth + 1)),
            ]

        return Blocks.of(
            *(
                Line(id=f"done-{at}", spans=spans)
                for at, spans in enumerate(lines(self, 0))
            )
        )


def is_done(annotation: Annotation) -> bool:
    """Say whether a method answering `annotation` answers a `Done`: one class deriving from it, or a union of them.

    >>> class Sent(Done):
    ...     line = "sent to {to}"
    ...     to: str
    >>> is_done(Sent), is_done(Sent | None), is_done(str), is_done(Done)
    (True, False, False, False)
    """
    if isinstance(annotation, UnionType):
        return all(is_done(each) for each in get_args(annotation))
    return (
        is_model(annotation) and issubclass(annotation, Done) and annotation is not Done
    )
