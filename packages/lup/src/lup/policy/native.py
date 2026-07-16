"""Separate native input decoding and output rendering capabilities."""

from abc import ABC, abstractmethod

from lup.policy.models import Decision, SemanticEvent


class NativeEventDecoder[N](ABC):
    """Decode one native boundary into Lup semantic events."""

    @abstractmethod
    def decode(self, event: N) -> SemanticEvent:
        """Decode or return conservative typed evidence."""


class NativeDecisionRenderer[N](ABC):
    """Render a semantic decision for one native boundary."""

    @abstractmethod
    def render(self, decision: Decision) -> N:
        """Render representable effects and fail closed otherwise."""
