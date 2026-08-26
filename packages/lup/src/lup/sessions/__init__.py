"""Provider-neutral session/turn engine: how any one agent turn runs.

Not :mod:`lup.orchestration.realtime` — that package is the sleep/wake
lifecycle machinery for persistent agents; this is the layer underneath it,
opening provider sessions and driving typed turns through them. Modules map
to concerns:

- :mod:`lup.sessions.capabilities` — the narrow capability seams (session
  factory, turn, event stream, interrupt, steer, fork, output binding);
  imports are type-only.
- :mod:`lup.sessions.events` — the immutable turn vocabulary every
  implementation shares (identifiers, blocks, events, requests, results,
  capability handles).
- :mod:`lup.sessions.errors` — typed turn and session-transition failures.
- :mod:`lup.sessions.composition` — builds sessions and turns from adapter
  callbacks and capabilities.
- :mod:`lup.sessions.middleware` — decorators around whole logical turns
  (timeouts, budgets, retries, persistence, tracing, usage, display).
- :mod:`lup.providers.routing` and :mod:`lup.providers.config` — first-match
  selection of a configured factory recipe.
- :mod:`lup.sessions.output` — validated submitted-output stores and the
  portable submission tool binding.
- :mod:`lup.orchestration.background` — a debounced consumer of the session
  capabilities that coalesces state wakes into turns on one persistent
  session.
- :mod:`lup.execution.threads` — blocking calls on a process-lifetime executor,
  so work in flight outlives any one loop's teardown.
- :mod:`lup.sessions.quota` — waiting out a provider account allowance, as
  distinct from a budget: the work is still wanted, just not yet runnable.
- :mod:`lup.sessions.budget` — a durable, shared spending ceiling over a
  rolling period, which waits for the window rather than failing the turn.

``contracts`` and ``models`` define the vocabulary; every other module
composes them; the named adapter packages implement them.
"""
