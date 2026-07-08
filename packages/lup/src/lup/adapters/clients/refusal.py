"""Consume-tracking refusal: an engine honors exactly what its translation reads.

:func:`refuse_unconsumed` runs an engine's translation over a
:class:`ConsumeTracker` view of the options and refuses any intent knob
the caller set but the translation never read — the engine has no lever
for what it does not consume. No second declaration of the honored set
exists to drift from the translation code.
"""

import logging
from collections.abc import Callable

from pydantic import PrivateAttr

from lup.adapters.errors import UnsupportedOptionsError
from lup.adapters.options import LupAgentOptions

logger = logging.getLogger(__name__)


INTENT_KNOBS: frozenset[str] = frozenset(
    {
        "max_turns",
        "max_thinking_tokens",
        "permission_mode",
        "tools",
        "reasoning_effort",
        "max_budget_usd",
        "turn_timeout_seconds",
    }
)
"""The scalar intent fields subject to consume-tracking refusal.

An engine that reads one of these during translation honors it; one it
leaves unread has no lever for it and refuses it. Mechanism payloads
(tool servers, hooks, subagents, served groups, dirs, output schema) and
their helpers (``usage_cost``, the estimator behind ``max_budget_usd``)
are outside this set — they keep their consume-or-ignore-freely
semantics and are never policed."""


class ConsumeTracker(LupAgentOptions):
    """A translation-time view of options that records intent-knob reads.

    Each ``create_*`` translates through one of these; an intent knob the
    caller SET but the translation never READ is a knob the engine has no
    lever for. Only :data:`INTENT_KNOBS` reads are recorded, so reading a
    mechanism payload records nothing.

    The ``__getattribute__`` override is the whole mechanism: it records a
    read for an intent-knob field name and otherwise defers to the base
    lookup, leaving pydantic's own machinery untouched. Type checkers
    resolve known members from the class, not through ``__getattribute__``,
    so pyright still sees each field's real declared type.
    """

    _consumed: set[str] = PrivateAttr(default_factory=set)

    @classmethod
    def tracking(cls, opts: LupAgentOptions) -> "ConsumeTracker":
        """A tracker over ``opts``' fields with an empty read record.

        ``model_construct`` copies the validated fields without re-running
        validation and initializes the empty read set — no intent knob is
        touched before translation begins.
        """
        return cls.model_construct(**opts.__dict__)

    @property
    def consumed(self) -> set[str]:
        """The intent-knob field names the translation has read so far."""
        return self._consumed

    def __getattribute__(self, name: str) -> object:
        if name in INTENT_KNOBS:
            self._consumed.add(name)
        return super().__getattribute__(name)


def refuse_unconsumed[N](
    engine_id: str,
    opts: LupAgentOptions,
    translate: Callable[[LupAgentOptions], N],
) -> N:
    """Translate ``opts`` and refuse the intent knobs the translation ignored.

    Runs ``translate`` over a :class:`ConsumeTracker`; any intent knob the
    caller set but the translation never read is one the engine cannot
    honor. Under ``on_unsupported="raise"`` (the session default) those
    fail the construction with :class:`~lup.adapters.errors.UnsupportedOptionsError`;
    under ``"drop"`` (the ``query()`` policy) they are logged and the
    already-untouched native result is returned as-is. Because the
    translation never read them, the native object already reflects their
    absence — dropping needs no re-translation.

    The alternative shape, weighed and set aside, is a per-engine intent
    model: each engine declares a small ``BaseModel`` of exactly the knobs
    it honors (Claude's would carry ``max_turns``/``max_thinking_tokens``/
    ``permission_mode``/``tools``/``reasoning_effort``/``max_budget_usd``,
    Codex's would omit them and carry ``turn_timeout_seconds``); refusal
    becomes "set fields absent from the model", conditional refusals become
    ``model_validator``s (Codex drops ``max_budget_usd`` unless
    ``usage_cost`` is present), and translation consumes the validated
    model. That shape makes the honored set a declared registry a reader
    can see at a glance, but it duplicates every knob's type across the
    neutral options and each engine's model, and the two can drift.
    Consume-tracking keeps the translation code itself as the single source
    of truth — what an engine reads is what it honors, with no second
    declaration to maintain — at the cost of a reflective override rather
    than a plain model. Both are sketched here so the choice can be made at
    review.
    """
    tracker = ConsumeTracker.tracking(opts)
    native = translate(tracker)
    offenders = sorted(
        knob
        for knob in INTENT_KNOBS
        if getattr(opts, knob) is not None and knob not in tracker.consumed
    )
    if offenders:
        match opts.on_unsupported:
            case "raise":
                raise UnsupportedOptionsError(engine_id, offenders)
            case "drop":
                logger.info(
                    "options %s are not supported on the %s engine (model=%r); "
                    "proceeding without them.",
                    offenders,
                    engine_id,
                    opts.model,
                )
    return native
