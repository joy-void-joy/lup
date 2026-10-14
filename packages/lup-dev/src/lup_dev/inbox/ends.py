"""No turn that won't end: a turn's end held once per thing, across turns.

`docs/host-tools.md`, *No turn that won't end*. An agent can always end its
turn, and nothing holds it again for what it's already been told. Every hold at
a turn's end, the inbox's and the judge's alike, goes through `holding`:
- **once, then the turn ends:** an end that follows a hold (`after_block`, from
  the runtime's `stop_hook_active` on both runtimes) is let through, whatever's
  still there;
- **once per thing, across turns:** what an end was let through past is
  remembered as passed, per conversation, by whoever holds; it holds no later end.
  A passed thing that's gone and comes back is a thing again.

Each holder remembers its own: an inbox item told in a hold's reason is told, so
it isn't waiting and holds nothing more; the judge's findings at a turn's end are
remembered as passed in its conversations' record (`policy/checkpoint.py`) once a
turn ends past them, and hold a later end only where they've changed. So the
agent stopping, the operator asking something, and the agent stopping again ends
the turn at once, unless something else came.
"""


def holding[T](things: list[T], passed: list[T], *, after_block: bool) -> list[T]:
    """Return what of `things` holds a conversation's turn's end: none where the end follows a hold, else those not `passed` before.

    >>> holding(["a", "b"], ["a"], after_block=False)
    ['b']
    >>> holding(["a", "b"], [], after_block=True)
    []
    """
    if after_block:
        return []
    return [each for each in things if each not in passed]
