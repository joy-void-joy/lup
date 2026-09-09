"""One DAG of typed nodes per repository, and nothing about what they mean.

Work that outlives the session which did it has to live somewhere a later
session finds. Prose rots because nothing checks it; a per-branch file forks
because every worktree holds one; a stored status keeps its label after the
support for it goes away. This is the mechanism that avoids all three, and it
is deliberately only the mechanism.

- :mod:`lup.ledger.store` — where the log lives: shared under the git
  directory, or declared in the tree.
- :mod:`lup.ledger.models` — the two bases every node and edge type extends.
- :mod:`lup.ledger.journal` — the log, and the typed reads over it.
- :mod:`lup.ledger.blobs` — bytes a node attaches, under their own digest.
- :mod:`lup.ledger.snapshot` — preserving the store on a branch of its own.

**One log, separate types.** A ``Task`` and a ``Claim`` are unrelated models
with their own fields; they share a log rather than a shape, and reads are per
type, so nothing outside deserialization sees them unioned. What requires the
one log is that standing is computed by asking *what points at this node* —
and that question must not span several files which can change between reads.

**No epistemics.** Nothing here says what counts as verified, what grades
exist, or what a claim owes before it may be recorded. Those are a project's,
and a library that answered them would be one every adopter had to argue with:
the scaffold's ``corpus`` module is one project's answer, declared beside its
tasks, and a project that wants its own declares its own types the same way.
"""
