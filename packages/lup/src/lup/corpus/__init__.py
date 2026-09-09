"""A body of claims, what backs each one, and what has since retired it.

The two repositories this design was read from were both corpora — one of
mathematical claims with proofs and measurements behind them, one of findings
with a correction register beside them — and both failed the same way: a
claim kept a label after the thing supporting it went away, and nothing
reported the difference. This is the set of default types that answers that
over :mod:`lup.ledger`: not a module with a switch, because everything
corpus-specific is a node kind, an edge kind, or the standing one of them
reads for itself — the store, recording, relating, listing and the cite check
are the ledger's. A project turns the corpus on by declaring these kinds, or
its own subclasses of them, exactly as it declares any other.

It declares no grade vocabulary. What a grade is called and what one is worth
is the project's question, the same one :mod:`lup.ledger` refuses to answer
about node types; a project's own ``Claim`` narrows the word.

- :mod:`lup.corpus.models` — the node and edge types, each answering its own
  standing over its neighbourhood.
"""
