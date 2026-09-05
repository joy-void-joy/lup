"""The order dependent work may run in, over whatever the work is.

Two things in this library schedule a graph. The resolver orders concerns so
a worker never starts before what it builds on has landed, and a run orders
its steps so a stage reads inputs that already exist. Both want the same
answers — which nodes may start together, what a node transitively rests on,
and what rests on it — and neither wants the other's vocabulary.

Nodes are held structurally: anything carrying an ``id`` and the
``dependencies`` it names is schedulable, so a caller keeps its own model and
still gets the ordering. The subject word is the caller's too, because "the
concern graph contains a cycle" and "the step graph contains a cycle" are read
by different people looking for different things.
"""

from typing import Protocol


class DependencyNode(Protocol):
    """A node that names itself and what it rests on.

    Structural rather than a base class: the models that ride this graph are
    declared in packages that know nothing of each other, and neither should
    have to inherit from a scheduling module to be scheduled by it.
    """

    @property
    def id(self) -> str:
        """This node's identity, unique within its graph."""
        ...

    @property
    def dependencies(self) -> list[str]:
        """The ids this node rests on, each of which must be in the graph."""
        ...


class DependencyGraphError(ValueError):
    """A graph references a missing node or contains a cycle."""


class DependencyGraph[N: DependencyNode]:
    """Validated immutable graph with deterministic topological batches."""

    def __init__(self, nodes: list[N], subject: str = "node") -> None:
        self.subject = subject
        self.nodes = {node.id: node for node in nodes}
        if len(self.nodes) != len(nodes):
            raise DependencyGraphError(f"{subject} ids must be unique")
        missing = sorted(
            {
                dependency
                for node in nodes
                for dependency in node.dependencies
                if dependency not in self.nodes
            }
        )
        if missing:
            raise DependencyGraphError(
                f"{subject} graph references missing nodes: {', '.join(missing)}"
            )
        self.topological_batches()

    def topological_batches(self) -> list[list[N]]:
        """Return independent roots together and every child after its parents."""
        remaining = {
            identifier: set(node.dependencies)  # lup: ignore[set-shape]
            for identifier, node in self.nodes.items()
        }
        batches: list[list[N]] = []  # lup: ignore[empty-collection]
        completed: set[str] = set()  # lup: ignore[set-shape,empty-collection]
        while remaining:
            ready_ids = sorted(
                identifier
                for identifier, dependencies in remaining.items()
                if dependencies <= completed
            )
            if not ready_ids:
                cycle = ", ".join(sorted(remaining))
                raise DependencyGraphError(
                    f"{self.subject} graph contains a cycle: {cycle}"
                )
            batches.append([self.nodes[identifier] for identifier in ready_ids])
            completed.update(ready_ids)
            for identifier in ready_ids:
                del remaining[identifier]
        return batches

    def ancestors(self, node_id: str) -> list[N]:
        """Return the complete transitive dependency set in topological order."""
        return self.reachable(node_id, self.dependency_edges())

    def descendants(self, node_id: str) -> list[N]:
        """Return everything that transitively rests on this node, in order.

        This is the direction invalidation travels: a node whose result was
        recomputed leaves every node downstream of it holding a conclusion
        drawn from an input that no longer stands.
        """
        return self.reachable(node_id, self.dependent_edges())

    def dependency_edges(self) -> dict[str, list[str]]:
        """For each node, the ids it rests on."""
        return {
            identifier: list(node.dependencies)
            for identifier, node in self.nodes.items()
        }

    def dependent_edges(self) -> dict[str, list[str]]:
        """For each node, the ids that rest on it."""
        return {
            identifier: [
                other
                for other, node in sorted(self.nodes.items())
                if identifier in node.dependencies
            ]
            for identifier in self.nodes
        }

    def reachable(self, node_id: str, edges: dict[str, list[str]]) -> list[N]:
        """Walk one edge direction from a node, in topological order.

        The walk itself is unordered, so the result is read back off the
        topological batches rather than off the traversal: a caller reruns
        what came back and has to be handed it parents-first whichever
        direction it asked about.
        """
        if node_id not in self.nodes:
            raise DependencyGraphError(f"unknown {self.subject} {node_id!r}")
        wanted: set[str] = set()  # lup: ignore[set-shape,empty-collection]
        pending = list(edges[node_id])
        while pending:
            identifier = pending.pop()
            if identifier in wanted:
                continue
            wanted.add(identifier)
            pending.extend(edges[identifier])
        return [
            node
            for batch in self.topological_batches()
            for node in batch
            if node.id in wanted
        ]
