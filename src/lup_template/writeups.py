"""This repository's writeups: documents generated from its own ledger.

A writeup is declared here the way guidance is declared — as parts in Python —
and written by `ledger writeup`. The prose is the author's; every figure and
every row is the ledger's, read at generation with its standing beside it, so
the document cannot carry a number the log stopped supporting. This one is
the work list: what the coordination ledger still holds to do, in the order a
reader picking it up asks — which tasks are not finished, what among them
waits on a person and what each costs, which handoffs nobody has closed.
Every kind it renders is committed with the code, so it is also a generated
file `harness generate all` writes and `dev check` holds current.

An adopting project replaces the parts, keeps the shape, and adds documents by
adding to `WRITEUPS` — one over its corpus, where it declares one.
"""

from lup.ledger.writeup import Listing, NeedsPerson, Prose, Stamp, Writeup

STATUS = Writeup(
    name="work-status",
    path="docs/work-status.md",
    source=__name__,
    parts=[
        Prose(
            text=(
                "# Work status\n\n"
                "What this repository's coordination ledger still holds to do: "
                "the tasks not yet finished, what among them waits on a person "
                "and what each costs, and the handoffs nobody has closed. Every "
                "row is the ledger's, read at generation with its standing beside "
                "it — cite the node, not this page. `ledger delegate` records a "
                "task, `ledger mine` renders one holder's, and `ledger show <id>` "
                "opens any row."
            )
        ),
        Listing(
            heading="Open tasks",
            of="coordination:task",
            excluding="done",
            numbered=True,
            empty="No task is open.",
        ),
        NeedsPerson(heading="What needs a person"),
        Listing(
            heading="Open handoffs",
            of="coordination:handoff",
            excluding="done",
            empty="No handoff is open.",
        ),
        Stamp(
            of=["coordination:task", "coordination:handoff"],
            counting=["coordination:task", "coordination:handoff"],
        ),
    ],
)
"""What this repository still has to do, as one document a reader opens on."""

# lup: ignore[constant-declaration] — the documents this repository generates
# from its ledger, decided here because nothing sits above it to be asked
WRITEUPS = [STATUS]
