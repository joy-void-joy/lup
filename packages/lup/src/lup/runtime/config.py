"""Independent configuration, profile, and routing capabilities."""

from abc import ABC, abstractmethod


class ConfigTransform[C](ABC):
    """Apply one immutable configuration transformation."""

    @abstractmethod
    def apply(self, config: C) -> C:
        """Return the transformed configuration."""


class ProfileResolver[C](ABC):
    """Resolve an optional profile name to a configuration transform."""

    @abstractmethod
    def resolve(self, name: str | None) -> ConfigTransform[C]:
        """Resolve explicit, active, or default profile selection."""


class ModelMatcher(ABC):
    """Decide whether one immutable route accepts a model name."""

    @abstractmethod
    def matches(self, model: str) -> bool:
        """Return whether this matcher accepts the model."""
