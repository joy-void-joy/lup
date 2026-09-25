"""Independent configuration, profile, and routing capabilities.

``ProfileSelector`` is the concrete surface a consumer holds over profile
resolution; the ABCs here are the engines it and ``ModelRouter`` compose.
"""

from abc import ABC, abstractmethod


class ConfigTransform[C](ABC):
    """Apply one immutable configuration transformation.

    A transform holds no shared behaviour of its own: it is a pure function
    over config, an ABC only so implementations can be named, stacked, and
    inspected before any provider resource exists. There is nothing for a
    composing surface to home, so applications stack transforms directly.
    """

    @abstractmethod
    def apply(self, config: C) -> C:
        """Return the transformed configuration."""


class ProfileResolver[C](ABC):
    """Resolve an optional profile name to a configuration transform."""

    @abstractmethod
    def resolve(self, name: str | None) -> ConfigTransform[C]:
        """Resolve explicit, active, or default profile selection."""


class ProfileSelector[C]:
    """Resolve a profile selection and apply it to the agent it configures."""

    def __init__(self, resolver: ProfileResolver[C]) -> None:
        self.resolver = resolver

    def transform(self, name: str | None = None) -> ConfigTransform[C]:
        """Resolve the selection as a transform, before any construction.

        The transform is the primitive rather than an intermediate step:
        selections compose with other config transforms and can be inspected
        or dry-run while no provider resource exists yet. Callers that only
        want the configured agent use :meth:`session_factory`.
        """
        return self.resolver.resolve(name)

    def session_factory(self, base: C, name: str | None = None) -> C:
        """Resolve the selection and apply it to ``base``, the agent it configures.

        What comes back opens the sessions: a provider's declaration is its
        own client, so selecting a profile is transforming one.
        """
        return self.transform(name).apply(base)


class ModelMatcher(ABC):
    """Decide whether one immutable route accepts a model name."""

    @abstractmethod
    def matches(self, model: str) -> bool:
        """Return whether this matcher accepts the model."""
