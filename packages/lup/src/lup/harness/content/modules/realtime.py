"""Persistent agents that control their own attention.

For an agent that exists over time — holding a conversation, monitoring
something, playing a game — the architecture inverts: the agent is a presence
that sleeps when it chooses and wakes on events, not a processor steered by an
event queue. The loop never ends its turn; the only way to yield is to sleep.

One tool group and nothing else, which understates it. On Claude that loop
runs in-process: ``sleep`` blocks on the Scheduler and a Stop hook holds the
turn open. On backends whose tools run in a subprocess the loop inverts again
— each wake is one turn — and this group is what spells it: ``reply`` and the
timing tools append events a parent-side watcher applies mid-turn, ``sleep``
records a request and ends the turn. So the group is not a convenience over
the pattern, it is the pattern, for every runtime that cannot hold a turn open.

The always-loaded document says nothing about writing one of these, which is a
real gap rather than a decision — the how-to lives in the orchestration page
core publishes, and a session meets it only if it goes looking.
"""

from lup.harness.content.modules.specs import REALTIME
from lup.harness.modules import Module


def module() -> Module:
    """The persistent-agent relay as one value."""
    return Module(spec=REALTIME, tool_groups=["session"])
