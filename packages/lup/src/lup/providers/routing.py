"""Which vendor serves a model id, and which recipe a configured route names.

Two questions with one vocabulary. A project that has declared its own
factories routes a model to one of them by name or by match; a caller holding
nothing but a model id asks the coarser question of which *provider* serves
it. Both are matching a model name, so both are expressed with the matchers
below rather than one of them growing a private prefix table -- which is what
the front door used to carry, and what made it reach for both adapters to
answer.
"""

from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import BaseModel

from lup.providers.config import ModelMatcher
from lup.sessions.client import Client


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


type FactoryRecipe = Callable[[], Client]


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

    def resolve(self, model: str, recipe: str | None = None) -> Client:
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
"""A provider by name, for the one route that dispatches rather than names."""


class ProviderRoute(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """One vendor, and the model ids it claims."""

    provider: Provider
    matcher: ModelMatcher


PROVIDER_ROUTES: list[ProviderRoute] = [
    ProviderRoute(provider="claude", matcher=PrefixModelMatcher("claude-")),
    ProviderRoute(provider="codex", matcher=PrefixModelMatcher("gpt-")),
    ProviderRoute(provider="codex", matcher=PrefixModelMatcher("o1-")),
    ProviderRoute(provider="codex", matcher=PrefixModelMatcher("o3-")),
    ProviderRoute(provider="codex", matcher=PrefixModelMatcher("o4-")),
]
"""Which vendor's models a model id belongs to.

A default rather than a fixture: a vendor ships a new family under a prefix
nobody here has heard of, and an adopter says so by passing its own list
instead of waiting for this one to catch up. A matcher rather than a bare
prefix, so that adopter can also name a model exactly, or write a matcher of
its own, where a prefix is the wrong shape for what it has to say.

First declared match wins, which is the rule :class:`ModelRouter` already
reads its own routes by. A narrower entry earns its answer by being written
above a broader one, where a reader can see the ordering rather than infer it
from a sort nothing on the page mentions.
"""


def provider_for(
    model: str, routes: Sequence[ProviderRoute] = PROVIDER_ROUTES
) -> Provider | None:
    """Which provider serves this model id, or None when nothing claims it."""
    return next(
        (route.provider for route in routes if route.matcher.matches(model)), None
    )
