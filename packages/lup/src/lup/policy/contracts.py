"""The decision seams: one typed semantic event in, one verdict out.

:class:`DecisionPolicy` is implemented by the validated policies in
:mod:`lup.policy.rules` and composed by :mod:`lup.policy.chain`;
:class:`Observer` receives events for side-channel auditing with no power
to change a verdict.
"""

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
