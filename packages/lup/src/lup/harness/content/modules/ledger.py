"""One DAG of typed notes per repository, and nothing about what they mean.

The mechanism half of the multi-agent record. What a note kind is for, what a
claim owes before it may be recorded, and whether a claim still holds are
questions a project answers; this module ships the DAG they are answered over
and names no kind of its own.

Its page is the whole of its surface here. There is no guidance section: a
session does not need to be told about a store before it reaches for one, and
the skills that record notes carry their own instructions.

What a project records over this log — claims, evidence, questions, or kinds
of its own — is the project's declaration, made where it declares `Task`. The
scaffold's worked example is its corpus, documented on the scaffold's side,
because everything corpus-specific is types and a type everybody edits is a
scaffold file rather than a library one.
"""

from lup.harness.content.docs import ledger
from lup.harness.content.docs.catalog import page
from lup.harness.content.modules.specs import LEDGER
from lup.harness.modules import Module


def module() -> Module:
    """The note DAG as one value."""
    return Module(
        spec=LEDGER,
        documents=[page("ledger", "ledger.md", lambda _: ledger.DOCUMENT)],
    )
