"""Deterministic conservative policy and observer composition."""

from lup.policy.contracts import DecisionPolicy, Observer
from lup.policy.models import (
    Decision,
    ObservationFailure,
    PolicyEvaluation,
    UnknownTool,
)


class OrderedPolicyChain[E](DecisionPolicy[E]):
    """Aggregate named policies with deny-before-ask precedence."""

    def __init__(self, policies: list[DecisionPolicy[E]]) -> None:
        self.policies = list(policies)

    def decide(self, event: E) -> Decision:
        decisions = [policy.decide(event) for policy in self.policies]
        denied = next(
            (decision for decision in decisions if decision.effect == "deny"), None
        )
        if denied is not None:
            return denied
        asked = next(
            (decision for decision in decisions if decision.effect == "ask"), None
        )
        if asked is not None:
            return asked
        if decisions:
            return Decision(effect="allow")
        return Decision(effect="ask", reason="no policy classified this event")


class UnknownToolPolicy(DecisionPolicy[UnknownTool]):
    """Fail conservatively when no adapter classification exists."""

    def decide(self, event: UnknownTool) -> Decision:
        return Decision(
            effect="ask",
            reason=f"unclassified tool {event.identity.original_name!r}",
        )


class PolicyDispatcher[E]:
    """Evaluate once, then notify observers without weakening the verdict."""

    def __init__(
        self, policy: DecisionPolicy[E], observers: list[Observer[E]] | None = None
    ) -> None:
        self.policy = policy
        self.observers = list(observers or [])

    def evaluate(self, event: E) -> PolicyEvaluation:
        decision = self.policy.decide(event)
        failures: list[ObservationFailure] = []
        for observer in self.observers:
            try:
                observer.observe(event)
            except Exception as error:
                failures.append(
                    ObservationFailure(
                        observer=type(observer).__name__, message=str(error)
                    )
                )
        return PolicyEvaluation(decision=decision, observation_failures=failures)
