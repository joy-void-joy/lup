"""What a delegated agent verifies, and what it leaves to whoever sent it.

A delegated agent inherits the repository's guidance and reads, correctly,
that the full gate is what has to be green. Nothing in that guidance tells it
that *it* is not the one to run it — so several agents dispatched to implement
several pieces each start the whole suite, in the one working tree they share.

Three things go wrong at once, and only the first is cost. Each run spreads
itself over every core, so four of them are four times the processes and
several times the wall clock. Each reads a tree the others are still editing,
so a green answers about a state that never existed and a red cannot be
attributed to whoever caused it. And the gate is the slowest thing in the
repository, so the redundancy is paid at its full price.

The tiers are not a weakening. A delegated agent gets the two checks a scope
narrows *exactly* — each answers about the files it is handed, and the type
checker resolves their imports itself — which is seconds rather than minutes
and is a true answer about its own change. What it does not get is the suite,
because a suite over a shared tree is not answering about its change at all.
The caller assembles the work and runs the gate once, over a tree that has
stopped moving, which is the only moment the full answer means anything.

An agent holding a tree of its own is in the opposite position and is
deliberately not covered: a resolver worker in its lease, or anything launched
as a session rather than dispatched inside one, *is* the owner of what it
checks, and gates itself exactly as a session does.
"""

VERIFICATION_GATE = "`uv run lup-devtools dev check`"
VERIFICATION_SCOPED = "`uv run lup-devtools dev check --changed`"
VERIFICATION_RECORD = "your report"

# lup: defer: an adopter that renames its devtools CLI gets lup's spellings
# here, because the host half this notice is joined in ships verbatim and
# carries no injected project values. Wiring it would mean compiling the
# subagent asset the way the policy dispatcher is compiled, which is a change
# to how that asset is built rather than to what it says.


def verification_notice(
    gate: str = VERIFICATION_GATE,
    scoped: str = VERIFICATION_SCOPED,
    record: str = VERIFICATION_RECORD,
) -> str:
    """What a delegated agent is told, at the moment it is dispatched.

    Said at the start rather than refused at the call, because by the time a
    refusal lands the agent has already planned around running the gate and
    has to plan again. This is the cheaper half of the same judgement, and the
    one that changes what gets planned.

    Phrased as what to do rather than what not to: an agent told only that
    something is refused reaches for the nearest substitute, and the nearest
    substitute for the gate is the gate under another name.
    """
    return (
        f"You are working in the tree of whoever dispatched you, beside other"
        f" agents editing it. Verify your own change with {scoped}, which is"
        f" seconds and answers exactly about the files you touched, and name"
        f" in {record} what you could not check. Leave {gate} and the commit"
        f" to your caller: over a tree still being edited the suite answers"
        f" about a state that never existed, and a failure in it cannot be"
        f" attributed to whoever caused it."
    )
