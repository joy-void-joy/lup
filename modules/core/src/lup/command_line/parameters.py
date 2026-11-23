"""A method's model, as the command line takes it: each field an argument or an option, read from the JSON Schema of the model the plan carries.

A field with no default is an argument; one with a default is an option, named
for the field's alias, else its name, as typer names one (`-` for `_`); a `bool`
is a flag, a `list` is repeated, a field limited to some words takes one of
them, and a field the command line can't say in words (a model, a mapping) is
written as JSON. A field's description, its docstring, is its help. An option left out isn't
sent, so the model's own default applies, whatever it is; but a field marked to be
filled from where it's typed (`lup.command_line.filled`), which is an option
whatever its default, and is filled from there.
"""

import inspect
import json
from enum import Enum, EnumType
from types import GenericAlias, UnionType
from typing import Literal

import typer
from pydantic import Field, JsonValue
from typer.main import get_command_name

from lup.command_line.filled import MARK, Filled, Marked, TypedIn
from lup.types import JsonObject, Model

type Kind = Literal["text", "integer", "number", "flag", "choice", "json"]
"""What a field takes, as the command line parses it."""

type Word = str | int | float | bool | Enum
"""A value typer parses from one word, as its parameter's type gives it."""

type Parsed = Word | list[Word] | None
"""What typer hands back for a parameter: a word's value, several, or none
where it's left out."""


def kind_of(type_: str) -> Kind:
    """Return the kind of a field of the JSON Schema type `type_`: a word of it, where the command line parses one, else JSON.

    >>> kind_of("integer"), kind_of("object")
    ('integer', 'json')
    """
    match type_:
        case "string":
            return "text"
        case "integer":
            return "integer"
        case "number":
            return "number"
        case "boolean":
            return "flag"
        case _:
            return "json"


def parsed_as(kind: Kind) -> type:
    """Return the type typer parses a word of `kind` as, but a choice, whose type is its own words."""
    match kind:
        case "integer":
            return int
        case "number":
            return float
        case "flag":
            return bool
        case "text" | "json" | "choice":
            return str


def choosing(name: str, words: list[str]) -> type[Enum]:
    """Return a type whose values are `words`, which typer parses one of, listing them in help.

    It's `Enum`'s functional API, called through its metaclass, which pyright
    reads as making a class rather than looking a member up.

    >>> [each.value for each in choosing("Shade", ["dark", "light"])]
    ['dark', 'light']
    """
    return EnumType.__call__(Enum, name, names={each: each for each in words})


class Schema(Model):
    """A JSON Schema, as much of it as the command line reads: a field's type, what it's limited to, its default and its description, and a model's fields."""

    type: str | list[str] | None = None
    enum: list[JsonValue] | None = None
    const: JsonValue = None
    items: Schema | None = None
    any_of: list[Schema] = Field(default=[], alias="anyOf")
    ref: str | None = Field(default=None, alias="$ref")
    default: JsonValue = None
    description: str | None = None
    properties: dict[str, Schema] = {}
    required: list[str] = []
    defs: dict[str, Schema] = Field(default={}, alias="$defs")
    marked: Marked | None = Field(default=None, alias=MARK)
    """What its mark says of it: filled from where it's typed, or the words
    said with a verb; none where it's unmarked."""

    def marking(self, defs: dict[str, Schema]) -> Marked | None:
        """Return what its mark says of it, as it or the schema it refers to is marked, an optional field's among them; none where neither is."""
        if self.marked is not None:
            return self.marked
        if self.ref is not None:
            named = {f"#/$defs/{name}": each for name, each in defs.items()}
            found = named.get(self.ref)
            return None if found is None else found.marking(defs)
        others = [each for each in self.any_of if each.type != "null"]
        if self.any_of and len(others) == 1:
            return others[0].marking(defs)
        return None

    def filling(self, defs: dict[str, Schema]) -> Filled | None:
        """Return what the command line fills it with where it's left out; none where it's marked as words or not at all."""
        marked = self.marking(defs)
        return None if marked == "words" else marked

    def defaulted(self) -> bool:
        """Say whether it gives a default."""
        return "default" in self.model_fields_set

    def resolved(self, defs: dict[str, Schema]) -> Schema:
        """Return the schema it refers to among `defs`, or itself where it refers to none; one that may also be null, as an optional field is, is read as what it is otherwise."""
        if self.ref is not None:
            named = {f"#/$defs/{name}": each for name, each in defs.items()}
            found = named.get(self.ref)
            return self if found is None else found.resolved(defs)
        others = [each for each in self.any_of if each.type != "null"]
        if self.any_of and len(others) == 1:
            return others[0].resolved(defs)
        return self

    def words(self) -> list[str] | None:
        """Return the words it's limited to, where every value it may take is one; none where it isn't so limited."""
        values = (
            self.enum
            if self.enum is not None
            else [self.const]
            if "const" in self.model_fields_set
            else None
        )
        if values is None or not all(isinstance(each, str) for each in values):
            return None
        return [str(each) for each in values]

    def kind(self) -> Kind:
        """Return what it takes, as the command line parses it."""
        if self.words() is not None:
            return "choice"
        return kind_of(self.type) if isinstance(self.type, str) else "json"


