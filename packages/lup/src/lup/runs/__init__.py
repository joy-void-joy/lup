"""Work that outlives the tool call which started it, and stays watchable.

A job long enough to be worth launching in the background is a job nobody can
see. The answer here is one directory and a protocol over it: the run declares
what it scheduled before starting, lands one atomically written result per
unit, claims a unit while it works on it, and writes a line each time
something happens. Everything a follower knows it reads from those, so a run
launched detached, from another session, or before this shell existed is
observable without being touched — and following one cannot perturb it.

- :mod:`lup.runs.models` — the records that layout consists of.
- :mod:`lup.runs.ledger` — the directory itself: where each record goes and
  how it is written, which is the one place both ends meet.
- :mod:`lup.runs.progress` — one reading of a run, taken from the directory
  alone, including the honest estimate of the time left.
- :mod:`lup.runs.follow` — the two ways to watch one: redrawn in place for a
  person, one line per event for an agent.
- :mod:`lup.runs.pipeline` — the runtime that produces such a run from a
  declared set of steps, reusing by fingerprint everything whose inputs have
  not changed.

``models`` is the shared vocabulary; ``pipeline`` is the only module that
composes the others, so a project that already has its own runner can write
the layout directly and be followed just the same.
"""
