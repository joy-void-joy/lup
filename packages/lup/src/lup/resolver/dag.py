"""Concern-DAG validation and the approval filter that rides on it.

The ordering itself is :mod:`lup.execution.dag`, which any dependent work
shares. What stays here is the part only a resolve has: a concern may be
approved for integration and still not be integrable, because one of the
concerns it builds on was not.
"""

from collections.abc import Collection

from lup.execution.dag import DependencyGraph
from lup.resolver.models import Concern


class ConcernGraph(DependencyGraph[Concern]):
    """A concern graph, ordered like any other and approved like no other."""

    def __init__(self, concerns: list[Concern]) -> None:
        super().__init__(concerns, subject="concern")

    def approved(self) -> list[Concern]:
        """Return eligible approved nodes whose entire ancestry is approved."""
        approved_ids = {
            concern.id
            for concern in self.nodes.values()
            if concern.eligible and concern.integration_approved
        }
        return self.transitively_approved(approved_ids)

    def transitively_approved(self, approved_ids: Collection[str]) -> list[Concern]:
        """Filter an explicit decision set through complete approved ancestry."""
        return [
            concern
            for batch in self.topological_batches()
            for concern in batch
            if concern.id in approved_ids
            and all(
                ancestor.id in approved_ids for ancestor in self.ancestors(concern.id)
            )
        ]
