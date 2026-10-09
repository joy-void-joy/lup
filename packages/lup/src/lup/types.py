"""The types every model and settings class starts from, in lup and its projects.

Models are frozen by default (`docs/conventions.md`, *Data shapes*): a value never
changes once made. The default lives in these bases, so no model writes `frozen`
itself. A model that must change derives from `MutableModel`, which says so where
the class is declared.
"""

from typing import dataclass_transform

from pydantic import BaseModel, Field, JsonValue, PrivateAttr
from pydantic._internal._model_construction import ModelMetaclass
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class Model(BaseModel, metaclass=FrozenModelMetaclass, frozen=True):
    """Start every model from this: frozen, so a value never changes once made.

    Frozen models can be hashed, and compared by their fields:

    >>> class Point(Model):
    ...     x: int
    >>> Point(x=1) == Point(x=1) and hash(Point(x=1)) == hash(Point(x=1))
    True
    """


class MutableModel(BaseModel):
    """Start a model from this when its values must change after it's made.

    It's the rare case, said where the model is declared.
    """


class Settings(BaseSettings):
    """Start every settings class from this: read from the environment, then frozen.

    Each field is an environment variable, so a package's settings class is where
    the variables it reads are named (`docs/conventions.md`, *Constants*). The
    freeze is in its configuration rather than its class keywords: pydantic's
    settings base isn't frozen, and pyright refuses a frozen class over it.
    """

    model_config = SettingsConfigDict(frozen=True)


type JsonObject = dict[str, JsonValue]
"""A JSON object whose schema lives elsewhere: a vendor's payload, a tool's input."""
