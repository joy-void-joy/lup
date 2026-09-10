"""One DAG of typed nodes per repository, and nothing about what they mean.

Work that outlives the session which did it has to live somewhere a later
session finds. Prose rots because nothing checks it; a per-branch file forks
because every worktree holds one; a stored status keeps its label after the
support for it goes away. This is the mechanism that avoids all three, and it
is deliberately only the mechanism.

- :mod:`lup.ledger.store` — where the log lives: one log in two journals,
  each kind declared committed with the code or local under the git
  directory.
- :mod:`lup.ledger.models` — the two bases every node and edge type extends.
- :mod:`lup.ledger.journal` — the log, and the typed reads over it.
- :mod:`lup.ledger.blobs` — bytes a node attaches, under their own digest.
- :mod:`lup.ledger.snapshot` — preserving the store on a branch of its own.
- :mod:`lup.ledger.files` — files as nodes, pinned by digest: the one kind
  this library declares.

**One log, separate types.** A ``Task`` and a ``Claim`` are unrelated models
with their own fields; they share a log rather than a shape, and reads are per
type, so nothing outside deserialization sees them unioned. What requires the
one log is that standing is computed by asking *what points at this node* —
and that question must not span several files which can change between reads.

**No epistemics, and one kind.** Nothing here says what counts as verified,
what grades exist, or what a claim owes before it may be recorded. Those are
a project's, and a library that answered them would be one every adopter had
to argue with: the scaffold's ``corpus`` module is one project's answer,
declared beside its tasks, and a project that wants its own declares its own
types the same way. The one node type declared here is ``File``, because a
file is not an epistemics: it says what bytes a path held, which every
project's files have in common, and it is the substrate standing already
rots against.
"""
