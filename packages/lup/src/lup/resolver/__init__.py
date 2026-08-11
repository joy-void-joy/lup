# lup: Check that the files are well placed. This `resolver/` sits at the
# library's top level rather than under `harness/`, where its only driver
# (`lup.devtools.harness.resolve`) lives — and `web/` reads the same way. I would
# like the folder hierarchy to make sense in general, so audit the whole layout
# rather than moving just these two.
"""Provider-neutral resolution of reviewed code concerns, split by concern.

Drives worker, review, and merge skill runs over a DAG of concerns, each on
its own branch in a leased worktree:

- :mod:`lup.resolver.models` — the schema-versioned semantic records
  (concerns, verdicts, questions, run state).
- :mod:`lup.resolver.dag` — concern-DAG validation and scheduling order.
- :mod:`lup.resolver.state` — atomic, file-locked persistence of run state.
- :mod:`lup.resolver.contracts` — the user-question delivery seam.
- :mod:`lup.resolver.orchestrator` — the git side effects: leases,
  worktrees, commits, and dependency bases, through the harness
  ``ProcessLauncher`` seam.
- :mod:`lup.resolver.core` — the state machine composing all of the above
  with the native skill invocations.

``models`` is the shared vocabulary the other modules import; ``core`` is
the only module that composes its siblings, so everything below it stays
independently testable.
"""
