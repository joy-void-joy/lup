"""This repository's writeups: documents generated from its own ledger.

A writeup is declared here the way guidance is declared — as parts in Python —
and written by `ledger writeup`. The prose is the author's; every figure and
every row is the ledger's, read at generation with its standing beside it, so
the document cannot carry a number the log stopped supporting. This one is the
scaffold's worked example: what this repository has recorded about itself, in
the order a reader picking it up asks — what is open, what is claimed and how
well it stands, what waits on a person, what was corrected.

An adopting project replaces the parts, keeps the shape, and adds documents by
adding to `WRITEUPS`.
"""

from lup.ledger.writeup import Listing, NeedsPerson, Prose, Stamp, Writeup

STATUS = Writeup(
    name="corpus-status",
    path="docs/corpus-status.md",
    source=__name__,
    parts=[
        Prose(
            text=(
                "# Corpus status\n\n"
                "What this repository has recorded about itself: the questions "
                "still open, the claims it is prepared to be held to and where each "
                "stands, what is waiting on a person, and what has been corrected. "
                "Every figure here is the ledger's, read at generation with its "
                "standing beside it — cite the node, not this page."
            )
        ),
        Listing(
            heading="Open questions",
            of="corpus:question",
            standing="open",
            numbered=True,
            empty="No question is open.",
        ),
        Listing(heading="Claims", of="corpus:claim", empty="No claim is recorded."),
        NeedsPerson(heading="What needs a person"),
        Listing(
            heading="Corrections",
            of="corpus:correction",
            empty="Nothing has been corrected.",
        ),
        Stamp(counting=["corpus:claim", "corpus:correction"]),
    ],
)
"""What this repository has recorded, as one document a reader opens on."""

# lup: ignore[constant-declaration] — the documents this repository generates
# from its ledger, decided here because nothing sits above it to be asked
WRITEUPS = [STATUS]
