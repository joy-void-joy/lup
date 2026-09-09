"""One DAG of typed notes per repository, and nothing about what they mean.

The mechanism half of the multi-agent record. What a note kind is for, what a
claim owes before it may be recorded, and whether a claim still holds are
questions a project answers; this module ships the DAG they are answered over
and names no kind of its own.

Its pages are the whole of its surface here. There is no guidance section: a
session does not need to be told about a store before it reaches for one, and
the skills that record notes carry their own instructions.

The second page is the corpus — the default knowledge kinds a project may
declare over this log. It is a page here and not a module of its own because
everything corpus-specific is types: the store, recording, relating, listing
and the cite check are the ledger's, and a project turns the corpus on by
declaring the kinds, exactly as it declares any other.
"""

from lup.harness.content.docs import corpus, ledger
from lup.harness.content.docs.catalog import page
from lup.harness.content.modules.specs import LEDGER
from lup.harness.modules import Module


def module() -> Module:
    """The note DAG as one value."""
    return Module(
        spec=LEDGER,
        documents=[
            page("ledger", "ledger.md", lambda _: ledger.DOCUMENT),
            page("corpus", "corpus.md", lambda _: corpus.DOCUMENT),
        ],
    )
