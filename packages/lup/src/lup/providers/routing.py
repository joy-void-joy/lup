"""Which recipe a configured route names, and which runtime lists a model.

A project that has declared its own agents routes a model to one of them by
name or by match; a caller holding nothing but a model id asks the coarser
question of which runtime's own catalog lists it.
"""

from collections.abc import Callable
from typing import Literal, get_args

from pydantic import BaseModel

from lup.providers.claude.models import ClaudeModel
from lup.providers.codex.models import CodexModel
from lup.providers.config import ModelMatcher
from lup.sessions.surface import Agent


class ExactModelMatcher(ModelMatcher):
    """Match exactly one model name."""

    def __init__(self, expected: str) -> None:
        if not expected:
            raise ValueError("an exact model matcher cannot be empty")
        self.expected = expected

    def matches(self, model: str) -> bool:
        return model == self.expected


class PrefixModelMatcher(ModelMatcher):
    """Match a non-empty model-name prefix."""

    def __init__(self, prefix: str) -> None:
        if not prefix:
            raise ValueError("a prefix model matcher cannot be empty")
        self.prefix = prefix

    def matches(self, model: str) -> bool:
        return model.startswith(self.prefix)


type FactoryRecipe = Callable[[], Agent]


class ModelRoute(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """One immutable matcher and configured factory recipe."""

    name: str
    matcher: ModelMatcher
    recipe: FactoryRecipe


class ModelRouter:
    """Select explicit recipes first, then the first model match."""

    def __init__(self, routes: list[ModelRoute]) -> None:
        names = [route.name for route in routes]
        if len(names) != len(dict.fromkeys(names)):
            raise ValueError("model route names must be unique")
        self.routes = tuple(routes)

    def resolve(self, model: str, recipe: str | None = None) -> Agent:
        if recipe is not None:
            selected = next(
                (route for route in self.routes if route.name == recipe), None
            )
            if selected is None:
                raise LookupError(f"unknown factory recipe {recipe!r}")
            return selected.recipe()
        selected = next(
            (route for route in self.routes if route.matcher.matches(model)), None
        )
        if selected is None:
            raise LookupError(f"no configured route accepts model {model!r}")
        return selected.recipe()


type Provider = Literal["claude", "codex"]
"""A runtime by name, as a catalog lookup or a pin answers it."""


def catalog_provider(model: str) -> Provider | None:
    """Which provider's own catalog lists this name, or None when neither does.

    A catalog is the vendor's own answer: an alias such as ``opus`` carries no
    vendor prefix at all, so a guess from its spelling could only miss it.
    """
    if model in get_args(ClaudeModel.__value__):
        return "claude"
    if model in get_args(CodexModel.__value__):
        return "codex"
    return None
