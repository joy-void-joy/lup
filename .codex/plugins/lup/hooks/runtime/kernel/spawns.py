"""A spawned agent carries a name, so what lists, messages or stops it says what it is for.

A runtime shows a subagent by the name it was spawned with and otherwise by
its type, and a type is generic by construction: a session with three
general-purpose subagents running has three rows saying the same thing. The
name is also the address a message or a stop takes, so a spawn without one
is one nobody reaches except by the id the runtime minted.

The rule is presence and spelling. Which words make a good name is the
caller's judgement and the recovery says the shape; that the characters are
ones every runtime here accepts is this rule's, because leaving it to the
runtime was measured to fail quietly — one rejects a name it dislikes with
no hook record at all, so a spawn our gate passed died where nothing could
see it, and the caller learned the shape by guessing. The declaration names
the characters rather than this module, since the safe set is a property of
the runtimes a project runs on.

A spawn carrying a name of that shape is deferred rather than allowed,
because this kernel grants nothing it was not asked to grant: the runtime's
own permissions still settle a call it says nothing more about.
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

    def refused(what: str) -> KernelDecision:
        """The denial, or the approval question an escalation marker asks for."""
        why = escalated_reason(values)
        if why:
            return KernelDecision(
                "ask", f"escalated ({why}): {what}", recovery=row["recovery"]
            )
        return KernelDecision(
            "deny", what, recovery=f"{row['recovery']} {TOOL_ESCALATE_HINT}"
        )

    def alphanumeric(character: str) -> bool:
        """A letter or digit in ASCII, which is what both validators read.

        Narrower than ``str.isalnum``, deliberately: a name of letters no
        runtime here would accept is not made acceptable by Python agreeing
        that they are letters.
        """
        return character.isascii() and character.isalnum()

    def spelled(named: str) -> bool:
        """Whether the name is the shape the declaration accepts."""
        return (
            len(named) <= row["limit"]
            and alphanumeric(named[0])
            and all(
                alphanumeric(character) or character in row["punctuation"]
                for character in named
            )
        )

    named = name.strip()
    if not named:
        return refused(row["reason"])
    if not spelled(named):
        return refused(f"{named!r}: {row['misspelled']}")
    return KernelDecision("defer", f"the spawn is named {named!r}")
