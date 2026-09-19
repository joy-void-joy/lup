"""A spawned agent carries a name, so what lists, messages or stops it says what it is for.

A runtime shows a subagent by the name it was spawned with and otherwise by
its type, and a type is generic by construction: a session with three
general-purpose subagents running has three rows saying the same thing. The
name is also the address a message or a stop takes, so a spawn without one
is one nobody reaches except by the id the runtime minted.

The rule is presence. Which words make a good name is the caller's
judgement, and the recovery says the shape; whether the runtime accepts the
spelling is the runtime's, which validates it on the call. A spawn carrying
a name is deferred rather than allowed, because this kernel grants nothing
it was not asked to grant: the runtime's own permissions still settle a call
it says nothing more about.
"""

from .decision import KernelDecision
from .rows import SpawnNameRow
from .tools import TOOL_ESCALATE_HINT, escalated_reason


def decide_spawn(
    name: str, values: list[str], row: SpawnNameRow | None
) -> KernelDecision:
    """The verdict on one spawn: refused without a name, deferred with one.

    ``None`` for the row is a project that requires no name, which leaves the
    call to the runtime. An escalation marker among the call's inputs turns
    the refusal into the approval question the caller asked for, the way a
    refused tool's does.
    """
    if row is None:
        return KernelDecision("defer", "no spawn name is required here")
    if name.strip():
        return KernelDecision("defer", f"the spawn is named {name.strip()!r}")
    why = escalated_reason(values)
    if why:
        return KernelDecision(
            "ask", f"escalated ({why}): {row['reason']}", recovery=row["recovery"]
        )
    return KernelDecision(
        "deny", row["reason"], recovery=f"{row['recovery']} {TOOL_ESCALATE_HINT}"
    )
