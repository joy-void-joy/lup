"""Cohesive policy and observation capability contracts."""

from abc import ABC, abstractmethod

from lup.policy.models import Decision


class DecisionPolicy[E](ABC):
    """Compute a security decision for one typed semantic event."""

    @abstractmethod
    def decide(self, event: E) -> Decision:
        """Return allow, ask, or deny with evidence."""


class Observer[E](ABC):
    """Observe an event without permission-granting authority."""

    @abstractmethod
    def observe(self, event: E) -> None:
        """Record or publish an event after policy evaluation."""
