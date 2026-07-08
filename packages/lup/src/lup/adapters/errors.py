"""The seam's error vocabulary: what engines raise, in neutral terms.

Refusal is behavioral, not declared: an engine that cannot honor an
intent knob refuses it at construction
(:class:`UnsupportedOptionsError`), an operation it cannot perform
raises at the point of use (:class:`UnsupportedOperationError`), and the
run-governance errors (:class:`TurnTimeoutError`,
:class:`BudgetExceededError`) surface when an engine enforces the
corresponding knob itself.
"""


class UnsupportedOperationError(NotImplementedError):
    """The engine behind this client cannot perform the requested operation.

    Raised at the point of use — ``interrupt()`` on a runtime with no
    interruption support, ``session(resume=...)`` on an engine that cannot
    restore threads. A ``NotImplementedError`` subclass, so generic
    ``except NotImplementedError`` handlers also catch it.
    """


class UnsupportedOptionsError(ValueError):
    """The engine cannot honor intent knobs the options carry.

    Raised at construction (``on_unsupported="raise"``, the session
    default), so a session that asked for, say, ``max_turns`` on a runtime
    without turn caps fails before it starts. ``fields`` names the
    offenders. With ``on_unsupported="drop"`` the engine clears them and
    logs instead — the one-shot ``query()`` policy.
    """

    def __init__(self, engine: str, fields: list[str]) -> None:
        self.engine = engine
        self.fields = sorted(fields)
        super().__init__(
            f"options {self.fields} are not supported on the {engine} engine; "
            "unset them or run on an engine that honors them."
        )


class TurnTimeoutError(RuntimeError):
    """A turn exceeded its wall-clock timeout and was cancelled client-side.

    Raised by engines that enforce ``turn_timeout_seconds`` when a single
    turn runs past it. The backend thread's state is undefined afterwards
    — close the session rather than sending further turns on it.
    """


class BudgetExceededError(RuntimeError):
    """A session refused to start a turn: accumulated cost reached the budget.

    Raised between turns by engines that enforce ``max_budget_usd``
    through their own usage accounting (the Codex runtime reports token
    counts, not cost). The turn that crossed the budget has already
    completed — this error stops the *next* one.
    """
