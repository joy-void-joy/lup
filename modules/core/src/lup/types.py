"""The types every model and settings class starts from, in lup and its projects.

Models are frozen by default: a value never changes once made. The default lives
in these bases, so no model writes `frozen` itself. A model that must change
derives from `MutableModel`, which says so where the class is declared.

A field's docstring, the string standing alone under it, is its description in
the model's JSON Schema, which a tool's input and a command's help carry
(`described`). It's read as a schema is written, never as a class is made:
pydantic's own `use_attribute_docstrings` reads each class's source as it's
defined, which made importing lup's models about half as slow again.
"""

from functools import cache
from itertools import pairwise
from typing import dataclass_transform
lazy import ast
lazy import inspect
lazy import textwrap

from pydantic import BaseModel, Field, JsonValue, PrivateAttr
from pydantic._internal._model_construction import ModelMetaclass
from pydantic_settings import BaseSettings, SettingsConfigDict


@cache
def written(model: type) -> dict[str, str]:
    """Return the docstring written under each field the class `model` itself declares, by the field's name: a string standing alone just after it; none where its source can't be read. A class's source is read once, at the first schema written for it."""
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(model)))
    except OSError, TypeError, SyntaxError:
        return {}
    defined = next((each for each in tree.body if isinstance(each, ast.ClassDef)), None)
    if defined is None:
        return {}
    return {
        field.target.id: inspect.cleandoc(said.value.value)
        for field, said in pairwise(defined.body)
        if isinstance(field, ast.AnnAssign)
        and isinstance(field.target, ast.Name)
        and isinstance(said, ast.Expr)
        and isinstance(said.value, ast.Constant)
        and isinstance(said.value.value, str)
    }


def described(schema: dict[str, JsonValue], model: type) -> None:
    """Describe each field of `model`'s JSON Schema, `schema`, by its docstring, where nothing else describes it: pydantic calls it as it writes a model's schema.

    A class's own docstrings win over those of the classes it derives from.

    >>> from lup.running.plan import Doorway
    >>> Doorway.model_json_schema()["properties"]["description"]["description"]
    "Its docstring, which describes it: a command's help."
    """
    docs: dict[str, str] = {}
    for each in reversed(model.__mro__):
        if issubclass(each, BaseModel) and each is not BaseModel:
            docs |= written(each)
    # lup: ignore("dict-literal-key", why="a JSON Schema is the dict pydantic hands its hook to change in place, `properties` its fields by name")
    properties = schema.get("properties")
    fields = model.model_fields if issubclass(model, BaseModel) else {}
    if not isinstance(properties, dict):
        return
    for name, field in fields.items():
        shown = properties.get(field.alias or name)
        if name in docs and isinstance(shown, dict) and "description" not in shown:
            shown["description"] = docs[name]


@dataclass_transform(
    kw_only_default=True,
    frozen_default=True,
    field_specifiers=(Field, PrivateAttr),
)
class FrozenModelMetaclass(ModelMetaclass):
    """Tell type checkers every subclass of `Model` is frozen, without it saying so.

    pyright reads a model's frozenness from its own class keywords, so a subclass of
    a frozen base that doesn't repeat `frozen=True` counts as mutable, and as an
    error ("a non-frozen class cannot inherit from a class that is frozen"). Marking
    the metaclass frozen by default (PEP 681's `frozen_default`) makes silence mean
    frozen, and keeps pyright refusing assignment to a field. It extends pydantic's
    own metaclass, which pydantic keeps in a private module.
    """


class Model(
    BaseModel,
    metaclass=FrozenModelMetaclass,
    frozen=True,
    json_schema_extra=described,
):
    """Start every model from this: frozen, so a value never changes once made.

    Frozen models can be hashed, and compared by their fields:

    >>> class Point(Model):
    ...     x: int
    >>> Point(x=1) == Point(x=1) and hash(Point(x=1)) == hash(Point(x=1))
    True
    """


class MutableModel(BaseModel, json_schema_extra=described):
    """Start a model from this when its values must change after it's made.

    It's the rare case, said where the model is declared.
    """


class Settings(BaseSettings):
    """Start every settings class from this: read from the environment, then frozen.

    Each field is an environment variable, so a package's settings class is where
    the variables it reads are named. The freeze is in its configuration rather
    than its class keywords: pydantic's settings base isn't frozen, and pyright
    refuses a frozen class over it.
    """

    model_config = SettingsConfigDict(frozen=True)


type JsonObject = dict[str, JsonValue]
"""A JSON object whose schema lives elsewhere: a vendor's payload, a tool's input."""