class Parameter(Model):
    """One field of a method's model, as the command line takes it: an argument where it has no default, else an option."""

    key: str
    """The field as what's sent names it: its alias, else its name."""
    position: int
    """Its place among the model's fields, which names it to typer."""
    kind: Kind
    many: bool = False
    """Whether it takes several, each a word: a `list`, an option repeated."""
    words: list[str] = []
    """The words a choice takes."""
    required: bool
    default: JsonValue = None
    """Its default, as help shows it."""
    defaulted: bool = False
    """Whether the schema gives its default, which help shows."""
    description: str | None = None
    filled: Filled | None = None
    """What the command line fills it with where it's left out: an option
    then, whatever its default."""
    said: bool = False
    """Whether it takes the words said with a verb (`lup.Words`): what's typed
    after what's cited."""

    @classmethod
    def of(cls, position: int, key: str, field: Schema, model: Schema) -> Parameter:
        """Return how the command line takes the field `key` of `model`, the `position`th."""
        plain = field.resolved(model.defs)
        each = plain.items.resolved(model.defs) if plain.items is not None else None
        many = plain.type == "array" and each is not None and each.kind() != "json"
        taken = each if many and each is not None else plain
        return cls(
            key=key,
            position=position,
            kind=taken.kind(),
            many=many,
            words=taken.words() or [],
            required=key in model.required,
            default=field.default,
            defaulted=field.defaulted(),
            description=field.description or plain.description,
            filled=field.filling(model.defs),
            said=field.marking(model.defs) == "words",
        )

    @property
    def name(self) -> str:
        """Its name to typer, which hands its value back by it."""
        return f"given_{self.position}"

    def option(self) -> str:
        """Return its option, as typer names one: `--` and its key, each `_` a `-`."""
        return f"--{get_command_name(self.key)}"

    def options(self) -> list[str]:
        """Return the names typer takes it by as an option: its own, and `-r` for a repository filled from where it's typed."""
        option = self.option()
        if self.kind == "flag" and not self.many and self.default is True:
            return [f"{option}/--no-{option.removeprefix('--')}"]
        return [*(["-r"] if self.filled == "repository" else []), option]

    def helped(self, typed_in: TypedIn) -> str | None:
        """Return its help: its description, then what fills it where it's left out, or its default where it's an option whose schema gives one."""
        match self.filled:
            case "repository":
                filled = typed_in.repository or "none: name one, outside a worktree"
                return f"{self.description or 'The repository.'}  [left out: {filled}]"
            case "common":
                filled = typed_in.common or "none: name one, outside a worktree"
                return (
                    f"{self.description or 'Where git keeps it.'}  [left out: {filled}]"
                )
            case None:
                pass
        if self.required or not self.defaulted:
            return self.description
        default = f"[default: {json.dumps(self.default)}]"
        return f"{self.description}  {default}" if self.description else default

    def annotation(self) -> type | GenericAlias:
        """Return the type typer parses it as: a word of its kind, one of its words, or a list of either."""
        one = (
            choosing(f"Choice{self.position}", self.words)
            if self.kind == "choice"
            else parsed_as(self.kind)
        )
        return GenericAlias(list, one) if self.many else one

    def optional(self) -> UnionType | type:
        """Return the type typer parses it as, or none where it's left out."""
        return self.annotation() | None

    def parameter(self, typed_in: TypedIn) -> inspect.Parameter:
        """Return it as a parameter of the function typer builds a command from: an argument, required, or an option, left out where it isn't given; one filled from where it's typed is an option, whatever its default, its help saying what fills it there (`typed_in`)."""
        if self.required and self.filled is None:
            given = typer.Argument(
                ...,
                metavar=self.key.upper(),
                help=self.description,
                show_default=False,
            )
            annotation = self.annotation()
        else:
            given = typer.Option(
                None,
                *self.options(),
                help=self.helped(typed_in),
                show_default=False,
            )
            annotation = self.optional()
        return inspect.Parameter(
            self.name,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=annotation,
            default=given,
        )

    def sent(self, value: Parsed) -> JsonValue:
        """Return a value typer parsed for it as it's sent: a choice as its word, several as a list, and what's written as JSON read as JSON, or as the words written where they aren't JSON."""
        match value:
            case Enum():
                return str(value.value)
            case list():
                return [self.sent(each) for each in value]
            case str() if self.kind == "json":
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            case _:
                return value


def parameters(schema: JsonObject) -> list[Parameter]:
    """Return how the command line takes each field of the model `schema` describes, in order."""
    model = Schema.model_validate(schema)
    return [
        Parameter.of(position, key, field, model)
        for position, (key, field) in enumerate(model.properties.items())
    ]


def sent(
    taken: list[Parameter], values: dict[str, Parsed], typed_in: TypedIn
) -> JsonObject:
    """Return what's sent for the values typer parsed, by each parameter's name: each field given, by its key, none left out, and each marked to be filled from where it's typed (`typed_in`) filled there.

    Raise `typer.BadParameter` where one isn't given and the command line is
    typed in no repository's worktree: the words don't parse, and nothing
    runs.
    """

    def filled(parameter: Parameter, value: Parsed) -> JsonValue:
        """Return what's sent for `parameter`, marked to be filled from where it's typed: the value given, or, left out, what fills it there."""
        if value is not None:
            return parameter.sent(value)
        found = (
            typed_in.repository
            if parameter.filled == "repository"
            else None
            if typed_in.common is None
            else str(typed_in.common)
        )
        if found is None:
            option = " / ".join(f"'{each}'" for each in parameter.options())
            message = (
                f"{typed_in.directory} is in no repository's worktree: name it "
                f"with {option}"
            )
            raise typer.BadParameter(message, param_hint=option)
        return found

    return {
        each.key: (
            each.sent(values[each.name])
            if each.filled is None
            else filled(each, values.get(each.name))
        )
        for each in taken
        if each.filled is not None or values.get(each.name) is not None
    }
